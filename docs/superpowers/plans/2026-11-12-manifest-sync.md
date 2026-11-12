# 清单同步（生成 + 精准下载）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 工具内一键生成本地项目的 `media.gmsync` 清单；「列出文件」优先读云盘清单按目录分组精准定位，缺失时回退全量扫描。

**Architecture:** 新增纯逻辑模块 `downloader/manifest.py`（解析/校验/分组/扫描/写入，不依赖 aligo）；`storage.py` 增加清单读取与精准定位两个方法；`gui.py` 加「生成清单」按钮与 `_list_worker` 清单优先分支。下载链路（build_entries → 树 → 下载）零改动。

**Tech Stack:** Python 3.12、Tkinter/ttk、aligo 6.2.8、pytest；标准库 json/os/pathlib。

**Spec:** `docs/superpowers/specs/2026-11-12-manifest-sync-design.md`

## Global Constraints

- 清单文件名固定 `media.gmsync`；内容 UTF-8 JSON；`version` 固定 `1`；`path` 为相对项目根的正斜杠路径；`size` 为字节数。
- 默认后缀（逐字）：`jpg jpeg png gif webp bmp svg mp4 mov mkv avi webm m4v mp3 wav flac m4a psd`。
- 只做下载不做上传；只增不删；git 已跟踪文件与 `.git/` 永不入清单、永不下载。
- 云存储仅经 aligo 封装；`request_interval=1` 不变；`get_file_list` 必带 `image_thumbnail_process=""`、`image_url_process=""`、`video_thumbnail_process=""`。
- 老 `config.json` 无 `exts` 字段时默认 `""`（用默认后缀），不迁移、不报错。
- 清单来自云端属不可信输入：`path` 必须校验（拒绝 `..`、绝对路径、反斜杠、盘符、Windows 非法字符）。
- 生成清单纯本地操作，不要求登录云盘；写入用 tmp + `os.replace` 原子替换。
- 运行测试统一用 `.venv\Scripts\python -m pytest`（Windows Git Bash 下为 `.venv/Scripts/python -m pytest`）。

## Review Focus

- 清单 `path` 含 `../`、绝对路径、盘符 → 必须拒绝，绝不写到本地项目之外（Task 1 参数化测试）。
- 云端同步未完成：清单有而云端缺失/大小不符 → 跳过 + 警告，不中断、不下载半截文件（Task 3 测试）。
- 老 `config.json` 无 `exts` → 加载不崩、走默认后缀（Task 2 测试）。
- 清单 JSON 损坏 → 明确报错，绝不静默回退慢扫描（Task 5 测试）。
- 生成清单混入 git 已跟踪文件或 `.git/` 内容 → 源码泄露上云，必须排除（Task 2 测试）。

---

### Task 1: manifest.py 数据模型与解析校验

**Files:**
- Create: `downloader/manifest.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: 无（纯逻辑，仅用标准库；复用 `downloader.core` 的风格但不 import aligo）。
- Produces:
  - `MANIFEST_NAME = "media.gmsync"`、`MANIFEST_VERSION = 1`
  - `ManifestFile(path: str, size: int)` — frozen dataclass
  - `Manifest(version: int, generated_at: str, files: list[ManifestFile])` — frozen dataclass
  - `ManifestError(ValueError)`
  - `parse_manifest(text: str) -> Manifest`
  - `group_by_folder(files: list[ManifestFile]) -> dict[str, list[ManifestFile]]`（key 为父目录相对路径，根目录 key 为 `""`；保持插入序）

- [ ] **Step 1: 写失败测试** `tests/test_manifest.py`

```python
import pytest

from downloader.manifest import (
    Manifest, ManifestError, ManifestFile, group_by_folder, parse_manifest,
)

VALID = '{"version": 1, "generated_at": "2026-11-12T21:30:00", "files": [{"path": "assets/a.png", "size": 3}]}'


def test_parse_valid():
    m = parse_manifest(VALID)
    assert m == Manifest(1, "2026-11-12T21:30:00", [ManifestFile("assets/a.png", 3)])


def test_parse_generated_at_optional():
    assert parse_manifest('{"version": 1, "files": []}').generated_at == ""


@pytest.mark.parametrize("text", ["{ bad", "[]", '{"version": 2, "files": []}',
                                  '{"version": 1}', '{"version": 1, "files": {}}'])
def test_parse_bad_shape_raises(text):
    with pytest.raises(ManifestError):
        parse_manifest(text)


@pytest.mark.parametrize("path", ["../a.png", "a/../b.png", "/a.png", "a\\b.png",
                                  "C:/a.png", "", "a//b.png", "a/./b.png", 'a<b.png', "a:b.png"])
def test_parse_bad_path_raises(path):
    with pytest.raises(ManifestError):
        parse_manifest('{"version": 1, "files": [{"path": %s, "size": 1}]}' % __import__("json").dumps(path))


@pytest.mark.parametrize("size", [-1, "3", 1.5, True, None])
def test_parse_bad_size_raises(size):
    with pytest.raises(ManifestError):
        parse_manifest('{"version": 1, "files": [{"path": "a.png", "size": %s}]}' % __import__("json").dumps(size))


def test_parse_duplicate_path_raises():
    with pytest.raises(ManifestError):
        parse_manifest('{"version": 1, "files": [{"path": "a.png", "size": 1}, {"path": "a.png", "size": 2}]}')


def test_group_by_folder():
    files = [ManifestFile("a.png", 1), ManifestFile("d/b.png", 2), ManifestFile("d/e/c.png", 3)]
    assert group_by_folder(files) == {
        "": [files[0]], "d": [files[1]], "d/e": [files[2]],
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_manifest.py -v`
Expected: FAIL（`ModuleNotFoundError: downloader.manifest`）

- [ ] **Step 3: 实现 `downloader/manifest.py`**

按 Interfaces 签名实现。校验规则（`parse_manifest` 内，违规一律 `ManifestError` 带中文原因）：
- `json.loads` 失败、顶层非 dict、`version != 1`、`files` 非 list → 报错；`generated_at` 缺省 `""`，存在则必须为 str。
- 每项必须为 dict；`path` 为 str 且：非空、不以 `/` 开头、不含 `\`、`split("/")` 各段不在 `("", ".", "..")`、不含 `<>:"|?*` 任一字符；`size` 为 int（`isinstance(size, bool)` 拒绝）且 `>= 0`；path 重复报错。
- `group_by_folder`：`key = path.rsplit("/", 1)[0] if "/" in path else ""`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_manifest.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add downloader/manifest.py tests/test_manifest.py
git commit -m "feat: manifest model, parsing and path validation"
```

---

### Task 2: manifest.py 生成侧 + Project.exts 配置

**Files:**
- Modify: `downloader/manifest.py`（追加）
- Modify: `downloader/config.py:18-22`（Project 加字段）
- Test: `tests/test_manifest.py`（追加）、`tests/test_config.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `ManifestFile`、`MANIFEST_NAME`、`MANIFEST_VERSION`；`downloader.core.git_tracked` 由调用方传入 tracked 集合（本模块不跑 git）。
- Produces:
  - `DEFAULT_EXTS: frozenset[str]`（Global Constraints 的默认清单，小写无点）
  - `parse_exts(text: str) -> frozenset[str]`
  - `scan_media_files(local_root: Path, tracked: set[str], exts: frozenset[str]) -> list[ManifestFile]`（按 path 排序）
  - `write_manifest(local_root: Path, files: list[ManifestFile]) -> Path`
  - `Project(name: str, cloud_path: str, local_path: str, exts: str = "")`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_manifest.py`）

```python
from downloader.manifest import DEFAULT_EXTS, parse_exts, scan_media_files, write_manifest


def test_parse_exts_default_when_empty():
    assert parse_exts("") == DEFAULT_EXTS
    assert parse_exts("  , ， ") == DEFAULT_EXTS


def test_parse_exts_custom_normalized():
    assert parse_exts("JPG, .png ，mp4") == frozenset({"jpg", "png", "mp4"})


def test_scan_filters_tracked_git_and_exts(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "x.png").write_bytes(b"1")
    (tmp_path / "tracked.png").write_bytes(b"12")
    (tmp_path / "a.png").write_bytes(b"123")
    (tmp_path / "b.txt").write_bytes(b"1234")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.MP4").write_bytes(b"12345")
    out = scan_media_files(tmp_path, {"tracked.png"}, DEFAULT_EXTS)
    assert out == [ManifestFile("a.png", 3), ManifestFile("sub/c.MP4", 5)]


def test_write_manifest_roundtrip_and_overwrite(tmp_path):
    p = write_manifest(tmp_path, [ManifestFile("a.png", 3)])
    assert p == tmp_path / "media.gmsync"
    assert parse_manifest(p.read_text(encoding="utf-8")).files == [ManifestFile("a.png", 3)]
    write_manifest(tmp_path, [])
    assert parse_manifest(p.read_text(encoding="utf-8")).files == []
    assert list(tmp_path.glob("*.tmp")) == []
```

追加到 `tests/test_config.py`：

```python
def test_project_exts_default_and_roundtrip(tmp_path):
    assert Project("a", "/c", "/l").exts == ""
    store = ConfigStore(tmp_path / "c.json")
    cfg = Config([Project("a", "/c", "/l", "jpg,png")])
    store.save(cfg)
    assert store.load() == cfg


def test_load_old_config_without_exts(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"projects": [{"name": "x", "cloud_path": "/c", "local_path": "/l"}]}', encoding="utf-8")
    assert ConfigStore(p).load().projects[0].exts == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_manifest.py tests/test_config.py -v`
Expected: FAIL（ImportError / TypeError: unexpected keyword 'exts'）

- [ ] **Step 3: 实现**

- `config.py`：`Project` 增加 `exts: str = ""`（其余不动；`ConfigStore.load` 的 `Project(**p)` 天然兼容老配置）。
- `manifest.py` 追加：
  - `DEFAULT_EXTS = frozenset("jpg jpeg png gif webp bmp svg mp4 mov mkv avi webm m4v mp3 wav flac m4a psd".split())`
  - `parse_exts`：`re.split(r"[,，\s]+", text)`，去空段、lower、去前导 `.`；结果为空集 → 返回 `DEFAULT_EXTS`。
  - `scan_media_files`：`os.walk`，`dirs` 中剔除 `.git`；`relpath = (Path(dir) / name).relative_to(local_root).as_posix()`；跳过 tracked；后缀 `os.path.splitext(name)[1].lower().lstrip(".")` 在 exts 中才纳入；`size = stat.st_size`；按 path 排序返回。
  - `write_manifest`：组装 `{"version": MANIFEST_VERSION, "generated_at": datetime.now().isoformat(timespec="seconds"), "files": [{"path": f.path, "size": f.size} ...]}`，`json.dumps(ensure_ascii=False, indent=2)` 写 `media.gmsync.tmp` 再 `os.replace`，返回清单 Path。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_manifest.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add downloader/manifest.py downloader/config.py tests/test_manifest.py tests/test_config.py
git commit -m "feat: local manifest generation with ext whitelist and per-project exts"
```

---

### Task 3: storage.py 云端清单读取与精准定位

**Files:**
- Modify: `downloader/storage.py`（追加两个方法 + import）
- Test: `tests/test_storage.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `Manifest`、`ManifestFile`、`parse_manifest`、`group_by_folder`、`MANIFEST_NAME`；现有 `_sanitize`、`_REFERER`、`get_download_urls`、`CloudFile`。
- Produces:
  - `AligoStorage.read_manifest(cloud_path: str) -> Manifest | None`（不存在/同名文件夹 → None；损坏抛 `ManifestError`；网络/链接失败抛 `StorageError`）
  - `AligoStorage.resolve_manifest_files(cloud_path: str, manifest: Manifest, on_progress: Callable[[int, int], None] | None = None) -> tuple[list[CloudFile], list[str]]`（返回解析出的文件 + 警告文案列表；on_progress(已完成目录数, 已定位文件数)）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_storage.py`；先扩展 FakeAli）

FakeAli 改为 `def __init__(self, folders_by_path, children, files_by_path=None)`，新增：

```python
    def get_file_by_path(self, path):
        return (self.files_by_path or {}).get(path.strip("/"))
```

新增测试：

```python
import json

from downloader.manifest import Manifest, ManifestError, ManifestFile


def _manifest(*files):
    return Manifest(1, "t", list(files))


class FakeResp:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def test_read_manifest_missing_returns_none():
    assert _storage_with(FakeAli({}, {})).read_manifest("p") is None


def test_read_manifest_folder_with_same_name_returns_none():
    ali = FakeAli({}, {}, {"p/media.gmsync": _folder("m", "media.gmsync")})
    assert _storage_with(ali).read_manifest("p") is None


def test_read_manifest_parses_content(monkeypatch):
    body = json.dumps({"version": 1, "files": [{"path": "a.png", "size": 3}]}).encode("utf-8")
    ali = FakeAli({}, {}, {"p/media.gmsync": _file("m", "media.gmsync", len(body))})
    ali.batch_download_url = lambda file_id_list: [_url_resp("m", "u")]
    monkeypatch.setattr(storage.requests, "get", lambda url, **kw: FakeResp(body))
    m = _storage_with(ali).read_manifest("p")
    assert m.files == [ManifestFile("a.png", 3)]


def test_read_manifest_bad_json_raises(monkeypatch):
    ali = FakeAli({}, {}, {"p/media.gmsync": _file("m", "media.gmsync", 5)})
    ali.batch_download_url = lambda file_id_list: [_url_resp("m", "u")]
    monkeypatch.setattr(storage.requests, "get", lambda url, **kw: FakeResp(b"{ bad"))
    with pytest.raises(ManifestError):
        _storage_with(ali).read_manifest("p")


def test_resolve_groups_and_matches():
    folders = {"p": _folder("root", "p"), "p/assets": _folder("sub", "assets")}
    children = {
        "root": [_file("f1", "a.png", 3), _file("x", "unlisted.png", 9)],
        "sub": [_file("f2", "b.png", 4), _folder("f3", "c.png"), _file("f4", "d.png", 99)],
    }
    m = _manifest(ManifestFile("a.png", 3), ManifestFile("assets/b.png", 4),
                  ManifestFile("assets/c.png", 5), ManifestFile("assets/d.png", 5),
                  ManifestFile("assets/gone.png", 1))
    calls = []
    files, warnings = _storage_with(FakeAli(folders, children)).resolve_manifest_files(
        "p", m, on_progress=lambda d, n: calls.append((d, n)))
    assert files == [CloudFile("a.png", "a.png", 3, "f1"), CloudFile("assets/b.png", "b.png", 4, "f2")]
    assert len(warnings) == 3  # c.png 是文件夹、d.png 大小不符、gone.png 缺失
    assert calls == [(1, 1), (2, 2)]


def test_resolve_missing_folder_warns_and_skips():
    m = _manifest(ManifestFile("nope/a.png", 3))
    files, warnings = _storage_with(FakeAli({}, {})).resolve_manifest_files("p", m)
    assert files == []
    assert len(warnings) == 1 and "nope" in warnings[0]


def test_resolve_null_item_raises():
    folders = {"p": _folder("root", "p")}
    children = {"root": [_null()]}
    with pytest.raises(StorageError):
        _storage_with(FakeAli(folders, children)).resolve_manifest_files("p", _manifest(ManifestFile("a.png", 3)))
```

注意：`test_resolve_groups_and_matches` 需 `from downloader.core import CloudFile`（文件头部已有 storage import，CloudFile 要补 import）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_storage.py -v`
Expected: FAIL（AttributeError: read_manifest / resolve_manifest_files）

- [ ] **Step 3: 实现两个方法**

`read_manifest`：未登录抛 `StorageError("尚未登录")`；`base = cloud_path.strip("/")`；`item = self._ali.get_file_by_path(f"{base}/{MANIFEST_NAME}")`；`None`/`Null`/`item.type != "file"` → 返回 `None`；`urls = self.get_download_urls([item.file_id])`，无 url 抛 `StorageError("获取清单下载链接失败")`；`requests.get(url, headers={"Referer": _REFERER}, timeout=30)`，`raise_for_status()`，`parse_manifest(resp.content.decode("utf-8"))`；`requests.RequestException` 包装为 `StorageError(f"读取清单失败：{e}")`。

`resolve_manifest_files`：未登录抛错；`groups = group_by_folder(manifest.files)`；逐组：`path = f"{base}/{folder}" if folder else base` → `get_folder_by_path(path, create_folder=False)`；`None`/`Null` → 警告 `f"云端目录不存在，跳过 {len(mfs)} 个文件：{folder or '/'}"`；否则单层 `get_file_list`（带三个空处理串），`Null` 项抛 `StorageError("列出云盘文件失败")`，仅 `type != "folder"` 的项按 `_sanitize(item.name)` 建索引；逐条匹配：缺失 → `f"云端未找到：{mf.path}"`；`(item.size or 0) != mf.size` → `f"云端大小与清单不符（可能同步未完成）：{mf.path}（清单 {mf.size}，云端 {item.size or 0}）"`；命中 → `CloudFile(mf.path, name, mf.size, item.file_id)`。每组结束调 `on_progress(组序号, 累计文件数)`。返回 `(files, warnings)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_storage.py -v`
Expected: PASS（含原有用例）

- [ ] **Step 5: Commit**

```bash
git add downloader/storage.py tests/test_storage.py
git commit -m "feat: cloud manifest reading and folder-grouped precise resolution"
```

---

### Task 4: GUI 生成清单（按钮 + 项目弹窗后缀行 + worker）

**Files:**
- Modify: `downloader/gui.py`（ProjectDialog、_build_center、_set_busy、新增两个方法、import）
- Test: `tests/test_gui.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `parse_exts`、`scan_media_files`、`write_manifest`、`MANIFEST_NAME`、`Project.exts`；现有 `git_tracked`、`NotAGitRepo`、`human_size`、`_run`/`_q`/`_set_busy`。
- Produces:
  - `App._generate_manifest()`（按钮回调，不要求登录）
  - `App._generate_worker(local: str, exts: str)`（后台线程，消息走 `_q`）
  - `ProjectDialog` 新增 `exts_var`，`result` 为含 exts 的 `Project`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_gui.py`）

```python
from downloader.core import NotAGitRepo
from downloader.manifest import parse_manifest


def test_generate_worker_writes_manifest(app, monkeypatch, tmp_path):
    monkeypatch.setattr(gui, "git_tracked", lambda root: {"tracked.png"})
    (tmp_path / "a.png").write_bytes(b"123")
    (tmp_path / "tracked.png").write_bytes(b"1")
    (tmp_path / "b.txt").write_bytes(b"1")
    app._generate_worker(str(tmp_path), "")
    done = [m for m in _drain(app) if m[0] == "done"][-1]
    assert "已生成 media.gmsync：1 个文件" in done[1]
    assert parse_manifest((tmp_path / "media.gmsync").read_text(encoding="utf-8")).files[0].path == "a.png"


def test_generate_worker_custom_exts(app, monkeypatch, tmp_path):
    monkeypatch.setattr(gui, "git_tracked", lambda root: set())
    (tmp_path / "a.png").write_bytes(b"1")
    (tmp_path / "b.txt").write_bytes(b"1")
    app._generate_worker(str(tmp_path), "txt")
    m = parse_manifest((tmp_path / "media.gmsync").read_text(encoding="utf-8"))
    assert [f.path for f in m.files] == ["b.txt"]


def test_generate_worker_not_git_repo(app, monkeypatch, tmp_path):
    def boom(root):
        raise NotAGitRepo("no git")
    monkeypatch.setattr(gui, "git_tracked", boom)
    app._generate_worker(str(tmp_path), "")
    assert any(m[0] == "error" for m in _drain(app))


def test_generate_requires_no_login(app, monkeypatch, tmp_path):
    app.logged_in = False
    app._set_busy(False)
    app.local_var.set(str(tmp_path))
    calls = []
    monkeypatch.setattr(app, "_run", lambda fn: calls.append(fn))
    app._generate_manifest()
    assert len(calls) == 1
    app._set_busy(False)


def test_project_dialog_carries_exts(app):
    dlg = gui.ProjectDialog(app)
    dlg.name_var.set("A2")
    dlg.cloud_var.set("/c")
    dlg.local_var.set("/l")
    dlg.exts_var.set("jpg, png")
    dlg._ok()
    assert dlg.result == Project("A2", "/c", "/l", "jpg, png")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_gui.py -v -k "generate or dialog_carries"`
Expected: FAIL（AttributeError: _generate_worker / exts_var）

- [ ] **Step 3: 实现 GUI 改动**

- import 增加：`from downloader.manifest import MANIFEST_NAME, parse_exts, scan_media_files, write_manifest`。
- `ProjectDialog`：row 3 加「素材后缀」Label + `exts_var` Entry（width 40，columnspan 2）；row 4 加提示 Label「逗号分隔，留空使用默认（jpg png mp4 等）」；按钮行移到 row 5；`_ok` 构造 `Project(name, cloud, local, self.exts_var.get().strip())`；编辑时 `exts_var` 初值取 `project.exts`。
- `_build_center`：`list_btn` 后加 `self.gen_btn = ttk.Button(bar, text="生成清单", command=self._generate_manifest)`，`pack(side="left", padx=(6, 0))`。
- `_set_busy`：`gen_btn` 与 `list_btn` 同样随 busy 禁用/启用。
- `_generate_manifest`：busy 直接返回；`local = self.local_var.get().strip()`，空则 warning「请填写本地路径」；**不检查登录**；`p = self._current()`，`exts = p.exts if p else ""`；`_set_busy(True)`；日志 `f"正在扫描 {local} 生成清单 …"`；`_run(lambda: self._generate_worker(local, exts))`。
- `_generate_worker(local, exts)`：`git_tracked` 失败 → `("error", f"本地不是 git 仓库或未安装 git：{e}")`；`scan_media_files` + `write_manifest` 的 `OSError` → `("error", f"生成清单失败：{e}")`；成功 → `("done", f"已生成 {MANIFEST_NAME}：{len(files)} 个文件，共 {human_size(sum(f.size for f in files))}。等待自动同步上传后，即可在其他设备列出下载")`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_gui.py -v`
Expected: PASS（含原有用例）

- [ ] **Step 5: Commit**

```bash
git add downloader/gui.py tests/test_gui.py
git commit -m "feat: generate manifest button with per-project ext whitelist"
```

---

### Task 5: GUI 列出文件清单优先 + 回退

**Files:**
- Modify: `downloader/gui.py:468-495`（`_list_worker`）
- Test: `tests/test_gui.py`（追加）

**Interfaces:**
- Consumes: Task 3 的 `read_manifest`、`resolve_manifest_files`；Task 1 的 `ManifestError`、`MANIFEST_NAME`；现有缓存/进度/`build_entries` 流程。
- Produces: `_list_worker` 新行为（签名不变）；`FakeStorage` 增加 `manifest`、`manifest_error`、`resolve_result`、`iter_calls` 属性与两个新方法。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_gui.py`；先扩展 FakeStorage）

FakeStorage `__init__` 增加：`self.manifest = None`、`self.manifest_error = None`、`self.resolve_result = ([], [])`、`self.iter_calls = 0`；`iter_cloud_files` 首行 `self.iter_calls += 1`；新增：

```python
    def read_manifest(self, cloud_path):
        if self.manifest_error is not None:
            raise self.manifest_error
        return self.manifest

    def resolve_manifest_files(self, cloud_path, manifest, on_progress=None):
        if on_progress is not None:
            on_progress(1, len(self.resolve_result[0]))
        return self.resolve_result
```

新增测试：

```python
from downloader.manifest import Manifest, ManifestError, ManifestFile


def _manifest_setup(app, monkeypatch, manifest, result=([], []), error=None):
    _list_setup(app, monkeypatch)
    app.storage.manifest = manifest
    app.storage.manifest_error = error
    app.storage.resolve_result = result
    app.storage.iter_calls = 0


def test_list_worker_uses_manifest(app, monkeypatch, tmp_path):
    m = Manifest(1, "2026-11-12T21:30:00", [ManifestFile("a.png", 3)])
    _manifest_setup(app, monkeypatch, m,
                    result=([CloudFile("a.png", "a.png", 3, "fid")], ["云端未找到：b.png"]))
    app._list_worker("/cloud/A", str(tmp_path))
    msgs = _drain(app)
    fresh = [msg for msg in msgs if msg[0] == "entries"][-1]
    assert fresh[1][0].relpath == "a.png"
    assert app.storage.iter_calls == 0
    assert any(msg[0] == "log" and "已读取清单 media.gmsync：1 个文件" in msg[1] for msg in msgs)
    assert any(msg[0] == "log" and "⚠ 云端未找到：b.png" in msg[1] for msg in msgs)
    assert app.cache.load("/cloud/A")[0] == [CloudFile("a.png", "a.png", 3, "fid")]


def test_list_worker_falls_back_without_manifest(app, monkeypatch, tmp_path):
    _manifest_setup(app, monkeypatch, None)
    app.storage.cloud_files = [CloudFile("n.png", "n.png", 1, "nid")]
    app._list_worker("/cloud/A", str(tmp_path))
    msgs = _drain(app)
    assert app.storage.iter_calls == 1
    assert any(msg[0] == "log" and "回退全量扫描" in msg[1] for msg in msgs)
    assert [msg for msg in msgs if msg[0] == "entries"][-1][1][0].relpath == "n.png"


def test_list_worker_manifest_error_reports_no_fallback(app, monkeypatch, tmp_path):
    _manifest_setup(app, monkeypatch, None, error=ManifestError("坏清单"))
    app._list_worker("/cloud/A", str(tmp_path))
    msgs = _drain(app)
    assert any(msg[0] == "error" and "清单" in msg[1] for msg in msgs)
    assert app.storage.iter_calls == 0
    assert not [msg for msg in msgs if msg[0] == "entries"]


def test_list_worker_manifest_network_error_keeps_cache(app, monkeypatch, tmp_path):
    _manifest_setup(app, monkeypatch, None, error=StorageError("网络断了"))
    app.cache.save("/cloud/A", [CloudFile("old.png", "old.png", 1, "oid")])
    app._list_worker("/cloud/A", str(tmp_path))
    msgs = _drain(app)
    assert any(msg[0] == "cached_entries" for msg in msgs)
    assert "刷新失败" in [msg for msg in msgs if msg[0] == "done"][-1][1]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_gui.py -v -k "manifest"`
Expected: FAIL（FakeStorage 无 read_manifest 属性 / 行为不符）

- [ ] **Step 3: 改造 `_list_worker`**

`git_tracked`、缓存加载、`prog` 定义不变。扫描段改为（异常顺序是关键：`ManifestError` 必须在通用 `Exception` 之前，且**不**走缓存回退）：

```python
try:
    manifest = self.storage.read_manifest(cloud)
    if manifest is not None:
        self._q.put(("log", f"已读取清单 {MANIFEST_NAME}：{len(manifest.files)} 个文件（生成于 {manifest.generated_at}）"))
        cloud_files, warnings = self.storage.resolve_manifest_files(cloud, manifest, on_progress=prog)
        for w in warnings:
            self._q.put(("log", f"⚠ {w}"))
    else:
        self._q.put(("log", f"未找到 {MANIFEST_NAME}，回退全量扫描 …"))
        cloud_files = list(self.storage.iter_cloud_files(cloud, on_progress=prog))
except StorageError as e:
    # 原有逻辑不变：有缓存 → done「刷新失败…仍显示缓存」，无缓存 → error
    ...
except ManifestError as e:
    self._q.put(("error", f"清单文件损坏：{e}"))
    return
except Exception as e:  # noqa: BLE001
    self._q.put(("error", str(e)))
    return
self.cache.save(cloud, cloud_files)
self._q.put(("entries", build_entries(cloud_files, root, tracked), cached is not None))
```

import 增加 `ManifestError`（`MANIFEST_NAME` Task 4 已引入）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_gui.py -v`
Expected: PASS（含原有用例——FakeStorage.manifest 默认 None，老用例自动走回退分支）

- [ ] **Step 5: Commit**

```bash
git add downloader/gui.py tests/test_gui.py
git commit -m "feat: manifest-first listing with full-scan fallback"
```

---

### Task 6: README 更新 + 全量回归

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1-5 全部行为。
- Produces: 文档与绿色全量测试。

- [ ] **Step 1: 更新 README**

- 「使用步骤」第 4 步前插入生成侧说明：设备 A 选中项目点「生成清单」（纯本地、无需登录），在项目根生成 `media.gmsync`；自动同步后缀白名单需加入 `gmsync` 及素材后缀。
- 第 4 步改为：优先读云盘根目录 `media.gmsync` 精准定位（日志显示清单文件数与生成时间）；无清单回退全量扫描；清单损坏报错；云端缺失/大小不符的文件跳过并警告。
- 新增「清单格式」小节：贴 spec 中的 JSON 示例与字段表（version/generated_at/files[].path/files[].size），注明 UTF-8、正斜杠相对路径、字节大小。
- 「结构」一节加 `downloader/manifest.py 清单生成/解析/校验/分组（纯逻辑）`。

- [ ] **Step 2: 全量回归**

Run: `.venv/Scripts/python -m pytest`
Expected: 全部 PASS，无失败无报错

- [ ] **Step 3: 手动冒烟（可选但推荐）**

Run: `.venv/Scripts/python main.py`
检查：项目弹窗有「素材后缀」行；未登录可点「生成清单」并在本地项目根看到 `media.gmsync`；「列出文件」日志出现清单读取或回退提示。

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: manifest generation and precise download usage"
```

---

## Self-Review 记录

- Spec 覆盖：清单约定 → Task 1/2；生成（默认+项目级后缀、原子写、免登录）→ Task 2/4；精准定位（分组、警告、回退、损坏报错）→ Task 3/5；文档 → Task 6。无缺口。
- 类型一致性：`ManifestFile/Manifest/parse_manifest/group_by_folder`（T1）→ T2/T3/T5 同名使用；`read_manifest/resolve_manifest_files`（T3）→ T5 FakeStorage 同签名；`Project.exts`（T2）→ T4 弹窗。
- Review Focus 五条均有对应测试：路径穿越（T1）、同步未完成（T3）、老配置（T2）、损坏报错不回退（T5）、tracked/.git 排除（T2）。