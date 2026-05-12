from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import AsyncGenerator

from ipcam_checker._logging import get_logger
from ipcam_checker.checks.onvif_check import check_onvif
from ipcam_checker.checks.ping import check_ping
from ipcam_checker.checks.ports import scan_ports
from ipcam_checker.checks.rtsp import check_rtsp
from ipcam_checker.checks.snapshot import check_snapshot
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig, CameraResult, PingResult
from ipcam_checker.plugins.base import AbstractPlugin

_log = get_logger("checker")


async def _resolved(value):
    return value


async def check_camera(
    camera: CameraConfig,
    settings: Settings | None = None,
    plugins: list[AbstractPlugin] | None = None,
) -> CameraResult:
    if settings is None:
        settings = Settings()
    if plugins is None:
        plugins = []

    t0 = time.perf_counter()
    _log.info("camera.start", extra={"camera": camera.name, "ip": camera.ip})

    with ThreadPoolExecutor(max_workers=settings.thread_pool_size) as executor:
        ping = (
            await check_ping(camera.ip, settings, executor)
            if settings.check_ping_enabled else None
        )

        main_stream = None
        sub_stream = None
        snapshot_base64 = None
        port_results = []
        onvif_result = None

        # Run remaining checks when ping is disabled (unknown) or succeeded
        run_checks = (ping is None) or ping.ok
        if run_checks:
            main_coro = (
                check_rtsp(camera, camera.rtsp_url_main, settings, executor)
                if (settings.check_rtsp_enabled and camera.rtsp_url_main) else _resolved(None)
            )
            sub_coro = (
                check_rtsp(camera, camera.rtsp_url_sub, settings, executor)
                if (settings.check_rtsp_enabled and camera.rtsp_url_sub) else _resolved(None)
            )
            snap_coro = (
                check_snapshot(camera, settings, executor)
                if settings.check_snapshot_enabled else _resolved(None)
            )
            port_coro = (
                scan_ports(camera.ip, settings)
                if settings.check_ports_enabled else _resolved([])
            )
            onvif_coro = (
                check_onvif(camera, settings, executor)
                if settings.check_onvif_enabled else _resolved(None)
            )
            main_stream, sub_stream, snapshot_base64, port_results, onvif_result = await asyncio.gather(
                main_coro, sub_coro, snap_coro, port_coro, onvif_coro,
            )
        elif ping is not None and not ping.ok:
            _log.info(
                "camera.skip_checks",
                extra={"camera": camera.name, "ip": camera.ip, "reason": "ping failed"},
            )

        result = CameraResult(
            name=camera.name,
            ip=camera.ip,
            checked_at=datetime.now(timezone.utc),
            ping=ping,
            main_stream=main_stream,
            sub_stream=sub_stream,
            snapshot_base64=snapshot_base64,
            port_results=port_results,
            onvif_result=onvif_result,
            plugin_results={},
        )

        if plugins and run_checks:
            plugin_tasks = [
                asyncio.create_task(_run_plugin(p, camera, result, executor, settings))
                for p in plugins
            ]
            plugin_outputs = await asyncio.gather(*plugin_tasks, return_exceptions=True)
            for plugin, output in zip(plugins, plugin_outputs):
                if isinstance(output, Exception):
                    _log.error(
                        "plugin.exception",
                        extra={"camera": camera.name, "ip": camera.ip,
                               "plugin": plugin.name, "error": str(output)},
                        exc_info=output,
                    )
                    result.plugin_results[plugin.name] = {"error": str(output)}
                else:
                    result.plugin_results[plugin.name] = output

    duration_ms = round((time.perf_counter() - t0) * 1000)
    _log.info(
        "camera.done",
        extra={
            "camera": camera.name,
            "ip": camera.ip,
            "duration_ms": duration_ms,
            "ping_ok": ping.ok if ping is not None else None,
            "main_ok": main_stream.ok if main_stream else None,
            "sub_ok": sub_stream.ok if sub_stream else None,
            "snapshot_ok": snapshot_base64 is not None,
        },
    )
    return result


async def _run_plugin(
    plugin: AbstractPlugin,
    camera: CameraConfig,
    result: CameraResult,
    executor: ThreadPoolExecutor,
    settings: Settings,
) -> dict:
    _log.debug("plugin.start", extra={"camera": camera.name, "ip": camera.ip, "plugin": plugin.name})
    return await plugin.run(camera, result, executor, settings)


async def check_cameras(
    cameras: list[CameraConfig],
    settings: Settings | None = None,
    plugins: list[AbstractPlugin] | None = None,
) -> AsyncGenerator[CameraResult, None]:
    if settings is None:
        settings = Settings()

    total = len(cameras)
    _log.info("bulk.start", extra={"count": total})
    t0 = time.perf_counter()

    semaphore = asyncio.Semaphore(settings.max_concurrent_cameras)
    queue: asyncio.Queue[CameraResult] = asyncio.Queue()

    async def bounded_check(camera: CameraConfig) -> None:
        async with semaphore:
            try:
                result = await check_camera(camera, settings, plugins)
            except Exception as exc:
                _log.error(
                    "camera.fatal",
                    extra={"camera": camera.name, "ip": camera.ip, "error": str(exc)},
                    exc_info=True,
                )
                result = CameraResult(
                    name=camera.name,
                    ip=camera.ip,
                    checked_at=datetime.now(timezone.utc),
                    ping=PingResult(
                        ok=False, latency_ms=None, jitter_ms=None,
                        packet_loss_percent=None, error=str(exc),
                    ),
                    main_stream=None,
                    sub_stream=None,
                    snapshot_base64=None,
                    plugin_results={},
                )
            await queue.put(result)

    tasks = [asyncio.create_task(bounded_check(cam)) for cam in cameras]
    done_count = 0

    while done_count < total:
        result = await queue.get()
        yield result
        done_count += 1

    await asyncio.gather(*tasks, return_exceptions=True)

    duration_ms = round((time.perf_counter() - t0) * 1000)
    _log.info("bulk.done", extra={"count": total, "duration_ms": duration_ms})
