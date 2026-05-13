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
    onvif_username: str = ""
    onvif_password: str = ""
    vapix_port: int = 80
    vapix_ssl: bool = False
    vapix_username: str = ""
    vapix_password: str = ""
    snmp_community_read: str = "public"
    # Per-camera overrides (None = inherit global Settings flag)
    check_ping: bool | None = None
    check_rtsp: bool | None = None
    check_snapshot: bool | None = None
    check_ports: bool | None = None
    check_onvif: bool | None = None
    check_vapix: bool | None = None
    # check_snmp: None=inherit global, "Axis"=use Axis SNMP implementation
    check_snmp: str | None = None


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


class VapixSensor(BaseModel):
    id: str
    name: str | None = None
    celsius: float | None = None
    fahrenheit: float | None = None


class VapixHeater(BaseModel):
    id: str
    status: str | None = None
    time_until_stop: int | None = None


class VapixResult(BaseModel):
    ok: bool
    sensors: list[VapixSensor] = Field(default_factory=list)
    heaters: list[VapixHeater] = Field(default_factory=list)
    error: str | None = None


class SnmpTempSensor(BaseModel):
    sensor_type: str | None = None  # "common", "housing", "rack", "cpu"
    sensor_id: int
    status: str | None = None       # "ok", "failure", "outOfBoundary"
    celsius: int | None = None


class SnmpVideoChannel(BaseModel):
    channel_id: int
    signal_status: str | None = None  # "signalOk", "noSignal"


class SnmpStorageEntry(BaseModel):
    index: int
    descr: str | None = None
    storage_type: str | None = None   # "ram", "virtualMemory", "fixedDisk", "flashMemory", …
    total_mb: float | None = None
    used_mb: float | None = None


class SnmpInterface(BaseModel):
    index: int
    name: str | None = None           # ifDescr (e.g. "eth0")
    speed_mbps: int | None = None     # ifSpeed / 1_000_000
    admin_status: str | None = None   # "up" / "down"
    oper_status: str | None = None
    rx_bytes: int | None = None       # ifInOctets
    tx_bytes: int | None = None       # ifOutOctets
    rx_errors: int | None = None      # ifInErrors
    tx_errors: int | None = None      # ifOutErrors
    rx_discards: int | None = None    # ifInDiscards


class SnmpResult(BaseModel):
    ok: bool
    sys_descr: str | None = None
    sys_name: str | None = None
    uptime_s: int | None = None
    temp_sensors: list[SnmpTempSensor] = Field(default_factory=list)
    video_channels: list[SnmpVideoChannel] = Field(default_factory=list)
    cpu_loads: list[int] = Field(default_factory=list)      # per-CPU load % (0-100)
    storage: list[SnmpStorageEntry] = Field(default_factory=list)
    interfaces: list[SnmpInterface] = Field(default_factory=list)
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
    analytics_modules: list[str] = Field(default_factory=list)
    error: str | None = None


class CheckTiming(BaseModel):
    name: str           # "ping", "rtsp_main", "rtsp_sub", "snapshot", "ports", "onvif", "vapix", "snmp"
    wall_ms: float
    # process_time() delta — accurate for blocking (ThreadPoolExecutor) checks;
    # approximate for pure-async checks because other coroutines run concurrently.
    cpu_ms: float | None = None


class CameraTelemetry(BaseModel):
    wall_ms: float
    cpu_ms: float | None = None
    checks: list[CheckTiming] = Field(default_factory=list)
    threads_at_start: int | None = None   # threading.active_count() before checks
    threads_at_end: int | None = None     # threading.active_count() after checks


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
    vapix_result: VapixResult | None = None
    snmp_result: SnmpResult | None = None
    plugin_results: dict[str, Any]
    telemetry: CameraTelemetry | None = None
