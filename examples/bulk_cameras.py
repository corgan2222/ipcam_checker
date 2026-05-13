"""Example: check multiple IP cameras, streaming results."""

import asyncio
import json

from ipcam_checker import CameraConfig, Settings, check_cameras

cameras = [
    CameraConfig(
        name=f"Kamera-{i}",
        ip=f"192.168.1.{100 + i}",
        rtsp_port=554,
        rtsp_url_main="/stream1",
        rtsp_url_sub="/stream2",
        rtsp_username="admin",
        rtsp_password="secret",
    )
    for i in range(5)
]

settings = Settings(
    ping_timeout_s=2.0,
    rtsp_timeout_s=10.0,
    max_concurrent_cameras=10,
    thread_pool_size=20,
)


async def main() -> None:
    async for result in check_cameras(cameras, settings):
        summary = {
            "name": result.name,
            "ip": result.ip,
            "ping_ok": result.ping.ok,
            "ping_ms": result.ping.latency_ms,
            "main_stream": result.main_stream.model_dump() if result.main_stream else None,
            "sub_stream": result.sub_stream.model_dump() if result.sub_stream else None,
        }
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
