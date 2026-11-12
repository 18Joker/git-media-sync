import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from aligo import Null

from downloader import storage
from downloader.storage import AligoStorage, StorageError


def _folder(file_id, name):
    return SimpleNamespace(file_id=file_id, name=name, type="folder")


def _file(file_id, name, size):
    return SimpleNamespace(file_id=file_id, name=name, type="file", size=size)


def _null():
    return Null(SimpleNamespace(json=lambda: {}))


class FakeAli:
    """模拟 aligo 真实契约：get_folder_by_path 只解析文件夹，文件/缺失返回 None。"""

    def __init__(self, folders_by_path, children):
        self.folders_by_path = folders_by_path
        self.children = children
        self.list_kwargs = []

    def get_folder_by_path(self, path, create_folder=False):
        return self.folders_by_path.get(path.strip("/"))

    def get_file_list(self, parent_file_id, **kw):
        self.list_kwargs.append(kw)
        return self.children[parent_file_id]


def _storage_with(fake):
    s = AligoStorage()
    s._ali = fake
    return s


def test_iter_resolves_folder_path():
    folders = {"备份/proj": _folder("root", "proj")}
    children = {
        "root": [_folder("sub", "assets"), _folder("g", ".git"), _file("f1", "a.png", 3)],
        "sub": [_file("f2", "b.png", 4)],
    }
    out = list(_storage_with(FakeAli(folders, children)).iter_cloud_files("备份/proj"))
    assert {c.relpath for c in out} == {"a.png", "assets/b.png"}


def test_iter_missing_path_raises():
    with pytest.raises(StorageError):
        list(_storage_with(FakeAli({}, {})).iter_cloud_files("nope"))


def test_iter_file_path_raises():
    # 路径指向文件而非文件夹：get_folder_by_path 返回 None
    with pytest.raises(StorageError):
        list(_storage_with(FakeAli({}, {})).iter_cloud_files("备份/a.png"))


def test_iter_null_item_raises():
    folders = {"p": _folder("root", "p")}
    children = {"root": [_null()]}
    with pytest.raises(StorageError):
        list(_storage_with(FakeAli(folders, children)).iter_cloud_files("p"))


def test_iter_sanitizes_illegal_name():
    folders = {"p": _folder("root", "p")}
    children = {"root": [_file("f1", 'a:b?.png', 3)]}
    out = list(_storage_with(FakeAli(folders, children)).iter_cloud_files("p"))
    assert out[0].relpath == "a_b_.png"


def test_iter_reports_progress():
    folders = {"p": _folder("root", "p")}
    children = {
        "root": [_file("f1", "a.png", 3), _folder("sub", "assets")],
        "sub": [_file("f2", "b.png", 4)],
    }
    calls = []
    out = list(
        _storage_with(FakeAli(folders, children)).iter_cloud_files(
            "p", on_progress=lambda f, n: calls.append((f, n))
        )
    )
    assert len(out) == 2
    assert calls == [(1, 0), (2, 1)]


def test_iter_disables_thumbnail_urls():
    folders = {"p": _folder("root", "p")}
    children = {"root": [_file("f1", "a.png", 3)]}
    ali = FakeAli(folders, children)
    list(_storage_with(ali).iter_cloud_files("p"))
    kw = ali.list_kwargs[0]
    assert kw["image_thumbnail_process"] == ""
    assert kw["image_url_process"] == ""
    assert kw["video_thumbnail_process"] == ""


def _capture_aligo(monkeypatch):
    captured = {}

    class FakeAligo:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.nick_name = "user"

    monkeypatch.setattr("downloader.storage.Aligo", FakeAligo)
    return captured


def test_token_login_paces_requests(monkeypatch):
    captured = _capture_aligo(monkeypatch)
    AligoStorage().login_token("tok")
    assert captured["request_interval"] == 1


def test_qr_login_paces_requests(monkeypatch):
    captured = _capture_aligo(monkeypatch)
    AligoStorage().login_qr(on_qr=lambda link: None)
    assert captured["request_interval"] == 1


# ---- 批量下载链接 ----


def _url_resp(file_id, url, status=200):
    return SimpleNamespace(id=file_id, status=status, body=SimpleNamespace(url=url))


class FakeBatchAli:
    def __init__(self, responses):
        self.responses = responses

    def batch_download_url(self, file_id_list):
        return self.responses


def test_get_download_urls_maps_ids():
    ali = FakeBatchAli([_url_resp("f1", "u1"), _url_resp("f2", "u2")])
    assert _storage_with(ali).get_download_urls(["f1", "f2"]) == {"f1": "u1", "f2": "u2"}


def test_get_download_urls_skips_failed_items():
    ali = FakeBatchAli([
        _url_resp("f1", "u1"),
        SimpleNamespace(id="f2", status=403, body={"code": "Forbidden"}),
    ])
    assert _storage_with(ali).get_download_urls(["f1", "f2"]) == {"f1": "u1"}


def test_get_download_urls_null_raises():
    with pytest.raises(StorageError):
        _storage_with(FakeBatchAli([_null()])).get_download_urls(["f1"])


# ---- 流式下载 ----


class FakeResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield from self._chunks


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_download_url_writes_and_reports_progress(tmp_path):
    dest = tmp_path / "sub" / "a.bin"
    seen = []
    s = FakeSession([FakeResponse([b"ab", b"cd"])])
    storage.download_url_to("u", dest, 4, on_progress=seen.append, session=s)
    assert dest.read_bytes() == b"abcd"
    assert seen == [2, 2]


def test_download_url_sends_range_and_referer(tmp_path):
    s = FakeSession([FakeResponse([b"abcd"])])
    storage.download_url_to("u", tmp_path / "a.bin", 4, session=s)
    _, kwargs = s.requests[0]
    assert kwargs["headers"]["Range"] == "bytes=0-"
    assert kwargs["headers"]["Referer"] == "https://www.aliyundrive.com/"
    assert kwargs["stream"] is True


def test_download_url_retries_transient_error(tmp_path):
    s = FakeSession([requests.ConnectionError("boom"), FakeResponse([b"abcd"])])
    storage.download_url_to("u", tmp_path / "a.bin", 4, session=s, retry_delays=(0, 0))
    assert (tmp_path / "a.bin").read_bytes() == b"abcd"
    assert len(s.requests) == 2


def test_download_url_size_mismatch_exhausts_retries(tmp_path):
    dest = tmp_path / "a.bin"
    dest.write_bytes(b"old")
    s = FakeSession([FakeResponse([b"short"])] * 3)
    with pytest.raises(StorageError):
        storage.download_url_to("u", dest, 999, session=s, retry_delays=(0, 0))
    assert len(s.requests) == 3
    assert dest.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [dest]


def test_download_url_cancel_mid_stream(tmp_path):
    dest = tmp_path / "a.bin"
    cancel = threading.Event()
    s = FakeSession([FakeResponse([b"ab", b"cd"])])
    with pytest.raises(storage.DownloadCancelled):
        storage.download_url_to(
            "u", dest, 4, on_progress=lambda n: cancel.set(), cancel=cancel, session=s
        )
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_download_url_cancel_before_start(tmp_path):
    cancel = threading.Event()
    cancel.set()
    s = FakeSession([])
    with pytest.raises(storage.DownloadCancelled):
        storage.download_url_to("u", tmp_path / "a.bin", cancel=cancel, session=s)
    assert s.requests == []