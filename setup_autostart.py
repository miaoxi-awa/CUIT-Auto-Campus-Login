# -*- coding: utf-8 -*-
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(_sys.argv[0])))
"""开机自启管理。

exe 模式：写注册表 HKCU Run 键（比「启动」文件夹先执行，开机更早拉起登录，
不需要管理员权限），并清理旧版启动文件夹 VBS。
脚本模式：沿用启动文件夹 VBS。

用法:
    python setup_autostart.py install    # 安装自启
    python setup_autostart.py uninstall  # 取消自启
    python setup_autostart.py status     # 查询状态
"""
import os
import sys

try:
    import winreg
except ImportError:  # 非 Windows（理论用不到，项目只跑 Windows）
    winreg = None

from common import BASE_DIR, log

STARTUP_DIR = os.path.join(os.environ["APPDATA"],
                           "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
VBS_PATH = os.path.join(STARTUP_DIR, "CampusLogin.vbs")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CampusLogin"


def _registry_install(exe_path):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, '"%s" --boot' % exe_path)


def _registry_uninstall():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_NAME)
    except OSError:
        pass  # 本来就没有


def _registry_installed():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, RUN_NAME)
        return True
    except OSError:
        return False


def is_installed():
    """GUI 按钮文案用：exe 模式查注册表，脚本模式查 VBS"""
    if getattr(sys, "frozen", False) and winreg:
        return _registry_installed()
    return os.path.exists(VBS_PATH)


def get_interpreters():
    """返回 (pythonw, python)。exe 打包后就是它自己；否则优先内置 runtime"""
    if getattr(sys, "frozen", False):
        return sys.executable, sys.executable
    runtime_pyw = os.path.join(BASE_DIR, "runtime", "pythonw.exe")
    runtime_py = os.path.join(BASE_DIR, "runtime", "python.exe")
    if os.path.exists(runtime_pyw):
        return runtime_pyw, runtime_py
    venv_dir = os.path.join(BASE_DIR, ".venv")
    venv_pyw = os.path.join(venv_dir, "Scripts", "pythonw.exe")
    venv_py = os.path.join(venv_dir, "Scripts", "python.exe")
    if os.path.exists(venv_pyw):
        return venv_pyw, venv_py
    wb = r"C:\Users\LENOVO\.workbuddy\binaries\python\envs\default\Scripts"
    pyw = os.path.join(wb, "pythonw.exe")
    py = os.path.join(wb, "python.exe")
    if os.path.exists(py):
        return pyw, py
    return sys.executable, sys.executable


def install():
    frozen = getattr(sys, "frozen", False)
    if frozen and winreg:
        # exe 模式：注册表 Run 键，比启动文件夹先执行，开机更早联网
        exe = sys.executable
        _registry_install(exe)
        if os.path.exists(VBS_PATH):  # 旧版启动文件夹 VBS 迁移清理
            try:
                os.remove(VBS_PATH)
                log("已清理旧版启动文件夹自启项")
            except OSError:
                pass
        if not _registry_installed():
            log("注册表 Run 键写入失败", "ERROR")
            return 1
        log("已安装开机自启（注册表 Run，早于启动文件夹执行）: %s" % exe)
        return 0

    # 脚本模式：沿用启动文件夹 VBS
    pyw, py = get_interpreters()
    script = os.path.join(BASE_DIR, "main.py")
    if not os.path.exists(script):
        log("找不到 main.py: %s" % script, "ERROR")
        return 1
    run_line = 'sh.Run """" & pyw & """ """ & py & """", 0, False'
    lines = [
        "Option Explicit",
        "Dim fso, sh, baseDir, pyw, py",
        'Set fso = CreateObject("Scripting.FileSystemObject")',
        'Set sh  = CreateObject("WScript.Shell")',
        'baseDir = "%s"' % BASE_DIR,
        'pyw = "%s"' % pyw,
        'py = "%s"' % script,
        "If Not fso.FileExists(pyw) Or Not fso.FileExists(py) Then WScript.Quit 1",
        "sh.CurrentDirectory = baseDir",
        run_line,
    ]
    # 必须 UTF-16LE+BOM（Python 的 utf-16 带 BOM），否则中文路径乱码、静默失败
    with open(VBS_PATH, "w", encoding="utf-16") as f:
        f.write("\r\n".join(lines) + "\r\n")
    # 读回来核对：exe 模式校验自身路径 + --boot 启动行；脚本模式校验 pythonw
    with open(VBS_PATH, "r", encoding="utf-16") as f:
        content = f.read()
    ok = ('pyw = "%s"' % pyw) in content and run_line in content
    if not ok:
        log("VBS 内容异常，请检查", "ERROR")
        return 1
    log("已安装开机自启: %s" % VBS_PATH)
    log("启动目标: %s" % pyw)
    return 0


def uninstall():
    removed = False
    if winreg and _registry_installed():
        _registry_uninstall()
        removed = True
        log("已取消开机自启（注册表 Run）")
    if os.path.exists(VBS_PATH):
        os.remove(VBS_PATH)
        removed = True
        log("已取消开机自启（启动文件夹 VBS）")
    if not removed:
        log("本来就没有自启项")
    return 0


def status():
    if winreg and _registry_installed():
        log("开机自启: 已安装（注册表 Run）")
    elif os.path.exists(VBS_PATH):
        log("开机自启: 已安装 (%s)" % VBS_PATH)
    else:
        log("开机自启: 未安装")
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    sys.exit({"install": install, "uninstall": uninstall, "status": status}.get(
        action, lambda: (log("未知操作: %s" % action, "ERROR"), 1)[1])())
