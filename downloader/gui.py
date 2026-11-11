"""Tkinter 界面：项目管理、扫码登录、线程编排。树形清单与下载在 Task 5 补入 self.center。"""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import qrcode
from PIL import ImageTk

from downloader.config import Config, ConfigStore, Project
from downloader.storage import AligoStorage


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


class ProjectDialog(tk.Toplevel):
    def __init__(self, parent, project: Project | None = None):
        super().__init__(parent)
        self.title("编辑项目" if project else "添加项目")
        self.resizable(False, False)
        self.result: Project | None = None
        self.transient(parent)
        self.grab_set()

        frm = ttk.Frame(self, padding=12)
        frm.grid(sticky="nsew")
        self.name_var = tk.StringVar(value=project.name if project else "")
        self.cloud_var = tk.StringVar(value=project.cloud_path if project else "")
        self.local_var = tk.StringVar(value=project.local_path if project else "")

        ttk.Label(frm, text="名称(别名)").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.name_var, width=40).grid(
            row=0, column=1, columnspan=2, pady=3
        )
        ttk.Label(frm, text="云盘路径").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.cloud_var, width=40).grid(
            row=1, column=1, columnspan=2, pady=3
        )
        ttk.Label(frm, text="本地路径").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.local_var, width=40).grid(row=2, column=1, pady=3)
        ttk.Button(frm, text="浏览", command=self._browse).grid(row=2, column=2, padx=(6, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="确定", command=self._ok).pack(side="right")
        self.bind("<Return>", lambda e: self._ok())

    def _browse(self):
        path = filedialog.askdirectory(parent=self)
        if path:
            self.local_var.set(path)
            if not self.name_var.get():
                self.name_var.set(Path(path).name)

    def _ok(self):
        name = self.name_var.get().strip()
        cloud = self.cloud_var.get().strip()
        local = self.local_var.get().strip()
        if not name or not cloud or not local:
            messagebox.showwarning("提示", "名称、云盘路径、本地路径都不能为空", parent=self)
            return
        self.result = Project(name, cloud, local)
        self.destroy()


class LoginDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("扫码登录阿里云盘")
        self.resizable(False, False)
        self.transient(parent)
        self._img = None

        frm = ttk.Frame(self, padding=12)
        frm.grid(sticky="nsew")
        self.qr_label = ttk.Label(frm, text="正在获取二维码…", anchor="center")
        self.qr_label.grid(row=0, column=0, columnspan=2, pady=(0, 8))
        self.status_var = tk.StringVar(value="请用阿里云盘 App 扫描二维码")
        ttk.Label(frm, textvariable=self.status_var, anchor="center").grid(
            row=1, column=0, columnspan=2
        )
        ttk.Label(frm, text="refresh_token").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.token_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.token_var, width=32).grid(
            row=2, column=1, pady=(10, 0)
        )
        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="刷新二维码", command=lambda: parent._start_qr_login(self)).pack(
            side="left"
        )
        ttk.Button(btns, text="用 token 登录", command=lambda: parent._start_token_login(self)).pack(
            side="left", padx=6
        )
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right")

    def show_qr(self, link: str):
        img = qrcode.make(link).get_image().resize((240, 240))
        self._img = ImageTk.PhotoImage(img)
        self.qr_label.configure(image=self._img, text="")
        self.status_var.set("请用阿里云盘 App 扫描二维码")

    def set_status(self, text: str):
        self.status_var.set(text)


class App(tk.Tk):
    def __init__(self, store: ConfigStore, storage: AligoStorage):
        super().__init__()
        self.store = store
        self.storage = storage
        self.title("Git 媒体下载器")
        self.geometry("920x620")
        self._q = queue.Queue()
        self._login_dialog: LoginDialog | None = None
        self.logged_in = False

        cfg = self.store.load()
        self.projects: list[Project] = list(cfg.projects)
        self._last = cfg.last

        self._build_ui()
        self._refresh_projects(select=self._last)
        self.after(100, self._poll)

    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=8)
        left.grid(row=0, column=0, sticky="ns")
        ttk.Label(left, text="项目").pack(anchor="w")
        self.project_list = tk.Listbox(left, width=24, exportselection=False, activestyle="none")
        self.project_list.pack(fill="y", expand=True, pady=(4, 6))
        self.project_list.bind("<<ListboxSelect>>", self._on_select_project)
        btns = ttk.Frame(left)
        btns.pack(fill="x")
        ttk.Button(btns, text="添加", command=self._add_project).pack(side="left")
        ttk.Button(btns, text="编辑", command=self._edit_project).pack(side="left", padx=4)
        ttk.Button(btns, text="删除", command=self._delete_project).pack(side="left")

        right = ttk.Frame(self, padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)

        ttk.Label(right, text="云盘路径").grid(row=0, column=0, sticky="w", pady=2)
        self.cloud_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.cloud_var).grid(
            row=0, column=1, columnspan=2, sticky="ew", pady=2
        )
        ttk.Label(right, text="本地路径").grid(row=1, column=0, sticky="w", pady=2)
        self.local_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.local_var).grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Button(right, text="浏览", command=self._browse_local).grid(row=1, column=2, padx=(6, 0))

        login_row = ttk.Frame(right)
        login_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 6))
        ttk.Button(login_row, text="扫码登录", command=self._open_login).pack(side="left")
        self.login_status = ttk.Label(login_row, text="未登录")
        self.login_status.pack(side="left", padx=8)

        self.center = ttk.Frame(right)
        self.center.grid(row=3, column=0, columnspan=3, sticky="nsew")

        ttk.Label(right, text="日志").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.log = tk.Text(right, height=8, state="disabled", wrap="none")
        self.log.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(2, 0))

    # ---- 项目管理 ----
    def _refresh_projects(self, select: str | None = None):
        self.project_list.delete(0, "end")
        for p in self.projects:
            self.project_list.insert("end", p.name)
        idx = None
        if select:
            for i, p in enumerate(self.projects):
                if p.name == select:
                    idx = i
                    break
        if idx is None and self.projects:
            idx = 0
        if idx is not None:
            self.project_list.selection_set(idx)
            self.project_list.see(idx)
            self._load_project(self.projects[idx])

    def _current(self) -> Project | None:
        sel = self.project_list.curselection()
        if not sel:
            return None
        return self.projects[sel[0]]

    def _load_project(self, p: Project):
        self.cloud_var.set(p.cloud_path)
        self.local_var.set(p.local_path)

    def _on_select_project(self, _event=None):
        p = self._current()
        if p:
            self._load_project(p)

    def _save(self):
        cur = self._current()
        self.store.save(Config(self.projects, last=cur.name if cur else None))

    def _add_project(self):
        dlg = ProjectDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        if any(p.name == dlg.result.name for p in self.projects):
            messagebox.showwarning("提示", f"项目名已存在：{dlg.result.name}")
            return
        self.projects.append(dlg.result)
        self._refresh_projects(select=dlg.result.name)
        self._save()

    def _edit_project(self):
        p = self._current()
        if not p:
            return
        dlg = ProjectDialog(self, p)
        self.wait_window(dlg)
        if not dlg.result:
            return
        if any(q.name == dlg.result.name and q is not p for q in self.projects):
            messagebox.showwarning("提示", f"项目名已存在：{dlg.result.name}")
            return
        self.projects[self.projects.index(p)] = dlg.result
        self._refresh_projects(select=dlg.result.name)
        self._save()

    def _delete_project(self):
        p = self._current()
        if not p:
            return
        if not messagebox.askyesno("确认", f"删除项目「{p.name}」？（不会删除本地文件）"):
            return
        self.projects.remove(p)
        self._refresh_projects()
        self._save()

    def _browse_local(self):
        path = filedialog.askdirectory(parent=self)
        if path:
            self.local_var.set(path)

    # ---- 登录 ----
    def _open_login(self):
        if self._login_dialog is not None and self._login_dialog.winfo_exists():
            self._login_dialog.lift()
            return
        self._login_dialog = LoginDialog(self)
        self._start_qr_login(self._login_dialog)

    def _start_qr_login(self, dialog: LoginDialog):
        dialog.set_status("正在获取二维码…")
        self._run(lambda: self._qr_worker())

    def _qr_worker(self):
        try:
            name = self.storage.login_qr(on_qr=lambda link: self._q.put(("qr", link)))
            self._q.put(("login_ok", name))
        except Exception as e:  # noqa: BLE001 - 登录异常需回报 GUI
            self._q.put(("login_err", str(e)))

    def _start_token_login(self, dialog: LoginDialog):
        token = dialog.token_var.get().strip()
        if not token:
            dialog.set_status("请先粘贴 refresh_token")
            return
        dialog.set_status("正在用 token 登录…")
        self._run(lambda: self._token_worker(token))

    def _token_worker(self, token: str):
        try:
            name = self.storage.login_token(token)
            self._q.put(("login_ok", name))
        except Exception as e:  # noqa: BLE001
            self._q.put(("login_err", str(e)))

    # ---- 线程基础设施 ----
    def _run(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _poll(self):
        try:
            while True:
                self._handle(self._q.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "log":
            self._log(msg[1])
        elif kind == "qr":
            if self._login_dialog and self._login_dialog.winfo_exists():
                self._login_dialog.show_qr(msg[1])
        elif kind == "login_ok":
            self.logged_in = True
            self.login_status.configure(text=f"已登录：{msg[1]}")
            if self._login_dialog and self._login_dialog.winfo_exists():
                self._login_dialog.destroy()
            self._login_dialog = None
            self._log(f"登录成功：{msg[1]}")
        elif kind == "login_err":
            if self._login_dialog and self._login_dialog.winfo_exists():
                self._login_dialog.set_status(f"登录失败：{msg[1]}")
            self._log(f"登录失败：{msg[1]}")
        elif kind == "error":
            messagebox.showerror("错误", msg[1])
            self._log(f"错误：{msg[1]}")
        # entries / progress / done 由 Task 5 处理

    def _log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")