from __future__ import annotations

import asyncio
import datetime
import sys
from concurrent.futures import ThreadPoolExecutor

from ipcam_checker._logging import get_logger
from ipcam_checker.config import Settings
from ipcam_checker.models import (
    CameraConfig,
    SnmpResult,
    SnmpTempSensor,
    SnmpVideoChannel,
)

_log = get_logger("snmp")

# Standard MIB-II
_OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
_OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
_OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"

# AXIS-VIDEO-MIB — temperature sensor table (axisVideoTempSensorEntry)
_OID_TEMP_TABLE = "1.3.6.1.4.1.368.4.1.3.1"
_TEMP_COL_TYPE = 1    # 1=common, 2=housing, 3=rack, 4=cpu
_TEMP_COL_ID = 2
_TEMP_COL_STATUS = 3  # 1=ok, 2=failure, 3=outOfBoundary
_TEMP_COL_CELSIUS = 4

# AXIS-VIDEO-MIB — video channel table (axisVideoChannelEntry)
_OID_VIDEO_TABLE = "1.3.6.1.4.1.368.4.1.4.1"
_VIDEO_COL_CHANNEL_ID = 1
_VIDEO_COL_SIGNAL = 2  # 1=signalOk, 2=noSignal

_TEMP_TYPE_MAP = {1: "common", 2: "housing", 3: "rack", 4: "cpu"}
_TEMP_STATUS_MAP = {1: "ok", 2: "failure", 3: "outOfBoundary"}
_SIGNAL_MAP = {1: "signalOk", 2: "noSignal"}


def _decode(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


def _uptime_s(val) -> int | None:
    if val is None:
        return None
    if isinstance(val, datetime.timedelta):
        return int(val.total_seconds())
    try:
        # TimeTicks are in centiseconds when returned as int
        return int(val) // 100
    except (TypeError, ValueError):
        return None


def _oid_col_index(oid: str, table_oid: str) -> tuple[int, str] | None:
    prefix = table_oid + "."
    if not oid.startswith(prefix):
        return None
    rest = oid[len(prefix):]
    parts = rest.split(".", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), parts[1]
    except ValueError:
        return None


async def _snmp_async(puresnmp, ip: str, community: str, port: int, timeout: float) -> SnmpResult:
    client = puresnmp.Client(ip, puresnmp.V2C(community), port=port, timeout=int(timeout))

    sys_vars = await client.multiget([_OID_SYS_DESCR, _OID_SYS_NAME, _OID_SYS_UPTIME])
    sys_descr = _decode(sys_vars[0])
    sys_name = _decode(sys_vars[1])
    uptime_s = _uptime_s(sys_vars[2])

    # Walk temperature sensor table
    temp_rows: dict[str, dict[int, object]] = {}
    try:
        async for varbind in client.bulkwalk([_OID_TEMP_TABLE]):
            oid = str(varbind.oid)
            parsed = _oid_col_index(oid, _OID_TEMP_TABLE)
            if parsed is None:
                continue
            col, row_idx = parsed
            temp_rows.setdefault(row_idx, {})[col] = varbind.value
    except Exception as exc:
        _log.debug("snmp.temp_walk_fail", extra={"ip": ip, "error": str(exc)})

    temp_sensors: list[SnmpTempSensor] = []
    for row_idx, cols in temp_rows.items():
        try:
            sensor_id = int(str(cols.get(_TEMP_COL_ID, row_idx)))
        except (ValueError, TypeError):
            sensor_id = 0
        type_int = cols.get(_TEMP_COL_TYPE)
        status_int = cols.get(_TEMP_COL_STATUS)
        celsius_raw = cols.get(_TEMP_COL_CELSIUS)
        celsius: int | None = None
        if celsius_raw is not None:
            try:
                celsius = int(celsius_raw)
            except (ValueError, TypeError):
                pass
        temp_sensors.append(SnmpTempSensor(
            sensor_type=_TEMP_TYPE_MAP.get(int(type_int)) if type_int is not None else None,
            sensor_id=sensor_id,
            status=_TEMP_STATUS_MAP.get(int(status_int)) if status_int is not None else None,
            celsius=celsius,
        ))

    # Walk video channel table
    video_rows: dict[str, dict[int, object]] = {}
    try:
        async for varbind in client.bulkwalk([_OID_VIDEO_TABLE]):
            oid = str(varbind.oid)
            parsed = _oid_col_index(oid, _OID_VIDEO_TABLE)
            if parsed is None:
                continue
            col, row_idx = parsed
            video_rows.setdefault(row_idx, {})[col] = varbind.value
    except Exception as exc:
        _log.debug("snmp.video_walk_fail", extra={"ip": ip, "error": str(exc)})

    video_channels: list[SnmpVideoChannel] = []
    for row_idx, cols in video_rows.items():
        ch_raw = cols.get(_VIDEO_COL_CHANNEL_ID)
        sig_raw = cols.get(_VIDEO_COL_SIGNAL)
        try:
            channel_id = int(str(ch_raw)) if ch_raw is not None else int(row_idx.split(".")[0])
        except (ValueError, TypeError):
            channel_id = 0
        video_channels.append(SnmpVideoChannel(
            channel_id=channel_id,
            signal_status=_SIGNAL_MAP.get(int(sig_raw)) if sig_raw is not None else None,
        ))

    return SnmpResult(
        ok=True,
        sys_descr=sys_descr,
        sys_name=sys_name,
        uptime_s=uptime_s,
        temp_sensors=temp_sensors,
        video_channels=video_channels,
    )


def _snmp_worker(ip: str, community: str, port: int, timeout: float) -> SnmpResult:
    """Run SNMP in a thread with SelectorEventLoop (required for UDP on Windows)."""
    try:
        import puresnmp  # noqa: PLC0415
    except ImportError:
        return SnmpResult(ok=False, error="puresnmp not installed — run: pip install puresnmp")

    # ProactorEventLoop (Windows default) has UDP issues; SelectorEventLoop works correctly.
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_snmp_async(puresnmp, ip, community, port, timeout))
    except Exception as exc:
        err = str(exc)
        if not err or "timeout" in err.lower():
            return SnmpResult(ok=False, error=f"timeout — check SNMP community string and firewall (UDP {port})")
        return SnmpResult(ok=False, error=err)
    finally:
        loop.close()


async def check_snmp(camera: CameraConfig, settings: Settings) -> SnmpResult:
    ip = camera.ip
    port = settings.snmp_port
    community = camera.snmp_community_read
    timeout = settings.snmp_timeout_s

    _log.debug("snmp.start", extra={"camera": camera.name, "ip": ip})

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as ex:
        result = await loop.run_in_executor(
            ex, _snmp_worker, ip, community, port, timeout
        )

    if result.ok:
        _log.info(
            "snmp.ok",
            extra={
                "camera": camera.name,
                "ip": ip,
                "sys_name": result.sys_name,
                "temp_sensors": len(result.temp_sensors),
                "video_channels": len(result.video_channels),
            },
        )
    else:
        _log.info("snmp.fail", extra={"camera": camera.name, "ip": ip, "error": result.error})

    return result
