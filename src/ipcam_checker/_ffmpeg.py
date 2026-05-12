from __future__ import annotations

import sys
from pathlib import Path

import local_ffmpeg


def ensure_ffmpeg(bin_dir: Path) -> tuple[Path, Path]:
    """Return (ffmpeg_path, ffprobe_path), downloading binaries if needed."""
    bin_dir.mkdir(parents=True, exist_ok=True)

    # local_ffmpeg.install() is idempotent — skips download if already present
    success, message = local_ffmpeg.install(str(bin_dir))
    if not success:
        raise RuntimeError(f"Failed to install ffmpeg: {message}")

    # Binary names are platform-specific
    if sys.platform == "win32":
        ffmpeg_name = "ffmpeg.exe"
        ffprobe_name = "ffprobe.exe"
    else:
        ffmpeg_name = "ffmpeg"
        ffprobe_name = "ffprobe"

    ffmpeg_path = bin_dir / ffmpeg_name
    ffprobe_path = bin_dir / ffprobe_name
    return ffmpeg_path, ffprobe_path
