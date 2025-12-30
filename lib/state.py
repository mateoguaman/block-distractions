"""Daily state tracking for block_distractions."""

import json
import logging
import subprocess
import tempfile
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any

# Default state file location
DEFAULT_STATE_PATH = Path(__file__).parent.parent / "state.json"

logger = logging.getLogger(__name__)


class RemoteStateStore:
    """Loads/saves state on a remote host via SSH with a lock."""

    MAX_RETRIES = 3
    INITIAL_BACKOFF = 2  # seconds
    BACKOFF_MULTIPLIER = 2

    def __init__(self, config: dict[str, Any], fallback: dict[str, Any] | None = None):
        fallback = fallback or {}
        self.enabled = config.get("enabled", False)
        self.host = config.get("host") or fallback.get("host", "")
        self.user = config.get("user") or fallback.get("user", "")
        self.state_path = config.get("state_path", "/etc/block_distractions/state.json")
        self.state_dir = str(Path(self.state_path).parent)
        self.lock_path = config.get("lock_path", "/tmp/block_distractions_state.lock")
        use_sudo = config.get("use_sudo")
        if use_sudo is None:
            use_sudo = self.state_path.startswith(("/etc/", "/var/"))
        self.use_sudo = bool(use_sudo)

    def is_configured(self) -> bool:
        """Return True if remote state is enabled and has host/user."""
        return bool(self.enabled and self.host and self.user and self.state_path)

    def _run_with_retry(self, cmd: list[str], description: str) -> tuple[bool, str, str]:
        """Run a command with retry logic for transient SSH failures."""
        backoff = self.INITIAL_BACKOFF
        last_error = ""

        for attempt in range(self.MAX_RETRIES):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return True, result.stdout, result.stderr

            last_error = result.stderr.strip()
            transient_errors = [
                "Connection reset by peer",
                "Connection refused",
                "Connection timed out",
                "Network is unreachable",
                "No route to host",
            ]
            is_transient = any(err in last_error for err in transient_errors)

            if not is_transient or attempt == self.MAX_RETRIES - 1:
                break

            logger.warning(
                f"Remote state {description} failed (attempt {attempt + 1}/{self.MAX_RETRIES}): "
                f"{last_error}. Retrying in {backoff}s..."
            )
            time.sleep(backoff)
            backoff *= self.BACKOFF_MULTIPLIER

        return False, "", last_error

    def load_state(self) -> dict[str, Any]:
        """Load state JSON from the remote host."""
        if not self.is_configured():
            return {}

        remote = f"{self.user}@{self.host}"
        sudo = "sudo " if self.use_sudo else ""
        cmd = [
            "ssh",
            remote,
            f"flock -s {self.lock_path} -c '{sudo}cat {self.state_path} 2>/dev/null || true'",
        ]
        success, stdout, error = self._run_with_retry(cmd, "load")
        if not success:
            logger.error(f"Failed to load remote state: {error}")
            return {}

        if not stdout.strip():
            return {}

        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            logger.error("Remote state JSON is invalid; starting fresh.")
            return {}

    def get_today_iso(self) -> str:
        """Get today's date (ISO) from the remote host to avoid timezone drift.

        We prefer the remote's local date (without forcing UTC) to respect the
        host's timezone and avoid surprises across user timezones.
        """
        if not self.is_configured():
            return date.today().isoformat()

        remote = f"{self.user}@{self.host}"
        # Use the remote's local date; this matches how users experience their VM
        # and avoids UTC vs local discrepancies for day rollovers.
        cmd = ["ssh", remote, "date +%F"]
        success, stdout, error = self._run_with_retry(cmd, "date")
        if success and stdout.strip():
            return stdout.strip()

        logger.warning(f"Falling back to local date for remote state: {error}")
        return date.today().isoformat()

    def save_state(self, state: dict[str, Any]) -> None:
        """Save state JSON to the remote host."""
        if not self.is_configured():
            return

        temp_path = None
        remote = f"{self.user}@{self.host}"
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
                json.dump(state, f, indent=2)
                temp_path = f.name

            success, _, error = self._run_with_retry(
                ["scp", temp_path, f"{remote}:/tmp/state.json.tmp"],
                "scp",
            )
            if not success:
                logger.error(f"Failed to copy remote state: {error}")
                return

            sudo = "sudo " if self.use_sudo else ""
            cmd = [
                "ssh",
                remote,
                "flock -x {lock} -c '{sudo}mkdir -p {dir} "
                "&& {sudo}mv /tmp/state.json.tmp {path} "
                "&& {sudo}chmod 600 {path} {chown}'".format(
                    lock=self.lock_path,
                    sudo=sudo,
                    dir=self.state_dir,
                    path=self.state_path,
                    chown=f'&& {sudo}chown root:root {self.state_path}' if self.use_sudo else "",
                ),
            ]
            success, _, error = self._run_with_retry(cmd, "save")
            if not success:
                logger.error(f"Failed to save remote state: {error}")
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)


class State:
    """Manages daily state for unlock tracking."""

    def __init__(
        self,
        state_path: Path | str | None = None,
        remote_store: RemoteStateStore | None = None,
    ):
        self.state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self.remote_store = remote_store
        self._state: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load state from file."""
        if self.remote_store:
            self._state = self.remote_store.load_state()
        else:
            if self.state_path.exists():
                with open(self.state_path, "r") as f:
                    self._state = json.load(f)
            else:
                self._state = {}

        # Check if we need to reset for a new day
        self._check_day_reset()

    def save(self) -> None:
        """Save state to file."""
        if self.remote_store:
            self.remote_store.save_state(self._state)
            return

        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self._state, f, indent=2)

    def _check_day_reset(self) -> None:
        """Reset state if it's a new day."""
        today = (
            self.remote_store.get_today_iso()
            if self.remote_store
            else date.today().isoformat()
        )
        if self._state.get("date") != today:
            self._state = {
                "date": today,
                "unlocked_until": 0,
                "emergency_count": 0,
                "last_emergency_wait": 0,
                "blocked": True,
            }
            self.save()

    @property
    def today(self) -> str:
        """Get today's date as ISO string."""
        return date.today().isoformat()

    @property
    def is_blocked(self) -> bool:
        """Check if sites are currently blocked."""
        self._check_day_reset()
        unlocked_until = self._state.get("unlocked_until", 0)
        if unlocked_until > 0:
            # There was an unlock set - check if it's still active
            if time.time() < unlocked_until:
                return False  # Unlock still active
            else:
                # Unlock expired - persist the blocked state immediately
                self._state["unlocked_until"] = 0
                self._state["blocked"] = True
                self.save()
                return True  # Unlock expired, should be blocked
        # No unlock was set, use the permanent blocked state
        return self._state.get("blocked", True)

    @property
    def unlocked_until(self) -> float:
        """Get the timestamp when unlock expires."""
        return self._state.get("unlocked_until", 0)

    @property
    def unlock_remaining_seconds(self) -> int:
        """Get remaining seconds of unlock time."""
        remaining = self.unlocked_until - time.time()
        return max(0, int(remaining))

    @property
    def unlock_remaining_formatted(self) -> str:
        """Get remaining unlock time as formatted string."""
        seconds = self.unlock_remaining_seconds
        if seconds <= 0:
            return "0:00"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @property
    def emergency_count(self) -> int:
        """Get the number of emergency unlocks used today."""
        self._check_day_reset()
        return self._state.get("emergency_count", 0)

    @property
    def last_emergency_wait(self) -> int:
        """Get the last emergency wait time in seconds."""
        return self._state.get("last_emergency_wait", 0)

    def set_unlocked(self, duration_seconds: int) -> None:
        """Set the unlock duration from now."""
        self._check_day_reset()
        self._state["unlocked_until"] = time.time() + duration_seconds
        self._state["blocked"] = False
        self.save()

    def extend_unlock(self, duration_seconds: int) -> None:
        """Extend current unlock or create new one."""
        self._check_day_reset()
        current_until = self._state.get("unlocked_until", 0)
        now = time.time()

        if current_until > now:
            # Extend from current end time
            self._state["unlocked_until"] = current_until + duration_seconds
        else:
            # Start new unlock from now
            self._state["unlocked_until"] = now + duration_seconds

        self._state["blocked"] = False
        self.save()

    def record_emergency_unlock(self, wait_time: int) -> None:
        """Record an emergency unlock usage."""
        self._check_day_reset()
        self._state["emergency_count"] = self.emergency_count + 1
        self._state["last_emergency_wait"] = wait_time
        self.save()

    def can_emergency_unlock(self, max_per_day: int) -> bool:
        """Check if emergency unlock is available."""
        self._check_day_reset()
        return self.emergency_count < max_per_day

    def get_next_emergency_wait(self, initial_wait: int, multiplier: int) -> int:
        """Calculate the next emergency wait time."""
        count = self.emergency_count
        return initial_wait * (multiplier ** count)

    def force_block(self) -> None:
        """Force sites to be blocked immediately."""
        self._check_day_reset()
        self._state["unlocked_until"] = 0
        self._state["blocked"] = True
        self.save()

    def get_status(self) -> dict[str, Any]:
        """Get a status summary."""
        self._check_day_reset()
        return {
            "date": self.today,
            "blocked": self.is_blocked,
            "unlocked_until": self.unlocked_until,
            "unlock_remaining": self.unlock_remaining_formatted,
            "emergency_count": self.emergency_count,
            "emergency_remaining": max(0, 3 - self.emergency_count),  # Will use config
        }


def get_state(
    config: Any | None = None,
    state_path: Path | str | None = None,
) -> State:
    """Get a State instance."""
    remote_store = None
    if config is not None:
        remote_cfg = config.get("remote_state", {}) if hasattr(config, "get") else {}
        remote_store = RemoteStateStore(remote_cfg, getattr(config, "remote_sync_settings", {}))
        if not remote_store.is_configured():
            if remote_cfg.get("enabled"):
                logger.warning("Remote state enabled but not fully configured; using local state.")
            remote_store = None
    return State(state_path, remote_store=remote_store)
