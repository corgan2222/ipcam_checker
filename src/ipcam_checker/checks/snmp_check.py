from __future__ import annotations

import asyncio

import puresnmp

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


def _oid_col_index(oid: str, table_oid: str) -> tuple[int, str] | None:
    """Extract (column, row_index) from a table OID."""
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


async def _bulkwalk(ip: str, community: str, base_oid: str, port: int, timeout: float):
    """Walk all OIDs under base_oid using puresnmp bulkwalk."""
    client = puresnmp.Client(
        ip,
        puresnmp.V2C(community),
        port=port,
        timeout=timeout,
    )
    results = []
    async for varbind in client.bulkwalk([base_oid]):
        results.append(varbind)
    return results


async def check_snmp(camera: CameraConfig, settings: Settings) -> SnmpResult:
    ip = camera.ip
    port = settings.snmp_port
    community = camera.snmp_community_read
    timeout = settings.snmp_timeout_s

    _log.debug("snmp.start", extra={"camera": camera.name, "ip": ip})

    try:
        # Fetch scalar system OIDs
        client = puresnmp.Client(ip, puresnmp.V2C(community), port=port, timeout=timeout)
        sys_vars = await client.multiget([_OID_SYS_DESCR, _OID_SYS_NAME, _OID_SYS_UPTIME])

        sys_descr = str(sys_vars[0]) if sys_vars[0] is not None else None
        sys_name = str(sys_vars[1]) if sys_vars[1] is not None else None
        uptime_raw = sys_vars[2]
        uptime_s: int | None = None
        if uptime_raw is not None:
            try:
                # sysUpTime is in centiseconds (TimeTicks)
                uptime_s = int(uptime_raw) // 100
            except (TypeError, ValueError):
                pass

        # Walk temperature sensor table
        temp_rows: dict[str, dict[int, object]] = {}
        try:
            for varbind in await _bulkwalk(ip, community, _OID_TEMP_TABLE, port, timeout):
                oid = str(varbind.oid)
                parsed = _oid_col_index(oid, _OID_TEMP_TABLE)
                if parsed is None:
                    continue
                col, row_idx = parsed
                row = temp_rows.setdefault(row_idx, {})
                row[col] = varbind.value
        except Exception as exc:
            _log.debug("snmp.temp_walk_fail", extra={"camera": camera.name, "error": str(exc)})

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
            for varbind in await _bulkwalk(ip, community, _OID_VIDEO_TABLE, port, timeout):
                oid = str(varbind.oid)
                parsed = _oid_col_index(oid, _OID_VIDEO_TABLE)
                if parsed is None:
                    continue
                col, row_idx = parsed
                row = video_rows.setdefault(row_idx, {})
                row[col] = varbind.value
        except Exception as exc:
            _log.debug("snmp.video_walk_fail", extra={"camera": camera.name, "error": str(exc)})

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

        _log.info(
            "snmp.ok",
            extra={
                "camera": camera.name,
                "ip": ip,
                "sys_name": sys_name,
                "temp_sensors": len(temp_sensors),
                "video_channels": len(video_channels),
            },
        )
        return SnmpResult(
            ok=True,
            sys_descr=sys_descr,
            sys_name=sys_name,
            uptime_s=uptime_s,
            temp_sensors=temp_sensors,
            video_channels=video_channels,
        )

    except asyncio.TimeoutError:
        return SnmpResult(ok=False, error=f"timeout — SNMP port {port}/udp not reachable or community wrong")
    except Exception as exc:
        err = str(exc)
        if "timeout" in err.lower():
            return SnmpResult(ok=False, error=f"timeout — SNMP port {port}/udp not reachable or community wrong")
        _log.warning("snmp.fail", extra={"camera": camera.name, "ip": ip, "error": err})
        return SnmpResult(ok=False, error=err)
