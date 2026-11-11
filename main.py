"""入口：windowed 模式流重定向 + 启动 GUI。"""
import sys

from downloader import config


def ensure_streams() -> None:
    # PyInstaller --windowed 下 stdout/stderr 为 None，会让 aligo 的 tqdm/日志崩溃
    if sys.stdout is None or sys.stderr is None:
        stream = open(config.app_dir() / "app.log", "a", encoding="utf-8")
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