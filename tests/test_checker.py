from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from ipcam_checker.checker import _effective, check_camera, check_cameras
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig, CameraResult, PingResult, StreamResult
from ipcam_checker.plugins.base import AbstractPlugin


def make_ping_ok():
    return PingResult(ok=True, latency_ms=1.0, jitter_ms=0.1, packet_loss_percent=0.0, error=None)


def make_ping_fail():
    return PingResult(ok=False, latency_ms=None, jitter_ms=None, packet_loss_percent=100.0, error="timeout")


def make_stream_ok():
    return StreamResult(ok=True, width=1920, height=1080, fps=25.0, codec="h264", bitrate_kbps=2048.0, error=None)


@pytest.fixture
def camera():
    return CameraConfig(
        name="Cam1",
        ip="192.168.1.100",
        rtsp_port=554,
        rtsp_url_main="/stream1",
        rtsp_url_sub="/stream2",
        rtsp_username="admin",
        rtsp_password="secret",
        snapshot_url="http://192.168.1.100/snap.jpg",
    )


@pytest.mark.asyncio
async def test_full_flow_ping_ok(camera):
    settings = Settings()
    with patch("ipcam_checker.checker.check_ping", return_value=make_ping_ok()), \
         patch("ipcam_checker.checker.check_rtsp", return_value=make_stream_ok()), \
         patch("ipcam_checker.checker.check_snapshot", return_value="base64data"):
        result = await check_camera(camera, settings)
    assert result.ping.ok is True
    assert result.main_stream.ok is True
    assert result.sub_stream.ok is True
    assert result.snapshot_base64 == "base64data"


@pytest.mark.asyncio
async def test_ping_fail_skips_streams(camera):
    settings = Settings()
    with patch("ipcam_checker.checker.check_ping", return_value=make_ping_fail()), \
         patch("ipcam_checker.checker.check_rtsp") as mock_rtsp, \
         patch("ipcam_checker.checker.check_snapshot") as mock_snap:
        result = await check_camera(camera, settings)
    assert result.ping.ok is False
    assert result.main_stream is None
    assert result.sub_stream is None
    assert result.snapshot_base64 is None
    mock_rtsp.assert_not_called()
    mock_snap.assert_not_called()


@pytest.mark.asyncio
async def test_plugins_called_after_streams(camera):
    settings = Settings()

    class DummyPlugin(AbstractPlugin):
        name = "dummy"
        called_with_result: CameraResult | None = None

        async def run(self, cam, result, executor, s) -> dict:
            self.called_with_result = result
            return {"status": "checked"}

    plugin = DummyPlugin()
    with patch("ipcam_checker.checker.check_ping", return_value=make_ping_ok()), \
         patch("ipcam_checker.checker.check_rtsp", return_value=make_stream_ok()), \
         patch("ipcam_checker.checker.check_snapshot", return_value=None):
        result = await check_camera(camera, settings, plugins=[plugin])
    assert result.plugin_results == {"dummy": {"status": "checked"}}
    assert plugin.called_with_result is not None
    assert plugin.called_with_result.ping.ok is True


# ── _effective helper ─────────────────────────────────────────────────────────

def test_effective_none_inherits_true():
    assert _effective(None, True) is True


def test_effective_none_inherits_false():
    assert _effective(None, False) is False


def test_effective_true_overrides_false():
    assert _effective(True, False) is True


def test_effective_false_overrides_true():
    assert _effective(False, True) is False


# ── Telemetry ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_telemetry_present_on_result(camera):
    settings = Settings()
    with patch("ipcam_checker.checker.check_ping", return_value=make_ping_ok()), \
         patch("ipcam_checker.checker.check_rtsp", return_value=make_stream_ok()), \
         patch("ipcam_checker.checker.check_snapshot", return_value=None):
        result = await check_camera(camera, settings)
    assert result.telemetry is not None
    assert result.telemetry.wall_ms >= 0
    assert isinstance(result.telemetry.checks, list)


@pytest.mark.asyncio
async def test_telemetry_contains_ping_timing(camera):
    settings = Settings(check_rtsp_enabled=False, check_snapshot_enabled=False)
    with patch("ipcam_checker.checker.check_ping", return_value=make_ping_ok()):
        result = await check_camera(camera, settings)
    names = [c.name for c in result.telemetry.checks]
    assert "ping" in names


# ── Per-camera override wiring ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_per_camera_ping_disabled_overrides_global(camera):
    """check_ping=False on camera must suppress ping even when global flag is True."""
    camera_no_ping = CameraConfig(
        name="NoPing", ip="192.168.1.200", check_ping=False
    )
    settings = Settings(check_ping_enabled=True)
    with patch("ipcam_checker.checker.check_ping") as mock_ping:
        result = await check_camera(camera_no_ping, settings)
    mock_ping.assert_not_called()
    assert result.ping is None


@pytest.mark.asyncio
async def test_per_camera_ping_forced_on_overrides_global():
    """check_ping=True on camera must run ping even when global flag is False."""
    camera_force_ping = CameraConfig(
        name="ForcePing", ip="192.168.1.201", check_ping=True
    )
    settings = Settings(check_ping_enabled=False)
    with patch("ipcam_checker.checker.check_ping", return_value=make_ping_ok()) as mock_ping:
        result = await check_camera(camera_force_ping, settings)
    mock_ping.assert_called_once()
    assert result.ping is not None


@pytest.mark.asyncio
async def test_bulk_check_yields_results():
    cameras = [
        CameraConfig(name=f"Cam{i}", ip=f"192.168.1.{i}", rtsp_url_main="/s1", rtsp_url_sub="/s2")
        for i in range(1, 4)
    ]
    settings = Settings(max_concurrent_cameras=2)
    results = []
    with patch("ipcam_checker.checker.check_ping", return_value=make_ping_fail()):
        async for result in check_cameras(cameras, settings):
            results.append(result)
    assert len(results) == 3
    assert all(r.ping.ok is False for r in results)
