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
        self.b_relogin = ttk.Button(bar1, text="断线重连", width=16,
                                    command=lambda: self.run_flow(["--once", "--offline"], "断线重连中"))
        self.b_login.pack(side="left", padx=(0, 8))
        self.b_logout.pack(side="left", padx=8)
        self.b_relogin.pack(side="left", padx=8)

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
        self.op_box.pack(side="left", padx=(0, 8))
        ttk.Label(bar_op, text="（登录时会按此选择自动确认）", foreground="#888").pack(side="left")
        self.op_box.bind("<<ComboboxSelected>>", self.on_operator_change)

        self.all_buttons = [self.b_login, self.b_logout, self.b_relogin,
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
        from setup_autostart import VBS_PATH
        return "取消开机自启" if os.path.exists(VBS_PATH) else "安装开机自启"

    def open_logs(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        os.startfile(LOG_DIR)

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
                                   "校园网密码（此数据保存在本地，项目开源，不用担心）:",
                                   show="*", parent=self.root)
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

    def ensure_operator(self):
        """登录类操作前确保已选运营商，避免 GUI 模式下无法交互选择"""
        if self.op_var.get().strip():
            return True
        messagebox.showwarning("请选择运营商", "先在「运营商」下拉框选择你的运营商，再登录。")
        return False

    # ---------- 开机自启 ----------
    def toggle_autostart(self):
        import setup_autostart as sa
        if os.path.exists(sa.VBS_PATH):
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
                    self.b_auto.config(text=self.autostart_label())
                    ok = code in ("0", "None", "")
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
        # 开机自启：不弹窗，静默登录，完成后自动退出
        root.withdraw()
        root.after(300, lambda: app.run_flow(["--once", "--silent", "--boot"], "开机自动登录"))
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
