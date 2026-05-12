from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CameraConfig(BaseModel):
    name: str
    ip: str
    rtsp_port: int = 554
    rtsp_url_main: str
    rtsp_url_sub: str
    rtsp_username: str = ""
    rtsp_password: str = ""
    snapshot_url: str | None = None


class PingResult(BaseModel):
    ok: bool
    latency_ms: float | None
    jitter_ms: float | None
    packet_loss_percent: float | None
    error: str | None


class StreamResult(BaseModel):
    ok: bool
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    bitrate_kbps: float | None
    error: str | None


class CameraResult(BaseModel):
    name: str
    ip: str
    checked_at: datetime
    ping: PingResult
    main_stream: StreamResult | None
    sub_stream: StreamResult | None
    snapshot_base64: str | None
    plugin_results: dict[str, Any]
