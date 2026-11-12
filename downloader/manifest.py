"""media.gmsync 清单：数据模型、解析校验、按目录分组、本地扫描生成。纯逻辑，不依赖 aligo。"""
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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


DEFAULT_EXTS = frozenset(
    "jpg jpeg png gif webp bmp svg mp4 mov mkv avi webm m4v mp3 wav flac m4a psd".split()
)


def parse_exts(text: str) -> frozenset[str]:
    exts = {e.lower().lstrip(".") for e in re.split(r"[,，\s]+", text) if e.strip(" .")}
    return frozenset(exts) if exts else DEFAULT_EXTS


def scan_media_files(
    local_root: Path, tracked: set[str], exts: frozenset[str]
) -> list[ManifestFile]:
    local_root = Path(local_root)
    files: list[ManifestFile] = []
    for dirpath, dirnames, filenames in os.walk(local_root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            relpath = (Path(dirpath) / name).relative_to(local_root).as_posix()
            if relpath == MANIFEST_NAME or relpath in tracked:
                continue
            if os.path.splitext(name)[1].lower().lstrip(".") not in exts:
                continue
            files.append(ManifestFile(relpath, (Path(dirpath) / name).stat().st_size))
    files.sort(key=lambda f: f.path)
    return files


def write_manifest(local_root: Path, files: list[ManifestFile]) -> Path:
    path = Path(local_root) / MANIFEST_NAME
    data = {
        "version": MANIFEST_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "files": [{"path": f.path, "size": f.size} for f in files],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path