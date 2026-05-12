"""Example: check a single IP camera."""
import asyncio
import json

from ipcam_checker import CameraConfig, Settings, check_camera

camera = CameraConfig(
    name="Eingang",
    ip="192.168.1.100",
    rtsp_port=554,
    rtsp_url_main="/stream1",
    rtsp_url_sub="/stream2",
    rtsp_username="admin",
    rtsp_password="secret",
    snapshot_url="http://192.168.1.100/snapshot.jpg",
)

settings = Settings(
    ping_timeout_s=2.0,
    rtsp_timeout_s=10.0,
    max_concurrent_cameras=1,
)


async def main() -> None:
    result = await check_camera(camera, settings)
    print(json.loads(result.model_dump_json(indent=2)))


if __name__ == "__main__":
    asyncio.run(main())
