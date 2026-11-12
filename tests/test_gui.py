import re
import threading
import time

import pytest

from downloader import gui
from downloader.config import CacheStore, Config, ConfigStore, Project
from downloader.core import CloudFile, FileEntry, NotAGitRepo
from downloader.gui import App
from downloader.manifest import parse_manifest
from downloader.storage import StorageError


class FakeStorage:
    def __init__(self):
        self.login_qr_calls = 0
        self.url_map = None
        self.cloud_files = []
        self.iter_error = None

    def login_qr(self, on_qr):
        self.login_qr_calls += 1
        return "user"

    def login_token(self, token):
        return "user"

    def get_download_urls(self, file_ids):
        if self.url_map is not None:
            return dict(self.url_map)
        return {fid: f"u-{fid}" for fid in file_ids}

    def iter_cloud_files(self, cloud_path, on_progress=None):
        if self.iter_error is not None:
            raise self.iter_error
        if on_progress is not None:
            on_progress(1, len(self.cloud_files))
        yield from self.cloud_files


class FakeDialog:
    def set_status(self, text):
        pass


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gui")
    store = ConfigStore(tmp / "c.json")
    store.save(
        Config(
            [
                Project("A", "/cloud/A", str(tmp / "A")),
                Project("B", "/cloud/B", str(tmp / "B")),
            ]
        )
    )
    a = App(store, FakeStorage(), cache=CacheStore(tmp / "cache.json"))
    yield a
    a.destroy()


def _entries():
    return [
        FileEntry("a/x.png", "x.png", 1, "f1", "pending"),
        FileEntry("a/y.png", "y.png", 1, "f2", "same"),
    ]


def test_populate_enables_download(app):
    app._populate(_entries())
    app.update()
    assert str(app.download_btn["state"]) == "normal"
    assert len(app._checked) == 1


def test_project_switch_clears_state(app):
    app._populate(_entries())
    app.update()
    app.project_list.selection_set(1)
    app._on_select_project()
    app.update()
    assert app._entries == []
    assert app._checked == set()
    assert app.tree.get_children() == ()
    assert str(app.download_btn["state"]) == "disabled"


def test_toggle_folder_tristate(app):
    app._populate(_entries())
    folder = next(n for n in app._roots if n.name == "a")
    app._toggle(folder)
    assert app._checked == {"a/x.png", "a/y.png"}
    app._toggle(folder)
    assert app._checked == set()


def test_login_single_flight(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "_run", lambda fn: calls.append(fn))
    app._login_busy = True
    app._start_qr_login(FakeDialog())
    assert calls == []


def test_login_ok_resets_busy(app):
    app._login_busy = True
    app._handle(("login_ok", "user"))
    assert app._login_busy is False
    assert app.logged_in is True


# ---- 下载编排 ----


def _drain(app):
    msgs = []
    while not app._q.empty():
        msgs.append(app._q.get_nowait())
    return msgs


def _files(n, size=10):
    return [FileEntry(f"f{i}.bin", f"f{i}.bin", size, f"id{i}", "pending") for i in range(n)]


def _fake_download(monkeypatch, app, impl):
    app.storage.url_map = None
    app._cancel = threading.Event()
    monkeypatch.setattr(gui, "download_url_to", impl, raising=False)


def _write_and_report(url, dest, size, *, on_progress=None, cancel=None, session=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"x" * size)
    if on_progress:
        on_progress(size)
    return dest


def test_download_worker_runs_two_in_parallel(app, monkeypatch, tmp_path):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def impl(url, dest, size, *, on_progress=None, cancel=None, session=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        try:
            return _write_and_report(url, dest, size, on_progress=on_progress)
        finally:
            with lock:
                active -= 1

    _fake_download(monkeypatch, app, impl)
    app._download_worker(_files(5), tmp_path)
    msgs = _drain(app)
    done = [m for m in msgs if m[0] == "done"][-1]
    assert done[1] == "下载完成：成功 5，失败 0，取消 0"
    assert max_active == 2


def test_download_worker_cancel_counts(app, monkeypatch, tmp_path):
    monkeypatch.setattr(gui, "DOWNLOAD_WORKERS", 1, raising=False)

    def impl(url, dest, size, *, on_progress=None, cancel=None, session=None):
        _write_and_report(url, dest, size, on_progress=on_progress)
        cancel.set()
        return dest

    _fake_download(monkeypatch, app, impl)
    app._download_worker(_files(5), tmp_path)
    done = [m for m in _drain(app) if m[0] == "done"][-1]
    assert done[1] == "下载完成：成功 1，失败 0，取消 4"


def test_download_worker_missing_url_fails(app, monkeypatch, tmp_path):
    _fake_download(monkeypatch, app, _write_and_report)
    app.storage.url_map = {"id0": "u0"}
    app._download_worker(_files(2), tmp_path)
    msgs = _drain(app)
    done = [m for m in msgs if m[0] == "done"][-1]
    assert done[1] == "下载完成：成功 1，失败 1，取消 0"
    assert any(m[0] == "progress" and m[1].startswith("✗ f1.bin") for m in msgs)


def test_download_worker_url_fetch_failure(app, monkeypatch, tmp_path):
    _fake_download(monkeypatch, app, _write_and_report)

    def boom(file_ids):
        raise StorageError("网络断了")

    monkeypatch.setattr(app.storage, "get_download_urls", boom)
    app._download_worker(_files(2), tmp_path)
    done = [m for m in _drain(app) if m[0] == "done"][-1]
    assert done[1] == "下载完成：成功 0，失败 2，取消 0"


def test_download_worker_progress_messages(app, monkeypatch, tmp_path):
    _fake_download(monkeypatch, app, _write_and_report)
    app._download_worker(_files(3), tmp_path)
    msgs = _drain(app)
    assert ("dl_start", 3, 30) in msgs
    last = [m for m in msgs if m[0] == "dl_progress"][-1]
    assert last[1] == 3 and last[2] == 3 and last[3] == 30 and last[4] == 30


def test_download_status_format():
    assert gui.download_status(3, 10, 300, 1000, 100) == "3/10 · 100B/s · 剩余 7秒"
    assert gui.download_status(0, 10, 0, 1000, 0) == "0/10 · 0B/s · 剩余 --"


def test_format_eta():
    assert gui.format_eta(7) == "7秒"
    assert gui.format_eta(65) == "1分05秒"
    assert gui.format_eta(3700) == "1小时01分"


def test_handle_dl_progress_updates_widgets(app):
    app._handle(("dl_start", 10, 1000))
    app._handle(("dl_progress", 3, 10, 300, 1000, 100))
    app.update()
    assert app.dl_bar["maximum"] == 1000
    assert app.dl_bar["value"] == 300
    assert app.dl_status["text"] == "3/10 · 100B/s · 剩余 7秒"


def test_handle_dl_start_resets_bar(app):
    app._handle(("dl_progress", 3, 10, 300, 1000, 100))
    app._handle(("dl_start", 5, 500))
    app.update()
    assert app.dl_bar["value"] == 0
    assert app.dl_status["text"] == "0/5"


# ---- 列举缓存与进度 ----


def _list_setup(app, monkeypatch, files=None, error=None):
    app.cache.path.unlink(missing_ok=True)
    app.storage.cloud_files = files or []
    app.storage.iter_error = error
    monkeypatch.setattr(gui, "git_tracked", lambda root: set())


def test_list_worker_uses_cache_then_refreshes(app, monkeypatch, tmp_path):
    _list_setup(app, monkeypatch, files=[CloudFile("new.png", "new.png", 2, "nid")])
    app.cache.save("/cloud/A", [CloudFile("old.png", "old.png", 1, "oid")])
    app._list_worker("/cloud/A", str(tmp_path))
    msgs = _drain(app)
    cached = [m for m in msgs if m[0] == "cached_entries"]
    assert len(cached) == 1 and cached[0][1][0].relpath == "old.png"
    fresh = [m for m in msgs if m[0] == "entries"][-1]
    assert fresh[1][0].relpath == "new.png" and fresh[2] is True
    assert app.cache.load("/cloud/A")[0] == app.storage.cloud_files


def test_list_worker_without_cache(app, monkeypatch, tmp_path):
    _list_setup(app, monkeypatch, files=[CloudFile("n.png", "n.png", 1, "nid")])
    app._list_worker("/cloud/A", str(tmp_path))
    msgs = _drain(app)
    assert not [m for m in msgs if m[0] == "cached_entries"]
    fresh = [m for m in msgs if m[0] == "entries"][-1]
    assert fresh[2] is False


def test_list_worker_refresh_failure_keeps_cache(app, monkeypatch, tmp_path):
    _list_setup(app, monkeypatch, error=StorageError("网络断了"))
    app.cache.save("/cloud/A", [CloudFile("old.png", "old.png", 1, "oid")])
    app._list_worker("/cloud/A", str(tmp_path))
    msgs = _drain(app)
    assert any(m[0] == "cached_entries" for m in msgs)
    done = [m for m in msgs if m[0] == "done"][-1]
    assert "刷新失败" in done[1] and "缓存" in done[1]
    assert not [m for m in msgs if m[0] == "error"]


def test_list_worker_reports_progress(app, monkeypatch, tmp_path):
    _list_setup(app, monkeypatch, files=[CloudFile("n.png", "n.png", 1, "nid")])
    app._list_worker("/cloud/A", str(tmp_path))
    assert ("list_progress", 1, 1) in _drain(app)


def test_populate_preserve_keeps_unchecked(app):
    app._populate(_entries())
    app._checked.discard("a/x.png")
    more = _entries() + [FileEntry("a/z.png", "z.png", 1, "f3", "pending")]
    app._populate(more, preserve=True)
    assert "a/x.png" not in app._checked
    assert "a/z.png" in app._checked


def test_populate_preserve_keeps_manual_check(app):
    app._populate(_entries())
    app._checked.add("a/y.png")
    app._populate(_entries(), preserve=True)
    assert "a/y.png" in app._checked


def test_handle_list_progress_updates_label(app):
    app._handle(("list_progress", 3, 42))
    app.update()
    assert app.dl_status["text"] == "已扫描 3 个文件夹 / 42 个文件"


def test_handle_cached_entries_keeps_busy(app):
    app._clear_tree()
    app._set_busy(True)
    app._handle(("cached_entries", _entries(), "2026-11-12T09:00:00"))
    app.update()
    assert app._busy is True
    assert len(app._entries) == 2


def test_log_prefixes_timestamp(app):
    app.log.configure(state="normal")
    app.log.delete("1.0", "end")
    app._log("hello")
    text = app.log.get("1.0", "end").strip()
    assert re.match(r"^\d{2}:\d{2}:\d{2} hello$", text)


# ---- 生成清单 ----


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