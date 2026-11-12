"""media.gmsync 清单：数据模型、解析校验、按目录分组。纯逻辑，不依赖 aligo。"""
import json
import re
from dataclasses import dataclass

MANIFEST_NAME = "media.gmsync"
MANIFEST_VERSION = 1

_ILLEGAL_PATH = re.compile(r'[<>:"|?*]')


@dataclass(frozen=True)
class ManifestFile:
    path: str
    size: int


@dataclass(frozen=True)
class Manifest:
    version: int
    generated_at: str
    files: list[ManifestFile]


class ManifestError(ValueError):
    """清单内容损坏或不受支持（JSON 非法、版本不符、路径越界等）。"""


def _validate_path(path: str) -> None:
    if not path or path.startswith("/"):
        raise ManifestError(f"path 必须是非空相对路径：{path!r}")
    if "\\" in path:
        raise ManifestError(f"path 不能含反斜杠：{path!r}")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ManifestError(f"path 不能含空段、. 或 ..：{path!r}")
    if _ILLEGAL_PATH.search(path):
        raise ManifestError(f"path 含非法字符：{path!r}")


def parse_manifest(text: str) -> Manifest:
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ManifestError(f"清单不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise ManifestError("清单顶层必须是 JSON 对象")
    version = data.get("version")
    if version != MANIFEST_VERSION:
        raise ManifestError(f"不支持的清单版本：{version!r}（期望 {MANIFEST_VERSION}）")
    generated_at = data.get("generated_at", "")
    if not isinstance(generated_at, str):
        raise ManifestError("generated_at 必须是字符串")
    raw_files = data.get("files")
    if not isinstance(raw_files, list):
        raise ManifestError("files 必须是数组")
    files: list[ManifestFile] = []
    seen: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            raise ManifestError("files 每项必须是对象")
        path = item.get("path")
        if not isinstance(path, str):
            raise ManifestError("path 必须是字符串")
        _validate_path(path)
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ManifestError(f"size 必须是非负整数：{path!r} 的 {size!r}")
        if path in seen:
            raise ManifestError(f"path 重复：{path!r}")
        seen.add(path)
        files.append(ManifestFile(path, size))
    return Manifest(version, generated_at, files)


def group_by_folder(files: list[ManifestFile]) -> dict[str, list[ManifestFile]]:
    groups: dict[str, list[ManifestFile]] = {}
    for f in files:
        key = f.path.rsplit("/", 1)[0] if "/" in f.path else ""
        groups.setdefault(key, []).append(f)
    return groups