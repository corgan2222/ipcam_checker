"""Camera discovery: mDNS (Bonjour) + TCP port scan."""
from __future__ import annotations

import asyncio
import functools
import ipaddress
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from ipcam_checker._logging import get_logger
from ipcam_checker.models import DiscoveredDevice, MdnsService

_log = get_logger("discover")

# TCP ports that suggest a camera when open
DEFAULT_PORTS: list[int] = [80, 443, 554, 8080, 8554]

# mDNS service types to browse (must end with ".local.")
DEFAULT_MDNS_TYPES: list[str] = [
    "_axis-video._tcp.local.",
    "_onvif._tcp.local.",
    "_rtsp._tcp.local.",
]


# ── Port scan ──────────────────────────────────────────────────────────────────

def _tcp_open(ip: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _scan_subnet(
    network: str,
    ports: list[int],
    timeout: float,
    max_workers: int,
    on_found: Callable[[str, int], None] | None,
) -> dict[str, list[int]]:
    """TCP-connect scan every host in *network*. Returns {ip: [open_ports]}."""
    hosts = [str(h) for h in ipaddress.IPv4Network(network, strict=False).hosts()]
    results: dict[str, list[int]] = {}
    lock = threading.Lock()

    _log.info(
        "discover.scan.start",
        extra={"network": network, "hosts": len(hosts), "ports": ports},
    )

    def _check(ip: str, port: int) -> tuple[str, int, bool]:
        return ip, port, _tcp_open(ip, port, timeout)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_check, ip, port) for ip in hosts for port in ports]
        for fut in as_completed(futures):
            ip, port, is_open = fut.result()
            if is_open:
                with lock:
                    results.setdefault(ip, []).append(port)
                if on_found:
                    on_found(ip, port)

    _log.info(
        "discover.scan.done",
        extra={"network": network, "active_hosts": len(results)},
    )
    return results


# ── mDNS browse ───────────────────────────────────────────────────────────────

def _mdns_browse(
    service_types: list[str],
    timeout_s: float,
) -> dict[str, list[MdnsService]]:
    """Browse mDNS for camera service types. Returns {ip: [MdnsService]}."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf  # type: ignore[import]
    except ImportError:
        _log.warning(
            "discover.mdns.unavailable",
            extra={"reason": "zeroconf not installed — run: pip install zeroconf"},
        )
        return {}

    collected: dict[str, list[MdnsService]] = {}
    lock = threading.Lock()

    class _Handler:
        def add_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name, timeout=2000)
            if not info:
                return
            # Resolve IP addresses
            try:
                addrs: list[str] = info.parsed_addresses()
            except AttributeError:
                import struct
                addrs = [socket.inet_ntoa(a) for a in info.addresses]

            # Decode TXT record
            txt: dict[str, str] = {}
            for k, v in (info.properties or {}).items():
                try:
                    key = k.decode() if isinstance(k, bytes) else str(k)
                    val = v.decode() if isinstance(v, bytes) else (str(v) if v is not None else "")
                    txt[key] = val
                except Exception:
                    pass

            svc = MdnsService(
                service_type=type_.removesuffix(".local.").removesuffix("."),
                name=name,
                port=info.port,
                txt=txt,
            )
            _log.debug(
                "discover.mdns.found",
                extra={"name": name, "type": type_, "addrs": addrs},
            )
            with lock:
                for ip in addrs:
                    collected.setdefault(ip, []).append(svc)

        def remove_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
            pass

        def update_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
            self.add_service(zc, type_, name)

    _log.info(
        "discover.mdns.start",
        extra={"service_types": service_types, "timeout_s": timeout_s},
    )
    zc = Zeroconf()
    try:
        _handler = _Handler()
        ServiceBrowser(zc, service_types, _handler)
        time.sleep(timeout_s)
    finally:
        zc.close()

    _log.info("discover.mdns.done", extra={"found": len(collected)})
    return collected


# ── Public API ─────────────────────────────────────────────────────────────────

async def discover_cameras(
    network: str,
    *,
    scan_ports: list[int] | None = None,
    mdns_timeout_s: float = 5.0,
    port_timeout_s: float = 0.5,
    port_scan_workers: int = 150,
    mdns_service_types: list[str] | None = None,
    on_port_found: Callable[[str, int], None] | None = None,
) -> list[DiscoveredDevice]:
    """Discover cameras on *network* using mDNS + TCP port scan in parallel.

    Args:
        network:            CIDR notation, e.g. "192.168.2.0/24"
        scan_ports:         TCP ports to probe (default: 80/443/554/8080/8554)
        mdns_timeout_s:     How long to listen for mDNS announcements
        port_timeout_s:     Per-connection TCP timeout
        port_scan_workers:  Thread pool size for port scan
        mdns_service_types: mDNS service types to browse (default: axis/onvif/rtsp)
        on_port_found:      Optional callback(ip, port) fired as open ports are found

    Returns:
        List of DiscoveredDevice sorted by IP, mDNS-only and port-scan-only merged.
    """
    ports      = scan_ports        or DEFAULT_PORTS
    svc_types  = mdns_service_types or DEFAULT_MDNS_TYPES

    loop = asyncio.get_running_loop()

    scan_fn = functools.partial(
        _scan_subnet, network, ports, port_timeout_s, port_scan_workers, on_port_found,
    )
    mdns_fn = functools.partial(_mdns_browse, svc_types, mdns_timeout_s)

    # Run both blocking tasks concurrently in the default thread pool
    port_results, mdns_results = await asyncio.gather(
        loop.run_in_executor(None, scan_fn),
        loop.run_in_executor(None, mdns_fn),
    )

    all_ips = set(port_results) | set(mdns_results)
    devices = [
        DiscoveredDevice(
            ip=ip,
            open_ports=sorted(port_results.get(ip, [])),
            mdns_services=mdns_results.get(ip, []),
        )
        for ip in sorted(all_ips, key=lambda x: ipaddress.IPv4Address(x))
    ]

    cameras = sum(1 for d in devices if d.likely_camera)
    _log.info(
        "discover.done",
        extra={"network": network, "total_hosts": len(devices), "likely_cameras": cameras},
    )
    return devices
