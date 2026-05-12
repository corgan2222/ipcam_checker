from datetime import datetime, timezone
from ipcam_checker.models import (
    CameraConfig,
    CameraResult,
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
    r = PingResult(ok=False, latency_ms=None, jitter_ms=None, packet_loss_percent=None, error="timeout")
    assert r.ok is False


def test_stream_result_ok():
    r = StreamResult(ok=True, width=1920, height=1080, fps=25.0, codec="h264", bitrate_kbps=2048.0, error=None)
    assert r.width == 1920


def test_camera_result_json_serializable():
    result = CameraResult(
        name="Cam1",
        ip="10.0.0.1",
        checked_at=datetime.now(timezone.utc),
        ping=PingResult(ok=False, latency_ms=None, jitter_ms=None, packet_loss_percent=None, error="timeout"),
        main_stream=None,
        sub_stream=None,
        snapshot_base64=None,
        plugin_results={},
    )
    data = result.model_dump_json()
    assert '"ok":false' in data
