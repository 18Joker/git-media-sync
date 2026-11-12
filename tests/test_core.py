import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from downloader.core import (
    CloudFile,
    FileEntry,
    NotAGitRepo,
    build_entries,
    build_tree,
    folder_state,
    git_tracked,
)


def test_git_tracked_parses_z(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=b"a.txt\x00dir/b.png\x00"),
    )
    assert git_tracked(Path("x")) == {"a.txt", "dir/b.png"}


def test_git_tracked_not_repo(monkeypatch):
    def boom(*a, **k):
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(NotAGitRepo):
        git_tracked(Path("x"))


def test_git_tracked_git_not_installed(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(NotAGitRepo):
        git_tracked(Path("x"))


def test_build_entries_skip_tracked_and_git(tmp_path):
    cf = [
        CloudFile("a.png", "a.png", 1, "f1"),
        CloudFile(".git/config", "config", 1, "f2"),
        CloudFile("src/app.py", "app.py", 1, "f3"),
    ]
    out = build_entries(cf, tmp_path, tracked={"src/app.py"})
    assert [e.relpath for e in out] == ["a.png"]


def test_build_entries_status(tmp_path):
    (tmp_path / "same.png").write_bytes(b"x")
    (tmp_path / "diff.png").write_bytes(b"xx")
    cf = [
        CloudFile("miss.png", "miss.png", 9, "f1"),
        CloudFile("same.png", "same.png", 1, "f2"),
        CloudFile("diff.png", "diff.png", 5, "f3"),
    ]
    st = {e.relpath: e.status for e in build_entries(cf, tmp_path, set())}
    assert st == {"miss.png": "pending", "same.png": "same", "diff.png": "overwrite"}


def test_build_entries_unicode_space(tmp_path):
    cf = [CloudFile("素材/图 一.png", "图 一.png", 3, "f1")]
    out = build_entries(cf, tmp_path, set())
    assert out[0].relpath == "素材/图 一.png" and out[0].status == "pending"


def test_build_tree_nests_and_counts():
    es = [
        FileEntry("a/x.png", "x.png", 1, "f1", "pending"),
        FileEntry("a/b/y.png", "y.png", 1, "f2", "pending"),
        FileEntry("z.png", "z.png", 1, "f3", "pending"),
    ]
    roots = build_tree(es)
    a = next(n for n in roots if n.name == "a")
    assert a.is_folder and len(a.children) == 2


def test_folder_state_tristate():
    es = [
        FileEntry("a/x.png", "x.png", 1, "f1", "pending"),
        FileEntry("a/y.png", "y.png", 1, "f2", "pending"),
    ]
    a = next(n for n in build_tree(es) if n.name == "a")
    assert folder_state(a, set()) == "none"
    assert folder_state(a, {"a/x.png"}) == "partial"
    assert folder_state(a, {"a/x.png", "a/y.png"}) == "all"