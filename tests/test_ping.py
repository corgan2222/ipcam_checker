from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ipcam_checker.checks.check_ping import check_ping
from ipcam_checker.config import Settings


def _mock_host(*, is_alive, avg_rtt, jitter, packet_loss, packets_received):
    host = MagicMock()
    host.is_alive = is_alive
    host.avg_rtt = avg_rtt
    host.jitter = jitter
    host.packet_loss = packet_loss
    host.packets_received = packets_received
    return host


@pytest.mark.asyncio
async def test_ping_ok():
    settings = Settings(ping_count=4, ping_timeout_s=2.0)
    host = _mock_host(is_alive=True, avg_rtt=1.5, jitter=0.5, packet_loss=0.0, packets_received=4)
    with patch("ipcam_checker.checks.check_ping.async_ping", new=AsyncMock(return_value=host)):
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_ping("192.168.1.1", settings, executor)
    assert result.ok is True
    assert result.latency_ms == pytest.approx(1.5, rel=0.01)
    assert result.jitter_ms == pytest.approx(0.5, rel=0.01)
    assert result.packet_loss_percent == 0.0
    assert result.error is None


@pytest.mark.asyncio
async def test_ping_partial_loss():
    settings = Settings(ping_count=4, ping_timeout_s=2.0)
    host = _mock_host(is_alive=True, avg_rtt=1.0, jitter=0.0, packet_loss=0.5, packets_received=2)
    with patch("ipcam_checker.checks.check_ping.async_ping", new=AsyncMock(return_value=host)):
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_ping("192.168.1.1", settings, executor)
    assert result.ok is True
    assert result.packet_loss_percent == 50.0
    assert result.latency_ms == pytest.approx(1.0, rel=0.01)


@pytest.mark.asyncio
async def test_ping_fail():
    settings = Settings(ping_count=4, ping_timeout_s=2.0)
    host = _mock_host(is_alive=False, avg_rtt=0.0, jitter=0.0, packet_loss=1.0, packets_received=0)
    with patch("ipcam_checker.checks.check_ping.async_ping", new=AsyncMock(return_value=host)):
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_ping("192.168.1.1", settings, executor)
    assert result.ok is False
    assert result.packet_loss_percent == 100.0
    assert result.error == "host unreachable"


@pytest.mark.asyncio
async def test_ping_exception():
    settings = Settings()
    with patch(
        "ipcam_checker.checks.check_ping.async_ping",
        new=AsyncMock(side_effect=OSError("socket error")),
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_ping("192.168.1.1", settings, executor)
    assert result.ok is False
    assert result.error is not None
