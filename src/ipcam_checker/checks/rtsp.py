from __future__ import annotations

import asyncio
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ipcam_checker._ffmpeg import ensure_ffmpeg
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig, StreamResult

_ffprobe_path: Path | None = None


def _get_ffprobe_path(settings: Settings) -> Path:
    global _ffprobe_path
    if _ffprobe_path is None:
        _, _ffprobe_path = ensure_ffmpeg(settings.bin_dir)
    return _ffprobe_path


def _build_rtsp_url(camera: CameraConfig, stream_path: str) -> str:
    if stream_path.startswith("rtsp://"):
        return stream_path
    auth = ""
    if camera.rtsp_username:
        auth = f"{camera.rtsp_username}:{camera.rtsp_password}@"
    return f"rtsp://{auth}{camera.ip}:{camera.rtsp_port}{stream_path}"


def _parse_fps(r_frame_rate: str) -> float | None:
    try:
        num, den = r_frame_rate.split("/")
        return round(int(num) / int(den), 3)
    except Exception:
        return None


def _run_ffprobe(camera: CameraConfig, stream_path: str, settings: Settings) -> StreamResult:
    try:
        ffprobe = _get_ffprobe_path(settings)
        url = _build_rtsp_url(camera, stream_path)
        analyze_us = int(settings.ffprobe_analyze_duration_s * 1_000_000)
        timeout_us = int(settings.rtsp_timeout_s * 1_000_000)
        cmd = [
            str(ffprobe),
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-analyzeduration", str(analyze_us),
            "-probesize", "1000000",
            "-timeout", str(timeout_us),
            url,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.rtsp_timeout_s + 5,
        )
        if proc.returncode != 0:
            return StreamResult(ok=False, width=None, height=None, fps=None,
                                codec=None, bitrate_kbps=None,
                                error=proc.stderr.strip() or "ffprobe error")

        data = json.loads(proc.stdout)
        video = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            None,
        )
        if video is None:
            return StreamResult(ok=False, width=None, height=None, fps=None,
                                codec=None, bitrate_kbps=None, error="no video stream found")

        bitrate_raw = video.get("bit_rate")
        bitrate_kbps = round(int(bitrate_raw) / 1024, 2) if bitrate_raw else None

        return StreamResult(
            ok=True,
            width=video.get("width"),
            height=video.get("height"),
            fps=_parse_fps(video.get("r_frame_rate", "")),
            codec=video.get("codec_name"),
            bitrate_kbps=bitrate_kbps,
            error=None,
        )
    except Exception as exc:
        return StreamResult(ok=False, width=None, height=None, fps=None,
                            codec=None, bitrate_kbps=None, error=str(exc))


async def check_rtsp(
    camera: CameraConfig,
    stream_path: str,
    settings: Settings,
    executor: ThreadPoolExecutor,
) -> StreamResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _run_ffprobe, camera, stream_path, settings)
