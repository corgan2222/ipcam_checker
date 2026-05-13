"""Tests for ipcam_checker.discover — port scan + mDNS discovery."""

from __future__ import annotations

import ipaddress
from unittest.mock import patch

import pytest

from ipcam_checker.discover import _scan_subnet, _tcp_open, discover_cameras
from ipcam_checker.models import DiscoveredDevice, MdnsService

# ── _tcp_open ─────────────────────────────────────────────────────────────────


def test_tcp_open_success():
    with patch("socket.create_connection"):
        assert _tcp_open("192.168.1.1", 80, 0.1) is True


def test_tcp_open_failure():
    with patch("socket.create_connection", side_effect=OSError("refused")):
        assert _tcp_open("192.168.1.1", 80, 0.1) is False


# ── _scan_subnet ──────────────────────────────────────────────────────────────


def test_scan_subnet_finds_open_ports():
    def fake_tcp(ip, port, timeout):
        return ip == "192.168.1.1" and port == 554

    with patch("ipcam_checker.discover._tcp_open", side_effect=fake_tcp):
        results = _scan_subnet("192.168.1.0/30", [554, 80], 0.1, 4, None)

    assert "192.168.1.1" in results
    assert 554 in results["192.168.1.1"]
    assert 80 not in results.get("192.168.1.1", [])


def test_scan_subnet_callback_fired():
    found: list[tuple[str, int]] = []

    def fake_tcp(ip, port, timeout):
        return port == 554

    with patch("ipcam_checker.discover._tcp_open", side_effect=fake_tcp):
        _scan_subnet("192.168.1.0/30", [554], 0.1, 4, lambda ip, p: found.append((ip, p)))

    assert all(p == 554 for _, p in found)
    assert len(found) > 0


def test_scan_subnet_empty_network():
    # /32 has no hosts
    results = _scan_subnet("192.168.1.1/32", [80], 0.1, 2, None)
    assert results == {}


# ── discover_cameras (async) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discover_cameras_merges_port_and_mdns():
    port_results = {"192.168.1.10": [554, 80]}
    mdns_svc = MdnsService(service_type="_axis-video._tcp", name="AXIS-cam", port=80)
    mdns_results = {"192.168.1.20": [mdns_svc]}

    with (
        patch("ipcam_checker.discover._scan_subnet", return_value=port_results),
        patch("ipcam_checker.discover._mdns_browse", return_value=mdns_results),
    ):
        devices = await discover_cameras("192.168.1.0/24")

    ips = [d.ip for d in devices]
    assert "192.168.1.10" in ips
    assert "192.168.1.20" in ips


@pytest.mark.asyncio
async def test_discover_cameras_sorted_by_ip():
    port_results = {
        "192.168.1.30": [80],
        "192.168.1.10": [554],
        "192.168.1.20": [443],
    }
    with (
        patch("ipcam_checker.discover._scan_subnet", return_value=port_results),
        patch("ipcam_checker.discover._mdns_browse", return_value={}),
    ):
        devices = await discover_cameras("192.168.1.0/24")

    ips = [d.ip for d in devices]
    assert ips == sorted(ips, key=lambda x: ipaddress.IPv4Address(x))


@pytest.mark.asyncio
async def test_discover_cameras_returns_discovered_device_objects():
    port_results = {"192.168.1.5": [554]}
    with (
        patch("ipcam_checker.discover._scan_subnet", return_value=port_results),
        patch("ipcam_checker.discover._mdns_browse", return_value={}),
    ):
        devices = await discover_cameras("192.168.1.0/24")

    assert len(devices) == 1
    assert isinstance(devices[0], DiscoveredDevice)
    assert devices[0].ip == "192.168.1.5"
    assert 554 in devices[0].open_ports


@pytest.mark.asyncio
async def test_discover_cameras_empty_network():
    with (
        patch("ipcam_checker.discover._scan_subnet", return_value={}),
        patch("ipcam_checker.discover._mdns_browse", return_value={}),
    ):
        devices = await discover_cameras("192.168.1.0/24")

    assert devices == []


@pytest.mark.asyncio
async def test_discover_cameras_on_port_found_callback():
    called: list[tuple[str, int]] = []

    def fake_scan(network, ports, timeout, workers, on_found):
        if on_found:
            on_found("192.168.1.10", 554)
        return {"192.168.1.10": [554]}

    with (
        patch("ipcam_checker.discover._scan_subnet", side_effect=fake_scan),
        patch("ipcam_checker.discover._mdns_browse", return_value={}),
    ):
        await discover_cameras(
            "192.168.1.0/24",
            on_port_found=lambda ip, p: called.append((ip, p)),
        )

    assert ("192.168.1.10", 554) in called


@pytest.mark.asyncio
async def test_discover_cameras_mdns_merged_with_ports():
    """Same IP found by both port scan and mDNS — should appear once with both."""
    svc = MdnsService(service_type="_onvif._tcp", name="cam", port=80)
    port_results = {"192.168.1.10": [554, 80]}
    mdns_results = {"192.168.1.10": [svc]}

    with (
        patch("ipcam_checker.discover._scan_subnet", return_value=port_results),
        patch("ipcam_checker.discover._mdns_browse", return_value=mdns_results),
    ):
        devices = await discover_cameras("192.168.1.0/24")

    assert len(devices) == 1
    d = devices[0]
    assert 554 in d.open_ports
    assert d.mdns_services[0].service_type == "_onvif._tcp"
    assert d.likely_camera is True
