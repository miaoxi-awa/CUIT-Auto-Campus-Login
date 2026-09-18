# -*- coding: utf-8 -*-
"""校园网自动登录 图形界面（tkinter，可被 PyInstaller 打包成 exe）。

用法:
    python campus_gui.py               # 打开图形界面
    python campus_gui.py --boot        # 开机自启模式：静默登录后自动退出
    python campus_gui.py --shot x.png  # 预览模式：渲染界面后截图保存并退出
"""
import os
import sys
import queue
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, scrolledtext

import common
import main as core
from common import AUTHOR, BASE_DIR, LOG_DIR

FROZEN = getattr(sys, "frozen", False)
BOOT = "--boot" in sys.argv
DONE = "__DONE__"


class StdoutCaptor:
    """把 print/日志输出导进队列（线程安全），GUI 线程统一消费显示"""
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s and s.strip():
            self.q.put(s)

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.boot_retries = 3  # 开机时网络可能未就绪，静默登录失败自动重试
        self.warned_browsers = set()  # 已提示过驱动下载的浏览器（每会话一次）

        root.title("校园网自动登录 · py: %s" % AUTHOR)
        root.geometry("600x500")
        root.minsize(520, 430)

        head = ttk.Frame(root, padding=(12, 10, 12, 0))
        head.pack(fill="x")
        ttk.Label(head, text="校园网自动登录", font=("微软雅黑", 14, "bold")).pack(side="left")
        ttk.Label(head, text="py: %s" % AUTHOR, foreground="#888").pack(side="right")

        self.status = ttk.Label(root, text="状态：就绪", padding=(14, 2),
                                font=("微软雅黑", 10), foreground="#1a7f37")
        self.status.pack(fill="x")

        bar1 = ttk.Frame(root, padding=(12, 6, 12, 2))
        bar1.pack(fill="x")
        self.b_login = ttk.Button(bar1, text="登录一次", width=16,
                                  command=lambda: self.run_flow(["--once"], "登录中"))
        self.b_logout = ttk.Button(bar1, text="仅下线", width=16,
                                   command=lambda: self.run_flow(["--logout-only"], "下线中"))
        self.b_login.pack(side="left", padx=(0, 8))
        self.b_logout.pack(side="left", padx=8)

        bar2 = ttk.Frame(root, padding=(12, 2, 12, 2))
        bar2.pack(fill="x")
        self.b_account = ttk.Button(bar2, text="设置账号密码", width=14, command=self.set_account)
        self.b_clear = ttk.Button(bar2, text="清除账号密码", width=14, command=self.clear_account)
        self.b_auto = ttk.Button(bar2, text=self.autostart_label(), width=14, command=self.toggle_autostart)
        self.b_logs = ttk.Button(bar2, text="打开日志", width=14, command=self.open_logs)
        self.b_account.pack(side="left", padx=(0, 8))
        self.b_clear.pack(side="left", padx=8)
        self.b_auto.pack(side="left", padx=8)
        self.b_logs.pack(side="left", padx=8)

        # 运营商选择：登录后弹窗会按这里的配置自动选
        bar_op = ttk.Frame(root, padding=(12, 2, 12, 2))
        bar_op.pack(fill="x")
        ttk.Label(bar_op, text="运营商：").pack(side="left")
        self.op_var = tk.StringVar()
        self.op_box = ttk.Combobox(bar_op, textvariable=self.op_var, width=10,
                                   values=("电信", "移动", "联通"), state="readonly")
        cur = (common.load_config().get("service") or "").strip()
        self.op_var.set(cur if cur in ("电信", "移动", "联通") else "")
        self.op_box.pack(side="left", padx=(0, 12))
        self.op_box.bind("<<ComboboxSelected>>", self.on_operator_change)

        # 自动化浏览器：自动探测本机已安装的浏览器，可切换
        ttk.Label(bar_op, text="浏览器：").pack(side="left")
        self.browsers = common.detect_browsers()  # [(key, 显示名, exe路径)]
        self.browser_var = tk.StringVar()
        self.browser_box = ttk.Combobox(bar_op, textvariable=self.browser_var, width=20,
                                        values=["自动（推荐）"] + [n for _, n, _p in self.browsers],
                                        state="readonly")
        name_map = {k: n for k, n, _p in self.browsers}
        cur_b = (common.load_config().get("browser") or "auto").lower()
        self.browser_var.set(name_map.get(cur_b, "自动（推荐）"))
        self.browser_box.pack(side="left")
        self.browser_box.bind("<<ComboboxSelected>>", self.on_browser_change)

        self.b_github = ttk.Button(bar_op, text="GitHub 项目页", width=14, command=self.open_github)
        self.b_github.pack(side="right")

        ttk.Label(root, padding=(14, 0, 14, 0), foreground="#888",
                  text="支持 Edge / Chrome / Firefox 及主流 Chromium 内核浏览器（360、QQ、搜狗、2345、UC、傲游、Brave、Opera、Vivaldi…，"
                       "自动识别本机已安装的）。选「自动」会依次尝试直到成功。\n"
                       "提示：Edge 驱动已内置缓存；首次使用 Chrome / Firefox 或其他内核浏览器需联网下载对应驱动，"
                       "建议先联网跑一次登录把驱动缓存下来，之后断网也能用。",
                  wraplength=560, justify="left").pack(fill="x")

        self.all_buttons = [self.b_login, self.b_logout,
                            self.b_account, self.b_clear, self.b_auto, self.b_logs]

        ttk.Label(root, text="运行日志：", padding=(14, 6, 0, 0)).pack(anchor="w")
        self.logbox = scrolledtext.ScrolledText(root, height=13, state="disabled",
                                                font=("Consolas", 9), bg="#111", fg="#ddd")
        self.logbox.pack(fill="both", expand=True, padx=12, pady=(2, 12))

        # 捕获 worker 线程里的所有 print（common.log 走 print）
        sys.stdout = StdoutCaptor(self.q)
        sys.stderr = StdoutCaptor(self.q)

        self.root.after(100, self.poll)

    # ---------- 工具 ----------
    def log_line(self, s):
        self.logbox.config(state="normal")
        self.logbox.insert("end", s if s.endswith("\n") else s + "\n")
        self.logbox.see("end")
        self.logbox.config(state="disabled")

    def autostart_label(self):
        import setup_autostart as sa
        return "取消开机自启" if sa.is_installed() else "安装开机自启"

    def open_logs(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        os.startfile(LOG_DIR)

    def open_github(self):
        import webbrowser
        webbrowser.open("https://github.com/miaoxi-awa/CUIT-Auto-Campus-Login")
        self.log_line("已在浏览器打开 GitHub 项目页")

    # ---------- 账号管理 ----------
    def ensure_account(self):
        """GUI 里没有控制台，首次使用用对话框引导输入"""
        cfg = common.load_config()
        if not core.creds_missing(cfg):
            return True
        u = simpledialog.askstring("首次使用", "校园网账号（学号/工号）:", parent=self.root)
        if not u or not u.strip():
            return False
        p = simpledialog.askstring("首次使用",
                                   "校园网密码（明文显示，方便核对；数据仅保存在本地，项目开源，不用担心）:",
                                   parent=self.root)
        if not p:
            return False
        common.save_account(u.strip(), p)
        self.log_line("账号密码已保存到本地 config.ini")
        return True

    def set_account(self):
        if self.ensure_account():
            self.status.config(text="状态：账号密码已更新")

    def clear_account(self):
        if messagebox.askyesno("确认", "将清除本地保存的账号密码\n（下次登录会重新引导输入）\n\n确定清除？"):
            common.clear_account()
            self.log_line("已清除账号密码。")

    # ---------- 运营商 ----------
    def on_operator_change(self, _event=None):
        val = self.op_var.get().strip()
        if val:
            common.save_service(val)
            self.log_line("运营商已设为「%s」，下次登录自动选择" % val)

    def on_browser_change(self, _event=None):
        name = self.browser_var.get().strip()
        if name.startswith("自动"):
            common.save_browser("auto")
            self.log_line("已切换为「自动」：按检测顺序尝试，第一个能启动的浏览器生效")
            return
        key = next((k for k, n, _p in self.browsers if n == name), "edge")
        common.save_browser(key)
        self.log_line("自动化浏览器已切换为 %s" % name)
        if key not in ("edge",):
            self.log_line("提示：首次使用 %s 时 Selenium 需联网下载对应驱动，建议先在已联网状态下"
                          "点一次登录把驱动缓存下来，之后再断网用就没问题。（Edge 驱动已缓存，不受影响）" % name)
            if key not in self.warned_browsers:
                self.warned_browsers.add(key)
                messagebox.showinfo(
                    "驱动下载提示",
                    "首次使用 %s，Selenium 需要联网下载对应驱动。\n\n"
                    "建议在已联网状态下先点一次「登录一次」把驱动缓存下来，"
                    "之后再断开网使用就没问题。\n\n"
                    "（Edge 驱动已内置缓存，不受影响）" % name)

    def ensure_operator(self):
        """登录类操作前确保已选运营商，避免 GUI 模式下无法交互选择"""
        if self.op_var.get().strip():
            return True
        messagebox.showwarning("请选择运营商", "先在「运营商」下拉框选择你的运营商，再登录。")
        return False

    # ---------- 开机自启 ----------
    def toggle_autostart(self):
        import setup_autostart as sa
        if sa.is_installed():
            sa.uninstall()
        else:
            if sa.install() != 0:
                messagebox.showerror("错误", "安装自启失败，详见日志")
        self.b_auto.config(text=self.autostart_label())

    # ---------- 流程执行 ----------
    def run_flow(self, args, title):
        if self.busy:
            return
        if not self.ensure_account():
            return
        if "--once" in args and not self.ensure_operator():
            return
        self.busy = True
        for b in self.all_buttons:
            b.config(state="disabled")
        self.op_box.config(state="disabled")
        self.browser_box.config(state="disabled")
        self.status.config(text="状态：%s..." % title, foreground="#b26a00")

        def worker():
            old_argv = sys.argv
            sys.argv = ["CampusLogin"] + args
            code = 0
            try:
                core.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 0
            except Exception as e:
                self.q.put("异常: %s\n" % e)
                code = 1
            finally:
                sys.argv = old_argv
                self.q.put(DONE + str(code))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, str) and item.startswith(DONE):
                    code = item[len(DONE):]
                    self.busy = False
                    for b in self.all_buttons:
                        b.config(state="normal")
                    self.op_box.config(state="readonly")
                    self.browser_box.config(state="readonly")
                    self.b_auto.config(text=self.autostart_label())
                    ok = code in ("0", "None", "")
                    if BOOT and not ok and self.boot_retries > 0:
                        # 开机自启失败：等 15 秒（多半是网络没就绪）自动重试
                        self.boot_retries -= 1
                        self.status.config(
                            text="状态：开机登录未成功，15 秒后自动重试...",
                            foreground="#b26a00")
                        self.root.after(15000, lambda: self.run_flow(
                            ["--once", "--boot"], "开机自动登录(重试)"))
                    else:
                        self.status.config(
                            text="状态：完成（%s）" % ("成功" if ok else "失败，详见日志/RESULT.txt"),
                            foreground="#1a7f37" if ok else "#c62828")
                        if BOOT:
                            self.root.after(400, self.root.destroy)
                else:
                    self.log_line(item)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def main():
    root = tk.Tk()
    app = App(root)

    if BOOT:
        # 开机自启：显示界面 → 自动点「登录一次」→ 登录完成后自动关闭
        # （不用 --silent，浏览器正常显示窗口，比 headless 启动更快）
        root.after(500, lambda: app.run_flow(["--once", "--boot"], "开机自动登录"))
    elif "--shot" in sys.argv:
        # 预览模式：渲染后截图保存并退出
        path = sys.argv[sys.argv.index("--shot") + 1]

        def take_shot():
            root.update_idletasks()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            w, h = root.winfo_width(), root.winfo_height()
            from PIL import ImageGrab
            ImageGrab.grab((x, y, x + w, y + h)).save(path)
            root.destroy()

        root.after(700, take_shot)

    root.mainloop()


if __name__ == "__main__":
    main()
