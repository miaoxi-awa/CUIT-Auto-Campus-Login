# -*- coding: utf-8 -*-
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(_sys.argv[0])))
"""开机自启管理：往「启动」文件夹写/删 VBS（不需要管理员权限）。

用法:
    python setup_autostart.py install    # 安装自启
    python setup_autostart.py uninstall  # 取消自启
    python setup_autostart.py status     # 查询状态
"""
import os
import sys

from common import BASE_DIR, log

STARTUP_DIR = os.path.join(os.environ["APPDATA"],
                           "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
VBS_PATH = os.path.join(STARTUP_DIR, "CampusLogin.vbs")


def get_interpreters():
    """返回 (pythonw, python)。优先内置便携 runtime，其次项目 .venv，最后 WorkBuddy venv"""
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
    pyw, py = get_interpreters()
    script = os.path.join(BASE_DIR, "main.py")
    if not os.path.exists(script):
        log("找不到 main.py: %s" % script, "ERROR")
        return 1
    # 注意：第三个参数必须是脚本路径，不能误传 python.exe
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
        'sh.Run """" & pyw & """ """ & py & """ --boot", 0, False',
    ]
    # 必须 UTF-16LE+BOM（Python 的 utf-16 带 BOM），否则中文路径乱码、静默失败
    with open(VBS_PATH, "w", encoding="utf-16") as f:
        f.write("\r\n".join(lines) + "\r\n")
    # 读回来核对：Run 行必须是 pythonw + main.py 的组合，防止静默失败
    with open(VBS_PATH, "r", encoding="utf-16") as f:
        content = f.read()
    if ('py = "%s"' % script) not in content or "pythonw" not in content:
        log("VBS 内容异常，请检查", "ERROR")
        return 1
    log("已安装开机自启: %s" % VBS_PATH)
    log("使用解释器: %s" % pyw)
    return 0


def uninstall():
    if os.path.exists(VBS_PATH):
        os.remove(VBS_PATH)
        log("已取消开机自启")
    else:
        log("本来就没有自启项")
    return 0


def status():
    if os.path.exists(VBS_PATH):
        log("开机自启: 已安装 (%s)" % VBS_PATH)
    else:
        log("开机自启: 未安装")
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    sys.exit({"install": install, "uninstall": uninstall, "status": status}.get(
        action, lambda: (log("未知操作: %s" % action, "ERROR"), 1)[1])())
