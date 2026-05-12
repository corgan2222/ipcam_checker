from __future__ import annotations

import asyncio
import socket
import time

from ipcam_checker._logging import get_logger
from ipcam_checker.config import Settings
from ipcam_checker.models import PortResult

_log = get_logger("ports")


async def _check_tcp(ip: str, port: int, timeout: float) -> PortResult:
    t0 = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        _log.debug("port.open", extra={"ip": ip, "port": port, "protocol": "tcp", "latency_ms": latency_ms})
        return PortResult(port=port, protocol="tcp", open=True, latency_ms=latency_ms)
    except asyncio.TimeoutError:
        return PortResult(port=port, protocol="tcp", open=False, error="timeout")
    except (ConnectionRefusedError, OSError) as exc:
        return PortResult(port=port, protocol="tcp", open=False, error=str(exc))
    except Exception as exc:
        _log.warning("port.error", extra={"ip": ip, "port": port, "protocol": "tcp", "error": str(exc)})
        return PortResult(port=port, protocol="tcp", open=False, error=str(exc))


async def _check_udp(ip: str, port: int, timeout: float) -> PortResult:
    """
    UDP port check: send a probe and wait for a response.
    - Response received  → open
    - ICMP unreachable   → closed
    - Timeout            → open|filtered (no ICMP came back)
    """
    t0 = time.perf_counter()
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        sock.connect((ip, port))
        await loop.sock_sendall(sock, b"\x00")
        try:
            await asyncio.wait_for(loop.sock_recv(sock, 1024), timeout=timeout)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            _log.debug("port.open", extra={"ip": ip, "port": port, "protocol": "udp", "latency_ms": latency_ms})
            return PortResult(port=port, protocol="udp", open=True, latency_ms=latency_ms)
        except asyncio.TimeoutError:
            # No ICMP unreachable → port is open or filtered
            return PortResult(port=port, protocol="udp", open=True, error="no response (open|filtered)")
        except ConnectionRefusedError:
            return PortResult(port=port, protocol="udp", open=False, error="ICMP unreachable")
    except Exception as exc:
        _log.warning("port.error", extra={"ip": ip, "port": port, "protocol": "udp", "error": str(exc)})
        return PortResult(port=port, protocol="udp", open=False, error=str(exc))
    finally:
        try:
            sock.close()
        except Exception:
            pass


async def scan_ports(ip: str, settings: Settings) -> list[PortResult]:
    _log.debug("portscan.start", extra={"ip": ip})
    tasks = (
        [_check_tcp(ip, p, settings.port_scan_timeout_s) for p in settings.port_scan_tcp_ports]
        + [_check_udp(ip, p, settings.port_scan_timeout_s) for p in settings.port_scan_udp_ports]
    )
    results: list[PortResult] = list(await asyncio.gather(*tasks))
    open_ports = [r for r in results if r.open]
    _log.info(
        "portscan.done",
        extra={"ip": ip, "scanned": len(results), "open": len(open_ports),
               "open_ports": [f"{r.port}/{r.protocol}" for r in open_ports]},
    )
    return results
