import sys

from main import ensure_streams


def test_ensure_streams_replaces_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr("downloader.config.app_dir", lambda: tmp_path)
    ensure_streams()
    assert sys.stderr is not None and sys.stdout is not None