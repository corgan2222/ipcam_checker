from __future__ import annotations

import asyncio
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import threading

from ipcam_checker._ffmpeg import ensure_ffmpeg
from ipcam_checker._logging import get_logger
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig, StreamResult

_log = get_logger("rtsp")
_ffprobe_path: Path | None = None
_ffprobe_lock = threading.Lock()


def _get_ffprobe_path(settings: Settings) -> Path:
    global _ffprobe_path
    if _ffprobe_path is not None:
        return _ffprobe_path
    with _ffprobe_lock:
        if _ffprobe_path is None:  # re-check after acquiring lock
            _log.info("ffmpeg.download.start", extra={"bin_dir": str(settings.bin_dir)})
            _, _ffprobe_path = ensure_ffmpeg(settings.bin_dir)
            _log.info("ffmpeg.download.done", extra={"ffprobe": str(_ffprobe_path)})
    return _ffprobe_path


def _build_rtsp_url(camera: CameraConfig, stream_path: str) -> str:
    if stream_path.startswith("rtsp://"):
        return stream_path
    auth = ""
    if camera.rtsp_username:
        auth = f"{camera.rtsp_username}:{camera.rtsp_password}@"
    return f"rtsp://{auth}{camera.ip}:{camera.rtsp_port}{stream_path}"


def _safe_stream_label(camera: CameraConfig, stream_path: str) -> str:
    """URL for logging — strips credentials."""
    if stream_path.startswith("rtsp://"):
        # mask user:pass@ if present
        import re
        return re.sub(r"rtsp://[^@]+@", "rtsp://<auth>@", stream_path)
    return f"{camera.ip}:{camera.rtsp_port}{stream_path}"


def _parse_fps(r_frame_rate: str) -> float | None:
    try:
        num, den = r_frame_rate.split("/")
        return round(int(num) / int(den), 3)
    except Exception:
        return None


def _compute_bitrate_kbps(data: dict) -> float | None:
    """Extract bitrate: stream metadata → format metadata → packet measurement."""
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    for raw in (
        video.get("bit_rate") if video else None,
        data.get("format", {}).get("bit_rate"),
    ):
        if raw and raw not in ("N/A", "0"):
            try:
                return round(int(raw) / 1024, 2)
            except ValueError:
                pass

    # Compute from video packet sizes + timestamps (works for RTP/RTSP live streams)
    packets = data.get("packets", [])
    if len(packets) < 2:
        return None
    try:
        total_bits = sum(int(p.get("size", 0)) * 8 for p in packets)
        times = [
            float(p["dts_time"]) for p in packets
            if p.get("dts_time") not in ("N/A", None, "")
        ]
        if len(times) < 2:
            times = [
                float(p["pts_time"]) for p in packets
                if p.get("pts_time") not in ("N/A", None, "")
            ]
        if len(times) >= 2:
            duration = times[-1] - times[0]
            if duration > 0:
                return round(total_bits / duration / 1024, 2)
    except (ValueError, KeyError, ZeroDivisionError):
        pass
    return None


def _run_ffprobe(camera: CameraConfig, stream_path: str, settings: Settings) -> StreamResult:
    label = _safe_stream_label(camera, stream_path)
    _log.debug("rtsp.start", extra={"camera": camera.name, "ip": camera.ip, "stream": label})
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
            "-show_format",
            "-show_packets",
            "-select_streams", "v:0",
            "-analyzeduration", str(analyze_us),
            "-probesize", "5000000",
            "-timeout", str(timeout_us),
            url,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.rtsp_timeout_s + 5,
        )

        if proc.returncode != 0:
            err = proc.stderr.strip() or "ffprobe error"
            _log.warning(
                "rtsp.fail",
                extra={"camera": camera.name, "ip": camera.ip, "stream": label, "error": err},
            )
            return StreamResult(
                ok=False, width=None, height=None, fps=None,
                codec=None, bitrate_kbps=None, error=err,
            )

        data = json.loads(proc.stdout)
        video = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            None,
        )
        if video is None:
            _log.warning(
                "rtsp.no_video_stream",
                extra={"camera": camera.name, "ip": camera.ip, "stream": label},
            )
            return StreamResult(
                ok=False, width=None, height=None, fps=None,
                codec=None, bitrate_kbps=None, error="no video stream found",
            )

        bitrate_kbps = _compute_bitrate_kbps(data)
        fps = _parse_fps(video.get("r_frame_rate", ""))
        width = video.get("width")
        height = video.get("height")
        codec = video.get("codec_name")

        _log.info(
            "rtsp.ok",
            extra={
                "camera": camera.name,
                "ip": camera.ip,
                "stream": label,
                "resolution": f"{width}x{height}",
                "fps": fps,
                "codec": codec,
                "bitrate_kbps": bitrate_kbps,
            },
        )
        return StreamResult(
            ok=True, width=width, height=height, fps=fps,
            codec=codec, bitrate_kbps=bitrate_kbps, error=None,
        )

    except subprocess.TimeoutExpired:
        _log.warning(
            "rtsp.timeout",
            extra={"camera": camera.name, "ip": camera.ip, "stream": label,
                   "timeout_s": settings.rtsp_timeout_s},
        )
        return StreamResult(
            ok=False, width=None, height=None, fps=None,
            codec=None, bitrate_kbps=None,
            error=f"ffprobe timeout after {settings.rtsp_timeout_s}s",
        )
    except Exception as exc:
        _log.error(
            "rtsp.exception",
            extra={"camera": camera.name, "ip": camera.ip, "stream": label, "error": str(exc)},
            exc_info=True,
        )
        return StreamResult(
            ok=False, width=None, height=None, fps=None,
            codec=None, bitrate_kbps=None, error=str(exc),
        )


async def check_rtsp(
    camera: CameraConfig,
    stream_path: str,
    settings: Settings,
    executor: ThreadPoolExecutor,
) -> StreamResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _run_ffprobe, camera, stream_path, settings)
