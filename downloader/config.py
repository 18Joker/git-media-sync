"""项目配置：app_dir 定位 + Project/Config 数据类 + JSON 读写。"""
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Project:
    name: str
    cloud_path: str
    local_path: str


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