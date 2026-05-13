from datetime import UTC, datetime

from ipcam_checker.models import (
    CameraConfig,
    CameraResult,
    CameraTelemetry,
    CheckTiming,
    DiscoveredDevice,
    MdnsService,
    PingResult,
    StreamResult,
)


def test_camera_config_defaults():
    cam = CameraConfig(
        name="Cam1",
        ip="10.0.0.1",
        rtsp_url_main="/stream1",
        rtsp_url_sub="/stream2",
    )
    assert cam.rtsp_port == 554
    assert cam.rtsp_username == ""
    assert cam.snapshot_url is None


def test_ping_result_ok():
    r = PingResult(ok=True, latency_ms=1.2, jitter_ms=0.3, packet_loss_percent=0.0, error=None)
    assert r.ok is True
    assert r.error is None


def test_ping_result_fail():
    r = PingResult(
        ok=False, latency_ms=None, jitter_ms=None, packet_loss_percent=None, error="timeout"
    )
    assert r.ok is False


def test_stream_result_ok():
    r = StreamResult(
        ok=True, width=1920, height=1080, fps=25.0, codec="h264", bitrate_kbps=2048.0, error=None
    )
    assert r.width == 1920


def test_camera_result_json_serializable():
    result = CameraResult(
        name="Cam1",
        ip="10.0.0.1",
        checked_at=datetime.now(UTC),
        ping=PingResult(
            ok=False, latency_ms=None, jitter_ms=None, packet_loss_percent=None, error="timeout"
        ),
        main_stream=None,
        sub_stream=None,
        snapshot_base64=None,
        plugin_results={},
    )
    data = result.model_dump_json()
    assert '"ok":false' in data


# ── Per-camera override fields ────────────────────────────────────────────────


def test_camera_config_override_defaults_are_none():
    cam = CameraConfig(name="X", ip="1.2.3.4")
    assert cam.check_ping is None
    assert cam.check_rtsp is None
    assert cam.check_snapshot is None
    assert cam.check_ports is None
    assert cam.check_onvif is None
    assert cam.check_vapix is None
    assert cam.check_snmp is None


def test_camera_config_override_explicit():
    cam = CameraConfig(name="X", ip="1.2.3.4", check_ping=False, check_snmp="Axis")
    assert cam.check_ping is False
    assert cam.check_snmp == "Axis"


# ── Telemetry models ──────────────────────────────────────────────────────────


def test_check_timing():
    t = CheckTiming(name="ping", wall_ms=45.1, cpu_ms=0.8)
    assert t.name == "ping"
    assert t.wall_ms == 45.1
    assert t.cpu_ms == 0.8


def test_camera_telemetry_defaults():
    tel = CameraTelemetry(wall_ms=500.0)
    assert tel.checks == []
    assert tel.threads_at_start is None
    assert tel.threads_at_end is None


def test_camera_telemetry_with_checks():
    tel = CameraTelemetry(
        wall_ms=200.0,
        cpu_ms=5.0,
        threads_at_start=4,
        threads_at_end=6,
        checks=[
            CheckTiming(name="ping", wall_ms=45.0, cpu_ms=0.5),
            CheckTiming(name="snmp", wall_ms=95.0, cpu_ms=3.0),
        ],
    )
    assert len(tel.checks) == 2
    assert tel.checks[0].name == "ping"
    assert tel.threads_at_end == 6


def test_telemetry_model_dump():
    tel = CameraTelemetry(wall_ms=100.0, checks=[CheckTiming(name="ping", wall_ms=50.0)])
    d = tel.model_dump()
    assert d["wall_ms"] == 100.0
    assert d["checks"][0]["name"] == "ping"


# ── Discovery models ──────────────────────────────────────────────────────────


def test_discovered_device_likely_camera_port_554():
    d = DiscoveredDevice(ip="192.168.1.10", open_ports=[80, 554])
    assert d.likely_camera is True


def test_discovered_device_likely_camera_port_8554():
    d = DiscoveredDevice(ip="192.168.1.10", open_ports=[8554])
    assert d.likely_camera is True


def test_discovered_device_not_camera_port_80_only():
    d = DiscoveredDevice(ip="192.168.1.10", open_ports=[80, 443])
    assert d.likely_camera is False


def test_discovered_device_likely_camera_mdns_axis():
    svc = MdnsService(service_type="_axis-video._tcp", name="AXIS-cam", port=80)
    d = DiscoveredDevice(ip="192.168.1.10", open_ports=[80], mdns_services=[svc])
    assert d.likely_camera is True


def test_discovered_device_likely_camera_mdns_onvif():
    svc = MdnsService(service_type="_onvif._tcp", name="cam._onvif._tcp.local.", port=80)
    d = DiscoveredDevice(ip="192.168.1.10", mdns_services=[svc])
    assert d.likely_camera is True


def test_discovered_device_no_ports_no_mdns():
    d = DiscoveredDevice(ip="192.168.1.10")
    assert d.likely_camera is False


def test_mdns_service_txt_default_empty():
    svc = MdnsService(service_type="_rtsp._tcp", name="cam", port=554)
    assert svc.txt == {}
