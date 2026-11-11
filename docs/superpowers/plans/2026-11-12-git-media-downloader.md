# Git 媒体下载器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Windows 单 exe 桌面工具，把阿里云盘里 git 未管理的媒体文件按原层级、可勾选、覆盖式增量下载到本地项目。

**Architecture:** 纯逻辑层 `core.py`（git 过滤/比对/树模型，无 aligo 依赖、可单测）+ 存储封装 `storage.py`（aligo 登录/列目录/下载）+ 配置 `config.py`（JSON）+ Tkinter 界面 `gui.py`（后台线程 + queue 编排）。`main.py` 入口处理 windowed 流重定向。

**Tech Stack:** Python 3.12, Tkinter/ttk（标准库）, aligo 6.2.8, qrcode + pillow（二维码）, PyInstaller（打包）, pytest（测试）。

**Spec:** `docs/superpowers/specs/2026-11-12-git-media-downloader-design.md`

## Global Constraints

- Python 3.12；GUI 仅用 Tkinter/ttk 标准库，不引入其它 GUI 框架。
- 云存储仅经 aligo 6.2.8；不直接裸调阿里云盘 API。
- 打包 PyInstaller `--onefile --windowed`，产物单个 exe。
- 下载只增不删；覆盖必须先下载到临时目录再 `os.replace`（aligo 遇已存在文件会跳过）。
- 跳过 git 已跟踪文件与 `.git/`；本地非 git 仓库或未装 git 必须报错停止。
- 工作线程不得直接操作 Tkinter 控件；GUI 更新一律经 `queue.Queue` + `after`。
- 相对路径内部统一用 `/` 分隔；本地落盘用 `pathlib.Path`。
- 配置 `config.json` 存于 `app_dir()`（frozen 时 exe 旁，否则项目根）。
- 已验证环境：`.venv` 已装 aligo 6.2.8，`aligo/qrcode/PIL/tqdm/coloredlogs/qrcode_terminal/requests` 均可导入。

## Review Focus

1. **云盘路径不存在或不是文件夹** → 明确报错，不崩溃、不误下。（Task 3 测试）
2. **本地不是 git 仓库 / 未装 git** → 明确报错停止，绝不退化成"下载全部"。（Task 2 测试）
3. **本地已存在同名但大小不同的文件** → 必须真正覆盖（aligo 默认跳过，需临时下载 + `os.replace`）。（Task 3 测试）
4. **文件名含中文/空格/Windows 非法字符** → relpath 映射与落盘一致，不丢文件。（Task 2 测试）
5. **windowed 模式 stderr 为 None / 扫码超时** → 启动不崩溃（流重定向），登录在后台线程不卡死、可重试。（Task 4 测试 + 手动）

---

## File Structure

```
main.py                      # 入口：ensure_streams() 重定向 + 启动 App
downloader/__init__.py
downloader/config.py         # app_dir / Project / Config / ConfigStore
downloader/core.py           # CloudFile / FileEntry / TreeNode / git_tracked / build_entries / build_tree / folder_state
downloader/storage.py        # AligoStorage：login_qr / login_token / iter_cloud_files / download_to
downloader/gui.py            # App(tk.Tk) + ProjectDialog + LoginDialog + 树清单 + 线程编排
tests/test_config.py
tests/test_core.py
tests/test_storage.py
requirements.txt             # aligo, qrcode, pillow
requirements-dev.txt         # pytest, pyinstaller
build.bat
README.md
.gitignore
```

---

### Task 1: 项目骨架 + 配置模块

**Files:**
- Create: `downloader/__init__.py`, `downloader/config.py`, `main.py`(占位), `tests/test_config.py`, `requirements.txt`, `requirements-dev.txt`, `.gitignore`
- 初始化 git 仓库（`git init`），便于后续提交。

**Interfaces:**
- Produces:
  - `app_dir() -> Path`：`getattr(sys, 'frozen', False)` 为真返回 `Path(sys.executable).parent`，否则返回项目根（`Path(__file__).resolve().parent.parent`）。
  - `@dataclass(frozen=True) Project: name: str; cloud_path: str; local_path: str`
  - `@dataclass Config: projects: list[Project]; last: str | None = None`
  - `class ConfigStore: __init__(self, path: Path | None = None)`（默认 `app_dir()/'config.json'`）；`load() -> Config`（文件不存在返回 `Config([])`）；`save(config: Config) -> None`（UTF-8，`ensure_ascii=False`，缩进 2）。

- [ ] **Step 1: 写失败测试** `tests/test_config.py`

```python
def test_load_missing_returns_empty(tmp_path):
    assert ConfigStore(tmp_path / "none.json").load() == Config([])

def test_save_load_roundtrip(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    cfg = Config([Project("demo", "/备份/demo", "D:/code/demo")], last="demo")
    store.save(cfg)
    assert store.load() == cfg

def test_save_unicode_readable(tmp_path):
    p = tmp_path / "c.json"
    ConfigStore(p).save(Config([Project("项目", "/云", "D:/本地")]))
    assert "项目" in p.read_text(encoding="utf-8")  # 非 \uXXXX 转义

def test_app_dir_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    assert app_dir() == tmp_path
```

- [ ] **Step 2: 运行确认失败** — `.venv/Scripts/python -m pytest tests/test_config.py -v`，预期 ImportError/FAIL。
- [ ] **Step 3: 实现** `downloader/config.py`（上述签名；`load` 用 `json.load` 还原 `Project`，`save` 用 `dataclasses.asdict`）。`main.py` 暂写 `from downloader.gui import App`（Task 4 补齐）前先放占位 `def main(): ...`。写 `requirements.txt`（aligo>=6.2.8, qrcode, pillow）、`requirements-dev.txt`（pytest, pyinstaller）、`.gitignore`（.venv/ __pycache__/ build/ dist/ *.spec app.log config.json）。
- [ ] **Step 4: 运行确认通过** — `.venv/Scripts/python -m pytest tests/test_config.py -v`，预期 PASS。
- [ ] **Step 5: 提交** — `git add -A && git commit -m "feat: project scaffold and JSON config store"`

---

### Task 2: 核心逻辑（git 过滤 + 比对 + 树模型）

**Files:**
- Create: `downloader/core.py`, `tests/test_core.py`

**Interfaces:**
- Consumes: 无 aligo 依赖（纯逻辑 + subprocess git）。
- Produces:
  - `@dataclass(frozen=True) CloudFile: relpath: str; name: str; size: int; file_id: str`（relpath 用 `/`）
  - `@dataclass(frozen=True) FileEntry: relpath: str; name: str; size: int; file_id: str; status: str`（status ∈ `'pending'|'overwrite'|'same'`）
  - `class NotAGitRepo(RuntimeError)`
  - `git_tracked(local_root: Path) -> set[str]`：`subprocess.run(['git','-C',str(local_root),'ls-files','-z'], capture_output=True, check=True)`，stdout 按 `\0` 切分去空串；`CalledProcessError`/`FileNotFoundError` → 抛 `NotAGitRepo`。
  - `build_entries(cloud_files: Iterable[CloudFile], local_root: Path, tracked: set[str]) -> list[FileEntry]`：跳过 `relpath in tracked` 或 relpath 任一路径段为 `.git`；本地 `local_root/relpath` 不存在→pending，存在且 `size != 本地 size`→overwrite，相等→same。
  - `@dataclass TreeNode: name: str; relpath: str; is_folder: bool; children: list[TreeNode]; entry: FileEntry | None = None`
  - `build_tree(entries: list[FileEntry]) -> list[TreeNode]`：按 relpath 拆段建文件夹节点（文件夹同名合并），文件挂到父节点；返回顶层节点列表（排序：文件夹在前、按名）。
  - `folder_state(node: TreeNode, checked: set[str]) -> str`：返回 `'all'|'none'|'partial'`，依据后代文件 relpath 是否在 `checked` 集合。

- [ ] **Step 1: 写失败测试** `tests/test_core.py`

```python
def test_git_tracked_parses_z(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
        lambda *a, **k: SimpleNamespace(stdout=b"a.txt\x00dir/b.png\x00"))
    assert git_tracked(Path("x")) == {"a.txt", "dir/b.png"}

def test_git_tracked_not_repo(monkeypatch):
    def boom(*a, **k): raise subprocess.CalledProcessError(128, "git")
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(NotAGitRepo): git_tracked(Path("x"))

def test_build_entries_skip_tracked_and_git(tmp_path):
    cf = [CloudFile("a.png","a.png",1,"f1"),
          CloudFile(".git/config","config",1,"f2"),
          CloudFile("src/app.py","app.py",1,"f3")]
    out = build_entries(cf, tmp_path, tracked={"src/app.py"})
    assert [e.relpath for e in out] == ["a.png"]

def test_build_entries_status(tmp_path):
    (tmp_path/"same.png").write_bytes(b"x")      # size 1
    (tmp_path/"diff.png").write_bytes(b"xx")     # size 2
    cf = [CloudFile("miss.png","miss.png",9,"f1"),
          CloudFile("same.png","same.png",1,"f2"),
          CloudFile("diff.png","diff.png",5,"f3")]
    st = {e.relpath: e.status for e in build_entries(cf, tmp_path, set())}
    assert st == {"miss.png":"pending","same.png":"same","diff.png":"overwrite"}

def test_build_entries_unicode_space(tmp_path):
    cf = [CloudFile("素材/图 一.png","图 一.png",3,"f1")]
    out = build_entries(cf, tmp_path, set())
    assert out[0].relpath == "素材/图 一.png" and out[0].status == "pending"

def test_build_tree_nests_and_counts():
    es = [FileEntry("a/x.png","x.png",1,"f1","pending"),
          FileEntry("a/b/y.png","y.png",1,"f2","pending"),
          FileEntry("z.png","z.png",1,"f3","pending")]
    roots = build_tree(es)
    a = next(n for n in roots if n.name == "a")
    assert a.is_folder and len(a.children) == 2  # b/ 与 x.png

def test_folder_state_tristate():
    es = [FileEntry("a/x.png","x.png",1,"f1","pending"),
          FileEntry("a/y.png","y.png",1,"f2","pending")]
    a = next(n for n in build_tree(es) if n.name == "a")
    assert folder_state(a, set()) == "none"
    assert folder_state(a, {"a/x.png"}) == "partial"
    assert folder_state(a, {"a/x.png","a/y.png"}) == "all"
```

- [ ] **Step 2: 运行确认失败** — `.venv/Scripts/python -m pytest tests/test_core.py -v`。
- [ ] **Step 3: 实现** `downloader/core.py`（上述签名）。`build_tree` 用 `dict[relpath, TreeNode]` 缓存文件夹节点；`folder_state` 收集后代文件 relpath 后与 checked 求交判断。
- [ ] **Step 4: 运行确认通过** — `.venv/Scripts/python -m pytest tests/test_core.py -v`。
- [ ] **Step 5: 提交** — `git add downloader/core.py tests/test_core.py && git commit -m "feat: git filter, size compare and tree model"`

---

### Task 3: 存储封装（aligo）

**Files:**
- Create: `downloader/storage.py`, `tests/test_storage.py`

**Interfaces:**
- Consumes: `core.CloudFile`；aligo `Aligo / BaseFile / Null`。
- Produces:
  - `class StorageError(RuntimeError)`
  - `class AligoStorage:`
    - `__init__(self, name: str = 'git-media-downloader')`（持有 `self._ali: Aligo | None = None`）
    - `login_qr(self, on_qr: Callable[[str], None]) -> str`：`self._ali = Aligo(name=self._name, show=on_qr, level=logging.WARNING)`；返回 `self._ali.nick_name`。**阻塞**，须在工作线程调用。
    - `login_token(self, refresh_token: str) -> str`：`Aligo(name=..., refresh_token=refresh_token, level=logging.WARNING)`；返回 nick_name。
    - `iter_cloud_files(self, cloud_path: str) -> Iterator[CloudFile]`：`folder = self._ali.get_file_by_path(cloud_path)`；None 或 `type != 'folder'` → `StorageError`；递归 `get_file_list(parent_file_id=...)`，跳过名为 `.git` 的文件夹，文件产出 `CloudFile(relpath, name, size, file_id)`；列表含 `Null` → `StorageError`。
    - `download_to(self, file_id: str, dest: Path) -> Path`：`dest.parent.mkdir(parents=True, exist_ok=True)`；`with tempfile.TemporaryDirectory(dir=dest.parent) as td:` `local = self._ali.download_file(file_id=file_id, local_folder=td)`；`os.replace(local, dest)`；返回 dest。

- [ ] **Step 1: 写失败测试** `tests/test_storage.py`（用 fake aligo，不联网）

```python
class FakeAli:
    def __init__(self, tree): self.tree = tree  # {file_id: BaseFile-like}
    def get_file_by_path(self, path): return self.tree.get(path)
    def get_file_list(self, parent_file_id): return self.tree[parent_file_id]
    def download_file(self, *, file_id, local_folder):
        p = Path(local_folder) / "f.bin"; p.write_bytes(b"data"); return str(p)

def _storage_with(fake):
    s = AligoStorage(); s._ali = fake; return s

def test_iter_recurses_and_skips_git():
    folder = SimpleNamespace(file_id="root", type="folder", name="proj")
    sub = SimpleNamespace(file_id="sub", type="folder", name="assets")
    git = SimpleNamespace(file_id="g", type="folder", name=".git")
    f1 = SimpleNamespace(file_id="f1", type="file", name="a.png", size=3)
    tree = {"proj": folder, "root": [sub, git, f1], "sub": [
        SimpleNamespace(file_id="f2", type="file", name="b.png", size=4)]}
    out = list(_storage_with(FakeAli(tree)).iter_cloud_files("proj"))
    assert {c.relpath for c in out} == {"a.png", "assets/b.png"}

def test_iter_missing_path_raises():
    with pytest.raises(StorageError):
        list(_storage_with(FakeAli({})).iter_cloud_files("nope"))

def test_download_to_overwrites_existing(tmp_path):
    dest = tmp_path / "a.png"; dest.write_bytes(b"old")
    s = _storage_with(FakeAli({}))
    s.download_to("f1", dest)
    assert dest.read_bytes() == b"data"  # 真正覆盖，而非 aligo 的跳过
```

- [ ] **Step 2: 运行确认失败** — `.venv/Scripts/python -m pytest tests/test_storage.py -v`。
- [ ] **Step 3: 实现** `downloader/storage.py`（上述签名）。`iter_cloud_files` 内部递归辅助函数携带当前 relpath 前缀；用 `isinstance(x, Null)` 判错。`download_to` 用临时目录 + `os.replace` 保证覆盖。
- [ ] **Step 4: 运行确认通过** — `.venv/Scripts/python -m pytest tests/test_storage.py -v`。
- [ ] **Step 5: 提交** — `git add downloader/storage.py tests/test_storage.py && git commit -m "feat: aligo storage wrapper with qr login and atomic overwrite"`

---

### Task 4: GUI 外壳 + 项目管理 + 扫码登录 + 线程基础设施

**Files:**
- Create: `downloader/gui.py`（外壳部分）, 完善 `main.py`
- Modify: `tests/`（新增 `tests/test_main.py`）

**Interfaces:**
- Consumes: `config.ConfigStore/Project/Config/app_dir`，`storage.AligoStorage`。
- Produces:
  - `main.ensure_streams() -> None`：若 `sys.stdout is None` 或 `sys.stderr is None`，重定向到 `app_dir()/'app.log'`（追加，UTF-8）；保证 tqdm/coloredlogs 不崩。
  - `class App(tk.Tk)`：构造接收 `store: ConfigStore`、`storage: AligoStorage`（便于注入测试）。布局：左项目 `Listbox` + 添加/编辑/删除按钮；右云盘/本地 `Entry` + 浏览 + 扫码登录按钮 + 状态 `Label`；底部日志 `Text`。
  - `class ProjectDialog(tk.Toplevel)`：名称/云盘路径/本地路径输入，确定返回 `Project`。
  - `class LoginDialog(tk.Toplevel)`：二维码 `Label` + 状态 `Label` + refresh_token `Entry` + 登录/刷新按钮。
  - 线程基础设施：`self._q = queue.Queue()`；`self.after(100, self._poll)`；`_poll` 按消息类型分发（`'log'/'qr'/'login_ok'/'login_err'/'entries'/'progress'/'done'/'error'`）；`_run(fn)` 起 `threading.Thread(daemon=True)`。
  - 登录编排：扫码按钮 → 打开 LoginDialog → `_run(lambda: storage.login_qr(on_qr=lambda link: self._q.put(('qr', link))))`，成功 `put(('login_ok', name))`，异常 `put(('login_err', str(e)))`；`'qr'` 消息在主线程用 `qrcode.make(link)` + `PIL.ImageTk.PhotoImage` 渲染到 LoginDialog。

- [ ] **Step 1: 写失败测试** `tests/test_main.py`

```python
def test_ensure_streams_replaces_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr("downloader.config.app_dir", lambda: tmp_path)
    ensure_streams()
    assert sys.stderr is not None and sys.stdout is not None
```

- [ ] **Step 2: 运行确认失败** — `.venv/Scripts/python -m pytest tests/test_main.py -v`。
- [ ] **Step 3: 实现** `main.ensure_streams` 与 `main.main()`（`ensure_streams(); App(ConfigStore(), AligoStorage()).mainloop()`）。实现 `gui.py` 外壳：布局、ProjectDialog、LoginDialog、queue/_poll/_run、项目增删改（写回 ConfigStore）、登录编排。树清单与列出/下载留 Task 5。
- [ ] **Step 4: 运行确认通过 + 冒烟** — `.venv/Scripts/python -m pytest tests/test_main.py -v`；`.venv/Scripts/python -c "import tkinter; from downloader.gui import App; from downloader.config import ConfigStore; from downloader.storage import AligoStorage; a=App(ConfigStore(), AligoStorage()); a.update(); a.destroy(); print('GUI OK')"`（需桌面环境）。
- [ ] **Step 5: 提交** — `git add main.py downloader/gui.py tests/test_main.py && git commit -m "feat: gui shell, project management and qr login"`

---

### Task 5: GUI 树形清单 + 勾选 + 列出/下载编排

**Files:**
- Modify: `downloader/gui.py`
- Create: `tests/test_selection.py`（若把选择纯逻辑抽到 core）

**Interfaces:**
- Consumes: `core.git_tracked/build_entries/build_tree/folder_state/FileEntry/NotAGitRepo`，`storage.iter_cloud_files/download_to`。
- Produces（gui 内部）:
  - `Treeview`（tree 模式）：`#0` 名称列（前缀 ☑/▣/☐ + 名），`size` 大小列，`status` 状态列（pending→待下载/overwrite→将覆盖/same→已相同）。
  - `self._node_by_item: dict[str, TreeNode]`、`self._checked: set[str]`（文件 relpath）。
  - `_populate(entries)`：`build_tree` 后插入节点；默认把 pending/overwrite 文件加入 `_checked`；刷新文件夹三态前缀。
  - `_on_click(event)`：`identify_region == 'tree'` 时切换该行勾选；文件夹联动所有后代文件；重算祖先三态；更新"下载选中(N)"。
  - 全选/全不选/反选：改 `_checked` 后刷新。
  - 列出文件：`_run` 内 `tracked = git_tracked(local)`（`NotAGitRepo` → `put(('error', ...))`）；`entries = build_entries(storage.iter_cloud_files(cloud), local, tracked)`；`put(('entries', entries))`。
  - 下载选中：`_run` 内遍历 `_checked` 对应 `FileEntry`，`storage.download_to(file_id, local/relpath)`，逐个 `put(('progress', relpath))`；`threading.Event` 支持取消；结束 `put(('done', summary))`。

- [ ] **Step 1: 写失败测试**（把"由勾选集合 + 树取待下载文件"抽为纯函数 `core.selected_entries(roots, checked) -> list[FileEntry]`）

```python
def test_selected_entries_returns_checked_files():
    es = [FileEntry("a/x.png","x.png",1,"f1","pending"),
          FileEntry("a/y.png","y.png",1,"f2","same")]
    roots = build_tree(es)
    assert [e.relpath for e in selected_entries(roots, {"a/x.png"})] == ["a/x.png"]
```

- [ ] **Step 2: 运行确认失败** — `.venv/Scripts/python -m pytest tests/test_selection.py -v`。
- [ ] **Step 3: 实现** `core.selected_entries` + `gui.py` 树清单/勾选/工具栏/列出/下载编排（上述接口）。
- [ ] **Step 4: 运行确认通过 + 手动冒烟** — `.venv/Scripts/python -m pytest -v`；`.venv/Scripts/python main.py` 手动验证：加项目→扫码登录→列出文件（树形/三态）→勾选→下载选中→日志进度。（真实云盘需用户账号扫码。）
- [ ] **Step 5: 提交** — `git add downloader/core.py downloader/gui.py tests/test_selection.py && git commit -m "feat: tree file list with tri-state selection and download orchestration"`

---

### Task 6: 打包 + 文档 + 端到端验证

**Files:**
- Create: `build.bat`, `README.md`
- Modify: `requirements-dev.txt`（含 pyinstaller）

**Interfaces:**
- Consumes: 全部模块。
- Produces: `dist/GitMediaDownloader.exe`（单文件）。

- [ ] **Step 1: 写打包脚本** `build.bat`

```bat
@echo off
call .venv\Scripts\activate
pyinstaller --onefile --windowed --name GitMediaDownloader ^
  --collect-submodules aligo ^
  --hidden-import qrcode_terminal --hidden-import coloredlogs ^
  main.py
```

- [ ] **Step 2: 写 README** — 使用步骤（扫码登录/加项目/列出/勾选/下载）、refresh_token 获取法（浏览器 F12 → Application → Local Storage → token）、打包法、注意事项（exe 放可写目录、首次需登录、杀毒可能误报、只增不删）。
- [ ] **Step 3: 安装打包依赖并构建** — `.venv/Scripts/python -m pip install pyinstaller`；运行 `build.bat`，预期生成 `dist/GitMediaDownloader.exe`。
- [ ] **Step 4: 端到端验证** — 双击 exe：窗口正常打开（无控制台报错）；扫码登录成功；列出某项目文件树；勾选下载一个文件成功落盘。记录结果。（需用户云盘账号；无法自动化处明确标注手动。）
- [ ] **Step 5: 提交** — `git add build.bat README.md requirements-dev.txt && git commit -m "build: single-exe packaging and usage docs"`

---

## Self-Review

- **Spec 覆盖**：项目管理→Task1/4；扫码登录→Task3/4；树形可勾选清单→Task2/5；覆盖式增量下载→Task2/3/5；只增不删/git 过滤→Task2/3；单 exe→Task6；windowed 兼容→Task4。无遗漏。
- **类型一致**：`CloudFile/FileEntry/TreeNode` 定义于 core，storage 与 gui 复用；status 取值 `pending/overwrite/same` 全程一致；`ConfigStore.load()->Config`、`download_to(file_id, dest)->Path`、`iter_cloud_files(cloud_path)->Iterator[CloudFile]` 跨任务签名一致。
- **Review Focus 落点**：1→Task3 `test_iter_missing_path_raises`；2→Task2 `test_git_tracked_not_repo`；3→Task3 `test_download_to_overwrites_existing`；4→Task2 `test_build_entries_unicode_space`；5→Task4 `test_ensure_streams_replaces_none` + 登录后台线程设计。
- **比例**：计划以签名/测试断言/关键算法为主，未转录完整函数体；长度与 ~700 行工具相称。