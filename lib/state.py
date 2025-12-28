"""Daily state tracking for block_distractions."""

import json
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any

# Default state file location
DEFAULT_STATE_PATH = Path(__file__).parent.parent / "state.json"


class State:
    """Manages daily state for unlock tracking."""

    def __init__(self, state_path: Path | str | None = None):
        self.state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self._state: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load state from file."""
        if self.state_path.exists():
            with open(self.state_path, "r") as f:
                self._state = json.load(f)
        else:
            self._state = {}

        # Check if we need to reset for a new day
        self._check_day_reset()

    def save(self) -> None:
        """Save state to file."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self._state, f, indent=2)

    def _check_day_reset(self) -> None:
        """Reset state if it's a new day."""
        today = date.today().isoformat()
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


def get_state(state_path: Path | str | None = None) -> State:
    """Get a State instance."""
    return State(state_path)
