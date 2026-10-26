"""gallery-dl fallback for image-first posts (Pinterest, X photos, albums…).

Runs as a subprocess in its own process group so a hang can be killed
cleanly — no zombie processes haunting the container afterwards.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

from .downloader import IMAGE_EXTS, VIDEO_EXTS, DownloadedFile, MediaError

_TIMEOUT = 240  # seconds — generous, but not "go make coffee" generous


async def fetch_gallery(url: str, out_dir: Path, *, cookiefile: str | None = None,
                        proxy: str | None = None, limit: int = 20,
                        max_filesize: int = 49 * 1024 * 1024) -> list[DownloadedFile]:
    cmd = [
        sys.executable, "-m", "gallery_dl",
        "-D", str(out_dir),
        "-f", "item_{num:>03}.{extension}",
        "--no-skip",
    ]
    if cookiefile:
        cmd += ["--cookies", cookiefile]
    if proxy:
        cmd += ["--proxy", proxy]
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # own process group → clean group kill
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except TimeoutError:
        _kill_group(proc)
        raise MediaError("gallery-dl timed out") from None

    files: list[DownloadedFile] = []
    for path in sorted(out_dir.iterdir()):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in IMAGE_EXTS | VIDEO_EXTS:
            continue
        if path.stat().st_size > max_filesize or path.stat().st_size == 0:
            continue
        kind = "video" if ext in VIDEO_EXTS else "photo"
        files.append(DownloadedFile(path=path, title="gallery", kind=kind))
        if len(files) >= limit:
            break

    if not files:
        tail = (stderr or b"").decode(errors="ignore")[-300:]
        raise MediaError(f"gallery-dl found nothing: {tail}")
    return files


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()
