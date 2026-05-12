from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from ipcam_checker.config import Settings
from ipcam_checker.models import PingResult


def _build_ping_cmd(ip: str, count: int, timeout_s: float) -> list[str]:
    if sys.platform == "win32":
        return ["ping", "-n", str(count), "-w", str(int(timeout_s * 1000)), ip]
    return ["ping", "-c", str(count), "-W", str(int(timeout_s)), ip]


def _parse_ping_output(stdout: str, returncode: int, platform: str) -> PingResult:
    if returncode != 0 and not stdout:
        return PingResult(ok=False, latency_ms=None, jitter_ms=None, packet_loss_percent=None, error="ping failed")

    loss_match = re.search(r"(\d+)%\s*(?:loss|packet loss|Verlust)", stdout, re.IGNORECASE)
    packet_loss = float(loss_match.group(1)) if loss_match else None

    ok = returncode == 0 and packet_loss is not None and packet_loss < 100.0

    if platform == "win32":
        avg_match = re.search(r"Average\s*=\s*(\d+)ms", stdout, re.IGNORECASE)
        min_match = re.search(r"Minimum\s*=\s*(\d+)ms", stdout, re.IGNORECASE)
        max_match = re.search(r"Maximum\s*=\s*(\d+)ms", stdout, re.IGNORECASE)
        latency = float(avg_match.group(1)) if avg_match else None
        jitter = None
        if min_match and max_match:
            jitter = (float(max_match.group(1)) - float(min_match.group(1))) / 2.0
    else:
        rtt_match = re.search(
            r"rtt min/avg/max/mdev\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", stdout
        )
        latency = float(rtt_match.group(2)) if rtt_match else None
        jitter = float(rtt_match.group(4)) if rtt_match else None

    return PingResult(
        ok=ok,
        latency_ms=latency,
        jitter_ms=jitter,
        packet_loss_percent=packet_loss,
        error=None if ok else f"packet loss: {packet_loss}%",
    )


def _run_ping(ip: str, settings: Settings) -> PingResult:
    try:
        cmd = _build_ping_cmd(ip, settings.ping_count, settings.ping_timeout_s)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.ping_timeout_s * settings.ping_count + 5,
        )
        return _parse_ping_output(proc.stdout, proc.returncode, sys.platform)
    except Exception as exc:
        return PingResult(ok=False, latency_ms=None, jitter_ms=None, packet_loss_percent=None, error=str(exc))


async def check_ping(ip: str, settings: Settings, executor: ThreadPoolExecutor) -> PingResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _run_ping, ip, settings)
