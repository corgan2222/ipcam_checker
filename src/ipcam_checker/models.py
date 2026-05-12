from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CameraConfig(BaseModel):
    name: str
    ip: str
    rtsp_port: int = 554
    rtsp_url_main: str | None = None
    rtsp_url_sub: str | None = None
    rtsp_username: str = ""
    rtsp_password: str = ""
    snapshot_url: str | None = None
    onvif_port: int = 80


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
    # RTP transport stats (computed from packet data)
    packets_received: int | None = None
    packets_lost: int | None = None
    loss_percent: float | None = None
    jitter_avg_ms: float | None = None
    jitter_max_ms: float | None = None
    bitrate_avg_kbps: float | None = None
    # RTCP-derived stats (requires Sender Report parsing — not available via ffprobe JSON)
    clock_drift_status: str | None = None
    clock_drift_ms_per_min: float | None = None
    error: str | None


class PortResult(BaseModel):
    port: int
    protocol: str  # "tcp" or "udp"
    open: bool
    latency_ms: float | None = None
    error: str | None = None


class OnvifProfile(BaseModel):
    name: str
    token: str
    encoding: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bitrate_kbps: int | None = None


class OnvifResult(BaseModel):
    ok: bool
    manufacturer: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    serial_number: str | None = None
    hardware_id: str | None = None
    onvif_version: str | None = None
    profiles: list[OnvifProfile] = Field(default_factory=list)
    ptz_supported: bool = False
    analytics_supported: bool = False
    error: str | None = None


class CameraResult(BaseModel):
    name: str
    ip: str
    checked_at: datetime
    ping: PingResult | None
    main_stream: StreamResult | None
    sub_stream: StreamResult | None
    snapshot_base64: str | None
    port_results: list[PortResult] = Field(default_factory=list)
    onvif_result: OnvifResult | None = None
    plugin_results: dict[str, Any]
