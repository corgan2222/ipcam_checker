from __future__ import annotations

import asyncio
import base64
import io
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image

from ipcam_checker._logging import get_logger
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig

_log = get_logger("snapshot")


def _fetch_and_encode(camera: CameraConfig, settings: Settings) -> str | None:
    _log.debug("snapshot.start", extra={"camera": camera.name, "ip": camera.ip, "url": camera.snapshot_url})
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
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")

        _log.info(
            "snapshot.ok",
            extra={
                "camera": camera.name,
                "ip": camera.ip,
                "size_bytes": len(response.content),
                "output_bytes": len(buf.getvalue()),
            },
        )
        return encoded

    except httpx.TimeoutException:
        _log.warning(
            "snapshot.timeout",
            extra={"camera": camera.name, "ip": camera.ip,
                   "timeout_s": settings.snapshot_timeout_s},
        )
        return None
    except httpx.HTTPStatusError as exc:
        _log.warning(
            "snapshot.http_error",
            extra={"camera": camera.name, "ip": camera.ip,
                   "status_code": exc.response.status_code, "error": str(exc)},
        )
        return None
    except Exception as exc:
        _log.error(
            "snapshot.exception",
            extra={"camera": camera.name, "ip": camera.ip, "error": str(exc)},
            exc_info=True,
        )
        return None


async def check_snapshot(
    camera: CameraConfig,
    settings: Settings,
    executor: ThreadPoolExecutor,
) -> str | None:
    if not camera.snapshot_url:
        _log.debug("snapshot.skip", extra={"camera": camera.name, "ip": camera.ip, "reason": "no snapshot_url"})
        return None
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _fetch_and_encode, camera, settings)
