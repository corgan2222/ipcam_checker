from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_TEXT_FMT = "%(asctime)s %(levelname)-8s %(name)-30s %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"
_ROOT = "ipcam_checker"

try:
    from pythonjsonlogger import jsonlogger as _jl
    _HAS_JSON = True
except ImportError:
    _HAS_JSON = False


def setup_logging(
    level: str = "INFO",
    log_file: Path | str | None = None,
    json_file: bool = True,
    loki_url: str | None = None,
    loki_labels: dict[str, str] | None = None,
) -> None:
    """Configure ipcam_checker logging. Call once at application startup.

    Console output is plain text for human readability.
    File output is JSON (Loki/Promtail-ready) when python-json-logger is installed.
    Direct Loki push is optional via python-logging-loki.
    """
    root = logging.getLogger(_ROOT)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.propagate = False

    _add_console(root)

    if log_file:
        _add_file(root, Path(log_file), json_file)

    if loki_url:
        _add_loki(root, loki_url, loki_labels or {})


def _add_console(logger: logging.Logger) -> None:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter(_TEXT_FMT, datefmt=_DATE_FMT))
    logger.addHandler(h)


def _add_file(logger: logging.Logger, path: Path, as_json: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    if as_json and _HAS_JSON:
        h.setFormatter(_jl.JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt=_DATE_FMT,
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
        ))
    else:
        h.setFormatter(logging.Formatter(_TEXT_FMT, datefmt=_DATE_FMT))
    logger.addHandler(h)


def _add_loki(logger: logging.Logger, url: str, labels: dict[str, str]) -> None:
    try:
        import logging_loki  # type: ignore[import]
        h = logging_loki.LokiHandler(
            url=url,
            tags={"application": "ipcam-checker", **labels},
            version="1",
        )
        logger.addHandler(h)
    except ImportError:
        logger.warning("loki.unavailable — install python-logging-loki to enable direct push")
    except Exception as exc:
        logger.error("loki.setup.error", extra={"error": str(exc)})


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{_ROOT}.{component}")
