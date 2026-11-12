"""aligo 封装：扫码/refresh_token 登录、递归列目录、批量链接 + 流式下载。"""
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

import requests
from aligo import Aligo, Null

from downloader.core import CloudFile

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')
# 64KB：限速 ~33kB/s 时取消响应约 2 秒（1MB chunk 则要等 ~30 秒）
_CHUNK = 64 * 1024
_REFERER = "https://www.aliyundrive.com/"


def _sanitize(name: str) -> str:
    # 与 aligo 落盘清洗一致，保证 relpath 映射与磁盘文件名一致（Windows 非法字符）
    return _ILLEGAL.sub("_", name)


class StorageError(RuntimeError):
    """云盘操作失败（路径不存在、未登录、列出失败、下载校验失败等）。"""


class DownloadCancelled(Exception):
    """用户取消下载。"""


class AligoStorage:
    def __init__(self, name: str = "git-media-downloader"):
        self._name = name
        self._ali: Aligo | None = None

    def login_qr(self, on_qr: Callable[[str], None]) -> str:
        self._ali = Aligo(
            name=self._name, show=on_qr, level=logging.WARNING, login_timeout=120,
            request_interval=1,
        )
        return self._ali.nick_name

    def login_token(self, refresh_token: str) -> str:
        self._ali = Aligo(
            name=self._name, refresh_token=refresh_token, level=logging.WARNING,
            request_interval=1,
        )
        return self._ali.nick_name

    def iter_cloud_files(
        self, cloud_path: str, on_progress: Callable[[int, int], None] | None = None
    ) -> Iterator[CloudFile]:
        if self._ali is None:
            raise StorageError("尚未登录")
        # get_file_by_path 末段只查文件，文件夹路径会返回 None；必须用 get_folder_by_path
        folder = self._ali.get_folder_by_path(cloud_path, create_folder=False)
        if folder is None or isinstance(folder, Null):
            raise StorageError(f"云盘路径不存在或不是文件夹：{cloud_path}")
        stats = {"folders": 0, "files": 0}
        yield from self._walk(folder.file_id, "", stats, on_progress)

    def _walk(self, parent_file_id: str, prefix: str, stats: dict, on_progress) -> Iterator[CloudFile]:
        # 空处理串 = 不让服务端生成缩略图/预览 URL，响应更小、更不易触发限流
        items = self._ali.get_file_list(
            parent_file_id=parent_file_id,
            image_thumbnail_process="",
            image_url_process="",
            video_thumbnail_process="",
        )
        stats["folders"] += 1
        if on_progress is not None:
            on_progress(stats["folders"], stats["files"])
        for item in items:
            if isinstance(item, Null):
                raise StorageError("列出云盘文件失败")
            name = _sanitize(item.name)
            relpath = f"{prefix}/{name}" if prefix else name
            if item.type == "folder":
                if name == ".git":
                    continue
                yield from self._walk(item.file_id, relpath, stats, on_progress)
            else:
                stats["files"] += 1
                yield CloudFile(
                    relpath=relpath,
                    name=name,
                    size=item.size or 0,
                    file_id=item.file_id,
                )

    def get_download_urls(self, file_ids: list[str]) -> dict[str, str]:
        """批量取下载链接（aligo 按 100 个/批拆分）；失败的 file_id 不在结果中。"""
        if self._ali is None:
            raise StorageError("尚未登录")
        urls: dict[str, str] = {}
        for resp in self._ali.batch_download_url(file_id_list=file_ids):
            if isinstance(resp, Null):
                raise StorageError("批量获取下载链接失败")
            if resp.status == 200 and getattr(resp.body, "url", None):
                urls[resp.id] = resp.body.url
        return urls


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def download_url_to(
    url: str,
    dest: Path,
    expected_size: int | None = None,
    *,
    on_progress: Callable[[int], None] | None = None,
    cancel: threading.Event | None = None,
    session: requests.Session | None = None,
    retry_delays: tuple[float, ...] = (2.0, 5.0),
) -> Path:
    """流式下载到临时文件再原子替换；chunk 级取消；失败按 retry_delays 退避重试。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    get = session.get if session is not None else requests.get
    last_err: Exception | None = None
    for attempt in range(len(retry_delays) + 1):
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled()
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".dl-")
        try:
            with os.fdopen(fd, "wb") as f, get(
                url,
                headers={"Range": "bytes=0-", "Referer": _REFERER},
                stream=True,
                timeout=30,
            ) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=_CHUNK):
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled()
                    f.write(chunk)
                    if on_progress is not None:
                        on_progress(len(chunk))
            actual = Path(tmp).stat().st_size
            if expected_size is not None and actual != expected_size:
                raise StorageError(
                    f"下载大小不符（期望 {expected_size}，实际 {actual}）：{dest.name}"
                )
            os.replace(tmp, dest)
            return dest
        except DownloadCancelled:
            _remove(tmp)
            raise
        except (requests.RequestException, StorageError) as e:
            _remove(tmp)
            last_err = e
            if attempt < len(retry_delays):
                delay = retry_delays[attempt]
                if cancel is not None:
                    if cancel.wait(delay):
                        raise DownloadCancelled()
                else:
                    time.sleep(delay)
    raise StorageError(f"下载失败：{dest.name}（{last_err}）") from last_err