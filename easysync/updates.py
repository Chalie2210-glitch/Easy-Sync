"""Explicit, background update checks; verified downloads from our GitHub releases."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from .version import REPOSITORY, VERSION

API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_INSTALLER_SIZE = 512 * 1024 * 1024


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise ValueError("지원하지 않는 버전 형식입니다.")
    return tuple(map(int, match.groups()))


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str
    size: int


def parse_release(data: dict, current: str = VERSION) -> Release | None:
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(current):
        return None
    version = tag.removeprefix("v")
    filename = f"Easy-Sync-Setup-{version}-x64.exe"
    expected = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{filename}"
    asset = next((a for a in data.get("assets", []) if a.get("name") == filename), None)
    if not asset or asset.get("browser_download_url") != expected:
        raise ValueError("이 릴리스에 올바른 Windows 설치 파일이 없습니다.")
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        raise ValueError("설치 파일의 SHA-256 검증 정보를 확인할 수 없습니다.")
    size = asset.get("size", 0)
    if type(size) is not int or not 0 < size <= MAX_INSTALLER_SIZE:
        raise ValueError("설치 파일 크기가 올바르지 않습니다.")
    return Release(version, expected, digest[7:].lower(), size)


def _request(url: str):
    return urlopen(Request(url, headers={
        "User-Agent": f"Easy-Sync/{VERSION}",
        "Accept": "application/vnd.github+json" if url == API_URL else "application/octet-stream",
    }), timeout=30)


def check_latest() -> Release | None:
    with _request(API_URL) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("릴리스 응답이 너무 큽니다.")
    return parse_release(json.loads(raw))


def download(release: Release, cache: Path | None = None) -> Path:
    # Unique private directory; never reuse a possibly partial earlier download.
    base = cache or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EasySync" / "Updates"
    base.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="download-", dir=base))
    partial = folder / "installer.part"
    target = folder / f"Easy-Sync-Setup-{release.version}-x64.exe"
    digest = hashlib.sha256()
    total = 0
    deadline = time.monotonic() + 600
    try:
        with _request(release.url) as response, partial.open("xb") as out:
            while chunk := response.read(256 * 1024):
                total += len(chunk)
                if total > release.size or time.monotonic() > deadline:
                    raise ValueError("다운로드 크기 또는 시간 제한을 초과했습니다.")
                out.write(chunk)
                digest.update(chunk)
        if total != release.size or digest.hexdigest() != release.sha256:
            raise ValueError("설치 파일 검증에 실패했습니다. 다시 다운로드해 주세요.")
        partial.replace(target)
        return target
    except Exception:
        partial.unlink(missing_ok=True)
        folder.rmdir()
        raise
