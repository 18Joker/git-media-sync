import sys

import pytest

from downloader.config import Config, ConfigStore, Project, app_dir


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