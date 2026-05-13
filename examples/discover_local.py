"""Discover cameras on a local subnet via mDNS (Bonjour) + TCP port scan."""

import asyncio
from pathlib import Path

from ipcam_checker import setup_logging
from ipcam_checker.discover import discover_cameras

NETWORK = "192.168.2.0/24"

MDNS_TIMEOUT_S = 5.0  # how long to listen for mDNS announcements
PORT_TIMEOUT_S = 0.5  # per-connection TCP timeout
PORT_SCAN_WORKERS = 150  # concurrent TCP threads (150 handles /24 quickly)


def _on_port_found(ip: str, port: int) -> None:
    """Progress callback: print as soon as an open port is found."""
    print(f"  [+] {ip}:{port}", flush=True)


async def main() -> None:
    setup_logging(level="INFO", log_file=Path("logs/discover.log"))

    print(f"Scanning {NETWORK}")
    print(f"  port scan:  {PORT_SCAN_WORKERS} threads  timeout={PORT_TIMEOUT_S}s")
    print(f"  mDNS:       listening {MDNS_TIMEOUT_S}s")
    print()

    devices = await discover_cameras(
        NETWORK,
        mdns_timeout_s=MDNS_TIMEOUT_S,
        port_timeout_s=PORT_TIMEOUT_S,
        port_scan_workers=PORT_SCAN_WORKERS,
        on_port_found=_on_port_found,
    )

    cameras = [d for d in devices if d.likely_camera]
    others = [d for d in devices if not d.likely_camera]

    print(f"\n{'=' * 56}")
    print(f"  Found {len(devices)} active host(s)  —  {len(cameras)} likely camera(s)")
    print(f"{'=' * 56}\n")

    # ── Likely cameras ────────────────────────────────────────────────────────
    if cameras:
        print("CAMERAS")
        print("-------")
        for d in cameras:
            ports_str = "  ".join(str(p) for p in d.open_ports) or "—"
            print(f"  {d.ip}")
            print(f"    ports:  {ports_str}")
            for svc in d.mdns_services:
                print(f"    mdns:   [{svc.service_type}]  {svc.name}  port={svc.port}")
                useful = {k: v for k, v in svc.txt.items() if v}
                if useful:
                    txt_str = "  ".join(f"{k}={v}" for k, v in useful.items())
                    print(f"            {txt_str}")
        print()

    # ── Other active hosts ────────────────────────────────────────────────────
    if others:
        print("OTHER ACTIVE HOSTS")
        print("------------------")
        for d in others:
            ports_str = "  ".join(str(p) for p in d.open_ports) or "—"
            mdns_str = "  ".join(s.service_type for s in d.mdns_services)
            extra = f"  [{mdns_str}]" if mdns_str else ""
            print(f"  {d.ip}  ports: {ports_str}{extra}")
        print()

    print("Log written to: logs/discover.log")


if __name__ == "__main__":
    asyncio.run(main())
