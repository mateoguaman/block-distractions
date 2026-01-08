"""Tests for lib/unlock.py - Unlock logic and condition checking."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.unlock import UnlockManager, SHAME_PROMPTS, CONFIRMATION_PHRASE


class TestUnlockManagerInit:
    """Tests for UnlockManager initialization."""

    def test_initializes_with_dependencies(
        self, mock_config, mock_state, mock_hosts, mock_obsidian, mock_remote_sync,
        patch_condition_registry
    ):
        """UnlockManager should initialize with all dependencies."""
        manager = UnlockManager(
            mock_config, mock_state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        assert manager.config == mock_config
        assert manager.state == mock_state
        assert manager.hosts == mock_hosts
        assert manager.obsidian == mock_obsidian
        assert manager.remote_sync == mock_remote_sync


class TestProofOfWorkUnlock:
    """Tests for proof_of_work_unlock method."""

    def test_returns_already_unlocked_if_not_blocked(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should return early if already unlocked."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        success, message = manager.proof_of_work_unlock()

        assert success is True
        assert "Already unlocked" in message
        # Should not call condition checks
        patch_condition_registry.check.assert_not_called()

    def test_unlocks_when_condition_met(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should unlock when at least one condition is met."""
        from lib.state import State

        state = State(state_path=temp_state_file)

        # Mock condition check to return True
        patch_condition_registry.check.return_value = (True, "Checkbox checked")

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        success, message = manager.proof_of_work_unlock()

        assert success is True
        assert "Unlocked for" in message
        assert state.is_blocked is False
        mock_hosts.unblock_sites.assert_called_once()

    def test_uses_configured_duration(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should use proof_of_work_duration from config."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        patch_condition_registry.check.return_value = (True, "Checked")
        mock_config.unlock_settings["proof_of_work_duration"] = 1800  # 30 minutes

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        before = time.time()
        manager.proof_of_work_unlock()
        after = time.time()

        # Should be unlocked for ~30 minutes
        assert state.unlocked_until >= before + 1800
        assert state.unlocked_until <= after + 1800

    def test_fails_when_no_conditions_met(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should fail when no conditions are met."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        patch_condition_registry.check.return_value = (False, "Not checked")

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        success, message = manager.proof_of_work_unlock()

        assert success is False
        assert "No conditions met" in message
        assert state.is_blocked is True
        mock_hosts.unblock_sites.assert_not_called()

    def test_syncs_remote_on_unlock(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should sync remote when unlocking."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        patch_condition_registry.check.return_value = (True, "Checked")
        mock_remote_sync.enabled = True

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )
        manager.proof_of_work_unlock()

        # Should sync with empty list (unblock all)
        mock_remote_sync.sync.assert_called_once_with([])


class TestEmergencyUnlock:
    """Tests for emergency_unlock method."""

    def test_fails_when_limit_reached(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should fail when daily limit is reached."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        # Use up all emergency unlocks
        state.record_emergency_unlock(30)
        state.record_emergency_unlock(60)
        state.record_emergency_unlock(120)

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        success, message = manager.emergency_unlock(interactive=False)

        assert success is False
        assert "No emergency unlocks remaining" in message

    def test_non_interactive_unlocks_immediately(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Non-interactive mode should unlock without prompts."""
        from lib.state import State

        state = State(state_path=temp_state_file)

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        success, message = manager.emergency_unlock(interactive=False)

        assert success is True
        assert state.is_blocked is False
        assert state.emergency_count == 1
        mock_hosts.unblock_sites.assert_called_once()

    def test_uses_emergency_duration(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should use emergency_duration from config (shorter than proof-of-work)."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        mock_config.unlock_settings["emergency_duration"] = 300  # 5 minutes

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        before = time.time()
        manager.emergency_unlock(interactive=False)
        after = time.time()

        # Should be unlocked for ~5 minutes, not 2 hours
        assert state.unlocked_until >= before + 300
        assert state.unlocked_until <= after + 300
        assert state.unlocked_until < before + 7200  # Less than proof-of-work

    def test_records_emergency_usage(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should record emergency unlock usage."""
        from lib.state import State

        state = State(state_path=temp_state_file)

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        manager.emergency_unlock(interactive=False)

        assert state.emergency_count == 1
        assert state.last_emergency_wait == 30  # initial_wait

    def test_escalates_wait_time(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Wait time should escalate with each use."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        mock_config.unlock_settings["emergency_initial_wait"] = 30
        mock_config.unlock_settings["emergency_wait_multiplier"] = 2

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        # First unlock
        manager.emergency_unlock(interactive=False)
        assert state.last_emergency_wait == 30

        # Second unlock - state persists wait time
        manager.emergency_unlock(interactive=False)
        assert state.last_emergency_wait == 60

        # Third unlock
        manager.emergency_unlock(interactive=False)
        assert state.last_emergency_wait == 120


class TestForceBlock:
    """Tests for force_block method."""

    def test_force_block_blocks_sites(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """force_block should enable blocking."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)  # Start unlocked

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        message = manager.force_block()

        assert state.is_blocked is True
        mock_hosts.block_sites.assert_called_once_with(mock_config.blocked_sites)
        assert "blocked" in message.lower()

    def test_force_block_syncs_remote(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """force_block should sync blocked sites to remote."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        mock_remote_sync.enabled = True

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )
        manager.force_block()

        # Should sync with blocked sites list
        mock_remote_sync.sync.assert_called_once_with(mock_config.blocked_sites)


class TestSyncBlockingState:
    """Tests for sync_blocking_state method."""

    def test_syncs_blocked_state(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should sync hosts and remote when blocked."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        # Blocked by default

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )
        manager.sync_blocking_state()

        mock_hosts.sync_with_config.assert_called_once_with(
            mock_config.blocked_sites, True
        )

    def test_syncs_unblocked_state(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should sync unblocked state to hosts and remote."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )
        manager.sync_blocking_state()

        mock_hosts.sync_with_config.assert_called_once_with(
            mock_config.blocked_sites, False
        )


class TestCheckAllConditions:
    """Tests for check_all_conditions method."""

    def test_returns_all_condition_results(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Should return results for all conditions."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        mock_config.conditions = {
            "workout": {"type": "checkbox", "pattern": "- [x] Workout"},
            "reading": {"type": "checkbox", "pattern": "- [x] Reading"},
        }
        # First condition met, second not
        patch_condition_registry.check.side_effect = [
            (True, "Workout checked"),
            (False, "Reading not checked"),
        ]

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )
        any_met, results = manager.check_all_conditions()

        assert any_met is True
        assert len(results) == 2
        assert results[0] == ("workout", True, "Workout checked")
        assert results[1] == ("reading", False, "Reading not checked")

    def test_any_met_false_when_all_fail(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """any_met should be False when no conditions are met."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        patch_condition_registry.check.return_value = (False, "Not checked")

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )
        any_met, results = manager.check_all_conditions()

        assert any_met is False


class TestGetStatus:
    """Tests for get_status method."""

    def test_includes_all_status_fields(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """get_status should include all required fields."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        patch_condition_registry.check.return_value = (False, "Not checked")

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )
        status = manager.get_status()

        assert "blocked" in status
        assert "unlocked_until" in status
        assert "unlock_remaining" in status
        assert "emergency_count" in status
        assert "emergency_remaining" in status
        assert "conditions" in status

    def test_conditions_list_format(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Conditions should be in list format with name, met, description."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        patch_condition_registry.check.return_value = (True, "Checked")

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )
        status = manager.get_status()

        assert len(status["conditions"]) > 0
        cond = status["conditions"][0]
        assert "name" in cond
        assert "met" in cond
        assert "description" in cond


class TestUnlockExpiryBehavior:
    """Tests for unlock expiry behavior - the core bug we're investigating."""

    def test_state_becomes_blocked_after_expiry(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """After unlock expires, state should report blocked."""
        from lib.state import State

        state = State(state_path=temp_state_file)

        # Set a very short unlock
        state.set_unlocked(1)  # 1 second
        assert state.is_blocked is False

        # Wait for expiry
        time.sleep(1.5)

        # Should now be blocked
        assert state.is_blocked is True

    def test_sync_detects_expired_unlock(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """sync_blocking_state should detect expired unlock."""
        from lib.state import State

        state = State(state_path=temp_state_file)

        # Set up short unlock
        state.set_unlocked(1)
        assert state.is_blocked is False

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        # Wait for expiry
        time.sleep(1.5)

        # Sync should now detect blocked state
        manager.sync_blocking_state()

        # Should have synced blocked state
        mock_hosts.sync_with_config.assert_called_once_with(
            mock_config.blocked_sites, True  # should_block=True
        )

    def test_repeated_unlocks_possible(
        self, mock_config, mock_hosts, mock_obsidian, mock_remote_sync, temp_state_file,
        patch_condition_registry
    ):
        """Multiple unlocks in a day should work (current behavior)."""
        from lib.state import State

        state = State(state_path=temp_state_file)
        patch_condition_registry.check.return_value = (True, "Checked")

        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )

        # First unlock
        success1, _ = manager.proof_of_work_unlock()
        assert success1 is True
        first_unlock = state.unlocked_until

        # Force back to blocked
        state.force_block()
        assert state.is_blocked is True

        # Second unlock - should work
        success2, _ = manager.proof_of_work_unlock()
        assert success2 is True
        second_unlock = state.unlocked_until

        # Both unlocks should have succeeded
        assert first_unlock > 0
        assert second_unlock > 0
