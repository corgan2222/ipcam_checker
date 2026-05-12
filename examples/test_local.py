"""Live test against local cameras."""
import asyncio
import json
from pathlib import Path

from ipcam_checker import CameraConfig, Settings, check_cameras, setup_logging

CAMERAS = [
    CameraConfig(
        name="Sony-182",
        ip="192.168.2.182",
        rtsp_port=554,
        rtsp_url_main="/media/video1",
        rtsp_url_sub="/media/video2",
    ),
    CameraConfig(
        name="Sony-184",
        ip="192.168.2.184",
        rtsp_port=554,
        rtsp_url_main="/media/video1",
        rtsp_url_sub="/media/video2",
    ),
    CameraConfig(
        name="Sony-187",
        ip="192.168.2.187",
        rtsp_port=554,
        rtsp_url_main="/media/video1",
        rtsp_url_sub="/media/video2",
    ),
    CameraConfig(
        name="Axis-170",
        ip="192.168.2.170",
        rtsp_url_main="rtsp://192.168.2.170/axis-media/media.amp?videocodec=h264&camera=1&resolution=640x480",
        rtsp_url_sub="rtsp://192.168.2.170/axis-media/media.amp?videocodec=h264&camera=1&resolution=640x480",
    ),
]

SETTINGS = Settings(
    ping_count=2,
    ping_timeout_s=1.0,
    rtsp_timeout_s=4.0,
    ffprobe_analyze_duration_s=3.0,
    max_concurrent_cameras=10,
    log_level="DEBUG",
    log_file=Path("logs/ipcam_test.log"),
)


def _fmt(result) -> str:
    ping = result.ping
    lines = [
        f"\n{'='*50}",
        f"  {result.name}  ({result.ip})",
        f"{'='*50}",
        f"  ping:    {'OK' if ping.ok else 'FAIL'}  "
        f"latency={ping.latency_ms}ms  loss={ping.packet_loss_percent}%"
        + (f"  err={ping.error}" if not ping.ok else ""),
    ]

    for label, stream in [("main", result.main_stream), ("sub ", result.sub_stream)]:
        if stream is None:
            lines.append(f"  {label}:    skipped (ping failed)")
        elif stream.ok:
            lines.append(
                f"  {label}:    OK  {stream.width}x{stream.height}  "
                f"{stream.fps}fps  {stream.codec}  {stream.bitrate_kbps}kbps"
            )
        else:
            lines.append(f"  {label}:    FAIL  err={stream.error}")

    return "\n".join(lines)


async def main() -> None:
    setup_logging(
        level=SETTINGS.log_level,
        log_file=SETTINGS.log_file,
    )

    print(f"Checking {len(CAMERAS)} cameras...\n")
    async for result in check_cameras(CAMERAS, SETTINGS):
        print(_fmt(result))

    print(f"\nLog written to: {SETTINGS.log_file}")


if __name__ == "__main__":
    asyncio.run(main())
