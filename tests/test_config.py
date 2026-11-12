import sys

import pytest

from downloader import config
from downloader.config import Config, ConfigStore, Project, app_dir
from downloader.core import CloudFile


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
    assert "项目" in p.read_text(encoding="utf-8")


def test_app_dir_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    assert app_dir() == tmp_path


def test_load_corrupt_returns_empty_and_backs_up(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{ not json", encoding="utf-8")
    assert ConfigStore(p).load() == Config([])
    assert (tmp_path / "c.json.bak").exists()


def test_load_bad_shape_returns_empty(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"projects": [{"name": "x"}]}', encoding="utf-8")
    assert ConfigStore(p).load() == Config([])


# ---- 列举缓存 ----


def _cf(relpath, size=1):
    return CloudFile(relpath=relpath, name=relpath.split("/")[-1], size=size, file_id="id-" + relpath)


def test_cache_roundtrip(tmp_path):
    store = config.CacheStore(tmp_path / "cache.json")
    files = [_cf("a.png"), _cf("d/b.png", 5)]
    store.save("/云/p", files)
    loaded, saved_at = store.load("/云/p")
    assert loaded == files
    assert saved_at


def test_cache_missing_returns_none(tmp_path):
    assert config.CacheStore(tmp_path / "none.json").load("/x") is None


def test_cache_unknown_path_returns_none(tmp_path):
    store = config.CacheStore(tmp_path / "c.json")
    store.save("/a", [_cf("x.png")])
    assert store.load("/b") is None


def test_cache_corrupt_returns_none(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{ bad", encoding="utf-8")
    assert config.CacheStore(p).load("/x") is None


def test_cache_save_merges_paths(tmp_path):
    store = config.CacheStore(tmp_path / "c.json")
    store.save("/a", [_cf("x.png")])
    store.save("/b", [_cf("y.png")])
    assert store.load("/a")[0] == [_cf("x.png")]
    assert store.load("/b")[0] == [_cf("y.png")]


def test_cache_save_overwrites_same_path(tmp_path):
    store = config.CacheStore(tmp_path / "c.json")
    store.save("/a", [_cf("x.png")])
    store.save("/a", [_cf("z.png", 9)])
    assert store.load("/a")[0] == [_cf("z.png", 9)]


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