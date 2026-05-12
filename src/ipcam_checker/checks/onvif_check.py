from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from ipcam_checker._logging import get_logger
from ipcam_checker.config import Settings
from ipcam_checker.models import CameraConfig, OnvifProfile, OnvifResult

_log = get_logger("onvif")


def _run_onvif(camera: CameraConfig, settings: Settings) -> OnvifResult:
    try:
        from onvif import ONVIFCamera  # type: ignore[import]
        from zeep.transports import Transport  # type: ignore[import]
    except ImportError:
        return OnvifResult(
            ok=False,
            error="onvif-zeep not installed — run: pip install onvif-zeep",
        )

    try:
        transport = Transport(timeout=settings.onvif_timeout_s)
        cam = ONVIFCamera(
            camera.ip,
            camera.onvif_port,
            camera.rtsp_username,
            camera.rtsp_password,
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
