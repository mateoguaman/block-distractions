"""Experiment logging for multi-day diagnosis."""

import json
import logging
import os
import socket
import time
from datetime import datetime, date
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOG_DIR = Path(__file__).parent.parent / ".logs"
LOG_PATH = LOG_DIR / "experiment.log"
LOG_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
LOG_BACKUP_COUNT = 3
META_PATH = LOG_DIR / "experiment.meta.json"


class ExperimentLogger:
    """Write structured JSON lines to the experiment log."""

    def __init__(self, enabled: bool, days: int = 3, started_at: str | None = None):
        self.enabled = enabled
        self.days = days
        self.started_at = started_at
        self._logger = logging.getLogger("block_distractions.experiment")

        if self.enabled:
            LOG_DIR.mkdir(exist_ok=True)
            if not self._logger.handlers:
                handler = RotatingFileHandler(
                    LOG_PATH,
                    maxBytes=LOG_MAX_BYTES,
                    backupCount=LOG_BACKUP_COUNT,
                )
                handler.setFormatter(logging.Formatter("%(message)s"))
                self._logger.addHandler(handler)
                self._logger.setLevel(logging.INFO)
                self._logger.propagate = False

            self._normalize_started_at()
            self._ensure_meta()

    def _normalize_started_at(self) -> None:
        """Normalize started_at into an ISO string when possible."""
        if self.started_at is None:
            return
        if isinstance(self.started_at, datetime):
            self.started_at = self.started_at.isoformat(timespec="seconds")
            return
        if isinstance(self.started_at, date):
            self.started_at = self.started_at.isoformat()
            return
        if not isinstance(self.started_at, str):
            self.started_at = str(self.started_at)

    def _ensure_meta(self) -> None:
        """Ensure the experiment meta file exists to track start date."""
        if self.started_at:
            payload = {
                "started_at": self.started_at,
                "days": self.days,
            }
            META_PATH.write_text(json.dumps(payload, indent=2))
            return

        if META_PATH.exists():
            try:
                data = json.loads(META_PATH.read_text())
                self.started_at = data.get("started_at")
            except (json.JSONDecodeError, OSError):
                self.started_at = None

        if not self.started_at:
            self.started_at = datetime.now().isoformat(timespec="seconds")
            payload = {
                "started_at": self.started_at,
                "days": self.days,
            }
            META_PATH.write_text(json.dumps(payload, indent=2))
            self.log_event("experiment_start")

    def _experiment_day(self) -> int | None:
        """Compute the current experiment day (1-based)."""
        if not self.started_at:
            return None
        try:
            if isinstance(self.started_at, datetime):
                start_date = self.started_at.date()
            elif isinstance(self.started_at, date):
                start_date = self.started_at
            else:
                start_date = datetime.fromisoformat(str(self.started_at)).date()
        except (ValueError, TypeError):
            try:
                start_date = date.fromisoformat(str(self.started_at))
            except (ValueError, TypeError):
                return None
        return (date.today() - start_date).days + 1

    def log_event(self, event: str, **data: Any) -> None:
        """Log an event with structured context."""
        if not self.enabled:
            return

        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "epoch": round(time.time(), 3),
            "tz": time.tzname[0] if time.tzname else "",
            "event": event,
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "user": os.getenv("USER", ""),
            "host": socket.gethostname(),
            "experiment_day": self._experiment_day(),
            "experiment_days": self.days,
        }
        payload.update(data)
        self._logger.info(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def get_experiment_logger(config: Any) -> ExperimentLogger:
    """Get an ExperimentLogger configured by settings."""
    settings = {}
    if config is not None and hasattr(config, "get"):
        settings = config.get("experiment", {}) or {}
    enabled = bool(settings.get("enabled", False))
    days = int(settings.get("days", 3) or 3)
    started_at = settings.get("started_at") or None
    return ExperimentLogger(enabled=enabled, days=days, started_at=started_at)
