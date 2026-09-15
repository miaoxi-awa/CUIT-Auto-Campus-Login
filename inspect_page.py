# -*- coding: utf-8 -*-
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(_sys.argv[0])))
"""侦查模式 v2：穿透 Shadow DOM，轮询等待 SPA 渲染，dump 输入框/按钮/文字，不提交。

用法:
    python inspect_page.py            # 用 config.ini 里的 url（为空则自动探测跳转）
    python inspect_page.py <url>      # 用命令行指定的 url
"""
import json
import os
import sys
import time

from common import BASE_DIR, load_config, log, make_driver, shot, dump_page, save_url

# 用于探测认证页跳转的地址（http 站点，会被校园网网关劫持）
PROBE_URL = "http://captive.apple.com"

# 穿透 Shadow DOM 的深度遍历 JS：收集 input / 可点击元素 / 可见文字
DEEP_COLLECT = r"""
function walk(root, inputs, clicks, texts, seen) {
  var els = root.querySelectorAll('*');
  for (var i = 0; i < els.length; i++) {
    var el = els[i];
    var tag = el.tagName;
    if ((tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') && !el.dataset.__seen) {
      el.dataset.__seen = '1';
      inputs.push({
        tag: tag, type: el.type || '', id: el.id || '', name: el.name || '',
        ph: el.placeholder || '',
        fcn: el.getAttribute('formcontrolname') || el.getAttribute('ng-reflect-name') || '',
        visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
      });
    }
    var t = '';
    try { t = (el.innerText || '').replace(/\s+/g, ' ').trim(); } catch (e) {}
    if (tag === 'BUTTON' || tag === 'ION-BUTTON' || tag === 'A' || /btn|button|login/i.test(el.className || '')) {
      clicks.push({tag: tag, id: el.id || '', text: t.slice(0, 40),
                   cls: (el.className && el.className.toString ? el.className.toString() : '').slice(0, 60)});
    }
    if (t && t.length <= 40 && !seen[t]) { seen[t] = 1; texts.push(t); }
    if (el.shadowRoot) walk(el.shadowRoot, inputs, clicks, texts, seen);
  }
}
var out = {inputs: [], clicks: [], texts: []}, seen = {};
walk(document, out.inputs, out.clicks, out.texts, seen);
out.texts = out.texts.slice(0, 60);
return out;
"""


def wait_for_form(driver, timeout=25):
    """轮询等待 SPA 渲染出输入框（穿透 Shadow DOM），主文档没有就切进 iframe 再找"""
    deadline = time.time() + timeout
    switched = False
    while time.time() < deadline:
        info = driver.execute_script(DEEP_COLLECT)
        if info["inputs"]:
            return info
        if not switched:
            iframes = driver.find_elements("tag name", "iframe")
            for fr in iframes:
                try:
                    driver.switch_to.frame(fr)
                    switched = True
                    log("主文档没有表单，已切入 iframe 继续找")
                    break
                except Exception:
                    continue
        time.sleep(1)
    return None


def find_portal(driver, cfg_url):
    """拿到认证页 URL：优先用配置里的；没有就访问探测地址，取浏览器最终地址"""
    if cfg_url:
        driver.get(cfg_url)
    else:
        log("config 里没填 url，先用 %s 探测跳转..." % PROBE_URL)
        driver.get(PROBE_URL)
        time.sleep(3)
    final = driver.current_url
    log("当前页面地址: %s" % final)
    if not cfg_url and "captive.apple.com" in final:
        log("访问外网未被跳转到认证页 —— 可能校园网本来就是通的，或需要手动访问认证地址", "WARN")
    if not cfg_url:
        save_url(final)
        log("已把探测到的认证页地址写回 config.ini")
    return final


def main():
    url_override = sys.argv[1] if len(sys.argv) > 1 else ""
    cfg = load_config()
    if url_override:
        cfg["url"] = url_override

    driver = None
    try:
        driver = make_driver(headless=False)  # 侦查一律有头，方便肉眼确认
        log("打开浏览器...")
        portal = find_portal(driver, cfg["url"])

        # SPA（Angular/Ionic）渲染慢，轮询等待而不是固定 sleep
        log("等待页面渲染（最多 25 秒）...")
        info = wait_for_form(driver, 25)

        if not info:
            log("25 秒内没等到输入框出现！页面可能需要点击某个入口（如「继续上网」按钮）", "ERROR")
            shot(driver, "inspect_no_form")
            dump_page(driver, "inspect_no_form")
            sys.exit(1)

        report = {"final_url": portal, **info}
        path = os.path.join(BASE_DIR, "logs", "inspect_result.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        log("=" * 60)
        log("输入框 (%d 个):" % len(info["inputs"]))
        for i in info["inputs"]:
            log("  <%s> type=%-8s id=%-15s name=%-12s fcn=%-12s ph=%s visible=%s"
                % (i["tag"].lower(), i["type"], i["id"] or "-", i["name"] or "-",
                   i["fcn"] or "-", i["ph"] or "-", i["visible"]))
        log("按钮/链接 (%d 个):" % len(info["clicks"]))
        for b in info["clicks"][:25]:
            log("  <%s> id=%-15s text=%-25s cls=%s" % (b["tag"].lower(), b["id"] or "-", b["text"] or "-", b["cls"] or "-"))
        log("页面关键文字: %s" % " | ".join(info["texts"][:25]))
        log("=" * 60)
        log("侦查结果已存到: %s" % path)
        shot(driver, "inspect")
        dump_page(driver, "inspect")
        log("侦查完成")
    except SystemExit:
        raise
    except Exception as e:
        log("侦查出错: %s" % e, "ERROR")
        if driver:
            shot(driver, "inspect_error")
            dump_page(driver, "inspect_error")
        raise
    finally:
        if driver:
            driver.quit()
            log("浏览器已关闭")


if __name__ == "__main__":
    main()
