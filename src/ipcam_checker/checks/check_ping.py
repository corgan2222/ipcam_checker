from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from icmplib import async_ping

from ipcam_checker._logging import get_logger
from ipcam_checker.config import Settings
from ipcam_checker.models import PingResult

_log = get_logger("ping")


async def check_ping(ip: str, settings: Settings, executor: ThreadPoolExecutor) -> PingResult:
    _log.debug("ping.start", extra={"ip": ip})
    try:
        host = await async_ping(
            ip,
            count=settings.ping_count,
            interval=0.2,
            timeout=settings.ping_timeout_s,
            privileged=settings.ping_privileged,
        )
        ok = host.is_alive
        packet_loss = round(host.packet_loss * 100, 1)
        latency_ms = round(host.avg_rtt, 3) if host.packets_received > 0 else None
        jitter_ms = round(host.jitter, 3) if host.packets_received > 1 else None

        result = PingResult(
            ok=ok,
            latency_ms=latency_ms,
            jitter_ms=jitter_ms,
            packet_loss_percent=packet_loss,
            error=None
            if ok
            else (f"packet loss: {packet_loss}%" if packet_loss < 100.0 else "host unreachable"),
        )

        if ok:
            _log.info(
                "ping.ok",
                extra={
                    "ip": ip,
                    "latency_ms": latency_ms,
                    "jitter_ms": jitter_ms,
                    "packet_loss_pct": packet_loss,
                },
            )
        else:
            _log.warning(
                "ping.fail",
                extra={
                    "ip": ip,
                    "packet_loss_pct": packet_loss,
                    "packets_sent": host.packets_sent,
                    "packets_received": host.packets_received,
                    "error": result.error,
                },
            )
        return result

    except Exception as exc:
        _log.error("ping.exception", extra={"ip": ip, "error": str(exc)}, exc_info=True)
        return PingResult(
            ok=False,
            latency_ms=None,
            jitter_ms=None,
            packet_loss_percent=None,
            error=str(exc),
        )
