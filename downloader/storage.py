"""aligo 封装：扫码/refresh_token 登录、递归列目录、原子覆盖下载。"""
import logging
import os
import tempfile
from pathlib import Path
from typing import Callable, Iterator

from aligo import Aligo, Null

from downloader.core import CloudFile


class StorageError(RuntimeError):
    """云盘操作失败（路径不存在、未登录、列出失败等）。"""


class AligoStorage:
    def __init__(self, name: str = "git-media-downloader"):
        self._name = name
        self._ali: Aligo | None = None

    def login_qr(self, on_qr: Callable[[str], None]) -> str:
        self._ali = Aligo(name=self._name, show=on_qr, level=logging.WARNING)
        return self._ali.nick_name

    def login_token(self, refresh_token: str) -> str:
        self._ali = Aligo(
            name=self._name, refresh_token=refresh_token, level=logging.WARNING
        )
        return self._ali.nick_name

    def iter_cloud_files(self, cloud_path: str) -> Iterator[CloudFile]:
        if self._ali is None:
            raise StorageError("尚未登录")
        folder = self._ali.get_file_by_path(cloud_path)
        if folder is None or isinstance(folder, Null):
            raise StorageError(f"云盘路径不存在：{cloud_path}")
        if folder.type != "folder":
            raise StorageError(f"云盘路径不是文件夹：{cloud_path}")
        yield from self._walk(folder.file_id, "")

    def _walk(self, parent_file_id: str, prefix: str) -> Iterator[CloudFile]:
        for item in self._ali.get_file_list(parent_file_id=parent_file_id):
            if isinstance(item, Null):
                raise StorageError("列出云盘文件失败")
            relpath = f"{prefix}/{item.name}" if prefix else item.name
            if item.type == "folder":
                if item.name == ".git":
                    continue
                yield from self._walk(item.file_id, relpath)
            else:
                yield CloudFile(
                    relpath=relpath,
                    name=item.name,
                    size=item.size or 0,
                    file_id=item.file_id,
                )

    def download_to(self, file_id: str, dest: Path) -> Path:
        if self._ali is None:
            raise StorageError("尚未登录")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dest.parent) as td:
            local = self._ali.download_file(file_id=file_id, local_folder=td)
            os.replace(local, dest)
        return dest