from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from ipcam_checker._logging import get_logger
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig, OnvifProfile, OnvifResult

_log = get_logger("onvif")


def _port_reachable(ip: str, port: int, timeout: float) -> bool:
    import socket
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run_onvif(camera: CameraConfig, settings: Settings) -> OnvifResult:
    if not _port_reachable(camera.ip, camera.onvif_port, settings.onvif_timeout_s):
        _log.debug(
            "onvif.skip",
            extra={"camera": camera.name, "ip": camera.ip, "port": camera.onvif_port,
                   "reason": "port unreachable"},
        )
        return OnvifResult(ok=False, error=f"port {camera.onvif_port} unreachable")

    try:
        from onvif import ONVIFCamera  # type: ignore[import]
        from zeep.transports import Transport  # type: ignore[import]
    except ImportError:
        return OnvifResult(
            ok=False,
            error="onvif-zeep not installed — run: pip install onvif-zeep",
        )

    try:
        username = camera.onvif_username or camera.rtsp_username
        password = camera.onvif_password or camera.rtsp_password
        transport = Transport(timeout=settings.onvif_timeout_s)
        cam = ONVIFCamera(
            camera.ip,
            camera.onvif_port,
            username,
            password,
            transport=transport,
        )

        # Device information
        dev_info = cam.devicemgmt.GetDeviceInformation()
        manufacturer = getattr(dev_info, "Manufacturer", None)
        model = getattr(dev_info, "Model", None)
        firmware_version = getattr(dev_info, "FirmwareVersion", None)
        serial_number = getattr(dev_info, "SerialNumber", None)
        hardware_id = getattr(dev_info, "HardwareId", None)

        # ONVIF version from device service entry
        onvif_version: str | None = None
        try:
            services = cam.devicemgmt.GetServices({"IncludeCapability": False})
            for svc in services:
                ns = getattr(svc, "Namespace", "") or ""
                if "device" in ns.lower() and getattr(svc, "Version", None):
                    v = svc.Version
                    onvif_version = f"{v.Major}.{v.Minor}"
                    break
        except Exception:
            pass

        # Media profiles
        profiles: list[OnvifProfile] = []
        try:
            media = cam.create_media_service()
            raw_profiles = media.GetProfiles()
            for p in raw_profiles:
                prof = OnvifProfile(name=p.Name, token=p.token)
                vec = getattr(p, "VideoEncoderConfiguration", None)
                if vec:
                    prof.encoding = getattr(vec, "Encoding", None)
                    res = getattr(vec, "Resolution", None)
                    if res:
                        prof.width = getattr(res, "Width", None)
                        prof.height = getattr(res, "Height", None)
                    rc = getattr(vec, "RateControl", None)
                    if rc:
                        prof.fps = getattr(rc, "FrameRateLimit", None)
                        prof.bitrate_kbps = getattr(rc, "BitrateLimit", None)
                profiles.append(prof)
        except Exception as exc:
            _log.debug("onvif.profiles_error", extra={"camera": camera.name, "error": str(exc)})

        # Capabilities
        ptz_supported = False
        analytics_supported = False
        try:
            caps = cam.devicemgmt.GetCapabilities()
            ptz_supported = getattr(caps, "PTZ", None) is not None
            analytics_supported = getattr(caps, "Analytics", None) is not None
        except Exception:
            pass

        # Analytics modules (configured instances across all profiles)
        analytics_modules: list[str] = []
        if analytics_supported:
            try:
                analytics_svc = cam.create_analytics_service()
                seen: set[str] = set()
                for p in raw_profiles:
                    va_cfg = getattr(p, "VideoAnalyticsConfiguration", None)
                    if va_cfg is None:
                        continue
                    va_token = getattr(va_cfg, "token", None)
                    if not va_token:
                        continue
                    try:
                        modules = analytics_svc.GetAnalyticsModules(
                            {"ConfigurationToken": va_token}
                        )
                        for m in (modules or []):
                            name = getattr(m, "Name", None) or ""
                            if name and name not in seen:
                                seen.add(name)
                                analytics_modules.append(name)
                    except Exception:
                        pass
            except Exception as exc:
                _log.debug("onvif.analytics_error", extra={"camera": camera.name, "error": str(exc)})

        _log.info(
            "onvif.ok",
            extra={
                "camera": camera.name,
                "ip": camera.ip,
                "model": f"{manufacturer} {model}",
                "onvif_version": onvif_version,
                "profiles": len(profiles),
            },
        )
        return OnvifResult(
            ok=True,
            manufacturer=manufacturer,
            model=model,
            firmware_version=firmware_version,
            serial_number=serial_number,
            hardware_id=hardware_id,
            onvif_version=onvif_version,
            profiles=profiles,
            ptz_supported=ptz_supported,
            analytics_supported=analytics_supported,
            analytics_modules=analytics_modules,
        )

    except Exception as exc:
        _log.warning(
            "onvif.fail",
            extra={"camera": camera.name, "ip": camera.ip, "error": str(exc)},
        )
        return OnvifResult(ok=False, error=str(exc))


async def check_onvif(
    camera: CameraConfig,
    settings: Settings,
    executor: ThreadPoolExecutor,
) -> OnvifResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, _run_onvif, camera, settings)
