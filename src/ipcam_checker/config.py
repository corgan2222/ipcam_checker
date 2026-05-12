from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Settings(BaseModel):
    # Ping
    ping_count: int = 4
    ping_timeout_s: float = 2.0
    ping_privileged: bool = True  # False = no root needed on Linux (ignored on Windows)

    # RTSP / ffprobe
    rtsp_timeout_s: float = 10.0
    ffprobe_analyze_duration_s: float = 5.0

    # Snapshot
    snapshot_timeout_s: float = 5.0
    snapshot_width: int = 600
    snapshot_height: int = 400
    snapshot_rtsp_fallback: bool = True  # grab frame via ffmpeg when no snapshot_url

    # Port scan
    port_scan_enabled: bool = False
    port_scan_tcp_ports: list[int] = Field(default_factory=lambda: [80, 443, 8443, 8000])
    port_scan_udp_ports: list[int] = Field(default_factory=lambda: [161])
    port_scan_timeout_s: float = 2.0

    # Bulk concurrency
    max_concurrent_cameras: int = 50
    thread_pool_size: int = 20

    # ffmpeg binaries — default: ~/.ipcam_checker/bin (absolute, CWD-independent)
    # Override for Docker/system ffmpeg: Path("/usr/local/bin")
    bin_dir: Path = Path.home() / ".ipcam_checker" / "bin"

    # Logging
    log_level: str = "INFO"
    log_file: Path | None = None
    log_json: bool = True           # JSON format for log file (Loki/Promtail-ready)
    log_console: bool = False       # print log to stderr (useful during development)
    loki_url: str | None = None     # e.g. "http://loki:3100/loki/api/v1/push"
    loki_labels: dict[str, Any] = Field(default_factory=dict)

    def configure_logging(self) -> None:
        """Apply logging settings. Convenience wrapper around setup_logging()."""
        from ipcam_checker._logging import setup_logging
        setup_logging(
            level=self.log_level,
            log_file=self.log_file,
            json_file=self.log_json,
            console=self.log_console,
            loki_url=self.loki_url,
            loki_labels=self.loki_labels,
        )
