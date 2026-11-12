import sys

import main
from main import ensure_streams


def test_ensure_streams_replaces_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr("downloader.config.app_dir", lambda: tmp_path)
    ensure_streams()
    assert sys.stderr is not None and sys.stdout is not None


def test_rotating_stream_strips_ansi(tmp_path):
    p = tmp_path / "app.log"
    s = main.RotatingStream(p)
    s.write("\x1b[32m你好\x1b[0m\n")
    assert p.read_text(encoding="utf-8") == "你好\n"


def test_rotating_stream_rotates_and_caps_backups(tmp_path):
    p = tmp_path / "app.log"
    s = main.RotatingStream(p, max_bytes=100, backups=3)
    for _ in range(10):
        s.write("x" * 40 + "\n")
    assert sorted(f.name for f in tmp_path.iterdir()) == [
        "app.log", "app.log.1", "app.log.2", "app.log.3",
    ]
    assert p.stat().st_size <= 100