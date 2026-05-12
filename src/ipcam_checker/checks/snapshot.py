from __future__ import annotations

import asyncio
import base64
import io
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from PIL import Image

from ipcam_checker._ffmpeg import ensure_ffmpeg
from ipcam_checker._logging import get_logger
from ipcam_checker.checks.rtsp import _build_rtsp_url
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig

_log = get_logger("snapshot")

_ffmpeg_path: Path | None = None
_ffmpeg_lock = threading.Lock()


def _get_ffmpeg_path(settings: Settings) -> Path:
    global _ffmpeg_path
    if _ffmpeg_path is not None:
        return _ffmpeg_path
    with _ffmpeg_lock:
        if _ffmpeg_path is None:
            _ffmpeg_path, _ = ensure_ffmpeg(settings.bin_dir)
    return _ffmpeg_path


def _encode_image(raw: bytes, settings: Settings) -> str:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img = img.resize((settings.snapshot_width, settings.snapshot_height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _fetch_http(camera: CameraConfig, settings: Settings) -> str | None:
    _log.debug("snapshot.start", extra={"camera": camera.name, "ip": camera.ip, "url": camera.snapshot_url})
    try:
        auth = (camera.rtsp_username, camera.rtsp_password) if camera.rtsp_username else None
        with httpx.Client(timeout=settings.snapshot_timeout_s) as client:
            response = client.get(camera.snapshot_url, auth=auth)
        response.raise_for_status()
        encoded = _encode_image(response.content, settings)
        _log.info(
            "snapshot.ok",
            extra={
                "camera": camera.name, "ip": camera.ip,
                "source": "http",
                "size_bytes": len(response.content),
            },
        )
        return encoded
    except httpx.TimeoutException:
        _log.warning("snapshot.timeout", extra={"camera": camera.name, "ip": camera.ip,
                                                 "timeout_s": settings.snapshot_timeout_s})
        return None
    except httpx.HTTPStatusError as exc:
        _log.warning("snapshot.http_error", extra={"camera": camera.name, "ip": camera.ip,
                                                    "status_code": exc.response.status_code, "error": str(exc)})
        return None
    except Exception as exc:
        _log.error("snapshot.exception", extra={"camera": camera.name, "ip": camera.ip, "error": str(exc)},
                   exc_info=True)
        return None


def _fetch_rtsp_frame(camera: CameraConfig, rtsp_url: str, settings: Settings) -> str | None:
    _log.debug("snapshot.rtsp_frame.start", extra={"camera": camera.name, "ip": camera.ip})
    try:
        ffmpeg = _get_ffmpeg_path(settings)
        url = _build_rtsp_url(camera, rtsp_url)
        timeout_us = int(settings.snapshot_timeout_s * 1_000_000)
        cmd = [
            str(ffmpeg),
            "-rtsp_transport", "tcp",
            "-timeout", str(timeout_us),
            "-i", url,
            "-frames:v", "1",
            "-vf", f"scale={settings.snapshot_width}:{settings.snapshot_height}",
            "-f", "image2",
            "-vcodec", "mjpeg",
            "-q:v", "5",
            "-y",
            "pipe:1",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=settings.snapshot_timeout_s + 5,
        )
        if proc.returncode != 0 or not proc.stdout:
            err = proc.stderr.decode("utf-8", errors="replace").strip() or "no output"
            _log.warning("snapshot.rtsp_frame.fail", extra={"camera": camera.name, "ip": camera.ip, "error": err})
            return None

        encoded = _encode_image(proc.stdout, settings)
        _log.info("snapshot.ok", extra={"camera": camera.name, "ip": camera.ip,
                                        "source": "rtsp_frame", "size_bytes": len(proc.stdout)})
        return encoded

    except subprocess.TimeoutExpired:
        _log.warning("snapshot.timeout", extra={"camera": camera.name, "ip": camera.ip,
                                                 "timeout_s": settings.snapshot_timeout_s})
        return None
    except Exception as exc:
        _log.error("snapshot.exception", extra={"camera": camera.name, "ip": camera.ip, "error": str(exc)},
                   exc_info=True)
        return None


def _fetch_and_encode(camera: CameraConfig, settings: Settings) -> str | None:
    if camera.snapshot_url:
        return _fetch_http(camera, settings)
    if settings.snapshot_rtsp_fallback:
        rtsp_url = camera.rtsp_url_sub or camera.rtsp_url_main
        if rtsp_url:
            return _fetch_rtsp_frame(camera, rtsp_url, settings)
    return None


async def check_snapshot(
    camera: CameraConfig,
    settings: Settings,
    executor: ThreadPoolExecutor,
) -> str | None:
    has_rtsp = camera.rtsp_url_sub or camera.rtsp_url_main
    if not camera.snapshot_url and not (settings.snapshot_rtsp_fallback and has_rtsp):
        _log.debug("snapshot.skip", extra={"camera": camera.name, "ip": camera.ip, "reason": "no url"})
        return None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _fetch_and_encode, camera, settings)
