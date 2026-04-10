#!/usr/bin/env python3
"""
Structured JSON logger for pipeline scripts.

Writes one JSON object per log entry to both stdout (captured by GitHub
Actions) and a daily rotating file at `logs/YYYY-MM-DD.log`.

Usage:
    from execution.logging_utils import get_logger

    log = get_logger("auto_emailer")
    log.info("Processing lead", lead_id="abc123", days_since=7)
    log.warn("SMTP retry", attempt=2, error=str(exc))
    log.error("Giving up", lead_id="abc123")
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path


def _find_logs_dir() -> Path:
    """Resolve a writable `logs/` directory.

    Prefers `<repo>/Website Builder/logs/` relative to this file so the
    location is stable whether the script is invoked from the repo root,
    the `Website Builder` folder, or a GitHub Actions checkout.
    """
    here = Path(__file__).resolve().parent  # .../Website Builder/execution
    logs_dir = here.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


class StructuredLogger:
    def __init__(self, component: str):
        self.component = component
        self._log_path = _find_logs_dir() / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    def _write(self, level: str, message: str, **metadata):
        entry = {
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "level": level,
            "component": self.component,
            "msg": message,
        }
        if metadata:
            entry.update(metadata)
        line = json.dumps(entry, ensure_ascii=False)

        # Stdout for GitHub Actions and interactive runs.
        print(line, flush=True)

        # Best-effort persistent file log.
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            print(
                json.dumps(
                    {
                        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                        "level": "warn",
                        "component": "logging_utils",
                        "msg": "Could not write to log file",
                        "error": str(exc),
                        "path": str(self._log_path),
                    }
                ),
                file=sys.stderr,
                flush=True,
            )

    def info(self, message: str, **metadata):
        self._write("info", message, **metadata)

    def warn(self, message: str, **metadata):
        self._write("warn", message, **metadata)

    def error(self, message: str, **metadata):
        self._write("error", message, **metadata)

    def debug(self, message: str, **metadata):
        if os.environ.get("LOG_LEVEL", "").lower() == "debug":
            self._write("debug", message, **metadata)


def get_logger(component: str) -> StructuredLogger:
    """Return a StructuredLogger scoped to the given component name."""
    return StructuredLogger(component)
