from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import AsyncGenerator

from ipcam_checker.checks.ping import check_ping
from ipcam_checker.checks.rtsp import check_rtsp
from ipcam_checker.checks.snapshot import check_snapshot
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig, CameraResult
from ipcam_checker.plugins.base import AbstractPlugin


async def check_camera(
    camera: CameraConfig,
    settings: Settings | None = None,
    plugins: list[AbstractPlugin] | None = None,
) -> CameraResult:
    if settings is None:
        settings = Settings()
    if plugins is None:
        plugins = []

    with ThreadPoolExecutor(max_workers=settings.thread_pool_size) as executor:
        ping = await check_ping(camera.ip, settings, executor)

        main_stream = None
        sub_stream = None
        snapshot_base64 = None

        if ping.ok:
            main_task = asyncio.create_task(check_rtsp(camera, camera.rtsp_url_main, settings, executor))
            sub_task = asyncio.create_task(check_rtsp(camera, camera.rtsp_url_sub, settings, executor))
            snap_task = asyncio.create_task(check_snapshot(camera, settings, executor))
            main_stream, sub_stream, snapshot_base64 = await asyncio.gather(
                main_task, sub_task, snap_task
            )

        result = CameraResult(
            name=camera.name,
            ip=camera.ip,
            checked_at=datetime.now(timezone.utc),
            ping=ping,
            main_stream=main_stream,
            sub_stream=sub_stream,
            snapshot_base64=snapshot_base64,
            plugin_results={},
        )

        if plugins and ping.ok:
            plugin_tasks = [
                asyncio.create_task(_run_plugin(p, camera, result, executor, settings))
                for p in plugins
            ]
            plugin_outputs = await asyncio.gather(*plugin_tasks, return_exceptions=True)
            for plugin, output in zip(plugins, plugin_outputs):
                if isinstance(output, Exception):
                    result.plugin_results[plugin.name] = {"error": str(output)}
                else:
                    result.plugin_results[plugin.name] = output

    return result


async def _run_plugin(
    plugin: AbstractPlugin,
    camera: CameraConfig,
    result: CameraResult,
    executor: ThreadPoolExecutor,
    settings: Settings,
) -> dict:
    return await plugin.run(camera, result, executor, settings)


async def check_cameras(
    cameras: list[CameraConfig],
    settings: Settings | None = None,
    plugins: list[AbstractPlugin] | None = None,
) -> AsyncGenerator[CameraResult, None]:
    if settings is None:
        settings = Settings()

    semaphore = asyncio.Semaphore(settings.max_concurrent_cameras)
    queue: asyncio.Queue[CameraResult] = asyncio.Queue()

    async def bounded_check(camera: CameraConfig) -> None:
        async with semaphore:
            result = await check_camera(camera, settings, plugins)
            await queue.put(result)

    tasks = [asyncio.create_task(bounded_check(cam)) for cam in cameras]
    done_count = 0
    total = len(cameras)

    while done_count < total:
        result = await queue.get()
        yield result
        done_count += 1

    await asyncio.gather(*tasks, return_exceptions=True)
