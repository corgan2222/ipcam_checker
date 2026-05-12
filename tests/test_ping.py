import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from ipcam_checker.checks.ping import check_ping
from ipcam_checker.config import Settings


WINDOWS_OUTPUT_OK = (
    "Pinging 192.168.1.1 with 32 bytes of data:\n"
    "Reply from 192.168.1.1: bytes=32 time=1ms TTL=64\n"
    "Reply from 192.168.1.1: bytes=32 time=2ms TTL=64\n"
    "Reply from 192.168.1.1: bytes=32 time=1ms TTL=64\n"
    "Reply from 192.168.1.1: bytes=32 time=2ms TTL=64\n\n"
    "Ping statistics for 192.168.1.1:\n"
    "    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),\n"
    "Approximate round trip times in milli-seconds:\n"
    "    Minimum = 1ms, Maximum = 2ms, Average = 1ms\n"
)

LINUX_OUTPUT_OK = (
    "PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.\n"
    "64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=1.10 ms\n"
    "64 bytes from 192.168.1.1: icmp_seq=2 ttl=64 time=1.20 ms\n"
    "64 bytes from 192.168.1.1: icmp_seq=3 ttl=64 time=1.15 ms\n"
    "64 bytes from 192.168.1.1: icmp_seq=4 ttl=64 time=1.05 ms\n\n"
    "--- 192.168.1.1 ping statistics ---\n"
    "4 packets transmitted, 4 received, 0% packet loss, time 3001ms\n"
    "rtt min/avg/max/mdev = 1.050/1.125/1.200/0.058 ms\n"
)

LINUX_OUTPUT_FAIL = (
    "PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.\n\n"
    "--- 192.168.1.1 ping statistics ---\n"
    "4 packets transmitted, 0 received, 100% packet loss, time 3001ms\n"
)


@pytest.mark.asyncio
async def test_ping_ok_windows():
    settings = Settings(ping_count=4, ping_timeout_s=2.0)
    with patch("sys.platform", "win32"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = WINDOWS_OUTPUT_OK
        mock_run.return_value.stderr = ""
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_ping("192.168.1.1", settings, executor)
    assert result.ok is True
    assert result.latency_ms is not None
    assert result.packet_loss_percent == 0.0
    assert result.error is None


@pytest.mark.asyncio
async def test_ping_ok_linux():
    settings = Settings(ping_count=4, ping_timeout_s=2.0)
    with patch("sys.platform", "linux"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = LINUX_OUTPUT_OK
        mock_run.return_value.stderr = ""
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_ping("192.168.1.1", settings, executor)
    assert result.ok is True
    assert result.latency_ms == pytest.approx(1.125, rel=0.01)
    assert result.jitter_ms == pytest.approx(0.058, rel=0.01)
    assert result.packet_loss_percent == 0.0


@pytest.mark.asyncio
async def test_ping_fail_linux():
    settings = Settings(ping_count=4, ping_timeout_s=2.0)
    with patch("sys.platform", "linux"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = LINUX_OUTPUT_FAIL
        mock_run.return_value.stderr = ""
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_ping("192.168.1.1", settings, executor)
    assert result.ok is False
    assert result.packet_loss_percent == 100.0


@pytest.mark.asyncio
async def test_ping_exception():
    settings = Settings()
    with patch("subprocess.run", side_effect=OSError("no ping binary")):
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = await check_ping("192.168.1.1", settings, executor)
    assert result.ok is False
    assert result.error is not None
