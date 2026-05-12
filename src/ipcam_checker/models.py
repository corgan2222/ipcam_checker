from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CameraConfig(BaseModel):
    name: str
    ip: str
    rtsp_port: int = 554
    rtsp_url_main: str | None = None
    rtsp_url_sub: str | None = None
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
    profile: str | None = None
    pix_fmt: str | None = None
    level: int | None = None
    audio_codec: str | None = None
    bitrate_kbps: float | None
    title: str | None = None
    comment: str | None = None
    probe_score: int | None = None
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
