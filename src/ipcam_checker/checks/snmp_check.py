from __future__ import annotations

import asyncio
import os
import socket
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

# Standard MIB-II scalars
_OID_SYS_DESCR  = "1.3.6.1.2.1.1.1.0"
_OID_SYS_NAME   = "1.3.6.1.2.1.1.5.0"
_OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"

# AXIS-VIDEO-MIB tables
_OID_TEMP_TABLE  = "1.3.6.1.4.1.368.4.1.3.1"  # axisVideoTempSensorEntry
_OID_VIDEO_TABLE = "1.3.6.1.4.1.368.4.1.4.1"  # axisVideoChannelEntry

_TEMP_TYPE_MAP   = {1: "common", 2: "housing", 3: "rack", 4: "cpu"}
_TEMP_STATUS_MAP = {1: "ok", 2: "failure", 3: "outOfBoundary"}
_SIGNAL_MAP      = {1: "signalOk", 2: "noSignal"}


# ── BER encoder ──────────────────────────────────────────────────────────────

def _ber_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x100:
        return bytes([0x81, n])
    return bytes([0x82, (n >> 8) & 0xFF, n & 0xFF])


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _ber_len(len(content)) + content


def _enc_int(n: int) -> bytes:
    if n == 0:
        return b"\x02\x01\x00"
    buf: list[int] = []
    v = n
    while v not in (0, -1):
        buf.append(v & 0xFF)
        v >>= 8
    if n > 0 and buf[-1] & 0x80:
        buf.append(0)
    elif n < 0 and not (buf[-1] & 0x80):
        buf.append(0xFF)
    buf.reverse()
    return b"\x02" + _ber_len(len(buf)) + bytes(buf)


def _enc_oid(oid: str) -> bytes:
    parts = list(map(int, oid.split(".")))
    raw = [40 * parts[0] + parts[1]]
    for p in parts[2:]:
        if p == 0:
            raw.append(0)
        else:
            segs: list[int] = []
            while p:
                segs.append(p & 0x7F)
                p >>= 7
            segs.reverse()
            for i, s in enumerate(segs):
                raw.append(s | (0x80 if i < len(segs) - 1 else 0))
    content = bytes(raw)
    return b"\x06" + _ber_len(len(content)) + content


def _build_get(community: str, oids: list[str], req_id: int) -> bytes:
    vb = b"".join(_tlv(0x30, _enc_oid(o) + b"\x05\x00") for o in oids)
    pdu = _tlv(0xA0, _enc_int(req_id) + _enc_int(0) + _enc_int(0) + _tlv(0x30, vb))
    return _tlv(0x30, _enc_int(1) + _tlv(0x04, community.encode()) + pdu)


def _build_getbulk(community: str, oid: str, max_rep: int, req_id: int) -> bytes:
    vb = _tlv(0x30, _enc_oid(oid) + b"\x05\x00")
    # GETBULK: non-repeaters=0 (reused error-status slot), max-repetitions (error-index slot)
    pdu = _tlv(0xA5, _enc_int(req_id) + _enc_int(0) + _enc_int(max_rep) + _tlv(0x30, vb))
    return _tlv(0x30, _enc_int(1) + _tlv(0x04, community.encode()) + pdu)


# ── BER decoder ──────────────────────────────────────────────────────────────

def _read_len(data: bytes, off: int) -> tuple[int, int]:
    b = data[off]; off += 1
    if b < 0x80:
        return b, off
    count = b & 0x7F
    val = 0
    for _ in range(count):
        val = (val << 8) | data[off]; off += 1
    return val, off


def _read_tlv(data: bytes, off: int) -> tuple[int, bytes, int]:
    tag = data[off]; off += 1
    length, off = _read_len(data, off)
    return tag, data[off: off + length], off + length


def _dec_int(value: bytes) -> int:
    if not value:
        return 0
    n = value[0] if value[0] < 0x80 else value[0] - 256
    for b in value[1:]:
        n = (n << 8) | b
    return n


def _dec_oid(value: bytes) -> str:
    first = value[0]
    if first < 40:
        parts = [0, first]
    elif first < 80:
        parts = [1, first - 40]
    else:
        parts = [2, first - 80]
    i = 1
    while i < len(value):
        n = 0
        while i < len(value):
            b = value[i]; i += 1
            n = (n << 7) | (b & 0x7F)
            if not (b & 0x80):
                break
        parts.append(n)
    return ".".join(map(str, parts))


def _parse_response(data: bytes) -> list[tuple[str, object]]:
    """Return [(oid_str, value), ...] from an SNMPv2c response packet."""
    result: list[tuple[str, object]] = []
    try:
        _, msg, _ = _read_tlv(data, 0)
        off = 0
        _, _, off = _read_tlv(msg, off)   # skip version
        _, _, off = _read_tlv(msg, off)   # skip community
        pdu_tag, pdu, _ = _read_tlv(msg, off)
        if pdu_tag not in (0xA2, 0xA0):   # GetResponse or GetRequest
            return result
        off = 0
        _, _, off = _read_tlv(pdu, off)                  # request-id
        _, err_v, off = _read_tlv(pdu, off)              # error-status
        if _dec_int(err_v) != 0:
            return result
        _, _, off = _read_tlv(pdu, off)                  # error-index
        _, vbl, _ = _read_tlv(pdu, off)                  # varbind-list
        vb_off = 0
        while vb_off < len(vbl):
            _, vb, vb_off = _read_tlv(vbl, vb_off)
            v2 = 0
            _, oid_val, v2 = _read_tlv(vb, v2)
            oid_str = _dec_oid(oid_val)
            val_tag, val_bytes, _ = _read_tlv(vb, v2)
            if val_tag == 0x02:                          # INTEGER
                value: object = _dec_int(val_bytes)
            elif val_tag == 0x04:                        # OCTET STRING
                try:
                    value = val_bytes.decode("utf-8", errors="replace")
                except Exception:
                    value = val_bytes
            elif val_tag == 0x43:                        # TimeTicks
                value = _dec_int(val_bytes)
            elif val_tag == 0x06:                        # OID
                value = _dec_oid(val_bytes)
            elif val_tag in (0x80, 0x81, 0x82):          # noSuchObject / endOfMibView
                value = None
            else:
                value = val_bytes
            result.append((oid_str, value))
    except (IndexError, ValueError):
        pass
    return result


# ── Transport ─────────────────────────────────────────────────────────────────

def _udp_request(sock: socket.socket, ip: str, port: int,
                 packet: bytes, retries: int = 2) -> bytes | None:
    for _ in range(retries):
        try:
            sock.sendto(packet, (ip, port))
            data, _ = sock.recvfrom(65535)
            return data
        except socket.timeout:
            continue
        except OSError:
            return None
    return None


def _walk_table(sock: socket.socket, ip: str, port: int, community: str,
                base_oid: str, req_id: int) -> list[tuple[str, object]]:
    """GETBULK-walk a table OID until results leave the subtree."""
    current = base_oid
    rows: list[tuple[str, object]] = []
    seen: set[str] = set()
    prefix = base_oid + "."
    for _ in range(30):  # safety cap
        raw = _udp_request(sock, ip, port, _build_getbulk(community, current, 10, req_id))
        if raw is None:
            break
        varbinds = _parse_response(raw)
        if not varbinds:
            break
        advanced = False
        for oid, val in varbinds:
            if not oid.startswith(prefix):
                return rows
            if oid in seen or val is None:
                continue
            seen.add(oid)
            rows.append((oid, val))
            current = oid
            advanced = True
        if not advanced:
            break
    return rows


# ── Main sync worker (runs in ThreadPoolExecutor) ─────────────────────────────

def _snmp_worker(ip: str, community: str, port: int, timeout: float) -> SnmpResult:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
    except OSError as exc:
        return SnmpResult(ok=False, error=f"socket error: {exc}")

    try:
        req_id = os.getpid() & 0x7FFFFFFF

        # ── scalar GET ──
        raw = _udp_request(sock, ip, port,
                           _build_get(community, [_OID_SYS_DESCR, _OID_SYS_NAME, _OID_SYS_UPTIME], req_id))
        if raw is None:
            return SnmpResult(
                ok=False,
                error=f"timeout — check SNMP community string and firewall (UDP {port})",
            )

        scalars: dict[str, object] = dict(_parse_response(raw))
        sys_descr = scalars.get(_OID_SYS_DESCR)
        sys_name  = scalars.get(_OID_SYS_NAME)
        uptime_cs = scalars.get(_OID_SYS_UPTIME)

        if isinstance(sys_descr, (bytes, bytearray)):
            sys_descr = sys_descr.decode("utf-8", errors="replace")
        if isinstance(sys_name, (bytes, bytearray)):
            sys_name = sys_name.decode("utf-8", errors="replace")
        uptime_s = int(uptime_cs) // 100 if isinstance(uptime_cs, int) else None

        # ── temperature table ──
        temp_rows: dict[str, dict[int, object]] = {}
        for oid, val in _walk_table(sock, ip, port, community, _OID_TEMP_TABLE, req_id + 1):
            suffix = oid[len(_OID_TEMP_TABLE) + 1:]
            col_s, _, row_idx = suffix.partition(".")
            if col_s.isdigit():
                temp_rows.setdefault(row_idx, {})[int(col_s)] = val

        temp_sensors: list[SnmpTempSensor] = []
        for row_idx, cols in temp_rows.items():
            try:
                sensor_id = int(str(cols.get(2, row_idx.split(".")[0])))
            except (ValueError, TypeError):
                sensor_id = 0
            type_int   = cols.get(1)
            status_int = cols.get(3)
            celsius    = cols.get(4)
            temp_sensors.append(SnmpTempSensor(
                sensor_type=_TEMP_TYPE_MAP.get(int(type_int)) if isinstance(type_int, int) else None,
                sensor_id=sensor_id,
                status=_TEMP_STATUS_MAP.get(int(status_int)) if isinstance(status_int, int) else None,
                celsius=int(celsius) if isinstance(celsius, int) else None,
            ))

        # ── video channel table ──
        video_rows: dict[str, dict[int, object]] = {}
        for oid, val in _walk_table(sock, ip, port, community, _OID_VIDEO_TABLE, req_id + 2):
            suffix = oid[len(_OID_VIDEO_TABLE) + 1:]
            col_s, _, row_idx = suffix.partition(".")
            if col_s.isdigit():
                video_rows.setdefault(row_idx, {})[int(col_s)] = val

        video_channels: list[SnmpVideoChannel] = []
        for row_idx, cols in video_rows.items():
            ch_raw  = cols.get(1)
            sig_raw = cols.get(2)
            try:
                channel_id = int(ch_raw) if isinstance(ch_raw, int) else int(row_idx.split(".")[0])
            except (ValueError, TypeError):
                channel_id = 0
            video_channels.append(SnmpVideoChannel(
                channel_id=channel_id,
                signal_status=_SIGNAL_MAP.get(int(sig_raw)) if isinstance(sig_raw, int) else None,
            ))

        return SnmpResult(
            ok=True,
            sys_descr=sys_descr,
            sys_name=sys_name,
            uptime_s=uptime_s,
            temp_sensors=temp_sensors,
            video_channels=video_channels,
        )

    except OSError as exc:
        return SnmpResult(ok=False, error=str(exc))
    finally:
        sock.close()


# ── Async entry point ─────────────────────────────────────────────────────────

async def check_snmp(camera: CameraConfig, settings: Settings) -> SnmpResult:
    ip        = camera.ip
    port      = settings.snmp_port
    community = camera.snmp_community_read
    timeout   = settings.snmp_timeout_s

    _log.debug("snmp.start", extra={"camera": camera.name, "ip": ip})

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as ex:
        result = await loop.run_in_executor(ex, _snmp_worker, ip, community, port, timeout)

    if result.ok:
        _log.info("snmp.ok", extra={
            "camera": camera.name, "ip": ip,
            "sys_name": result.sys_name,
            "temp_sensors": len(result.temp_sensors),
            "video_channels": len(result.video_channels),
        })
    else:
        _log.info("snmp.fail", extra={"camera": camera.name, "ip": ip, "error": result.error})

    return result
