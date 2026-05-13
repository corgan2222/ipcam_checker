# ipcam-checker

Async IP camera health checker for Python 3.13+.

Checks ping, RTSP streams, snapshots, open ports, ONVIF device info, VAPIX sensors/heaters, and SNMP metrics. Discovers cameras on a subnet via mDNS (Bonjour) and TCP port scan. Includes a telemetry system that tracks per-check wall time, CPU time, and thread counts.

---

## Features

| Check | What it returns |
|---|---|
| **Ping** | Latency, jitter, packet loss |
| **RTSP** | Codec, resolution, FPS, bitrate, RTP packet stats |
| **Snapshot** | JPEG captured via HTTP or ffmpeg frame grab |
| **Ports** | TCP/UDP open port list |
| **ONVIF** | Manufacturer, model, firmware, profiles, PTZ/analytics caps |
| **VAPIX** | Temperature sensors, heater status (Axis cameras) |
| **SNMP (Axis)** | sysDescr, uptime, temp sensors, video signal, IF-MIB interface stats |
| **Discovery** | Subnet scan via mDNS + TCP port scan → list of likely cameras |


---

## Example output

### Axis camera (P1435-LE) — ONVIF + VAPIX + SNMP

```
==================================================
  Axis-170  (192.168.2.170)
==================================================
  ping:    OK  latency=1.747ms  loss=0.0%
  main:    OK  1920x1080  25.0fps  h264 (Main)  yuvj420p  Level41  10482.03kbps  title='Session streamed with GStreamer'  comment='rtsp-server'  probe=100
         rtp:  pkts=76  lost=0(0.0%)  jitter=0.008/0.022ms  avg=10482.03kbps
  sub :    OK  640x480  25.0fps  h264 (Main)  yuvj420p  Level41  533.35kbps  title='Session streamed with GStreamer'  comment='rtsp-server'  probe=100
         rtp:  pkts=76  lost=0(0.0%)  jitter=0.008/0.022ms  avg=533.35kbps
  ports:   80/tcp  443/tcp  554/tcp  161/udp
  onvif:   OK  ONVIF 2.21  AXIS  P1435-LE  FW:9.80.105  SN:ACCC8ED43FB1
           profiles: profile_1 h264(H264  640x400  25fps  2147483647kbps)  profile_1 jpeg(H264  640x400  25fps  2147483647kbps)
           caps: Analytics
  vapix:   OK  Image Sensor=29.0°C  Heater=26.8°C  IR led=26.4°C  IR led tele=26.4°C
           heater: H0=Stopped
  snmp:    OK  uptime=15065s
           descr:  ; AXIS P1435-LE; Network Camera; 9.80.105; Apr 03 2025 15:51; 70D.1; 1;
           temp: 1=29°C(ok)  2=26°C(ok)  3=26°C(ok)  4=26°C(ok)
           iface: eth0  100Mbps  rx=26.0MB  tx=52.6MB  rx_err=16  rx_drop=18
  timing:  camera=8340.0ms  cpu=1468.8ms  threads=1→5
           ping         wall=219.4ms  cpu=15.6ms
           vapix        wall=519.9ms  cpu=765.6ms
           snmp         wall=797.3ms  cpu=734.4ms
           snapshot     wall=1366.2ms cpu=1296.9ms
           ports        wall=2352.6ms cpu=1296.9ms
           rtsp_sub     wall=3961.0ms cpu=1390.6ms
           rtsp_main    wall=4202.9ms cpu=1421.9ms
           onvif        wall=8101.3ms cpu=1421.9ms
```

### Sony network camera (SNC-EM600)

```
==================================================
  Sony-182  (192.168.2.182)
==================================================
  ping:    OK  latency=2.551ms  loss=0.0%
  main:    OK  1280x720  25.0fps  h264 (High)  yuvj420p  Level31  929.99kbps  title='Sony RTSP Server'  probe=100
         rtp:  pkts=76  lost=0(0.0%)  jitter=0.0/0.0ms  avg=929.99kbps
  sub :    OK  640x480  10.0fps  h264 (Main)  yuvj420p  Level30  133.68kbps  title='Sony RTSP Server'  probe=100
         rtp:  pkts=31  lost=0(0.0%)  jitter=20.0/20.0ms  avg=133.68kbps
  ports:   80/tcp  554/tcp  161/udp
  onvif:   OK  ONVIF 17.6  Sony  SNC-EM600  FW:3.2.0  SN:5233423
           caps: PTZ  Analytics
  vapix:   disabled
  snmp:    disabled
  timing:  camera=4290.7ms  cpu=1453.1ms  threads=1→19
           ping         wall=221.6ms  cpu=31.2ms
           snapshot     wall=0.3ms   cpu=0.0ms
           onvif        wall=1021.4ms cpu=875.0ms
           ports        wall=2008.3ms cpu=875.0ms
           rtsp_main    wall=3617.1ms cpu=968.8ms
           rtsp_sub     wall=3710.4ms cpu=968.8ms
```




---

## Installation

```bash
pip install ipcam-checker
```

Optional extras:

```bash
pip install "ipcam-checker[onvif]"      # ONVIF support (onvif-zeep)
pip install "ipcam-checker[discovery]"  # mDNS discovery (zeroconf)
pip install "ipcam-checker[loki]"       # Loki log push (python-logging-loki)
```

---

## Quick start

```python
import asyncio
from ipcam_checker import CameraConfig, Settings, check_cameras, setup_logging

CAMERAS = [
    CameraConfig(
        name="Axis-170",
        ip="192.168.2.170",
        rtsp_url_main="rtsp://192.168.2.170/axis-media/media.amp?videocodec=h264",
        onvif_username="onvifadmin",
        onvif_password="secret",
        vapix_username="axisuser",
        vapix_password="secret",
        check_onvif=True,
        check_vapix=True,
        check_snmp="Axis",
        snmp_community_read="public",
    ),
]

SETTINGS = Settings(
    check_ping_enabled=True,
    check_rtsp_enabled=True,
    check_onvif_enabled=True,
    check_vapix_enabled=True,
    check_snmp_enabled=True,
)

async def main():
    setup_logging(level="INFO")
    async for result in check_cameras(CAMERAS, SETTINGS):
        print(result.name, result.ping, result.snmp_result)

asyncio.run(main())
```

---

## Camera configuration

```python
CameraConfig(
    # Identity
    name="MyCamera",
    ip="192.168.1.10",

    # RTSP
    rtsp_port=554,
    rtsp_url_main="rtsp://192.168.1.10/stream1",
    rtsp_url_sub="rtsp://192.168.1.10/stream2",
    rtsp_username="admin",
    rtsp_password="secret",

    # Snapshot
    snapshot_url="http://192.168.1.10/snapshot.jpg",

    # ONVIF
    onvif_port=80,
    onvif_username="onvifadmin",
    onvif_password="secret",

    # VAPIX (Axis only)
    vapix_port=80,
    vapix_ssl=False,
    vapix_username="user",
    vapix_password="secret",

    # SNMP
    snmp_community_read="public",

    # Per-camera check overrides (None = inherit global Settings flag)
    check_ping=None,        # bool | None
    check_rtsp=None,        # bool | None
    check_snapshot=None,    # bool | None
    check_ports=None,       # bool | None
    check_onvif=True,       # bool | None
    check_vapix=True,       # bool | None
    check_snmp="Axis",      # str | None  — None=inherit, "Axis"=Axis SNMP impl
)
```

### Per-camera overrides

Global `Settings` flags (e.g. `check_onvif_enabled`) act as defaults. Per-camera fields override them:

```python
# Inherit global setting (default)
CameraConfig(name="Cam1", ip="...", check_snmp=None)

# Force SNMP on regardless of global flag
CameraConfig(name="Cam2", ip="...", check_snmp="Axis")

# Disable a check for just this camera
CameraConfig(name="Cam3", ip="...", check_ping=False)
```

---

## Global settings

```python
Settings(
    # Check toggles (per-camera overrides win when set)
    check_ping_enabled=True,
    check_rtsp_enabled=True,
    check_snapshot_enabled=True,
    check_ports_enabled=False,
    check_onvif_enabled=False,
    check_vapix_enabled=False,
    check_snmp_enabled=False,

    # Ping
    ping_count=4,
    ping_timeout_s=2.0,

    # RTSP / ffprobe
    rtsp_timeout_s=10.0,
    ffprobe_analyze_duration_s=5.0,

    # ONVIF / VAPIX / SNMP timeouts
    onvif_timeout_s=5.0,
    vapix_timeout_s=5.0,
    snmp_timeout_s=5.0,
    snmp_port=161,

    # Port scan
    port_scan_tcp_ports=[80, 443, 554, 8000, 8443],
    port_scan_udp_ports=[161],
    port_scan_timeout_s=2.0,

    # Concurrency
    max_concurrent_cameras=50,
    thread_pool_size=20,

    # Logging
    log_level="INFO",
    log_file=Path("logs/ipcam.log"),
    log_json=True,           # JSON format (Loki/Promtail-ready)
    log_console=False,
    loki_url=None,           # "http://loki:3100/loki/api/v1/push"
)
```

---

## Camera discovery

Find cameras on a local subnet without a predefined list:

```python
import asyncio
from ipcam_checker.discover import discover_cameras

async def main():
    devices = await discover_cameras(
        "192.168.2.0/24",
        scan_ports=[80, 443, 554, 8080, 8554],
        mdns_timeout_s=5.0,
        port_timeout_s=0.5,
        port_scan_workers=150,
    )
    for d in devices:
        if d.likely_camera:
            print(d.ip, d.open_ports, [s.service_type for s in d.mdns_services])

asyncio.run(main())
```

`discover_cameras` runs mDNS browsing and TCP port scan **concurrently** in threads. Results are merged by IP and sorted.

**`likely_camera`** is `True` when port 554 is open or a known camera mDNS service is present (`_axis-video._tcp`, `_onvif._tcp`, `_rtsp._tcp`).

Requires: `pip install "ipcam-checker[discovery]"`

---

## Telemetry

Every `CameraResult` includes timing data:

```python
result.telemetry.wall_ms          # total camera check wall time
result.telemetry.cpu_ms           # process CPU time (approx for async checks)
result.telemetry.threads_at_start # threading.active_count() before checks
result.telemetry.threads_at_end   # threading.active_count() after checks

for c in result.telemetry.checks:
    print(c.name, c.wall_ms, c.cpu_ms)
# ping        45.1ms   0.8ms
# ports       1201.3ms  2.1ms
# onvif       312.4ms   4.7ms
# snmp        95.6ms    3.1ms
```

Telemetry data is a plain Pydantic model — serialize with `.model_dump()` and ship to any backend.

---

## Plugin system

Extend results with custom checks:

```python
from ipcam_checker.plugins.base import AbstractPlugin

class MyPlugin(AbstractPlugin):
    name = "my_plugin"

    async def run(self, camera, result, executor, settings) -> dict:
        # result already has ping, streams, onvif, etc.
        return {"custom_value": 42}

# Pass plugins to check_cameras
async for result in check_cameras(cameras, settings, plugins=[MyPlugin()]):
    print(result.plugin_results["my_plugin"])
```

---

## Logging

Log output goes to file (JSON by default, Loki/Promtail-ready) and optionally to stderr. Third-party libraries (httpx, httpcore) are redirected to the log file only and suppressed from stdout.

```python
from ipcam_checker import setup_logging
from pathlib import Path

setup_logging(
    level="DEBUG",
    log_file=Path("logs/ipcam.log"),
    json_file=True,      # JSON lines in file
    console=False,       # no stderr output
    loki_url="http://loki:3100/loki/api/v1/push",   # optional
)
```

Or via `Settings`:

```python
settings = Settings(log_level="DEBUG", log_file=Path("logs/ipcam.log"))
settings.configure_logging()
```

---

## Examples

| File | Description |
|---|---|
| `examples/test_local.py` | Check a predefined list of cameras, print full results + telemetry |
| `examples/discover_local.py` | Discover cameras on `192.168.2.0/24` via mDNS + port scan |

## Requirements

- Python 3.13+
- `pydantic >= 2.0`
- `httpx >= 0.27`
- `icmplib >= 3.0`
- `Pillow >= 10.0`
- `local-ffmpeg >= 0.1.0`
- `python-json-logger >= 2.0`

Optional:
- `onvif-zeep >= 0.2.12` — ONVIF checks
- `zeroconf >= 0.115` — mDNS camera discovery
- `python-logging-loki >= 0.3` — Loki log push
