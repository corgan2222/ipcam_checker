"""Live test against local cameras."""
import asyncio
import json
from pathlib import Path

from ipcam_checker import CameraConfig, Settings, check_cameras, setup_logging

CAMERAS = [
    # CameraConfig(
    #     name="Sony-182",
    #     ip="192.168.2.182",
    #     rtsp_port=554,
    #     rtsp_url_main="/media/video1",
    #     rtsp_url_sub="/media/video2",
    # ),
    # CameraConfig(
    #     name="Sony-184",
    #     ip="192.168.2.184",
    #     rtsp_port=554,
    #     rtsp_url_main="/media/video1",
    #     rtsp_url_sub="/media/video2",
    # ),
    # CameraConfig(
    #     name="Sony-187",
    #     ip="192.168.2.187",
    #     rtsp_port=554,
    #     rtsp_url_main="/media/video1",
    #     rtsp_url_sub="/media/video2",
    # ),
    CameraConfig(
        name="Axis-170",
        ip="192.168.2.170",
        rtsp_url_main="rtsp://192.168.2.170/axis-media/media.amp?videocodec=h264&camera=1&resolution=1920x1080",
        rtsp_url_sub="rtsp://192.168.2.170/axis-media/media.amp?videocodec=h264&camera=1&resolution=640x480",
        onvif_username="onvifadmin",
        onvif_password="REDACTED",
    )#,
    # CameraConfig(
    #     name="ReoLinkFront",
    #     ip="192.168.2.53",
    #     rtsp_url_main="rtsp://admin:REDACTED@192.168.2.53:554/h264Preview_01_main",
    #     rtsp_url_sub="rtsp://admin:REDACTED@192.168.2.53:554/h264Preview_01_sub",
    # ),
    # CameraConfig(
    #     name="ReoLinkFront-test",
    #     ip="192.168.2.53",
    #     rtsp_url_sub="/h264Preview_01_sub",
    #     rtsp_username="admin",
    #     rtsp_password="REDACTED",
    # ),
    # CameraConfig(
    #     name="FrontOld",
    #     ip="192.168.2.50",
    #     rtsp_url_main=None,
    #     rtsp_url_sub="rtsp://admin:REDACTED@192.168.2.50:554/cam/realmonitor?channel=1&subtype=1&unicast=true&proto=Onvif",
    # ),
]

SETTINGS = Settings(
    check_ping_enabled=True,
    check_rtsp_enabled=False,
    check_snapshot_enabled=False,
    check_ports_enabled=False,
    check_onvif_enabled=True,
    ping_count=2,
    ping_timeout_s=1.0,
    rtsp_timeout_s=4.0,
    ffprobe_analyze_duration_s=3.0,
    max_concurrent_cameras=10,
    snapshot_rtsp_fallback=False,
    log_level="DEBUG",
    log_file=Path("logs/ipcam_test.log"),
)


def _fmt(result) -> str:
    ping = result.ping
    lines = [
        f"\n{'='*50}",
        f"  {result.name}  ({result.ip})",
        f"{'='*50}",
    ]
    if ping is None:
        lines.append("  ping:    disabled")
    else:
        lines.append(
            f"  ping:    {'OK' if ping.ok else 'FAIL'}  "
            f"latency={ping.latency_ms}ms  loss={ping.packet_loss_percent}%"
            + (f"  err={ping.error}" if not ping.ok else "")
        )

    for label, stream in [("main", result.main_stream), ("sub ", result.sub_stream)]:
        if stream is None:
            lines.append(f"  {label}:    skipped")
        elif stream.ok:
            video_info = f"{stream.codec}"
            if stream.profile:
                video_info += f" ({stream.profile})"
            if stream.pix_fmt:
                video_info += f"  {stream.pix_fmt}"
            if stream.level is not None:
                video_info += f"  Level{stream.level}"
            if stream.audio_codec:
                video_info += f"  audio:{stream.audio_codec}"
            meta = ""
            if stream.title:
                meta += f"  title={stream.title!r}"
            if stream.comment:
                meta += f"  comment={stream.comment!r}"
            if stream.probe_score is not None:
                meta += f"  probe={stream.probe_score}"
            lines.append(
                f"  {label}:    OK  {stream.width}x{stream.height}  "
                f"{stream.fps}fps  {video_info}  {stream.bitrate_kbps}kbps{meta}"
            )
            rtp_parts = []
            if stream.packets_received is not None:
                rtp_parts.append(f"pkts={stream.packets_received}")
            if stream.packets_lost is not None:
                rtp_parts.append(f"lost={stream.packets_lost}({stream.loss_percent}%)")
            if stream.jitter_avg_ms is not None:
                rtp_parts.append(f"jitter={stream.jitter_avg_ms}/{stream.jitter_max_ms}ms")
            if stream.bitrate_avg_kbps is not None:
                rtp_parts.append(f"avg={stream.bitrate_avg_kbps}kbps")
            if rtp_parts:
                lines.append(f"         rtp:  {'  '.join(rtp_parts)}")
        else:
            lines.append(f"  {label}:    FAIL  err={stream.error}")

    if result.port_results:
        open_ports = [r for r in result.port_results if r.open]
        parts = [f"{r.port}/{r.protocol}" for r in open_ports]
        lines.append(f"  ports:   {('  '.join(parts)) if parts else 'none open'}")

    onvif = result.onvif_result
    if onvif is None:
        lines.append("  onvif:   disabled")
    elif not onvif.ok:
        lines.append(f"  onvif:   FAIL  err={onvif.error}")
    else:
        ver = f"ONVIF {onvif.onvif_version}" if onvif.onvif_version else "ONVIF"
        device = "  ".join(filter(None, [onvif.manufacturer, onvif.model]))
        fw = f"  FW:{onvif.firmware_version}" if onvif.firmware_version else ""
        sn = f"  SN:{onvif.serial_number}" if onvif.serial_number else ""
        caps = "  ".join(filter(None, [
            "PTZ" if onvif.ptz_supported else None,
            "Analytics" if onvif.analytics_supported else None,
        ]))
        lines.append(f"  onvif:   OK  {ver}  {device}{fw}{sn}")
        if onvif.profiles:
            prof_parts = []
            for p in onvif.profiles:
                res = f"{p.width}x{p.height}" if p.width and p.height else ""
                fps = f"{p.fps}fps" if p.fps else ""
                bps = f"{p.bitrate_kbps}kbps" if p.bitrate_kbps else ""
                enc = p.encoding or ""
                detail = "  ".join(filter(None, [enc, res, fps, bps]))
                prof_parts.append(f"{p.name}({detail})" if detail else p.name)
            lines.append(f"           profiles: {'  '.join(prof_parts)}")
        if caps:
            lines.append(f"           caps: {caps}")
        if onvif.analytics_modules:
            lines.append(f"           analytics: {'  '.join(onvif.analytics_modules)}")

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
