"""Tkinter 界面：项目管理、扫码登录、线程编排。树形清单与下载在 Task 5 补入 self.center。"""
import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import qrcode
import requests
from PIL import ImageTk

from downloader.config import CacheStore, Config, ConfigStore, Project
from downloader.core import (
    CloudFile,
    FileEntry,
    NotAGitRepo,
    TreeNode,
    build_entries,
    build_tree,
    folder_state,
    git_tracked,
    selected_entries,
)
from downloader.manifest import (
    MANIFEST_NAME,
    MANIFEST_VERSION,
    Manifest,
    ManifestError,
    ManifestFile,
    parse_exts,
    scan_media_files,
    write_manifest,
)
from downloader.storage import AligoStorage, DownloadCancelled, StorageError, download_url_to

STATUS_LABEL = {"pending": "待下载", "overwrite": "将覆盖", "same": "已相同"}
FOLDER_MARK = {"all": "☑", "partial": "▣", "none": "☐"}
DOWNLOAD_WORKERS = 2


def _count_files(node: TreeNode) -> int:
    if not node.is_folder:
        return 1 if node.entry is not None else 0
    return sum(_count_files(c) for c in node.children)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def format_eta(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}秒"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}分{s:02d}秒"
    h, m = divmod(m, 60)
    return f"{h}小时{m:02d}分"


def download_status(done: int, total: int, done_bytes: int, total_bytes: int, speed: float) -> str:
    eta = format_eta((total_bytes - done_bytes) / speed) if speed > 0 else "--"
    return f"{done}/{total} · {human_size(int(speed))}/s · 剩余 {eta}"


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
        self.exts_var = tk.StringVar(value=project.exts if project else "")

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
        ttk.Label(frm, text="素材后缀").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.exts_var, width=40).grid(
            row=3, column=1, columnspan=2, pady=3
        )
        ttk.Label(frm, text="逗号分隔，留空使用默认（jpg png mp4 等）").grid(
            row=4, column=1, columnspan=2, sticky="w"
        )

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=3, pady=(10, 0), sticky="e")
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
        self.result = Project(name, cloud, local, self.exts_var.get().strip())
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
    def __init__(self, store: ConfigStore, storage: AligoStorage, cache: CacheStore | None = None):
        super().__init__()
        self.store = store
        self.storage = storage
        self.cache = cache if cache is not None else CacheStore()
        self.title("Git 媒体下载器")
        self.geometry("920x620")
        self._q = queue.Queue()
        self._login_dialog: LoginDialog | None = None
        self.logged_in = False
        self._entries: list[FileEntry] = []
        self._roots: list[TreeNode] = []
        self._node_by_item: dict[str, TreeNode] = {}
        self._checked: set[str] = set()
        self._cancel = threading.Event()
        self._busy = False
        self._login_busy = False

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
        self._build_center()

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
        self._clear_tree()

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
        if self._login_busy:
            return
        self._login_busy = True
        dialog.set_status("登录中，请用阿里云盘 App 扫码…")
        self._run(lambda: self._qr_worker())

    def _qr_worker(self):
        try:
            name = self.storage.login_qr(on_qr=lambda link: self._q.put(("qr", link)))
            self._q.put(("login_ok", name))
        except Exception as e:  # noqa: BLE001 - 登录异常需回报 GUI
            self._q.put(("login_err", str(e)))

    def _start_token_login(self, dialog: LoginDialog):
        if self._login_busy:
            return
        token = dialog.token_var.get().strip()
        if not token:
            dialog.set_status("请先粘贴 refresh_token")
            return
        self._login_busy = True
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
            self._login_busy = False
            self.logged_in = True
            self.login_status.configure(text=f"已登录：{msg[1]}")
            if self._login_dialog and self._login_dialog.winfo_exists():
                self._login_dialog.destroy()
            self._login_dialog = None
            self._log(f"登录成功：{msg[1]}")
        elif kind == "login_err":
            self._login_busy = False
            if self._login_dialog and self._login_dialog.winfo_exists():
                self._login_dialog.set_status(f"登录失败：{msg[1]}")
            self._log(f"登录失败：{msg[1]}")
        elif kind == "error":
            self._set_busy(False)
            messagebox.showerror("错误", msg[1])
            self._log(f"错误：{msg[1]}")
        elif kind == "entries":
            self._populate(msg[1], preserve=msg[2])
            self._set_busy(False)
            self._log(f"列出 {len(msg[1])} 个 git 未管理文件")
        elif kind == "cached_entries":
            self._populate(msg[1])
            self._log(f"已加载缓存 {len(msg[1])} 个文件（{msg[2]}），后台刷新中…")
        elif kind == "list_progress":
            self.dl_status.configure(text=f"已扫描 {msg[1]} 个文件夹 / {msg[2]} 个文件")
        elif kind == "progress":
            self._log(msg[1])
        elif kind == "dl_start":
            self.dl_bar.configure(maximum=max(msg[2], 1), value=0)
            self.dl_status.configure(text=f"0/{msg[1]}")
        elif kind == "dl_progress":
            _, done, total, done_b, total_b, speed = msg
            self.dl_bar.configure(maximum=max(total_b, 1), value=done_b)
            self.dl_status.configure(text=download_status(done, total, done_b, total_b, speed))
        elif kind == "done":
            self._set_busy(False)
            self._log(msg[1])

    # ---- 树形清单 ----
    def _build_center(self):
        self.center.columnconfigure(0, weight=1)
        self.center.rowconfigure(1, weight=1)

        bar = ttk.Frame(self.center)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.list_btn = ttk.Button(bar, text="列出文件", command=self._list_files)
        self.list_btn.pack(side="left")
        self.gen_btn = ttk.Button(bar, text="生成清单", command=self._generate_manifest)
        self.gen_btn.pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="全选", command=self._select_all).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="全不选", command=self._select_none).pack(side="left", padx=6)
        ttk.Button(bar, text="反选", command=self._invert).pack(side="left")
        self.download_btn = ttk.Button(bar, text="下载选中(0)", command=self._download_selected)
        self.download_btn.pack(side="left", padx=(12, 0))
        self.cancel_btn = ttk.Button(bar, text="取消", command=self._cancel_download, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)

        wrap = ttk.Frame(self.center)
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(wrap, columns=("size", "status"), selectmode="browse")
        self.tree.heading("#0", text="名称")
        self.tree.column("#0", width=320, stretch=True)
        self.tree.heading("size", text="大小")
        self.tree.column("size", width=90, anchor="e", stretch=False)
        self.tree.heading("status", text="状态")
        self.tree.column("status", width=110, anchor="w", stretch=False)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)

        prog = ttk.Frame(self.center)
        prog.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.dl_bar = ttk.Progressbar(prog, maximum=1, value=0)
        self.dl_bar.pack(side="left", fill="x", expand=True)
        self.dl_status = ttk.Label(prog, text="", width=34, anchor="w")
        self.dl_status.pack(side="left", padx=(8, 0))

    def _set_busy(self, busy: bool):
        self._busy = busy
        self.list_btn.configure(state="disabled" if busy else "normal")
        self.gen_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        self._update_download_button()

    def _list_files(self):
        if self._busy:
            return
        if not self.logged_in:
            messagebox.showwarning("提示", "请先扫码登录")
            return
        cloud = self.cloud_var.get().strip()
        local = self.local_var.get().strip()
        if not cloud or not local:
            messagebox.showwarning("提示", "请填写云盘路径和本地路径")
            return
        self._set_busy(True)
        self._clear_tree()
        self._log(f"正在列出 {cloud} …")
        self._run(lambda: self._list_worker(cloud, local))

    def _list_worker(self, cloud: str, local: str):
        root = Path(local)
        try:
            tracked = git_tracked(root)
        except NotAGitRepo as e:
            self._q.put(("error", f"本地不是 git 仓库或未安装 git：{e}"))
            return
        cached = self.cache.load(cloud)
        if cached is not None:
            files, saved_at = cached
            self._q.put(("cached_entries", build_entries(files, root, tracked), saved_at))

        def prog(folders: int, files: int):
            self._q.put(("list_progress", folders, files))

        try:
            manifest = self.storage.read_manifest(cloud)
            if manifest is not None:
                self._q.put((
                    "log",
                    f"已读取清单 {MANIFEST_NAME}：{len(manifest.files)} 个文件"
                    f"（生成于 {manifest.generated_at}）",
                ))
                # 清单即云端快照：列举只做本地 path+size 比对，
                # file_id 留空、下载时按需解析，避免逐目录请求 SDK
                cloud_files = [
                    CloudFile(mf.path, mf.path.rsplit("/", 1)[-1], mf.size, "")
                    for mf in manifest.files
                    if mf.path != MANIFEST_NAME
                ]
            else:
                self._q.put(("log", f"未找到 {MANIFEST_NAME}，回退全量扫描 …"))
                cloud_files = list(self.storage.iter_cloud_files(cloud, on_progress=prog))
        except StorageError as e:
            if cached is not None:
                self._q.put(("done", f"刷新失败：{e}（仍显示缓存）"))
            else:
                self._q.put(("error", str(e)))
            return
        except ManifestError as e:
            self._q.put(("error", f"清单文件损坏：{e}"))
            return
        except Exception as e:  # noqa: BLE001 - 后台异常需回报 GUI
            self._q.put(("error", str(e)))
            return
        self.cache.save(cloud, cloud_files)
        self._q.put(("entries", build_entries(cloud_files, root, tracked), cached is not None))

    # ---- 生成清单 ----
    def _generate_manifest(self):
        if self._busy:
            return
        local = self.local_var.get().strip()
        if not local:
            messagebox.showwarning("提示", "请填写本地路径")
            return
        p = self._current()
        exts = p.exts if p else ""
        self._set_busy(True)
        self._log(f"正在扫描 {local} 生成清单 …")
        self._run(lambda: self._generate_worker(local, exts))

    def _generate_worker(self, local: str, exts: str):
        root = Path(local)
        try:
            tracked = git_tracked(root)
            files = scan_media_files(root, tracked, parse_exts(exts))
            write_manifest(root, files)
        except NotAGitRepo as e:
            self._q.put(("error", f"本地不是 git 仓库或未安装 git：{e}"))
            return
        except Exception as e:  # noqa: BLE001 - 后台异常需回报 GUI，否则线程静默死亡卡 busy
            self._q.put(("error", f"生成清单失败：{e}"))
            return
        total = human_size(sum(f.size for f in files))
        self._q.put((
            "done",
            f"已生成 {MANIFEST_NAME}：{len(files)} 个文件，共 {total}。"
            "等待自动同步上传后，即可在其他设备列出下载",
        ))

    def _clear_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._entries = []
        self._roots = []
        self._node_by_item = {}
        self._checked = set()
        self._update_download_button()

    def _populate(self, entries: list[FileEntry], preserve: bool = False):
        old_checked = self._checked
        old_relpaths = {e.relpath for e in self._entries}
        self.tree.delete(*self.tree.get_children())
        self._entries = entries
        self._roots = build_tree(entries)
        self._node_by_item = {}
        if preserve:
            self._checked = {
                e.relpath
                for e in entries
                if e.relpath in old_checked
                or (e.relpath not in old_relpaths and e.status in ("pending", "overwrite"))
            }
        else:
            self._checked = {e.relpath for e in entries if e.status in ("pending", "overwrite")}

        def insert(node: TreeNode, parent: str):
            item = self.tree.insert(
                parent, "end", text=self._node_text(node),
                values=self._node_values(node), open=True,
            )
            self._node_by_item[item] = node
            for child in node.children:
                insert(child, item)

        for root in self._roots:
            insert(root, "")
        self._update_download_button()

    def _node_text(self, node: TreeNode) -> str:
        if node.is_folder:
            return f"{FOLDER_MARK[folder_state(node, self._checked)]} {node.name}"
        mark = "☑" if node.entry.relpath in self._checked else "☐"
        return f"{mark} {node.name}"

    def _node_values(self, node: TreeNode):
        if node.is_folder:
            return (f"{_count_files(node)} 个文件", "")
        return (human_size(node.entry.size), STATUS_LABEL[node.entry.status])

    def _refresh_checks(self):
        for item, node in self._node_by_item.items():
            self.tree.item(item, text=self._node_text(node))
        self._update_download_button()

    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "tree":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self._toggle(self._node_by_item[item])

    def _iter_files(self, node: TreeNode):
        if not node.is_folder:
            if node.entry is not None:
                yield node.entry
            return
        for child in node.children:
            yield from self._iter_files(child)

    def _toggle(self, node: TreeNode):
        if node.is_folder:
            target = folder_state(node, self._checked) != "all"
            for f in self._iter_files(node):
                if target:
                    self._checked.add(f.relpath)
                else:
                    self._checked.discard(f.relpath)
        else:
            rp = node.entry.relpath
            if rp in self._checked:
                self._checked.discard(rp)
            else:
                self._checked.add(rp)
        self._refresh_checks()

    def _select_all(self):
        self._checked = {e.relpath for e in self._entries}
        self._refresh_checks()

    def _select_none(self):
        self._checked = set()
        self._refresh_checks()

    def _invert(self):
        self._checked = {e.relpath for e in self._entries if e.relpath not in self._checked}
        self._refresh_checks()

    def _update_download_button(self):
        enabled = (not self._busy) and bool(self._entries)
        self.download_btn.configure(
            text=f"下载选中({len(self._checked)})",
            state="normal" if enabled else "disabled",
        )

    # ---- 下载 ----
    def _download_selected(self):
        if self._busy:
            return
        if not self.logged_in:
            messagebox.showwarning("提示", "请先扫码登录")
            return
        files = selected_entries(self._roots, self._checked)
        if not files:
            messagebox.showwarning("提示", "没有勾选任何文件")
            return
        local = Path(self.local_var.get().strip())
        cloud = self.cloud_var.get().strip()
        self._cancel = threading.Event()
        self._set_busy(True)
        self._log(f"开始下载 {len(files)} 个文件 …")
        self._run(lambda: self._download_worker(files, local, cloud))

    def _download_worker(self, files: list[FileEntry], local: Path, cloud: str):
        ok = fail = cancelled = 0
        lock = threading.Lock()

        # 清单生成的条目 file_id 为空：仅对选中子集按目录解析，顺带校验云端大小
        missing = [e for e in files if not e.file_id]
        if missing:
            sub = Manifest(
                MANIFEST_VERSION, "",
                [ManifestFile(e.relpath, e.size) for e in missing],
            )
            try:
                resolved, warnings = self.storage.resolve_manifest_files(cloud, sub)
            except Exception as ex:  # noqa: BLE001 - 后台异常需回报 GUI
                resolved, warnings = [], [f"解析云端文件失败：{ex}"]
            for w in warnings:
                self._q.put(("log", f"⚠ {w}"))
            by_path = {cf.relpath: cf for cf in resolved}
            kept: list[FileEntry] = []
            for e in files:
                if e.file_id:
                    kept.append(e)
                    continue
                cf = by_path.get(e.relpath)
                if cf is None:
                    fail += 1
                    self._q.put(("progress", f"✗ {e.relpath}: 云端未找到或大小与清单不符"))
                else:
                    kept.append(FileEntry(cf.relpath, cf.name, cf.size, cf.file_id, e.status))
            files = kept

        total_bytes = sum(e.size for e in files)
        done_bytes = 0
        self._q.put(("dl_start", len(files), total_bytes))

        def on_bytes(n: int):
            nonlocal done_bytes
            with lock:
                done_bytes += n

        try:
            urls = self.storage.get_download_urls([e.file_id for e in files])
        except Exception as ex:  # noqa: BLE001 - 后台异常需回报 GUI
            urls = {}
            self._q.put(("progress", f"✗ 获取下载链接失败：{ex}"))

        tls = threading.local()

        def task(e: FileEntry):
            if self._cancel.is_set():
                raise DownloadCancelled()
            url = urls.get(e.file_id)
            if not url:
                raise StorageError("获取下载链接失败")
            session = getattr(tls, "session", None)
            if session is None:
                session = tls.session = requests.Session()
            self._q.put(("progress", f"↓ {e.relpath}（{human_size(e.size)}）"))
            t0 = time.monotonic()
            download_url_to(
                url, local / e.relpath, e.size,
                on_progress=on_bytes, cancel=self._cancel, session=session,
            )
            dt = time.monotonic() - t0
            speed = e.size / dt if dt > 0 else 0.0
            self._q.put((
                "progress",
                f"✓ {e.relpath}（{human_size(e.size)}，{dt:.0f}s，{human_size(int(speed))}/s）",
            ))

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = {pool.submit(task, e): e for e in files}
            pending = set(futures)
            last_t = time.monotonic()
            last_b = 0
            while pending:
                done_set, pending = wait(pending, timeout=0.5)
                for f in done_set:
                    e = futures[f]
                    try:
                        f.result()
                        ok += 1
                    except DownloadCancelled:
                        cancelled += 1
                    except Exception as ex:  # noqa: BLE001
                        fail += 1
                        self._q.put(("progress", f"✗ {e.relpath}: {ex}"))
                now = time.monotonic()
                with lock:
                    b = done_bytes
                speed = (b - last_b) / (now - last_t) if now > last_t else 0.0
                last_t, last_b = now, b
                self._q.put(("dl_progress", ok + fail + cancelled, len(files), b, total_bytes, speed))
        self._q.put(("done", f"下载完成：成功 {ok}，失败 {fail}，取消 {cancelled}"))

    def _cancel_download(self):
        self._cancel.set()
        self._log("正在取消 …")

    def _log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')} {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")