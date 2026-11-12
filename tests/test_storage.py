from pathlib import Path
from types import SimpleNamespace

import pytest
from aligo import Null

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

    def get_folder_by_path(self, path, create_folder=False):
        return self.folders_by_path.get(path.strip("/"))

    def get_file_list(self, parent_file_id, **kw):
        return self.children[parent_file_id]

    def download_file(self, *, file_id, local_folder):
        p = Path(local_folder) / "f.bin"
        p.write_bytes(b"data")
        return str(p)


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


def test_download_to_overwrites_existing(tmp_path):
    dest = tmp_path / "a.png"
    dest.write_bytes(b"old")
    _storage_with(FakeAli({}, {})).download_to("f1", dest)
    assert dest.read_bytes() == b"data"


def test_download_to_size_match(tmp_path):
    dest = tmp_path / "a.png"
    _storage_with(FakeAli({}, {})).download_to("f1", dest, expected_size=4)
    assert dest.read_bytes() == b"data"


def test_download_to_size_mismatch_preserves_original(tmp_path):
    dest = tmp_path / "a.png"
    dest.write_bytes(b"old")
    with pytest.raises(StorageError):
        _storage_with(FakeAli({}, {})).download_to("f1", dest, expected_size=999)
    assert dest.read_bytes() == b"old"