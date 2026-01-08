"""Tests for lib/daemon.py - Background daemon and auto-unlock logic."""

import json
import time
from datetime import datetime, date
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from contextlib import contextmanager

import pytest
from freezegun import freeze_time

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


@contextmanager
def mock_condition_registry(return_value=(False, "Not checked")):
    """Context manager to mock the condition registry for daemon tests.

    Args:
        return_value: The value to return from condition.check()
    """
    mock_condition = MagicMock()
    mock_condition.check.return_value = return_value
    with patch("lib.unlock.ConditionRegistry.create", return_value=mock_condition):
        yield mock_condition


class TestEvaluateAutoUnlock:
    """Tests for evaluate_auto_unlock method - the core auto-unlock decision logic."""

    @freeze_time("2026-01-06 10:00:00")
    def test_disabled_when_auto_unlock_disabled(self, temp_state_file, mock_config):
        """Should not auto-unlock when auto_unlock.enabled is False."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {"enabled": False, "earliest_time": "17:00"}

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

            assert should_unlock is False
            assert info["enabled"] is False

    @freeze_time("2026-01-06 10:00:00")
    def test_blocked_before_earliest_time(self, temp_state_file, mock_config):
        """Should not auto-unlock before earliest_time."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "17:00",
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

            assert should_unlock is False
            assert info["earliest_passed"] is False
            assert info["earliest_time"] == "17:00"

    @freeze_time("2026-01-06 18:00:00")
    def test_allowed_after_earliest_time(self, temp_state_file, mock_config):
        """Should evaluate conditions after earliest_time."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "17:00",
            "check_interval": 300,
        }

        with mock_condition_registry(return_value=(False, "Not checked")), \
             patch("lib.daemon.get_config", return_value=mock_config), \
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

            # Should have passed earliest time check
            assert info["earliest_passed"] is True
            # But no conditions met
            assert info["any_conditions_met"] is False
            assert should_unlock is False

    @freeze_time("2026-01-06 18:00:00")
    def test_skips_when_already_unlocked(self, temp_state_file, mock_config):
        """Should not auto-unlock when already unlocked."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "17:00",
            "check_interval": 300,
        }

        with patch("lib.daemon.get_config", return_value=mock_config), \
             patch("lib.daemon.get_state") as mock_get_state, \
             patch("lib.daemon.get_hosts_manager") as mock_get_hosts, \
             patch("lib.daemon.get_obsidian_parser") as mock_get_obsidian, \
             patch("lib.daemon.get_remote_sync_manager") as mock_get_remote_sync, \
             patch("lib.daemon.get_experiment_logger"):

            state = State(state_path=temp_state_file)
            state.set_unlocked(3600)  # Already unlocked
            mock_get_state.return_value = state
            mock_get_hosts.return_value = MagicMock()
            mock_get_obsidian.return_value = MagicMock()
            mock_get_remote_sync.return_value = MagicMock(enabled=False)

            daemon = BlockDaemon()
            should_unlock, info = daemon.evaluate_auto_unlock()

            assert should_unlock is False
            assert info["blocked"] is False

    @freeze_time("2026-01-06 18:00:00")
    def test_auto_unlocks_when_conditions_met(self, temp_state_file, mock_config):
        """Should auto-unlock when conditions are met after earliest_time."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "17:00",
            "check_interval": 300,
        }

        with mock_condition_registry(return_value=(True, "Workout checked")), \
             patch("lib.daemon.get_config", return_value=mock_config), \
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

            assert should_unlock is True
            assert info["earliest_passed"] is True
            assert info["blocked"] is True
            assert info["any_conditions_met"] is True


class TestAutoUnlockBug:
    """Tests for the auto-unlock bug fix (previously re-unlocked repeatedly)."""

    @freeze_time("2026-01-06 18:00:00")
    def test_fix_no_re_unlock_after_expiry(self, temp_state_file, mock_config):
        """
        FIXED: Auto-unlock should NOT fire again after previous unlock expires.

        The fix uses unlocked_via_conditions_today flag:
        1. Conditions met at 18:00 -> auto-unlock for 2 hours
        2. Flag set: unlocked_via_conditions_today = True
        3. At 20:01 -> unlock expired, state.is_blocked = True
        4. Daemon checks flag -> already unlocked today -> NO re-unlock
        """
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "17:00",
            "check_interval": 300,
        }
        mock_config.unlock_settings["proof_of_work_duration"] = 7200  # 2 hours

        with mock_condition_registry(return_value=(True, "Workout checked")), \
             patch("lib.daemon.get_config", return_value=mock_config), \
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
            mock_get_obsidian.return_value = MagicMock()
            mock_get_remote_sync.return_value = MagicMock(enabled=False)

            daemon = BlockDaemon()

            # First evaluation - should unlock
            should_unlock_1, info_1 = daemon.evaluate_auto_unlock()
            assert should_unlock_1 is True
            assert state.is_blocked is True  # Not unlocked yet, just evaluated

            # Simulate daemon unlocking (this happens in run_check)
            state.set_unlocked(mock_config.unlock_settings["proof_of_work_duration"])
            state.mark_unlocked_via_conditions()  # THE FIX: mark the flag
            assert state.is_blocked is False
            assert state.unlocked_via_conditions_today is True

            # Second evaluation while still unlocked - should NOT unlock
            should_unlock_2, info_2 = daemon.evaluate_auto_unlock()
            assert should_unlock_2 is False
            # Returns early due to flag, so blocked field may not be set
            assert info_2["unlocked_via_conditions_today"] is True

            # Now simulate unlock expiry
            state._state["unlocked_until"] = time.time() - 100  # Expired
            state._state["blocked"] = False  # But blocked field wasn't updated
            state.save()

            # Third evaluation after expiry - NOW FIXED
            # Flag is still True, so auto-unlock should NOT fire
            should_unlock_3, info_3 = daemon.evaluate_auto_unlock()

            # FIXED: Should NOT unlock because flag is set
            assert should_unlock_3 is False, "Fixed: flag prevents re-unlock"
            assert info_3["unlocked_via_conditions_today"] is True

    @freeze_time("2026-01-06 18:00:00")
    def test_flag_checked_before_conditions(self, temp_state_file, mock_config):
        """The unlocked_via_conditions_today flag should be checked early."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "17:00",
            "check_interval": 300,
        }

        with mock_condition_registry(return_value=(True, "Workout checked")), \
             patch("lib.daemon.get_config", return_value=mock_config), \
             patch("lib.daemon.get_state") as mock_get_state, \
             patch("lib.daemon.get_hosts_manager") as mock_get_hosts, \
             patch("lib.daemon.get_obsidian_parser") as mock_get_obsidian, \
             patch("lib.daemon.get_remote_sync_manager") as mock_get_remote_sync, \
             patch("lib.daemon.get_experiment_logger"):

            state = State(state_path=temp_state_file)
            state.mark_unlocked_via_conditions()  # Set flag before test
            mock_get_state.return_value = state

            mock_hosts = MagicMock()
            mock_hosts.is_blocking_active.return_value = True
            mock_get_hosts.return_value = mock_hosts
            mock_get_obsidian.return_value = MagicMock()
            mock_get_remote_sync.return_value = MagicMock(enabled=False)

            daemon = BlockDaemon()

            # Should NOT unlock because flag is already set
            should_unlock, info = daemon.evaluate_auto_unlock()

            assert should_unlock is False
            assert info["unlocked_via_conditions_today"] is True
            # Conditions weren't even evaluated since flag short-circuits
            assert info["any_conditions_met"] is False

    @freeze_time("2026-01-06 18:00:00")
    def test_unlock_count_not_tracked(self, temp_state_file, mock_config):
        """
        Shows that proof-of-work unlocks are NOT tracked like emergency unlocks.

        Emergency unlocks have a counter that limits daily usage.
        Proof-of-work unlocks have no such limit - they can happen unlimited times.
        """
        from lib.state import State

        state = State(state_path=temp_state_file)

        # Set unlock multiple times
        state.set_unlocked(3600)
        state.force_block()
        state.set_unlocked(3600)
        state.force_block()
        state.set_unlocked(3600)
        state.force_block()

        # No tracking of how many times we've unlocked
        # Unlike emergency_count which tracks emergency unlocks
        assert state.emergency_count == 0  # Unchanged
        # There's no "proof_of_work_count" field


class TestEarliestTimeBug:
    """Tests for the earliest_time bypass bug."""

    @freeze_time("2026-01-06 11:00:00")
    def test_11am_before_5pm(self, temp_state_file, mock_config):
        """11:00 AM should be before 17:00 (5 PM)."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "17:00",
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

            assert should_unlock is False
            assert info["earliest_passed"] is False

    @freeze_time("2026-01-06 16:59:00")
    def test_one_minute_before_earliest(self, temp_state_file, mock_config):
        """16:59 should be before 17:00."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "17:00",
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

            assert should_unlock is False
            assert info["earliest_passed"] is False

    @freeze_time("2026-01-06 17:00:00")
    def test_exactly_at_earliest(self, temp_state_file, mock_config):
        """17:00 should pass earliest_time check for 17:00."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": True,
            "earliest_time": "17:00",
            "check_interval": 300,
        }

        with mock_condition_registry(return_value=(False, "Not checked")), \
             patch("lib.daemon.get_config", return_value=mock_config), \
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

            assert info["earliest_passed"] is True


class TestRunCheck:
    """Tests for run_check method."""

    @freeze_time("2026-01-06 18:00:00")
    def test_syncs_blocking_state_on_each_check(self, temp_state_file, mock_config):
        """run_check should sync blocking state on each iteration."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": False,  # Disable auto-unlock for this test
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

            mock_hosts = MagicMock()
            mock_hosts.is_blocking_active.return_value = True
            mock_get_hosts.return_value = mock_hosts

            mock_get_obsidian.return_value = MagicMock()
            mock_remote_sync = MagicMock(enabled=False)
            mock_get_remote_sync.return_value = mock_remote_sync

            daemon = BlockDaemon()
            daemon.run_check()

            # Should have synced state
            mock_hosts.sync_with_config.assert_called()

    @freeze_time("2026-01-06 18:00:00")
    def test_re_enables_blocking_when_state_is_blocked(self, temp_state_file, mock_config):
        """Should re-enable blocking when state says blocked but hosts not blocking."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        # Disable auto-unlock to focus on the re-blocking behavior
        mock_config.auto_unlock_settings = {
            "enabled": False,
            "check_interval": 300,
        }
        # Use only checkbox condition to avoid wordcount module complexity
        mock_config.conditions = {
            "workout": {
                "type": "checkbox",
                "pattern": "- [x] Workout",
            }
        }

        with mock_condition_registry(return_value=(False, "Not checked")), \
             patch("lib.daemon.get_config", return_value=mock_config), \
             patch("lib.daemon.get_state") as mock_get_state, \
             patch("lib.daemon.get_hosts_manager") as mock_get_hosts, \
             patch("lib.daemon.get_obsidian_parser") as mock_get_obsidian, \
             patch("lib.daemon.get_remote_sync_manager") as mock_get_remote_sync, \
             patch("lib.daemon.get_experiment_logger"):

            state = State(state_path=temp_state_file)
            # State says blocked (default)
            mock_get_state.return_value = state

            mock_hosts = MagicMock()
            # Hosts not blocking initially
            mock_hosts.is_blocking_active.return_value = False
            mock_get_hosts.return_value = mock_hosts

            mock_obsidian = MagicMock()
            mock_obsidian.get_today_note_path.return_value = Path("/tmp/fake.md")
            mock_get_obsidian.return_value = mock_obsidian

            mock_remote_sync = MagicMock(enabled=False)
            mock_get_remote_sync.return_value = mock_remote_sync

            daemon = BlockDaemon()
            daemon.run_check()

            # Should have re-enabled blocking because state.is_blocked and hosts not blocking
            mock_hosts.block_sites.assert_called_once_with(mock_config.blocked_sites)


class TestDaemonStateReload:
    """Tests for state reloading in daemon."""

    def test_reloads_state_on_each_check(self, temp_state_file, mock_config):
        """Daemon should reload state from file on each check to pick up CLI changes."""
        from lib.daemon import BlockDaemon
        from lib.state import State

        mock_config.auto_unlock_settings = {
            "enabled": False,
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

            mock_hosts = MagicMock()
            mock_hosts.is_blocking_active.return_value = True
            mock_get_hosts.return_value = mock_hosts
            mock_get_obsidian.return_value = MagicMock()
            mock_get_remote_sync.return_value = MagicMock(enabled=False)

            daemon = BlockDaemon()

            # Externally modify state file (simulating CLI)
            state_data = json.loads(temp_state_file.read_text())
            state_data["emergency_count"] = 5
            temp_state_file.write_text(json.dumps(state_data))

            # Run check - should reload state
            daemon.run_check()

            # Verify state was reloaded
            assert daemon.state.emergency_count == 5
