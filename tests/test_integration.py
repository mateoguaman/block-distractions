"""Integration tests for unlock/block behavior across components.

These tests verify the full flow of blocking and unlocking, particularly
focusing on the reported bugs:

1. "Sometimes it unlocks before it should" - potentially related to earliest_time
2. "Once it unlocks, it stays unlocked for the rest of the day" - auto-unlock re-triggering
"""

import json
import time
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestFullUnlockExpiryCycle:
    """Test the complete unlock -> expiry -> re-block cycle."""

    def test_unlock_expires_and_blocks(self, temp_state_file, temp_hosts_file):
        """Full cycle: unlock -> wait -> expire -> blocked again."""
        from lib.state import State
        from lib.hosts import HostsManager
        from lib.config import Config

        # Setup
        state = State(state_path=temp_state_file)
        hosts = HostsManager(hosts_path=temp_hosts_file)

        # Initially blocked
        assert state.is_blocked is True

        # Unlock for 2 seconds
        state.set_unlocked(2)
        assert state.is_blocked is False

        # Wait for expiry
        time.sleep(2.5)

        # Should be blocked again
        assert state.is_blocked is True

        # State file should reflect blocked status
        saved = json.loads(temp_state_file.read_text())
        assert saved["blocked"] is True
        assert saved["unlocked_until"] == 0

    def test_external_state_modification(self, temp_state_file):
        """State changes from CLI should be picked up by daemon."""
        from lib.state import State

        # Daemon creates state
        daemon_state = State(state_path=temp_state_file)
        assert daemon_state.is_blocked is True

        # CLI modifies state file directly
        cli_state = State(state_path=temp_state_file)
        cli_state.set_unlocked(3600)
        cli_state.save()

        # Daemon reloads state
        daemon_state.load()
        assert daemon_state.is_blocked is False
        assert daemon_state.unlocked_until > time.time()


class TestObsidianConditionChecking:
    """Test Obsidian condition checking integration."""

    def test_checkbox_condition_parsing(self, temp_vault):
        """Checkbox conditions should be parsed correctly."""
        from lib.obsidian import ObsidianParser

        # Create today's daily note
        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("""# Daily Note

## Tasks
- [x] Workout
- [ ] Reading
- [x] Writing
""")

        parser = ObsidianParser(temp_vault, "Daily/{date}.md")

        # Workout checkbox should be detected as checked
        met, desc = parser.check_condition({
            "type": "checkbox",
            "pattern": "- [x] Workout"
        })
        assert met is True

        # Reading checkbox should be detected as not checked
        met, desc = parser.check_condition({
            "type": "checkbox",
            "pattern": "- [x] Reading"
        })
        assert met is False

    def test_daily_note_not_found(self, temp_vault):
        """Should handle missing daily note gracefully."""
        from lib.obsidian import ObsidianParser

        parser = ObsidianParser(temp_vault, "Daily/{date}.md")

        # No note exists for today
        met, desc = parser.check_condition({
            "type": "checkbox",
            "pattern": "- [x] Workout"
        })

        assert met is False
        assert "not found" in desc.lower()


class TestAutoUnlockIntegration:
    """Integration tests for auto-unlock behavior."""

    @freeze_time("2026-01-06 18:00:00")
    def test_full_auto_unlock_flow(self, temp_state_file, temp_vault, mock_config):
        """Test complete auto-unlock flow with real state and obsidian."""
        from lib.state import State
        from lib.obsidian import ObsidianParser
        from lib.hosts import HostsManager
        from lib.unlock import UnlockManager

        # Create today's daily note with checkbox checked
        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("- [x] Workout")

        state = State(state_path=temp_state_file)
        parser = ObsidianParser(temp_vault, "Daily/{date}.md")

        mock_hosts = MagicMock()
        mock_remote = MagicMock(enabled=False)

        manager = UnlockManager(mock_config, state, mock_hosts, parser, mock_remote)

        # Verify condition is met
        any_met, results = manager.check_all_conditions()
        assert any_met is True

        # Proof of work unlock should succeed
        success, message = manager.proof_of_work_unlock()
        assert success is True
        assert state.is_blocked is False


class TestMultipleUnlocksPerDay:
    """Test behavior when multiple unlocks happen in one day."""

    def test_emergency_unlock_limit_enforced(self, temp_state_file, mock_config):
        """Emergency unlocks should be limited per day."""
        from lib.state import State
        from lib.unlock import UnlockManager

        state = State(state_path=temp_state_file)
        mock_hosts = MagicMock()
        mock_obsidian = MagicMock()
        mock_remote = MagicMock(enabled=False)
        mock_config.unlock_settings["emergency_max_per_day"] = 3

        manager = UnlockManager(mock_config, state, mock_hosts, mock_obsidian, mock_remote)

        # Use all emergency unlocks
        for i in range(3):
            state.force_block()  # Re-block between unlocks
            success, _ = manager.emergency_unlock(interactive=False)
            assert success is True

        # Fourth attempt should fail
        state.force_block()
        success, message = manager.emergency_unlock(interactive=False)
        assert success is False
        assert "No emergency unlocks remaining" in message

    def test_proof_of_work_unlimited_but_conditions_based(
        self, temp_state_file, temp_vault, mock_config
    ):
        """Proof-of-work unlocks are unlimited but require conditions."""
        from lib.state import State
        from lib.obsidian import ObsidianParser
        from lib.unlock import UnlockManager

        # Create daily note with condition met
        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("- [x] Workout")

        state = State(state_path=temp_state_file)
        parser = ObsidianParser(temp_vault, "Daily/{date}.md")
        mock_hosts = MagicMock()
        mock_remote = MagicMock(enabled=False)

        manager = UnlockManager(mock_config, state, mock_hosts, parser, mock_remote)

        # Multiple proof-of-work unlocks should work
        for i in range(5):
            state.force_block()
            success, _ = manager.proof_of_work_unlock()
            assert success is True, f"Unlock {i+1} should succeed"


class TestStateConsistency:
    """Test state consistency across operations."""

    def test_state_persists_across_reloads(self, temp_state_file):
        """State changes should persist when reloaded."""
        from lib.state import State

        # First instance sets unlock
        state1 = State(state_path=temp_state_file)
        state1.set_unlocked(3600)
        unlock_time = state1.unlocked_until

        # Second instance should see same state
        state2 = State(state_path=temp_state_file)
        assert state2.is_blocked is False
        assert state2.unlocked_until == unlock_time

    def test_emergency_count_persists(self, temp_state_file):
        """Emergency unlock count should persist."""
        from lib.state import State

        state1 = State(state_path=temp_state_file)
        state1.record_emergency_unlock(30)
        state1.record_emergency_unlock(60)

        state2 = State(state_path=temp_state_file)
        assert state2.emergency_count == 2

    def test_day_reset_clears_emergency_count(self, temp_state_file):
        """Emergency count should reset on new day."""
        from lib.state import State
        from datetime import timedelta

        # Create state from yesterday
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        data = {
            "date": yesterday,
            "tz": "local",
            "blocked": True,
            "unlocked_until": 0,
            "emergency_count": 3,
            "last_emergency_wait": 120,
        }
        temp_state_file.write_text(json.dumps(data))

        # Load state - should reset
        state = State(state_path=temp_state_file)
        assert state.emergency_count == 0
        assert state._state["date"] == date.today().isoformat()


class TestBugScenarios:
    """Tests that reproduce and verify reported bugs."""

    def test_scenario_early_morning_unlock(self, temp_state_file, temp_vault, mock_config):
        """
        Scenario: User reports unlock at 11:22 AM despite earliest_time=17:00.

        Possible causes:
        1. Timezone mismatch between daemon and config
        2. Direct proof-of-work unlock (not auto-unlock) - doesn't respect earliest_time
        3. Bug in earliest_time check
        """
        from lib.state import State
        from lib.obsidian import ObsidianParser
        from lib.unlock import UnlockManager

        # Setup daily note with condition met
        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("- [x] Workout")

        state = State(state_path=temp_state_file)
        parser = ObsidianParser(temp_vault, "Daily/{date}.md")
        mock_hosts = MagicMock()
        mock_remote = MagicMock(enabled=False)

        manager = UnlockManager(mock_config, state, mock_hosts, parser, mock_remote)

        # NOTE: proof_of_work_unlock does NOT check earliest_time
        # Only auto-unlock in daemon checks earliest_time
        # This is expected behavior but may surprise users
        success, _ = manager.proof_of_work_unlock()
        assert success is True, "Manual unlock should work regardless of time"

    def test_scenario_permanent_unlock_fixed(self, temp_state_file, temp_vault, mock_config):
        """
        Scenario: Once unlocked, should NOT stay unlocked for rest of day (FIXED).

        The fix uses unlocked_via_conditions_today flag:
        1. First unlock sets the flag
        2. After unlock expires, flag remains True
        3. Auto-unlock checks flag and skips re-unlock

        NOTE: This test does NOT use freezegun because time.sleep() needs real time
        to pass for unlock expiry to work correctly.
        """
        from lib.state import State
        from lib.obsidian import ObsidianParser
        from lib.unlock import UnlockManager
        from lib.daemon import BlockDaemon

        # Setup daily note
        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("- [x] Workout")

        # Use a time that's definitely after 17:00 for auto_unlock
        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "00:00",  # Always after earliest_time
            "check_interval": 300,
        }

        # Simulate multiple daemon check cycles
        unlock_count = 0

        with patch("lib.daemon.get_config", return_value=mock_config), \
             patch("lib.daemon.get_state") as mock_get_state, \
             patch("lib.daemon.get_hosts_manager") as mock_get_hosts, \
             patch("lib.daemon.get_obsidian_parser") as mock_get_obsidian, \
             patch("lib.daemon.get_remote_sync_manager") as mock_get_remote_sync, \
             patch("lib.daemon.get_experiment_logger"):

            state = State(state_path=temp_state_file)
            mock_get_state.return_value = state

            mock_hosts = MagicMock()
            mock_hosts.is_blocking_active.return_value = True
            mock_get_hosts.return_value = mock_hosts

            mock_get_obsidian.return_value = ObsidianParser(temp_vault, "Daily/{date}.md")
            mock_get_remote_sync.return_value = MagicMock(enabled=False)

            daemon = BlockDaemon()

            # Check 1: Should auto-unlock
            should_unlock_1, _ = daemon.evaluate_auto_unlock()
            if should_unlock_1:
                unlock_count += 1
                state.set_unlocked(1)  # Very short unlock for test
                state.mark_unlocked_via_conditions()  # THE FIX

            assert unlock_count == 1, "First check should unlock"
            assert state.unlocked_via_conditions_today is True, "Flag should be set"

            # Wait for expiry
            time.sleep(1.5)
            assert state.is_blocked is True, "Unlock should have expired"
            assert state.unlocked_via_conditions_today is True, "Flag should persist"

            # Check 2: Should NOT auto-unlock again (FIXED)
            should_unlock_2, info_2 = daemon.evaluate_auto_unlock()
            if should_unlock_2:
                unlock_count += 1

            # FIXED: Should only have 1 unlock
            assert unlock_count == 1, "FIXED: No re-unlock after expiry"
            assert info_2["unlocked_via_conditions_today"] is True


class TestConfigurationEdgeCases:
    """Test edge cases in configuration."""

    def test_zero_unlock_duration(self, temp_state_file, temp_vault, mock_config):
        """Zero duration should effectively not unlock."""
        from lib.state import State
        from lib.obsidian import ObsidianParser
        from lib.unlock import UnlockManager

        # Setup
        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("- [x] Workout")

        state = State(state_path=temp_state_file)
        parser = ObsidianParser(temp_vault, "Daily/{date}.md")
        mock_hosts = MagicMock()
        mock_remote = MagicMock(enabled=False)
        mock_config.unlock_settings["proof_of_work_duration"] = 0

        manager = UnlockManager(mock_config, state, mock_hosts, parser, mock_remote)
        manager.proof_of_work_unlock()

        # Should be immediately blocked
        assert state.is_blocked is True

    def test_invalid_earliest_time_format(self, temp_state_file, mock_config):
        """Invalid earliest_time should be handled gracefully."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "invalid",
            "check_interval": 300,
        }

        with patch("lib.daemon.get_config", return_value=mock_config), \
             patch("lib.daemon.get_state") as mock_get_state, \
             patch("lib.daemon.get_hosts_manager") as mock_get_hosts, \
             patch("lib.daemon.get_obsidian_parser") as mock_get_obsidian, \
             patch("lib.daemon.get_remote_sync_manager") as mock_get_remote_sync, \
             patch("lib.daemon.get_experiment_logger"):

            state = State(state_path=temp_state_file)
            mock_get_state.return_value = state
            mock_get_hosts.return_value = MagicMock()
            mock_get_obsidian.return_value = MagicMock()
            mock_get_remote_sync.return_value = MagicMock(enabled=False)

            daemon = BlockDaemon()
            should_unlock, info = daemon.evaluate_auto_unlock()

            # Should not crash, should not unlock
            assert should_unlock is False
            assert "earliest_parse_error" in info
