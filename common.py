# -*- coding: utf-8 -*-
"""公共模块：配置加载、日志、Edge 驱动初始化"""
import configparser
import os
import sys
from datetime import datetime

# pythonw.exe 下 stdout/stderr 是 None，先兜底，否则 print 直接抛异常
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

# 署名
AUTHOR = "miaoxiawa"

# 内置默认认证页地址 / 运营商：单文件 exe 没有模板也能正确生成 config
DEFAULT_URL = "http://10.254.241.66/portal/entry/pc/authenticate;flowParams=undefined;from="
DEFAULT_SERVICE = "移动"

# 打包成 exe 后，__file__ 指向临时解压目录，配置必须跟着 exe 走
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    LOG_DIR = os.path.join(BASE_DIR, "logs")
    os.makedirs(LOG_DIR, exist_ok=True)
    CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")

_log_file = None


def _get_log_file():
    global _log_file
    if _log_file is None:
        name = datetime.now().strftime("%Y-%m-%d") + ".log"
        _log_file = open(os.path.join(LOG_DIR, name), "a", encoding="utf-8")
    return _log_file


def log(msg, level="INFO"):
    line = "[%s] [%-5s] %s" % (datetime.now().strftime("%H:%M:%S"), level, msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        f = _get_log_file()
        f.write(line + "\n")
        f.flush()
    except Exception:
        pass


def load_config():
    """返回 dict: username, password, url, service, headless

    config.ini 不存在时（新电脑首次运行），自动生成初始配置：
    优先用旁边的 config.example.ini；没有模板也行 —— 认证页地址和运营商
    已内置在程序里（DEFAULT_URL / DEFAULT_SERVICE），单文件 exe 也能用。"""
    if not os.path.exists(CONFIG_PATH):
        example = os.path.join(os.path.dirname(CONFIG_PATH), "config.example.ini")
        if os.path.exists(example):
            import shutil
            shutil.copyfile(example, CONFIG_PATH)
            log("config.ini 不存在，已用模板生成初始配置（认证页地址已带，只需补账号密码）")
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    url = cfg.get("portal", "url", fallback="").strip()
    # 为空、或被探测地址污染（旧版本 bug 会把 captive.apple.com 写进来）→ 自动纠正
    if not url or "captive.apple.com" in url or "baidu.com" in url:
        url = DEFAULT_URL
        _set_config("portal", "url", url)
        log("config 里 url 为空或无效，已写入内置默认认证页地址")
    service = cfg.get("portal", "service", fallback="").strip()
    if not service:
        service = DEFAULT_SERVICE
        _set_config("portal", "service", service)
        log("config 里 service 为空，已写入内置默认运营商「%s」" % service)
    browser = cfg.get("browser", "browser", fallback="").strip().lower()
    if not browser:
        browser = detect_browsers()[0][0]  # 本机检测到的第一个浏览器
        _set_config("browser", "browser", browser)
        log("config 里未指定浏览器，已自动选用本机的「%s」" % browser)
    return {
        "username": cfg.get("account", "username", fallback="").strip(),
        "password": cfg.get("account", "password", fallback="").strip(),
        "url": url,
        "service": service,
        "browser": browser,
        "headless": cfg.get("browser", "headless", fallback="false").strip().lower() == "true",
    }


def save_browser(browser):
    """把用户选择的自动化浏览器写回 config.ini"""
    _set_config("browser", "browser", browser)


def save_url(url):
    """侦查到真实认证页后，把 URL 写回 config.ini，下次不用再探测。
    校验：必须是 http(s) 内网地址，拒绝 data: 之类的无效值（真实案例：探测时
    current_url 抓到 "data:," 被写进配置，导致下次直接打不开认证页）。"""
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")) or u.lower().startswith("data:"):
        log("探测到无效认证页地址「%s」，拒绝写入配置" % u[:50], "WARN")
        return
    # 探测用的公网地址绝不能当认证页写进去（真实案例：在线状态探测不跳转，
    # captive.apple.com 自己被当成"认证页"写进配置，下次直接打不开登录页）
    if "captive.apple.com" in u or "baidu.com" in u:
        log("探测到的是探测/测试地址「%s」，不是认证页，拒绝写入配置" % u[:60], "WARN")
        return
    _set_config("portal", "url", u)


def save_service(name):
    """把用户选的运营商写回 config.ini，下次自动选"""
    _set_config("portal", "service", name)


def save_account(username, password):
    """首次运行时把控制台输入的账号密码写回 config.ini"""
    _set_config("account", "username", username)
    _set_config("account", "password", password)


def clear_account():
    """一键清除账号密码（还原为占位符，下次运行会重新引导输入）"""
    _set_config("account", "username", "你的学号")
    _set_config("account", "password", "你的密码")


def _set_config(section, key, value):
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, value)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write("# 校园网自动登录配置\n")
        cfg.write(f)


BROWSER_DEFS = [
    ("edge", "Edge", "msedge.exe", [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]),
    ("chrome", "Chrome", "chrome.exe", [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]),
    ("firefox", "Firefox", "firefox.exe", [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ]),
]


def _reg_app_path(exe_name):
    """查注册表 App Paths —— 能定位自定义安装目录（如 D:\\firefox\\firefox.exe）"""
    try:
        import winreg
    except ImportError:
        return None
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s" % exe_name
    sub32 = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\%s" % exe_name
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for path in (sub, sub32):
            try:
                with winreg.OpenKey(root, path) as k:
                    val, _ = winreg.QueryValueEx(k, "")
                if val and os.path.exists(val):
                    return val
            except OSError:
                continue
    return None


def _scan_drive_roots(exe_name, keyword):
    """扫各盘根目录一层，找自定义安装的浏览器（如 D:\\firefox\\firefox.exe）"""
    import string
    for letter in string.ascii_uppercase:
        for drive in ("%s:\\" % letter,):
            try:
                if not os.path.exists(drive):
                    continue
                for entry in os.listdir(drive):
                    low = entry.lower()
                    if keyword not in low:
                        continue
                    cand = os.path.join(drive, entry, exe_name)
                    if os.path.isfile(cand):
                        return cand
            except OSError:
                continue
    return None


def find_browser(key):
    """返回指定浏览器的可执行文件路径（找不到返回 None）"""
    for k, _name, exe_name, paths in BROWSER_DEFS:
        if k != key:
            continue
        for p in paths:
            if os.path.exists(p):
                return p
        p = _reg_app_path(exe_name)
        if p:
            return p
        return _scan_drive_roots(exe_name, k)
    return None


def detect_browsers():
    """探测本机已安装的浏览器，返回 [(key, 显示名, exe路径或None), ...]"""
    found = []
    for key, name, exe_name, paths in BROWSER_DEFS:
        p = next((x for x in paths if os.path.exists(x)), None)
        if not p:
            p = _reg_app_path(exe_name) or _scan_drive_roots(exe_name, key)
        if p:
            found.append((key, name, p))
    if not found:
        found = [("edge", "Edge", None)]  # 兜底：交给 Selenium Manager
    return found


def make_driver(headless=False, browser="edge"):
    """启动浏览器（edge/chrome/firefox）。必须在创建 driver 之前设置 no_proxy，
    否则 Selenium 连本机 WebDriver 端口会被系统代理劫持而失败。
    注意：首次使用某浏览器时 Selenium Manager 需联网下载对应驱动。"""
    os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"

    from selenium import webdriver

    exe_path = find_browser(browser)  # 自定义安装目录（如 D:\firefox）也能识别

    args = [
        "--ignore-certificate-errors",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        # 校园网网关/内网劫持依赖直连，绕开系统代理
        "--no-proxy-server",
        "--proxy-bypass-list=*",
    ]

    if browser == "chrome":
        options = webdriver.ChromeOptions()
        for a in args:
            options.add_argument(a)
        if headless:
            options.add_argument("--headless=new")
        _set_eager(options)
        if exe_path:
            options.binary_location = exe_path
        driver = webdriver.Chrome(options=options)
    elif browser == "firefox":
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("-headless")
        _set_eager(options)
        options.set_preference("network.proxy.type", 0)  # 直连，绕开系统代理
        if exe_path:
            options.binary_location = exe_path
        driver = webdriver.Firefox(options=options)
    else:
        options = webdriver.EdgeOptions()
        for a in args:
            options.add_argument(a)
        if headless:
            options.add_argument("--headless=new")
        _set_eager(options)
        if exe_path:
            options.binary_location = exe_path
        driver = webdriver.Edge(options=options)

    driver.set_page_load_timeout(25)
    return driver


def _set_eager(options):
    """eager：DOM 就绪就继续，不等图片等慢资源（提速；元素出现靠轮询保证）"""
    try:
        options.page_load_strategy = "eager"
    except Exception:
        pass


def shot(driver, name):
    """出错截图，存到 logs/ 下方便排查"""
    try:
        path = os.path.join(LOG_DIR, "%s_%s.png" % (datetime.now().strftime("%Y%m%d_%H%M%S"), name))
        driver.save_screenshot(path)
        log("截图已保存: %s" % path)
    except Exception as e:
        log("截图失败: %s" % e, "WARN")


def dump_page(driver, name):
    """落盘页面源码，远程排查用"""
    try:
        path = os.path.join(LOG_DIR, "%s_%s.html" % (datetime.now().strftime("%Y%m%d_%H%M%S"), name))
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(driver.page_source)
        log("页面源码已保存: %s" % path)
    except Exception as e:
        log("dump 失败: %s" % e, "WARN")
