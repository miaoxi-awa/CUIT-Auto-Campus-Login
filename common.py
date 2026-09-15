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
    """返回 dict: username, password, url, service, headless"""
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return {
        "username": cfg.get("account", "username", fallback="").strip(),
        "password": cfg.get("account", "password", fallback="").strip(),
        "url": cfg.get("portal", "url", fallback="").strip(),
        "service": cfg.get("portal", "service", fallback="").strip(),
        "headless": cfg.get("browser", "headless", fallback="false").strip().lower() == "true",
    }


def save_url(url):
    """侦查到真实认证页后，把 URL 写回 config.ini，下次不用再探测"""
    _set_config("portal", "url", url)


def save_service(name):
    """把用户选的运营商写回 config.ini，下次自动选"""
    _set_config("portal", "service", name)


def save_account(username, password):
    """首次运行时把控制台输入的账号密码写回 config.ini"""
    _set_config("account", "username", username)
    _set_config("account", "password", password)


def _set_config(section, key, value):
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, value)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write("# 校园网自动登录配置\n")
        cfg.write(f)


def make_driver(headless=False):
    """启动 Edge。必须在创建 driver 之前设置 no_proxy，
    否则 Selenium 连本机 WebDriver 端口会被系统代理劫持而失败。"""
    os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"

    from selenium import webdriver

    options = webdriver.EdgeOptions()
    args = [
        "--ignore-certificate-errors",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        # 校园网网关/内网劫持依赖直连，绕开系统代理
        "--no-proxy-server",
        "--proxy-bypass-list=*",
    ]
    for a in args:
        options.add_argument(a)
    if headless:
        options.add_argument("--headless=new")

    driver = webdriver.Edge(options=options)
    driver.set_page_load_timeout(30)
    return driver


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
