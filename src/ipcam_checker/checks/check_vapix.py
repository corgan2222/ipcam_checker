from __future__ import annotations

import httpx

from ipcam_checker._logging import get_logger
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig, VapixHeater, VapixResult, VapixSensor

_log = get_logger("vapix")


def _parse_temperature_response(text: str) -> VapixResult:
    sensors: dict[str, dict] = {}
    heaters: dict[str, dict] = {}

    for line in text.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        parts = key.split(".")
        if len(parts) != 3:
            continue
        group, entity_id, field = parts[0], parts[1], parts[2]

        if group == "Sensor":
            s = sensors.setdefault(entity_id, {"id": entity_id})
            if field == "Name":
                s["name"] = value
            elif field == "Celsius":
                try:
                    s["celsius"] = float(value)
                except ValueError:
                    pass
            elif field == "Fahrenheit":
                try:
                    s["fahrenheit"] = float(value)
                except ValueError:
                    pass
        elif group == "Heater":
            h = heaters.setdefault(entity_id, {"id": entity_id})
            if field == "Status":
                h["status"] = value
            elif field == "TimeUntilStop":
                try:
                    h["time_until_stop"] = int(value)
                except ValueError:
                    pass

    return VapixResult(
        ok=True,
        sensors=[VapixSensor(**s) for s in sensors.values()],
        heaters=[VapixHeater(**h) for h in heaters.values()],
    )


async def check_vapix(camera: CameraConfig, settings: Settings) -> VapixResult:
    scheme = "https" if camera.vapix_ssl else "http"
    url = f"{scheme}://{camera.ip}:{camera.vapix_port}/axis-cgi/temperaturecontrol.cgi"
    username = camera.vapix_username or camera.rtsp_username
    password = camera.vapix_password or camera.rtsp_password

    _log.debug("vapix.start", extra={"camera": camera.name, "ip": camera.ip, "url": url})
    try:
        async with httpx.AsyncClient(
            verify=False,
            timeout=settings.vapix_timeout_s,
        ) as client:
            resp = await client.get(url, auth=httpx.DigestAuth(username, password))

        if resp.status_code == 401:
            return VapixResult(ok=False, error="authentication failed (401)")
        if resp.status_code == 404:
            return VapixResult(ok=False, error="temperaturecontrol.cgi not found (404) — not supported by this camera")
        if resp.status_code != 200:
            return VapixResult(ok=False, error=f"HTTP {resp.status_code}")

        result = _parse_temperature_response(resp.text)
        _log.info(
            "vapix.ok",
            extra={
                "camera": camera.name,
                "ip": camera.ip,
                "sensors": len(result.sensors),
                "heaters": len(result.heaters),
            },
        )
        return result

    except httpx.ConnectError:
        return VapixResult(ok=False, error="connection refused")
    except httpx.TimeoutException:
        return VapixResult(ok=False, error="timeout")
    except Exception as exc:
        _log.warning("vapix.fail", extra={"camera": camera.name, "ip": camera.ip, "error": str(exc)})
        return VapixResult(ok=False, error=str(exc))
