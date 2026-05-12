from __future__ import annotations

import asyncio
import base64
import io
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image

from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig


def _fetch_and_encode(camera: CameraConfig, settings: Settings) -> str | None:
    if not camera.snapshot_url:
        return None
    try:
        auth = None
        if camera.rtsp_username:
            auth = (camera.rtsp_username, camera.rtsp_password)
        with httpx.Client(timeout=settings.snapshot_timeout_s) as client:
            response = client.get(camera.snapshot_url, auth=auth)
        response.raise_for_status()

        img = Image.open(io.BytesIO(response.content)).convert("RGB")
        img = img.resize((settings.snapshot_width, settings.snapshot_height), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


async def check_snapshot(
    camera: CameraConfig,
    settings: Settings,
    executor: ThreadPoolExecutor,
) -> str | None:
    if not camera.snapshot_url:
        return None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _fetch_and_encode, camera, settings)
