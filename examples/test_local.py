"""Live test against local cameras.

Credentials are read from environment variables so no secrets end up in source:

    AXIS_ONVIF_PASSWORD   onvif password for the Axis camera
    AXIS_VAPIX_PASSWORD   vapix password for the Axis camera
    REOLINK_PASSWORD      password for ReoLink cameras

Example (PowerShell):
    $env:AXIS_ONVIF_PASSWORD="<your-axis-onvif-pw>"
    $env:AXIS_VAPIX_PASSWORD="<your-axis-vapix-pw>"
    $env:REOLINK_PASSWORD="<your-reolink-pw>"
    python examples/test_local.py
"""
import asyncio
import os
from pathlib import Path

from ipcam_checker import CameraConfig, Settings, check_cameras, setup_logging

_AXIS_ONVIF_PW  = os.environ.get("AXIS_ONVIF_PASSWORD", "")
_AXIS_VAPIX_PW  = os.environ.get("AXIS_VAPIX_PASSWORD", "")
_REOLINK_PW     = os.environ.get("REOLINK_PASSWORD", "")

CAMERAS = [
    CameraConfig(
        name="Sony-182",
        ip="192.168.2.182",
        rtsp_port=554,
        rtsp_url_main="/media/video1",
        rtsp_url_sub="/media/video2",
        check_onvif=True,
        check_vapix=False,
        check_snmp="False",
    ),
    CameraConfig(
        name="Sony-184",
        ip="192.168.2.184",
        rtsp_port=554,
        rtsp_url_main="/media/video1",
        rtsp_url_sub="/media/video2",
        check_vapix=False,     
        check_snmp="False",
    ),
    CameraConfig(
        name="Sony-187",
        ip="192.168.2.187",
        rtsp_port=554,
        rtsp_url_main="/media/video1",
        rtsp_url_sub="/media/video2",
        check_onvif=False,
        check_vapix=False,     
        check_snmp="False",
    ),
    CameraConfig(
        name="Axis-170",
        ip="192.168.2.170",
        rtsp_url_main="rtsp://192.168.2.170/axis-media/media.amp?videocodec=h264&camera=1&resolution=1920x1080",
        rtsp_url_sub="rtsp://192.168.2.170/axis-media/media.amp?videocodec=h264&camera=1&resolution=640x480",
        onvif_username="onvifadmin",
        onvif_password=_AXIS_ONVIF_PW,
        vapix_username="axisuser",
        vapix_password=_AXIS_VAPIX_PW,
        check_onvif=True,
        check_vapix=True,
        check_snmp="Axis",
        snmp_community_read="public",
        snapshot_url="https://192.168.2.170/jpg/image.jpg"
    ),
    CameraConfig(
        name="ReoLinkFront",
        ip="192.168.2.53",
        rtsp_url_main=f"rtsp://admin:{_REOLINK_PW}@192.168.2.53:554/h264Preview_01_main",
        rtsp_url_sub=f"rtsp://admin:{_REOLINK_PW}@192.168.2.53:554/h264Preview_01_sub",
        check_onvif=False,
        check_vapix=False,    
        check_snmp="False", 
    ),
    CameraConfig(
        name="ReoLinkFront-test",
        ip="192.168.2.53",
        rtsp_url_sub="/h264Preview_01_sub",
        rtsp_username="admin",
        rtsp_password=_REOLINK_PW,
        check_onvif=False,
        check_vapix=False,  
        check_snmp="False",   
    ),
    CameraConfig(
        name="FrontOld",
        ip="192.168.2.50",
        rtsp_url_main=None,
        rtsp_url_sub=f"rtsp://admin:{_REOLINK_PW}@192.168.2.50:554/cam/realmonitor?channel=1&subtype=1&unicast=true&proto=Onvif",
        check_onvif=False,
        check_vapix=False,    
        check_snmp="False", 
    ),
]

SETTINGS = Settings(
    check_ping_enabled=True,
    check_rtsp_enabled=True,
    check_snapshot_enabled=True,
    check_ports_enabled=True,
    check_onvif_enabled=True,
    check_vapix_enabled=True,
    check_snmp_enabled=True,
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

    vapix = result.vapix_result
    if vapix is None:
        lines.append("  vapix:   disabled")
    elif not vapix.ok:
        lines.append(f"  vapix:   FAIL  err={vapix.error}")
    else:
        sensor_parts = [
            f"{s.name or s.id}={s.celsius}°C"
            for s in vapix.sensors if s.celsius is not None
        ]
        lines.append(f"  vapix:   OK  {'  '.join(sensor_parts) if sensor_parts else 'no sensors'}")
        if vapix.heaters:
            heater_parts = [f"{h.id}={h.status}" for h in vapix.heaters if h.status]
            if heater_parts:
                lines.append(f"           heater: {'  '.join(heater_parts)}")

    snmp = result.snmp_result
    if snmp is None:
        lines.append("  snmp:    disabled")
    elif not snmp.ok:
        lines.append(f"  snmp:    FAIL  err={snmp.error}")
    else:
        uptime = f"  uptime={snmp.uptime_s}s" if snmp.uptime_s is not None else ""
        name = f"  name={snmp.sys_name!r}" if snmp.sys_name else ""
        lines.append(f"  snmp:    OK{name}{uptime}")
        if snmp.sys_descr:
            lines.append(f"           descr: {snmp.sys_descr[:80]}")
        if snmp.cpu_loads:
            cpu_parts = [f"cpu{i}={v}%" for i, v in enumerate(snmp.cpu_loads)]
            lines.append(f"           cpu:  {'  '.join(cpu_parts)}")
        if snmp.temp_sensors:
            temp_parts = [
                f"{s.sensor_type or s.sensor_id}={s.celsius}°C({s.status})"
                for s in snmp.temp_sensors if s.celsius is not None
            ]
            if temp_parts:
                lines.append(f"           temp: {'  '.join(temp_parts)}")
        if snmp.video_channels:
            ch_parts = [f"ch{c.channel_id}={c.signal_status}" for c in snmp.video_channels]
            lines.append(f"           video: {'  '.join(ch_parts)}")
        if snmp.storage:
            for s in snmp.storage:
                if s.total_mb and s.total_mb > 0:
                    used_pct = f"  {round(s.used_mb / s.total_mb * 100)}%" if s.used_mb is not None else ""
                    lines.append(
                        f"           store: [{s.storage_type or '?'}] {s.descr or ''}  "
                        f"{s.used_mb}/{s.total_mb} MB{used_pct}"
                    )
        if snmp.interfaces:
            for iface in snmp.interfaces:
                spd = f"  {iface.speed_mbps}Mbps" if iface.speed_mbps else ""
                rx  = f"  rx={iface.rx_bytes/1e6:.1f}MB" if iface.rx_bytes is not None else ""
                tx  = f"  tx={iface.tx_bytes/1e6:.1f}MB" if iface.tx_bytes is not None else ""
                err_parts = []
                if iface.rx_errors:
                    err_parts.append(f"rx_err={iface.rx_errors}")
                if iface.tx_errors:
                    err_parts.append(f"tx_err={iface.tx_errors}")
                if iface.rx_discards:
                    err_parts.append(f"rx_drop={iface.rx_discards}")
                errs = ("  " + "  ".join(err_parts)) if err_parts else ""
                lines.append(f"           iface: {iface.name or iface.index}{spd}{rx}{tx}{errs}")

    t = result.telemetry
    if t:
        lines.append(f"  timing:  camera={t.wall_ms}ms  cpu={t.cpu_ms}ms"
                     f"  threads={t.threads_at_start}→{t.threads_at_end}")
        for c in t.checks:
            cpu = f"  cpu={c.cpu_ms}ms" if c.cpu_ms is not None else ""
            lines.append(f"           {c.name:<12} wall={c.wall_ms}ms{cpu}")

    return "\n".join(lines)


async def main() -> None:
    import time as _time
    setup_logging(
        level=SETTINGS.log_level,
        log_file=SETTINGS.log_file,
    )

    t_bulk_start = _time.perf_counter()
    results = []

    print(f"Checking {len(CAMERAS)} cameras...\n")
    async for result in check_cameras(CAMERAS, SETTINGS):
        print(_fmt(result))
        results.append(result)

    bulk_ms = round((_time.perf_counter() - t_bulk_start) * 1000)
    print(f"\n{'='*50}")
    print(f"  Bulk completed: {len(results)} camera(s)  total={bulk_ms}ms")
    for r in results:
        t = r.telemetry
        if t:
            print(f"  {r.name}: {t.wall_ms}ms  cpu={t.cpu_ms}ms  threads={t.threads_at_start}→{t.threads_at_end}")
    print(f"{'='*50}")
    print(f"\nLog written to: {SETTINGS.log_file}")


if __name__ == "__main__":
    asyncio.run(main())
