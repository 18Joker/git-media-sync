"""入口：windowed 模式流重定向（滚动 + 去 ANSI）+ 启动 GUI。"""
import io
import os
import re
import sys
from pathlib import Path

from downloader import config

_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


class RotatingStream(io.TextIOBase):
    """追加写日志文件，超过 max_bytes 滚动并保留 backups 份；清理 ANSI 转义。"""

    def __init__(self, path: Path, max_bytes: int = 5 * 1024 * 1024, backups: int = 3):
        self._path = Path(path)
        self._max = max_bytes
        self._backups = backups
        self._f = open(self._path, "a", encoding="utf-8")
        self._size = self._path.stat().st_size

    def write(self, s: str) -> int:
        clean = _ANSI.sub("", s)
        data = clean.encode("utf-8")
        if self._size + len(data) > self._max:
            self._rotate()
        self._f.write(clean)
        self._f.flush()
        self._size += len(data)
        return len(s)

    def flush(self) -> None:
        self._f.flush()

    def _rotate(self) -> None:
        self._f.close()
        for i in range(self._backups - 1, 0, -1):
            src = self._path.with_name(f"{self._path.name}.{i}")
            if src.exists():
                os.replace(src, self._path.with_name(f"{self._path.name}.{i + 1}"))
        if self._path.exists():
            os.replace(self._path, self._path.with_name(self._path.name + ".1"))
        self._f = open(self._path, "a", encoding="utf-8")
        self._size = 0


def ensure_streams() -> None:
    # PyInstaller --windowed 下 stdout/stderr 为 None，会让 aligo 的日志崩溃
    if sys.stdout is None or sys.stderr is None:
        stream = RotatingStream(config.app_dir() / "app.log")
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream


def main() -> None:
    ensure_streams()
    from downloader.config import ConfigStore
    from downloader.gui import App
    from downloader.storage import AligoStorage

    App(ConfigStore(), AligoStorage()).mainloop()


if __name__ == "__main__":
    main()