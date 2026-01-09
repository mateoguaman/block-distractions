"""Tests for lib/state.py - State management and unlock tracking."""

import json
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.state import State, DEFAULT_STATE_PATH
from tests.conftest import create_state_data


class TestStateInitialization:
    """Tests for State class initialization."""

    def test_creates_empty_state_if_file_missing(self, temp_state_file):
        """State should initialize with defaults if no state file exists."""
        temp_state_file.unlink()
        state = State(state_path=temp_state_file)

        assert state.is_blocked is True
        assert state.unlocked_until == 0
        assert state.emergency_count == 0

    def test_loads_existing_state(self, temp_state_file):
        """State should load existing data from file."""
        data = create_state_data(blocked=False, unlocked_until=time.time() + 3600)
        temp_state_file.write_text(json.dumps(data))

        state = State(state_path=temp_state_file)

        assert state.is_blocked is False
        assert state.unlocked_until > time.time()

    def test_resets_on_new_day(self, temp_state_file):
        """State should reset when date changes."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        data = create_state_data(
            blocked=False,
            unlocked_until=time.time() + 3600,
            emergency_count=2,
            date_str=yesterday,
        )
        temp_state_file.write_text(json.dumps(data))

        state = State(state_path=temp_state_file)

        # Should reset to blocked with zero counts
        assert state.is_blocked is True
        assert state.emergency_count == 0
        assert state._state["date"] == date.today().isoformat()


class TestIsBlocked:
    """Tests for the is_blocked property - core blocking logic."""

    def test_blocked_when_no_unlock_set(self, temp_state_file):
        """Should be blocked when unlocked_until is 0."""
        data = create_state_data(blocked=True, unlocked_until=0)
        temp_state_file.write_text(json.dumps(data))

        state = State(state_path=temp_state_file)

        assert state.is_blocked is True

    def test_unblocked_when_unlock_active(self, temp_state_file):
        """Should be unblocked when unlocked_until is in the future."""
        future_time = time.time() + 3600
        data = create_state_data(blocked=False, unlocked_until=future_time)
        temp_state_file.write_text(json.dumps(data))

        state = State(state_path=temp_state_file)

        assert state.is_blocked is False

    def test_blocked_when_unlock_expired(self, temp_state_file):
        """Should be blocked when unlocked_until is in the past."""
        past_time = time.time() - 100
        data = create_state_data(blocked=False, unlocked_until=past_time)
        temp_state_file.write_text(json.dumps(data))

        state = State(state_path=temp_state_file)

        # Reading is_blocked should detect expiry and reset
        assert state.is_blocked is True

        # Should persist the blocked state
        saved_data = json.loads(temp_state_file.read_text())
        assert saved_data["blocked"] is True
        assert saved_data["unlocked_until"] == 0

    def test_unlock_expiry_persists_immediately(self, temp_state_file):
        """When unlock expires, state should be saved immediately."""
        # Set up an unlock that expires in 1 second
        expire_time = time.time() + 1
        data = create_state_data(blocked=False, unlocked_until=expire_time)
        temp_state_file.write_text(json.dumps(data))

        state = State(state_path=temp_state_file)

        # Should still be unlocked
        assert state.is_blocked is False

        # Wait for expiry
        time.sleep(1.5)

        # Now should be blocked
        assert state.is_blocked is True

        # Verify file was updated
        saved_data = json.loads(temp_state_file.read_text())
        assert saved_data["blocked"] is True
        assert saved_data["unlocked_until"] == 0


class TestSetUnlocked:
    """Tests for set_unlocked method."""

    def test_sets_unlocked_duration(self, temp_state_file):
        """set_unlocked should set blocked=False and future unlocked_until."""
        state = State(state_path=temp_state_file)

        duration = 7200  # 2 hours
        before = time.time()
        state.set_unlocked(duration)
        after = time.time()

        assert state.is_blocked is False
        assert state.unlocked_until >= before + duration
        assert state.unlocked_until <= after + duration

    def test_set_unlocked_overwrites_existing_unlock(self, temp_state_file):
        """set_unlocked should overwrite any existing unlock."""
        # Set initial unlock for 1 hour
        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)
        first_unlock = state.unlocked_until

        # Set new unlock for 2 hours - should overwrite
        state.set_unlocked(7200)
        second_unlock = state.unlocked_until

        # New unlock should be later
        assert second_unlock > first_unlock
        # Should be approximately 2 hours from now
        assert abs(second_unlock - time.time() - 7200) < 5

    def test_set_unlocked_persists_to_file(self, temp_state_file):
        """set_unlocked should persist state to file."""
        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)

        # Read back from file
        saved_data = json.loads(temp_state_file.read_text())

        assert saved_data["blocked"] is False
        assert saved_data["unlocked_until"] > time.time()


class TestExtendUnlock:
    """Tests for extend_unlock method."""

    def test_extends_existing_unlock(self, temp_state_file):
        """extend_unlock should add time to existing unlock."""
        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)  # 1 hour
        original_until = state.unlocked_until

        state.extend_unlock(1800)  # Add 30 minutes

        # Should be extended
        assert state.unlocked_until == original_until + 1800

    def test_creates_new_unlock_if_expired(self, temp_state_file):
        """extend_unlock should create new unlock if previous expired."""
        state = State(state_path=temp_state_file)

        # Start with no unlock
        before = time.time()
        state.extend_unlock(3600)
        after = time.time()

        # Should be unlocked from now
        assert state.is_blocked is False
        assert state.unlocked_until >= before + 3600
        assert state.unlocked_until <= after + 3600


class TestEmergencyUnlock:
    """Tests for emergency unlock tracking."""

    def test_initial_emergency_count_is_zero(self, temp_state_file):
        """Emergency count should start at 0."""
        state = State(state_path=temp_state_file)
        assert state.emergency_count == 0

    def test_record_emergency_unlock_increments_count(self, temp_state_file):
        """record_emergency_unlock should increment the count."""
        state = State(state_path=temp_state_file)

        state.record_emergency_unlock(30)
        assert state.emergency_count == 1

        state.record_emergency_unlock(60)
        assert state.emergency_count == 2

    def test_can_emergency_unlock_respects_limit(self, temp_state_file):
        """can_emergency_unlock should respect daily limit."""
        state = State(state_path=temp_state_file)
        max_per_day = 3

        assert state.can_emergency_unlock(max_per_day) is True

        state.record_emergency_unlock(30)
        state.record_emergency_unlock(60)
        state.record_emergency_unlock(120)

        assert state.emergency_count == 3
        assert state.can_emergency_unlock(max_per_day) is False

    def test_get_next_emergency_wait_escalates(self, temp_state_file):
        """get_next_emergency_wait should escalate with each use."""
        state = State(state_path=temp_state_file)
        initial_wait = 30
        multiplier = 2

        # First time: 30s
        assert state.get_next_emergency_wait(initial_wait, multiplier) == 30

        state.record_emergency_unlock(30)
        # Second time: 60s
        assert state.get_next_emergency_wait(initial_wait, multiplier) == 60

        state.record_emergency_unlock(60)
        # Third time: 120s
        assert state.get_next_emergency_wait(initial_wait, multiplier) == 120


class TestForceBlock:
    """Tests for force_block method."""

    def test_force_block_clears_unlock(self, temp_state_file):
        """force_block should clear any active unlock."""
        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)

        assert state.is_blocked is False

        state.force_block()

        assert state.is_blocked is True
        assert state.unlocked_until == 0

    def test_force_block_persists(self, temp_state_file):
        """force_block should persist to file."""
        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)
        state.force_block()

        # Create new state instance to verify persistence
        state2 = State(state_path=temp_state_file)
        assert state2.is_blocked is True


class TestUnlockRemaining:
    """Tests for unlock time remaining calculations."""

    def test_unlock_remaining_seconds(self, temp_state_file):
        """unlock_remaining_seconds should return correct value."""
        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)

        remaining = state.unlock_remaining_seconds

        # Should be approximately 3600 seconds
        assert 3595 <= remaining <= 3600

    def test_unlock_remaining_zero_when_blocked(self, temp_state_file):
        """unlock_remaining_seconds should be 0 when blocked."""
        state = State(state_path=temp_state_file)

        assert state.unlock_remaining_seconds == 0

    def test_unlock_remaining_formatted(self, temp_state_file):
        """unlock_remaining_formatted should return proper format."""
        state = State(state_path=temp_state_file)

        # Test hours:minutes:seconds
        state.set_unlocked(3700)  # 1h 1m 40s
        formatted = state.unlock_remaining_formatted
        assert formatted.startswith("1:")  # 1:01:xx

        # Test minutes:seconds
        state.set_unlocked(300)  # 5 minutes
        formatted = state.unlock_remaining_formatted
        assert ":" in formatted


class TestDayReset:
    """Tests for daily state reset."""

    @freeze_time("2026-01-06 10:00:00")
    def test_resets_on_date_change(self, temp_state_file):
        """State should reset when the date changes."""
        # Create state from yesterday
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        data = create_state_data(
            blocked=False,
            unlocked_until=time.time() + 3600,
            emergency_count=2,
            date_str=yesterday,
        )
        temp_state_file.write_text(json.dumps(data))

        state = State(state_path=temp_state_file)

        # Should have reset
        assert state.is_blocked is True
        assert state.emergency_count == 0
        assert state._state["date"] == "2026-01-06"

    def test_does_not_reset_on_same_day(self, temp_state_file):
        """State should not reset on same day."""
        today = date.today().isoformat()
        data = create_state_data(
            blocked=False,
            unlocked_until=time.time() + 3600,
            emergency_count=2,
            date_str=today,
        )
        temp_state_file.write_text(json.dumps(data))

        state = State(state_path=temp_state_file)

        # Should NOT have reset
        assert state.is_blocked is False
        assert state.emergency_count == 2


class TestGetDebugSnapshot:
    """Tests for get_debug_snapshot method."""

    def test_includes_all_fields(self, temp_state_file):
        """get_debug_snapshot should include all state fields."""
        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)
        state.record_emergency_unlock(30)

        snapshot = state.get_debug_snapshot()

        assert "date" in snapshot
        assert "blocked" in snapshot
        assert "unlocked_until" in snapshot
        assert "emergency_count" in snapshot
        assert "is_blocked" in snapshot
        assert "unlock_remaining" in snapshot

    def test_snapshot_reflects_current_state(self, temp_state_file):
        """get_debug_snapshot should reflect current computed state."""
        state = State(state_path=temp_state_file)
        state.set_unlocked(3600)

        snapshot = state.get_debug_snapshot()

        assert snapshot["is_blocked"] is False
        assert snapshot["blocked"] is False  # Persisted value
        assert snapshot["unlocked_until"] > 0


class TestUnlockedViaConditionsToday:
    """Tests for the unlocked_via_conditions_today flag that prevents re-unlock."""

    def test_initially_false(self, temp_state_file):
        """unlocked_via_conditions_today should be False initially."""
        state = State(state_path=temp_state_file)
        assert state.unlocked_via_conditions_today is False

    def test_mark_unlocked_via_conditions(self, temp_state_file):
        """mark_unlocked_via_conditions should set the flag to True."""
        state = State(state_path=temp_state_file)
        state.mark_unlocked_via_conditions()
        assert state.unlocked_via_conditions_today is True

    def test_flag_persists_to_file(self, temp_state_file):
        """The flag should persist to the state file."""
        state = State(state_path=temp_state_file)
        state.mark_unlocked_via_conditions()

        # Load new state instance
        state2 = State(state_path=temp_state_file)
        assert state2.unlocked_via_conditions_today is True

    def test_flag_resets_on_new_day(self, temp_state_file):
        """The flag should reset when the day changes."""
        from datetime import timedelta

        # Create state from yesterday with flag set
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        data = {
            "date": yesterday,
            "tz": "local",
            "blocked": True,
            "unlocked_until": 0,
            "emergency_count": 0,
            "last_emergency_wait": 0,
            "unlocked_via_conditions_today": True,
        }
        temp_state_file.write_text(json.dumps(data))

        # Load state - should reset
        state = State(state_path=temp_state_file)
        assert state.unlocked_via_conditions_today is False

    def test_flag_survives_unlock_expiry(self, temp_state_file):
        """The flag should remain True even after unlock expires."""
        state = State(state_path=temp_state_file)

        # Mark as unlocked via conditions
        state.mark_unlocked_via_conditions()
        state.set_unlocked(1)  # Very short unlock

        # Wait for expiry
        time.sleep(1.5)

        # State should be blocked but flag should still be True
        assert state.is_blocked is True
        assert state.unlocked_via_conditions_today is True


class TestRemoteStateLoadFailure:
    """Tests for handling remote state load failures.

    These tests verify the fix for a bug where network failures during
    remote state load would cause a state reset that overwrote valid
    remote data when the network recovered.
    """

    def test_save_blocked_when_load_failed(self):
        """save_state should be blocked when load_state failed."""
        from lib.state import RemoteStateStore

        store = RemoteStateStore({
            "enabled": True,
            "host": "example.com",
            "user": "test",
            "state_path": "/etc/block/state.json",
        })

        # Simulate failed load
        store._load_succeeded = False

        # Try to save - should return False and not raise
        result = store.save_state({"date": "2026-01-08", "emergency_count": 0})
        assert result is False

    def test_save_allowed_when_load_succeeded(self):
        """save_state should proceed when load_state succeeded."""
        from lib.state import RemoteStateStore

        store = RemoteStateStore({
            "enabled": True,
            "host": "example.com",
            "user": "test",
            "state_path": "/etc/block/state.json",
        })

        # Simulate successful load
        store._load_succeeded = True

        # Mock the actual SSH calls to avoid real network access
        with patch.object(store, '_run_with_retry') as mock_retry:
            mock_retry.return_value = (True, "", "")
            result = store.save_state({"date": "2026-01-08", "emergency_count": 1})
            # save_state was allowed to proceed (would have called SSH)
            assert mock_retry.called

    def test_day_reset_skipped_when_remote_load_failed(self):
        """_check_day_reset should skip when remote load failed with empty state."""
        from lib.state import State, RemoteStateStore

        # Create a mock remote store that failed to load
        mock_store = MagicMock(spec=RemoteStateStore)
        mock_store.load_state.return_value = {}  # Empty state from failed load
        mock_store._load_succeeded = False
        mock_store.timezone = "America/Los_Angeles"

        # Create state with the failing remote store
        state = State(remote_store=mock_store)

        # State should remain empty (no reset triggered)
        assert state._state == {}

        # get_today_iso should NOT have been called (reset was skipped)
        mock_store.get_today_iso.assert_not_called()

    def test_day_reset_proceeds_when_remote_load_succeeded(self):
        """_check_day_reset should proceed normally when remote load succeeded."""
        from lib.state import State, RemoteStateStore

        # Create a mock remote store that successfully loaded empty state
        mock_store = MagicMock(spec=RemoteStateStore)
        mock_store.load_state.return_value = {}  # Empty but successful load
        mock_store._load_succeeded = True  # Load succeeded
        mock_store.timezone = "America/Los_Angeles"
        mock_store.get_today_iso.return_value = date.today().isoformat()

        # Create state with the successful remote store
        state = State(remote_store=mock_store)

        # State should have been initialized (reset triggered)
        assert state._state.get("date") == date.today().isoformat()
        assert state._state.get("emergency_count") == 0

        # get_today_iso should have been called (reset proceeded)
        mock_store.get_today_iso.assert_called()

    def test_state_preserved_when_load_fails_after_valid_state(self):
        """Emergency count should not be reset when network fails temporarily."""
        from lib.state import State, RemoteStateStore

        # Create a mock remote store that loaded valid state
        mock_store = MagicMock(spec=RemoteStateStore)
        mock_store.load_state.return_value = {
            "date": date.today().isoformat(),
            "tz": "America/Los_Angeles",
            "emergency_count": 2,
            "blocked": True,
            "unlocked_until": 0,
            "last_emergency_wait": 60,
        }
        mock_store._load_succeeded = True
        mock_store.timezone = "America/Los_Angeles"
        mock_store.get_today_iso.return_value = date.today().isoformat()

        state = State(remote_store=mock_store)

        # Verify emergency_count was preserved
        assert state.emergency_count == 2
        assert state._state.get("last_emergency_wait") == 60
