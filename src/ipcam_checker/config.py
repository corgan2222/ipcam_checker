from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    # Ping
    ping_count: int = 4
    ping_timeout_s: float = 2.0

    # RTSP / ffprobe
    rtsp_timeout_s: float = 10.0
    ffprobe_analyze_duration_s: float = 5.0

    # Snapshot
    snapshot_timeout_s: float = 5.0
    snapshot_width: int = 600
    snapshot_height: int = 400

    # Bulk concurrency
    max_concurrent_cameras: int = 50
    thread_pool_size: int = 20

    # ffmpeg binaries — override for Docker: Path("/usr/local/bin")
    bin_dir: Path = Path("bin")
