"""Unlock logic and shame prompts."""

import logging
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

from .config import Config
from .state import State
from .hosts import HostsManager, RemoteSyncManager
from .obsidian import ObsidianParser
from .wordcount import WordCounter


SHAME_PROMPTS = [
    "You're about to waste time you could spend on something meaningful.",
    "Remember why you set up this blocker in the first place.",
    "Is this really what you want to be doing right now?",
    "Your future self will thank you for staying focused.",
    "Distraction is the enemy of achievement.",
]

CONFIRMATION_PHRASE = "I CHOOSE DISTRACTION"


class UnlockManager:
    """Manages unlocking logic for proof-of-work and emergency unlocks."""

    def __init__(
        self,
        config: Config,
        state: State,
        hosts: HostsManager,
        obsidian: ObsidianParser,
        remote_sync: RemoteSyncManager | None = None,
    ):
        self.config = config
        self.state = state
        self.hosts = hosts
        self.obsidian = obsidian
        self.word_counter = WordCounter(obsidian)
        self.remote_sync = remote_sync

    def _sync_remote(self) -> bool:
        """Sync blocking state to remote DNS server.

        Returns:
            True if sync succeeded or was disabled, False on failure.
        """
        if not self.remote_sync or not self.remote_sync.enabled:
            return True

        # When unblocked, sync empty list to remote; when blocked, sync full list
        if self.state.is_blocked:
            success, message = self.remote_sync.sync(self.config.blocked_sites)
        else:
            success, message = self.remote_sync.sync([])  # Unblock all on remote

        if not success:
            logger.error(f"Remote sync failed: {message}")
        return success

    def check_all_conditions(self) -> tuple[bool, list[tuple[str, bool, str]]]:
        """Check all conditions and return results.

        Returns:
            Tuple of (any_met, list of (condition_name, met, description))
        """
        conditions = self.config.conditions
        results: list[tuple[str, bool, str]] = []
        any_met = False

        for name, condition_config in conditions.items():
            condition_type = condition_config.get("type", "checkbox")

            if condition_type == "linked_wordcount":
                met, description, _ = self.word_counter.check_wordcount_condition(condition_config)
            else:
                met, description = self.obsidian.check_condition(condition_config)

            results.append((name, met, description))
            if met:
                any_met = True

        return any_met, results

    def proof_of_work_unlock(self) -> tuple[bool, str]:
        """Attempt proof-of-work unlock.

        Returns:
            Tuple of (success, message)
        """
        # Check if already unlocked
        if not self.state.is_blocked:
            remaining = self.state.unlock_remaining_formatted
            return True, f"Already unlocked. {remaining} remaining."

        # Check conditions
        any_met, results = self.check_all_conditions()

        # Build status message
        status_lines = ["Condition check results:"]
        for name, met, description in results:
            status = "PASS" if met else "FAIL"
            status_lines.append(f"  [{status}] {name}: {description}")

        if any_met:
            # Unlock!
            duration = self.config.unlock_settings.get("proof_of_work_duration", 7200)
            self.state.set_unlocked(duration)
            self.state.mark_unlocked_via_conditions()  # Prevent auto re-unlock after expiry
            self.hosts.unblock_sites()
            self._sync_remote()

            hours = duration // 3600
            minutes = (duration % 3600) // 60
            time_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

            status_lines.append(f"\nUnlocked for {time_str}!")
            return True, "\n".join(status_lines)
        else:
            status_lines.append("\nNo conditions met. Sites remain blocked.")
            return False, "\n".join(status_lines)

    def emergency_unlock(self, interactive: bool = True) -> tuple[bool, str]:
        """Attempt emergency unlock with shame prompt.

        Args:
            interactive: If True, show countdown and require confirmation.

        Returns:
            Tuple of (success, message)
        """
        settings = self.config.unlock_settings
        max_per_day = settings.get("emergency_max_per_day", 3)
        initial_wait = settings.get("emergency_initial_wait", 30)
        multiplier = settings.get("emergency_wait_multiplier", 2)
        duration = settings.get("emergency_duration", 300)

        # Check if emergency unlocks available
        if not self.state.can_emergency_unlock(max_per_day):
            return False, f"No emergency unlocks remaining today (used {max_per_day}/{max_per_day})."

        # Calculate wait time
        wait_time = self.state.get_next_emergency_wait(initial_wait, multiplier)
        count = self.state.emergency_count + 1

        if interactive:
            # Show shame prompt
            import random
            shame = random.choice(SHAME_PROMPTS)
            print(f"\n{shame}")
            print(f"\nThis is emergency unlock #{count} of {max_per_day}.")
            print(f"You must wait {wait_time} seconds to continue.\n")

            # Countdown
            for remaining in range(wait_time, 0, -1):
                sys.stdout.write(f"\rWaiting... {remaining} seconds remaining   ")
                sys.stdout.flush()
                time.sleep(1)
            print("\n")

            # Require confirmation
            print(f"Type '{CONFIRMATION_PHRASE}' to unlock:")
            try:
                response = input("> ").strip()
            except (KeyboardInterrupt, EOFError):
                return False, "\nEmergency unlock cancelled."

            if response != CONFIRMATION_PHRASE:
                return False, "Incorrect confirmation. Emergency unlock cancelled."

        # Record the emergency unlock
        self.state.record_emergency_unlock(wait_time)

        # Unlock for the emergency duration
        self.state.set_unlocked(duration)
        self.hosts.unblock_sites()
        self._sync_remote()

        minutes = duration // 60
        remaining_unlocks = max_per_day - count

        return True, f"Emergency unlock activated for {minutes} minutes. {remaining_unlocks} emergency unlocks remaining today."

    def force_block(self) -> str:
        """Force sites to be blocked immediately."""
        self.state.force_block()
        self.hosts.block_sites(self.config.blocked_sites)
        self._sync_remote()
        return "Sites are now blocked."

    def sync_blocking_state(self) -> None:
        """Sync hosts file and remote DNS with current state."""
        should_block = self.state.is_blocked
        self.hosts.sync_with_config(self.config.blocked_sites, should_block)
        self._sync_remote()

    def get_status(self) -> dict[str, Any]:
        """Get current status."""
        status = self.state.get_status()

        # Add condition status
        _, conditions = self.check_all_conditions()
        status["conditions"] = [
            {"name": name, "met": met, "description": desc}
            for name, met, desc in conditions
        ]

        # Add emergency unlock info
        settings = self.config.unlock_settings
        max_per_day = settings.get("emergency_max_per_day", 3)
        status["emergency_remaining"] = max_per_day - status["emergency_count"]

        return status


def get_unlock_manager(
    config: Config,
    state: State,
    hosts: HostsManager,
    obsidian: ObsidianParser,
    remote_sync: RemoteSyncManager | None = None,
) -> UnlockManager:
    """Get an UnlockManager instance."""
    return UnlockManager(config, state, hosts, obsidian, remote_sync)
