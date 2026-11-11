"""纯逻辑：git 过滤、大小比对、树模型。不依赖 aligo，便于单测。"""
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class CloudFile:
    relpath: str
    name: str
    size: int
    file_id: str


@dataclass(frozen=True)
class FileEntry:
    relpath: str
    name: str
    size: int
    file_id: str
    status: str  # pending | overwrite | same


class NotAGitRepo(RuntimeError):
    """本地路径不是 git 仓库，或未安装 git。"""


def git_tracked(local_root: Path) -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(local_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise NotAGitRepo(f"无法读取 git 跟踪列表（{local_root}）：{e}") from e
    return {p for p in proc.stdout.decode("utf-8").split("\0") if p}


def _is_git_path(relpath: str) -> bool:
    return ".git" in relpath.split("/")


def build_entries(
    cloud_files: Iterable[CloudFile], local_root: Path, tracked: set[str]
) -> list[FileEntry]:
    entries: list[FileEntry] = []
    for cf in cloud_files:
        if cf.relpath in tracked or _is_git_path(cf.relpath):
            continue
        local = local_root / cf.relpath
        if not local.exists():
            status = "pending"
        elif local.stat().st_size != cf.size:
            status = "overwrite"
        else:
            status = "same"
        entries.append(FileEntry(cf.relpath, cf.name, cf.size, cf.file_id, status))
    return entries


@dataclass
class TreeNode:
    name: str
    relpath: str
    is_folder: bool
    children: list["TreeNode"] = field(default_factory=list)
    entry: FileEntry | None = None


def build_tree(entries: list[FileEntry]) -> list[TreeNode]:
    roots: list[TreeNode] = []
    folders: dict[str, TreeNode] = {}

    def ensure_folder(relpath: str) -> TreeNode:
        if relpath in folders:
            return folders[relpath]
        node = TreeNode(name=relpath.split("/")[-1], relpath=relpath, is_folder=True)
        folders[relpath] = node
        parent = relpath.rsplit("/", 1)[0] if "/" in relpath else ""
        if parent:
            ensure_folder(parent).children.append(node)
        else:
            roots.append(node)
        return node

    for e in entries:
        leaf = TreeNode(name=e.name, relpath=e.relpath, is_folder=False, entry=e)
        parent = e.relpath.rsplit("/", 1)[0] if "/" in e.relpath else ""
        if parent:
            ensure_folder(parent).children.append(leaf)
        else:
            roots.append(leaf)

    def sort(nodes: list[TreeNode]) -> None:
        nodes.sort(key=lambda n: (not n.is_folder, n.name))
        for n in nodes:
            if n.is_folder:
                sort(n.children)

    sort(roots)
    return roots


def _descendant_files(node: TreeNode) -> Iterator[FileEntry]:
    if not node.is_folder:
        if node.entry is not None:
            yield node.entry
        return
    for child in node.children:
        yield from _descendant_files(child)


def folder_state(node: TreeNode, checked: set[str]) -> str:
    files = list(_descendant_files(node))
    if not files:
        return "none"
    selected = sum(1 for f in files if f.relpath in checked)
    if selected == 0:
        return "none"
    if selected == len(files):
        return "all"
    return "partial"