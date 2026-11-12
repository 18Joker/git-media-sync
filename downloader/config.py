"""项目配置：app_dir 定位 + Project/Config 数据类 + JSON 读写 + 列举缓存。"""
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from downloader.core import CloudFile


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Project:
    name: str
    cloud_path: str
    local_path: str
    exts: str = ""


@dataclass
class Config:
    projects: list[Project]
    last: str | None = None


class ConfigStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else app_dir() / "config.json"

    def load(self) -> Config:
        if not self.path.exists():
            return Config([])
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            projects = [Project(**p) for p in data.get("projects", [])]
            return Config(projects, last=data.get("last"))
        except (ValueError, TypeError, KeyError, AttributeError):
            os.replace(self.path, self.path.with_name(self.path.name + ".bak"))
            return Config([])

    def save(self, config: Config) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "projects": [asdict(p) for p in config.projects],
            "last": config.last,
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)


class CacheStore:
    """列举结果缓存：可再生数据，损坏或形状不对直接忽略。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else app_dir() / "cache.json"

    def load(self, cloud_path: str) -> tuple[list[CloudFile], str] | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            entry = data["entries"][cloud_path]
            return [CloudFile(**f) for f in entry["files"]], entry["saved_at"]
        except (ValueError, TypeError, KeyError, AttributeError):
            return None

    def save(self, cloud_path: str, files: list[CloudFile]) -> None:
        data = {"entries": {}}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        if not isinstance(data.get("entries"), dict):
            data = {"entries": {}}
        data["entries"][cloud_path] = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "files": [asdict(f) for f in files],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)