# -*- coding: utf-8 -*-
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(_sys.argv[0])))
"""校园网自动登录主程序（锐捷 SAM / Angular+Ionic 版）。

用法:
    python main.py --once              # 登录一次（按 config.ini 的 headless 设置）
    python main.py --once --visible    # 登录一次（显示浏览器窗口，调试用）
    python main.py --boot              # 开机自启时由 VBS 调用，静默执行

设计要点：
- Angular/Ionic 页面渲染慢：轮询等待，不靠固定 sleep
- Ionic 组件在 Shadow DOM 里：用穿透 JS 深度查找输入框，元素以 WebElement
  返回后用 send_keys 填写（真实键盘事件，Angular 能正确感知）
- 密码错误立即停止（退出码 2），防止反复重试锁号
- 全程落盘：logs/ 下有日志、截图、页面源码和 RESULT.txt，断网跑完联网后可复盘
"""
import argparse
import os
import sys
import time
import threading
from datetime import datetime

from common import AUTHOR, LOG_DIR, clear_account, load_config, save_account, save_service, log, make_driver, shot, dump_page


class BrowserClosed(Exception):
    """用户手动关闭了浏览器窗口，任务应立即结束"""


# ---------- 浏览器看门狗 ----------
_browser_closed = threading.Event()
_wd_stop = threading.Event()


def start_watchdog(driver):
    """每 2 秒探测一次浏览器是否存活，用户关闭窗口则置位 _browser_closed"""
    _browser_closed.clear()
    _wd_stop.clear()

    def watch():
        while not _wd_stop.wait(2):
            try:
                _ = driver.current_url  # 轻量探测，窗口关闭会抛异常
            except Exception:
                if not _wd_stop.is_set():
                    _browser_closed.set()
                    log("检测到浏览器窗口已关闭，正在结束当前任务...", "WARN")
                return

    threading.Thread(target=watch, daemon=True).start()


def stop_watchdog():
    _wd_stop.set()


def check_browser():
    """在各等待循环中调用：浏览器已关闭则抛 BrowserClosed 终止任务"""
    if _browser_closed.is_set():
        raise BrowserClosed()


def show_banner():
    """启动署名横幅"""
    print("=" * 52)
    print("       校园网自动登录   py: %s" % AUTHOR)
    print("=" * 52)

FAIL_KEYWORDS = ["密码错误", "口令错误", "账号不存在", "用户不存在", "已锁定",
                 "认证失败", "locked", "incorrect", "不正确", "不存在"]
SUCCESS_KEYWORDS = ["认证成功", "登录成功", "上线成功", "成功", "在线", "下线", "注销"]

# 穿透 Shadow DOM 找输入框：返回 DOM 元素（Selenium 会自动序列化成 WebElement）
DEEP_FIND_INPUTS = r"""
function walk(root, out) {
  var els = root.querySelectorAll('*');
  for (var i = 0; i < els.length; i++) {
    var el = els[i], tag = el.tagName;
    if ((tag === 'INPUT' || tag === 'TEXTAREA') &&
        (el.offsetWidth || el.offsetHeight || el.getClientRects().length)) {
      out.push(el);
    }
    if (el.shadowRoot) walk(el.shadowRoot, out);
  }
}
var out = [];
walk(document, out);
var user = null, pass = null, others = [];
for (var i = 0; i < out.length; i++) {
  var t = (out[i].type || '').toLowerCase();
  if (t === 'password') { if (!pass) pass = out[i]; }
  else if (t === 'text' || t === 'tel' || t === 'number') {
    if (!user) user = out[i]; else others.push(out[i]);
  }
}
return {user: user, pass: pass, count: out.length};
"""

# 穿透 Shadow DOM 找登录按钮，返回元素
DEEP_FIND_BUTTON = r"""
function walk(root, out) {
  var els = root.querySelectorAll('*');
  for (var i = 0; i < els.length; i++) {
    var el = els[i], tag = el.tagName;
    if ((tag === 'BUTTON' || tag === 'ION-BUTTON') &&
        (el.offsetWidth || el.offsetHeight || el.getClientRects().length)) {
      var t = '';
      try { t = (el.innerText || el.textContent || el.value || '').replace(/\s+/g, '').toLowerCase(); } catch (e) {}
      var cls = (el.className && el.className.toString ? el.className.toString() : '').toLowerCase();
      if (t.indexOf('登录') > -1 || t.indexOf('登陆') > -1 || t.indexOf('login') > -1 ||
          t.indexOf('连接') > -1 || t.indexOf('上线') > -1 || cls.indexOf('login') > -1) {
        out.push(el);
      }
    }
    if (el.shadowRoot) walk(el.shadowRoot, out);
  }
}
var out = [];
walk(document, out);
return out.length ? out[0] : null;
"""


# 确保协议勾选框已勾上（锐捷门户不勾「同意协议」点登录会被拦）
DEEP_ENSURE_AGREE = r"""
function walk(root, out) {
  var els = root.querySelectorAll('*');
  for (var i = 0; i < els.length; i++) {
    var el = els[i];
    var isCk = el.tagName === 'INPUT' && el.type === 'checkbox';
    var isIon = el.tagName === 'ION-CHECKBOX';
    if ((isCk || isIon) && (el.offsetWidth || el.offsetHeight || el.getClientRects().length)) {
      var checked = isIon ? el.checked || el.getAttribute('aria-checked') === 'true'
                          : el.checked;
      if (!checked) { out.push(el); return out.length; }
    }
    if (el.shadowRoot) walk(el.shadowRoot, out);
  }
  return out.length;
}
var out = [];
return walk(document, out) > 0;
"""


def click_text_iframes(driver, text):
    """在主文档和所有 iframe 里按精确文字点击，返回是否点到"""
    try:
        if click_text_deep(driver, text):
            return True
    except Exception:
        pass
    try:
        for fr in driver.find_elements("tag name", "iframe"):
            try:
                driver.switch_to.frame(fr)
                if click_text_deep(driver, text):
                    return True
                driver.switch_to.default_content()
            except Exception:
                continue
    except Exception:
        pass
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return False





SELF_URL = "http://10.254.241.66/self/index"


def do_logout(driver, cfg):
    """自助服务中心下线：打开 self/index → 用同一账号密码登录
    → 点「我的设备」→ 点「下线」→ 处理确认弹窗。

    自助页是独立界面（非 iframe 套娃）：账号框 id=nameInput，按钮「立即登录」。
    """
    log("打开自助服务中心: %s" % SELF_URL)
    driver.get(SELF_URL)

    # 轮询等页面就绪：要么出现登录表单，要么已经是登录态（有「我的设备」）
    deadline = time.time() + 12
    found = None
    already_logged = False
    while time.time() < deadline:
        try:
            f = driver.execute_script(DEEP_FIND_INPUTS)
        except Exception:
            f = None
        if f and f.get("user") and f.get("pass"):
            found = f
            break
        if "我的设备" in visible_text(driver):
            already_logged = True
            break
        check_browser()
        time.sleep(0.3)

    if found:
        log("自助服务需要登录，填写账号密码...")
        user_el, pass_el = found["user"], found["pass"]
        user_el.clear()
        user_el.send_keys(cfg["username"])
        pass_el.clear()
        pass_el.send_keys(cfg["password"])
        try:  # 协议/记住我勾选框，有就勾上
            if driver.execute_script(DEEP_ENSURE_AGREE):
                driver.execute_script(
                    "function walk(root){var els=root.querySelectorAll('input[type=checkbox],ion-checkbox');"
                    "for(var i=0;i<els.length;i++){if(els[i].offsetWidth||els[i].offsetHeight){els[i].click();return true;}"
                    "if(els[i].shadowRoot&&walk(els[i].shadowRoot))return true;}return false;}"
                    "return walk(document);")
                log("已勾选页面勾选框")
        except Exception:
            pass
        btn = driver.execute_script(DEEP_FIND_BUTTON)
        if btn is None:
            log("自助登录页没找到「立即登录」按钮", "ERROR")
            shot(driver, "self_no_btn")
            dump_page(driver, "self_no_btn")
            write_result(False, "自助服务登录页没找到登录按钮")
            return False
        try:
            btn.click()
        except Exception:
            driver.execute_script("arguments[0].click()", btn)
        log("已点击「立即登录」")

        # 等登录结果：出现「我的设备」= 成功；失败关键词 = 停手防锁号
        # 注意用可见文字判断，page_source 里的 i18n 资源键（如 account.locked）会误判
        deadline = time.time() + 20
        logged_in = False
        while time.time() < deadline:
            vtext = visible_text(driver)
            if "我的设备" in vtext:
                logged_in = True
                break
            for kw in FAIL_KEYWORDS:
                if kw in vtext:
                    log("自助服务登录失败，页面提示「%s」，停止重试" % kw, "ERROR")
                    shot(driver, "self_login_fail")
                    dump_page(driver, "self_login_fail")
                    write_result(False, "自助服务登录失败：「%s」，勿反复重试" % kw)
                    sys.exit(2)
            check_browser()
            time.sleep(0.3)
        if not logged_in:
            log("等待自助服务登录完成超时", "WARN")  # 不直接判死，继续试找「我的设备」
    else:
        log("自助服务无需登录（已是登录态）")

    # 点「我的设备」（带轮询重试，最多 8 秒）；个别版本登录后直接有下线按钮，一并兜底
    deadline = time.time() + 8
    clicked_dev = False
    while time.time() < deadline:
        if click_text_iframes(driver, "我的设备"):
            clicked_dev = True
            break
        if click_text_iframes(driver, "下线") or click_text_iframes(driver, "我要下线"):
            confirm_logout_dialog(driver)
            log("已直接点击下线按钮（无需进入我的设备）")
            return True
        check_browser()
        time.sleep(0.3)
    if not clicked_dev:
        log("自助中心没找到「我的设备」入口", "ERROR")
        shot(driver, "no_mydevice")
        dump_page(driver, "no_mydevice")
        write_result(False, "自助中心登录后没找到「我的设备」")
        return False
    log("已点击「我的设备」")

    # 等「下线」按钮渲染出来（最多 8 秒），出现立刻点
    deadline = time.time() + 8
    while time.time() < deadline:
        if "下线" in visible_text(driver):
            break
        check_browser()
        time.sleep(0.3)

    if not click_text_iframes(driver, "下线"):
        log("「我的设备」里没找到「下线」按钮", "ERROR")
        shot(driver, "no_logout_btn2")
        dump_page(driver, "no_logout_btn2")
        write_result(False, "进入「我的设备」但没找到「下线」按钮")
        return False
    log("已点击「下线」")
    # 先存档确认弹窗现场（万一确认失败，这就是证据）
    time.sleep(1)
    shot(driver, "before_confirm")
    dump_page(driver, "before_confirm")
    confirm_logout_dialog(driver)

    # 用户要求：下线后不再请求外网验证，直接认为成功并结束
    log("下线操作已完成")
    return True


# 收集页面「可见文字」（含 Shadow DOM），用于成败关键词判断。
# 不能直接用 page_source：里面混着 JS/CSS/i18n 资源（如 account.locked 翻译键），
# 会造成「locked」之类的关键词误判，登录刚成功就被当成失败退出。
DEEP_VISIBLE_TEXT = r"""
function walk(root, out) {
  var els = root.querySelectorAll('*');
  for (var i = 0; i < els.length; i++) {
    var el = els[i];
    if (el.children.length === 0 && (el.offsetWidth || el.offsetHeight)) {
      var t = el.textContent || '';
      if (t && t.trim()) out.push(t.trim());
    }
    if (el.shadowRoot) walk(el.shadowRoot, out);
  }
}
var out = [];
walk(document, out);
return out.join(' ');
"""


def visible_text(driver):
    """取当前上下文的可见文字（含 iframe 时需先切换）"""
    try:
        return driver.execute_script(DEEP_VISIBLE_TEXT) or ""
    except Exception:
        return ""


def confirm_logout_dialog(driver):
    """下线确认弹窗：优先 Ant Design/nz-modal 主按钮，其次按文字匹配按钮元素。
    教训：模糊匹配叶子文字会点中「确定要下线吗？」这类提示文字（点了个寂寞），
    所以只对 button/a/btn 类元素做包含匹配，叶子元素仅限精确匹配。"""
    try:
        driver.switch_to.alert.accept()
        log("已确认下线（原生弹窗）")
        return True
    except Exception:
        pass
    time.sleep(1)

    js = r"""
    var exact = ['确定', '确认', '确认下线', '是', 'OK', 'Yes'];
    var contains = ['确认下线'];
    function norm(s){return (s||'').replace(/\s+/g,'');}
    function vis(el){return el.offsetWidth||el.offsetHeight||el.getClientRects().length;}
    function tryClick(el){ el.click(); return norm(el.innerText||el.textContent||'ok'); }

    // 1) Ant Design / nz-modal 弹窗里的主按钮（通常在 footer 最后一个）
    var prim = document.querySelectorAll(
      '.ant-modal-footer .ant-btn-primary, .ant-modal .ant-btn-primary, ' +
      '.ant-modal-confirm-btns .ant-btn-primary, .modal .ant-btn-primary, .ant-btn-primary');
    for (var i = prim.length - 1; i >= 0; i--) {
      if (vis(prim[i])) return tryClick(prim[i]);
    }
    // 2) 任意可见 button/a/btn 元素：文字精确匹配
    var els = document.querySelectorAll('button, a, [class*=btn], [class*=button]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!vis(el)) continue;
      var t = norm(el.innerText || '');
      for (var j = 0; j < exact.length; j++) {
        if (t === exact[j]) return tryClick(el);
      }
    }
    // 3) 按钮元素：文字包含匹配（仅限「确认下线」这类动作词）
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (!vis(el)) continue;
      var t = norm(el.innerText || '');
      for (var j = 0; j < contains.length; j++) {
        if (t.indexOf(contains[j]) > -1) return tryClick(el);
      }
    }
    // 4) 穿透 Shadow DOM：叶子元素文字精确匹配（不做包含，防止点中提示文字）
    function walk(root) {
      var els = root.querySelectorAll('*');
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        if (el.children.length === 0 && vis(el)) {
          var t = norm(el.textContent || '');
          for (var j = 0; j < exact.length; j++) {
            if (t === exact[j]) return tryClick(el);
          }
        }
        if (el.shadowRoot) { var r = walk(el.shadowRoot); if (r) return r; }
      }
      return null;
    }
    return walk(document);
    """
    hit = driver.execute_script(js)
    if not hit:
        # 弹窗可能渲染慢，重试两轮
        for _ in range(2):
            time.sleep(1.5)
            hit = driver.execute_script(js)
            if hit:
                break
    if hit:
        log("已点击确认按钮（%s）" % hit)
        # 若弹窗还在（点到了别处），再补一刀
        time.sleep(1.5)
        still = driver.execute_script(
            "return !!(document.querySelector('.ant-modal, .ant-modal-wrap') && "
            "document.querySelector('.ant-modal').offsetWidth);")
        if still:
            hit2 = driver.execute_script(js)
            log("弹窗仍在，补点一次: %s" % hit2)
        return True
    log("没找到确认按钮，截图存档排查", "WARN")
    shot(driver, "confirm_not_found")
    dump_page(driver, "confirm_not_found")
    return False


def creds_missing(cfg):
    """判断账号密码是否还是模板占位/为空（首次运行）"""
    return (not cfg["username"] or cfg["username"] == "你的学号"
            or not cfg["password"] or cfg["password"] == "你的密码")


def prompt_credentials(cfg):
    """首次运行引导：控制台输入账号密码并存入本地 config.ini"""
    print("=" * 52)
    print("  首次使用，请配置校园网账号")
    print("  （此数据保存在本地，项目开源，不用担心）")
    print("  py: %s" % AUTHOR)
    print("=" * 52)
    username = ""
    while not username.strip():
        username = input("请输入校园网账号（学号/工号）: ").strip()
    # 用户要求密码明文输入（不回显的话没法确认自己打对了没有）
    while True:
        password = input("请输入校园网密码: ")
        if password:
            break
        print("密码不能为空，请重新输入")
    save_account(username, password)
    log("账号密码已保存到本地 config.ini")
    print("已保存到本地 config.ini，下次无需再输入\n")
    cfg["username"], cfg["password"] = username, password
    return cfg


def write_result(ok, detail):
    """写一个一眼能看懂的结果文件，断网跑完联网后先看这个"""
    path = os.path.join(LOG_DIR, "RESULT.txt")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write("[%s] %s — %s\n" % (stamp, "OK 登录成功" if ok else "FAIL 登录失败", detail))


def already_online(driver):
    """访问 https://www.baidu.com 判断是否真的在线。

    为什么用 https 的百度而不是 http 探测站：
    - 未认证时网关能「透明劫持」http 站点 —— URL 不变、内容被换成认证页，极具迷惑性
    - https 有证书校验，网关劫持不了：未认证时连接直接失败（超时/证书错误）
    - 判定标准：页面标题包含「百度」才算在线
    """
    try:
        # 探测专用短超时：未认证时 https 连不上，别傻等 30 秒
        driver.set_page_load_timeout(8)
        driver.get("https://www.baidu.com")
        title = driver.title or ""
        if "百度" in title:
            return True
        log("baidu 打开了但标题异常（%r），按未登录处理" % title, "WARN")
        return False
    except Exception as e:
        log("访问 baidu.com 失败（%s）→ 判定未登录" % str(e).split("\n")[0][:80])
        return False
    finally:
        try:
            driver.set_page_load_timeout(25)
        except Exception:
            pass


def wait_form(driver, timeout=25):
    """轮询等待表单出现：先在当前文档找，找不到就切进 iframe 再找。

    锐捷 SAM 门户的登录表单在 <iframe src="/cas-sso/login..."> 里，
    不切 frame 的话主文档里一个输入框都没有。
    返回 (found 或 None, 是否已切换到 iframe)。
    """
    deadline = time.time() + timeout
    switched = False
    while time.time() < deadline:
        try:
            found = driver.execute_script(DEEP_FIND_INPUTS)
            if found and found.get("user") and found.get("pass"):
                return found, switched
            if not switched:
                iframes = driver.find_elements("tag name", "iframe")
                for fr in iframes:
                    try:
                        driver.switch_to.frame(fr)
                        switched = True
                        log("已切入 iframe 表单")
                        break
                    except Exception:
                        continue
        except Exception:
            pass
        check_browser()
        time.sleep(0.3)
    return None, switched


def judge_result(driver):
    """综合判断登录结果，返回 (status, kw)：'fail' / 'success' / 'unknown'"""
    def scan(src):
        for kw in FAIL_KEYWORDS:
            if kw in src:
                return ("fail", kw)
        for kw in SUCCESS_KEYWORDS:
            if kw in src:
                return ("success", kw)
        return None

    result = None
    try:  # 当前上下文（可能在 iframe 里）
        result = scan(visible_text(driver))
    except Exception:
        pass
    try:  # 主文档（登录成功常整页跳转）
        driver.switch_to.default_content()
        result = result or scan(visible_text(driver))
    except Exception:
        pass
    if result:
        return result
    if already_online(driver):
        return ("success", "外网探测(baidu)")
    return ("unknown", "")


def post_login_wait(driver, timeout=20):
    """点完登录后轮询：服务弹窗 / 失败提示 / 成功提示，谁先出现算谁（可见文字判断）"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        src = visible_text(driver)
        if "请选择服务" in src:
            return ("service", "")
        for kw in FAIL_KEYWORDS:
            if kw in src:
                return ("fail", kw)
        for kw in SUCCESS_KEYWORDS:
            if kw in src:
                return ("success", kw)
        check_browser()
        time.sleep(0.3)
    return ("timeout", "")


def wait_service_options(driver, timeout=10):
    """等运营商选项渲染出来，返回选项文字列表（穿透 Shadow DOM）"""
    js = (r"function walk(root,out){var els=root.querySelectorAll('*');"
          r"for(var i=0;i<els.length;i++){var el=els[i];"
          r"if(el.classList&&el.classList.contains('service')&&(el.offsetWidth||el.offsetHeight)){"
          r"var t=(el.innerText||'').trim();if(t)out.push(t);}"
          r"if(el.shadowRoot)walk(el.shadowRoot,out);}}"
          r"var out=[];walk(document,out);return out;")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            opts = driver.execute_script(js)
            if opts:
                return opts
        except Exception:
            pass
        check_browser()
        time.sleep(0.3)
    return []


def click_text_deep(driver, text):
    """按精确文字点击元素（穿透 Shadow DOM），返回是否点到。

    注意：target 必须存进闭包变量。如果直接在 walk 里写 arguments[0]，
    递归调用时 arguments 会指向 walk 自己的参数（root），永远匹配不上。
    """
    return driver.execute_script(
        r"var target = arguments[0];"
        r"function walk(root){var els=root.querySelectorAll('*');"
        r"for(var i=0;i<els.length;i++){var el=els[i];"
        r"var t=(el.innerText||'').replace(/\s+/g,'');"
        r"if(t===target&&el.children.length===0&&(el.offsetWidth||el.offsetHeight)){el.click();return true;}"
        r"if(el.shadowRoot&&walk(el.shadowRoot))return true;}return false;}"
        r"return walk(document);", text)


def handle_service_dialog(driver, cfg, interactive):
    """处理登录后的「请选择服务」弹窗。

    优先级：config 里已配置 → 自动选；
    未配置且是交互运行 → 控制台让用户选，并保存到 config；
    未配置且是开机自启 → 默认选第 1 个并警告。
    """
    opts = wait_service_options(driver, 10)
    if not opts:
        log("检测到服务选择弹窗但没抓到选项文字", "ERROR")
        shot(driver, "service_no_opts")
        dump_page(driver, "service_no_opts")
        write_result(False, "服务弹窗出现但没抓到选项")
        return False

    log("检测到运营商选择弹窗: %s" % " / ".join(opts))
    choice = None
    if cfg["service"]:
        for o in opts:
            if cfg["service"] in o or o in cfg["service"]:
                choice = o
                break
        if choice:
            log("按配置自动选择运营商: %s" % choice)

    if choice is None and interactive:
        try:
            print("\n" + "=" * 46)
            print("检测到运营商选择，请选择你的运营商:")
            for idx, o in enumerate(opts, 1):
                print("  %d. %s" % (idx, o))
            ans = input("输入编号后回车（直接回车 = 第 1 个）: ").strip()
            sel = int(ans) if ans.isdigit() and 1 <= int(ans) <= len(opts) else 1
            choice = opts[sel - 1]
            save_service(choice)
            print("已保存到 config.ini，下次自动选「%s」" % choice)
            print("=" * 46 + "\n")
            log("用户选择运营商: %s（已写入 config.ini）" % choice)
        except Exception as e:
            log("交互选择失败: %s" % e, "WARN")

    if choice is None:
        choice = opts[0]
        log("无法交互且未配置 service，默认选第 1 个: %s（建议在 config.ini 填 service）" % choice, "WARN")

    if not click_text_deep(driver, choice):
        log("点击运营商选项失败: %s" % choice, "ERROR")
        shot(driver, "service_click_fail")
    else:
        log("已点击运营商选项: %s" % choice)
    time.sleep(1)
    if click_text_deep(driver, "确定"):
        log("已点击确定")
    else:
        log("没找到确定按钮，尝试截图排查", "ERROR")
        shot(driver, "no_confirm")
        dump_page(driver, "no_confirm")
    # 轮询等弹窗消失（最多 6 秒），消失即继续
    deadline = time.time() + 6
    while time.time() < deadline:
        if "请选择服务" not in visible_text(driver):
            break
        check_browser()
        time.sleep(0.3)
    return True


def do_login(driver, cfg, interactive=True):
    """打开认证页并提交表单，返回 True/False"""
    driver.get(cfg["url"])

    # 开机自启时网络可能还没就绪，多等一会儿（interactive=False 即 boot 模式）
    log("等待登录表单渲染（最多 %d 秒，含 iframe）..." % (25 if interactive else 40))
    found, switched = wait_form(driver, 25 if interactive else 40)
    if not (found and found.get("user") and found.get("pass")):
        # 表单没出现：最常见的非故障原因是「本来就在线」（认证页不显示表单）。
        # 这时才做一次 baidu 探测兜底，平时零开销。
        if already_online(driver):
            log("认证页无表单，baidu 探测网络已通 —— 本来就在线，无需登录")
            write_result(True, "无表单+baidu 探测在线，未执行登录")
            return True
        log("没等到账号/密码输入框，页面结构可能特殊，请重跑侦查模式", "ERROR")
        shot(driver, "no_inputs")
        dump_page(driver, "no_inputs")
        write_result(False, "没找到输入框（含 iframe 查找），详见截图/页面源码")
        return False
    log("已定位输入框（页面共 %d 个可见输入元素）" % found["count"])

    user_el = found["user"]
    pass_el = found["pass"]
    user_el.clear()
    user_el.send_keys(cfg["username"])
    pass_el.clear()
    pass_el.send_keys(cfg["password"])
    log("已填入账号密码")

    # 确保协议勾选框勾上（没勾的话登录会被拦）
    try:
        if driver.execute_script(DEEP_ENSURE_AGREE):
            driver.execute_script(
                "function walk(root){var els=root.querySelectorAll('input[type=checkbox],ion-checkbox');"
                "for(var i=0;i<els.length;i++){if(els[i].offsetWidth||els[i].offsetHeight){els[i].click();return true;}"
                "if(els[i].shadowRoot&&walk(els[i].shadowRoot))return true;}return false;}"
                "return walk(document);")
            log("已自动勾选协议勾选框")
    except Exception as e:
        log("协议勾选框处理失败: %s" % e, "WARN")

    # 登录页若已带服务下拉，按配置直接选（没有就跳过）
    if cfg["service"]:
        try:
            hit = driver.execute_script(
                "var target = arguments[0];"
                "function walk(root){var els=root.querySelectorAll('option,li,span,ion-select-option,ion-radio');"
                "for(var i=0;i<els.length;i++){var t=(els[i].innerText||els[i].value||'').trim();"
                "if(t&&t.indexOf(target)>-1){els[i].click();return true;}"
                "if(els[i].shadowRoot&&walk(els[i].shadowRoot))return true;}return false;}"
                "return walk(document);", cfg["service"])
            if hit:
                log("登录页已有服务选项，已按配置选择: %s" % cfg["service"])
        except Exception as e:
            log("登录页选择服务失败（不影响主流程）: %s" % e, "WARN")

    btn = driver.execute_script(DEEP_FIND_BUTTON)
    if btn is None:
        log("没找到登录按钮，请重跑侦查模式确认按钮文字", "ERROR")
        shot(driver, "no_button")
        dump_page(driver, "no_button")
        write_result(False, "没找到登录按钮")
        return False
    try:
        btn.click()  # 原生 click，对 Shadow DOM 宿主元素有效
    except Exception:
        driver.execute_script("arguments[0].click()", btn)  # 兜底：JS click
    log("已点击登录按钮")
    check_browser()
    time.sleep(1)
    try:  # 服务弹窗在主文档，先切回去
        driver.switch_to.default_content()
    except Exception:
        pass

    # 点完登录后可能有三种走向：服务弹窗 / 失败提示 / 直接成功
    verdict, kw = post_login_wait(driver, 20)
    if verdict == "fail":
        log("登录失败，页面出现关键词「%s」，停止重试（防止锁号）" % kw, "ERROR")
        shot(driver, "login_fail")
        dump_page(driver, "login_fail")
        write_result(False, "页面提示「%s」——检查账号密码，请勿反复重试" % kw)
        sys.exit(2)
    if verdict == "service":
        if not handle_service_dialog(driver, cfg, interactive):
            return False

    # 最终判定
    status, kw = judge_result(driver)
    if status == "fail":
        log("登录失败，页面出现关键词「%s」，停止重试（防止锁号）" % kw, "ERROR")
        shot(driver, "login_fail")
        dump_page(driver, "login_fail")
        write_result(False, "页面提示「%s」——检查账号密码，请勿反复重试" % kw)
        sys.exit(2)
    if status == "success":
        log("登录成功（依据：%s）" % kw)
        write_result(True, "页面提示「%s」" % kw)
        return True
    shot(driver, "login_unknown")
    dump_page(driver, "login_unknown")
    write_result(False, "提交后外网仍不通且页面无明确提示，详见截图/页面源码")
    log("登录结果未知，外网仍不通", "ERROR")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="登录一次")
    ap.add_argument("--boot", action="store_true", help="开机自启模式（静默）")
    ap.add_argument("--visible", action="store_true", help="显示浏览器窗口")
    ap.add_argument("--silent", action="store_true", help="强制静默（不显示浏览器窗口），GUI 用")
    ap.add_argument("--offline", action="store_true", help="先点「我要下线」断网，等 10 秒再登录")
    ap.add_argument("--logout-only", action="store_true", help="仅断开校园网（点「我要下线」+等 10 秒），不重新登录")
    ap.add_argument("--clear-creds", action="store_true", help="一键清除本地保存的账号密码")
    args = ap.parse_args()

    show_banner()

    # 一键清除账号密码：不需要打开浏览器，确认后清空并退出
    if args.clear_creds:
        print("=" * 46)
        print("  将清除本地 config.ini 中保存的账号密码")
        print("  （清除后下次登录会重新引导输入）")
        print("=" * 46)
        ans = input("确认清除？(y/n): ").strip().lower()
        if ans in ("y", "yes"):
            clear_account()
            print("已清除账号密码。")
            log("用户已清除本地账号密码")
        else:
            print("已取消。")
        return

    cfg = load_config()

    # 仅下线不需要账号密码，其余模式先确保凭据已配置
    if not args.logout_only:
        if creds_missing(cfg):
            if args.boot:
                log("config.ini 未配置账号密码，开机自启无法登录", "ERROR")
                write_result(False, "未配置账号密码，请先手动运行一次完成首次配置")
                sys.exit(2)
            cfg = prompt_credentials(cfg)
    if not cfg["url"]:
        # 没填认证页地址，先探测一次并写回
        from inspect_page import find_portal
        driver = make_driver(headless=not args.visible, browser=cfg.get("browser", "edge"))
        try:
            cfg["url"] = find_portal(driver, "")
        finally:
            driver.quit()

    # --visible 强制显示窗口；否则按 config.ini 的 headless（默认 false → 有头窗口）
    headless = args.silent or ((not args.visible) and cfg["headless"])

    # 仅下线模式：优先点「我要下线」；找不到就重新登录，走「我的设备」→「下线」
    if args.logout_only:
        driver = None
        try:
            driver = make_driver(headless=headless, browser=cfg.get("browser", "edge"))
            start_watchdog(driver)
            log("=" * 60)
            log("仅下线模式启动（自助服务中心）")
            # 自助服务要用账号密码登录，缺就现场引导输入
            if creds_missing(cfg):
                if args.boot:
                    log("未配置账号密码，无法登录自助服务中心下线", "ERROR")
                    write_result(False, "未配置账号密码，无法下线")
                    sys.exit(2)
                cfg = prompt_credentials(cfg)
            ok = False
            if do_logout(driver, cfg):
                ok = True
                how = "自助服务中心下线"
            if ok:
                log("等待 10 秒让下线生效...")
                time.sleep(10)
                check_browser()
                write_result(True, "%s，已等待 10 秒，未重连" % how)
                log("下线完成")
                code = 0
            else:
                code = 1
            sys.exit(code)
        except SystemExit:
            raise
        except BrowserClosed:
            log("浏览器窗口已关闭，结束当前下线任务")
            write_result(False, "浏览器窗口被手动关闭，下线任务已结束")
            sys.exit(0)
        except Exception as e:
            log("下线流程出错: %s" % e, "ERROR")
            if driver:
                shot(driver, "logout_error")
            write_result(False, "下线流程异常: %s" % e)
            sys.exit(1)
        finally:
            stop_watchdog()
            if driver:
                driver.quit()
                log("浏览器已关闭")

    log("=" * 60)
    log("启动登录流程 (boot=%s, headless=%s)" % (args.boot, headless))
    driver = None
    try:
        driver = make_driver(headless=headless, browser=cfg.get("browser", "edge"))
        start_watchdog(driver)
        if args.offline:
            # 断线重连：先下线，等 10 秒，再走完整登录流程
            if not do_logout(driver, cfg):
                sys.exit(1)
            log("等待 10 秒让下线生效...")
            time.sleep(10)
            check_browser()
        log("开始登录 %s" % cfg["url"])
        if do_login(driver, cfg, interactive=not args.boot):
            log("登录完成")
        else:
            log("登录未确认成功，请查看 logs/ 下的 RESULT.txt、截图和页面源码", "ERROR")
            sys.exit(1)
    except SystemExit:
        raise
    except BrowserClosed:
        log("浏览器窗口已关闭，结束当前登录任务")
        write_result(False, "浏览器窗口被手动关闭，登录任务已结束")
        sys.exit(0)
    except Exception as e:
        log("登录流程出错: %s" % e, "ERROR")
        if driver:
            shot(driver, "error")
            dump_page(driver, "error")
        write_result(False, "脚本异常: %s" % e)
        sys.exit(1)
    finally:
        stop_watchdog()
        if driver:
            driver.quit()
            log("浏览器已关闭")


if __name__ == "__main__":
    main()
