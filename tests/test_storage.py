from pathlib import Path
from types import SimpleNamespace

import pytest

from downloader.storage import AligoStorage, StorageError


class FakeAli:
    def __init__(self, tree):
        self.tree = tree

    def get_file_by_path(self, path):
        return self.tree.get(path)

    def get_file_list(self, parent_file_id):
        return self.tree[parent_file_id]

    def download_file(self, *, file_id, local_folder):
        p = Path(local_folder) / "f.bin"
        p.write_bytes(b"data")
        return str(p)


def _storage_with(fake):
    s = AligoStorage()
    s._ali = fake
    return s


def test_iter_recurses_and_skips_git():
    folder = SimpleNamespace(file_id="root", type="folder", name="proj")
    sub = SimpleNamespace(file_id="sub", type="folder", name="assets")
    git = SimpleNamespace(file_id="g", type="folder", name=".git")
    f1 = SimpleNamespace(file_id="f1", type="file", name="a.png", size=3)
    tree = {
        "proj": folder,
        "root": [sub, git, f1],
        "sub": [SimpleNamespace(file_id="f2", type="file", name="b.png", size=4)],
    }
    out = list(_storage_with(FakeAli(tree)).iter_cloud_files("proj"))
    assert {c.relpath for c in out} == {"a.png", "assets/b.png"}


def test_iter_missing_path_raises():
    with pytest.raises(StorageError):
        list(_storage_with(FakeAli({})).iter_cloud_files("nope"))


def test_download_to_overwrites_existing(tmp_path):
    dest = tmp_path / "a.png"
    dest.write_bytes(b"old")
    s = _storage_with(FakeAli({}))
    s.download_to("f1", dest)
    assert dest.read_bytes() == b"data"