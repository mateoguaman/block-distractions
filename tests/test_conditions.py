"""Tests for lib/conditions/ - Extensible condition system."""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.conditions import ConditionContext, ConditionRegistry
from lib.conditions.base import Condition


class TestConditionRegistry:
    """Tests for the ConditionRegistry class."""

    def test_builtin_conditions_registered(self):
        """All built-in Obsidian conditions should be registered."""
        types = ConditionRegistry.list_types()

        assert "checkbox" in types
        assert "yaml" in types
        assert "heading" in types
        assert "regex" in types
        assert "linked_wordcount" in types

    def test_create_unknown_type_raises(self):
        """Creating unknown condition type should raise ValueError."""
        context = ConditionContext(vault_path=Path("/tmp/vault"))

        with pytest.raises(ValueError, match="Unknown condition type"):
            ConditionRegistry.create("nonexistent_type", context)

    def test_is_registered(self):
        """is_registered should return True for registered types."""
        assert ConditionRegistry.is_registered("checkbox") is True
        assert ConditionRegistry.is_registered("nonexistent") is False

    def test_custom_registration(self):
        """Custom conditions can be registered and created."""

        # Create a custom condition class
        class CustomCondition:
            def check(self, config):
                return True, "Custom condition met"

        @ConditionRegistry.register("test_custom")
        def create_custom(context):
            return CustomCondition()

        # Verify registration
        assert "test_custom" in ConditionRegistry.list_types()

        # Create and use
        context = ConditionContext(vault_path=Path("/tmp/vault"))
        condition = ConditionRegistry.create("test_custom", context)
        met, desc = condition.check({})

        assert met is True
        assert "Custom" in desc

        # Clean up
        del ConditionRegistry._conditions["test_custom"]


class TestConditionContext:
    """Tests for the ConditionContext dataclass."""

    def test_default_values(self):
        """Context should have sensible defaults."""
        context = ConditionContext()

        assert context.vault_path is None
        assert context.daily_note_pattern == "Daily/{date}.md"
        assert context.secrets == {}
        assert context.full_config == {}

    def test_get_secret_nested_path(self):
        """get_secret should support dot-separated paths."""
        context = ConditionContext(
            secrets={
                "strava": {
                    "client_id": "test_id",
                    "client_secret": "test_secret",
                }
            }
        )

        assert context.get_secret("strava.client_id") == "test_id"
        assert context.get_secret("strava.client_secret") == "test_secret"
        assert context.get_secret("strava.missing", default="default") == "default"
        assert context.get_secret("missing.path") is None


class TestCheckboxCondition:
    """Tests for CheckboxCondition."""

    def test_checkbox_checked(self, temp_vault):
        """Should return True when checkbox is checked."""
        from lib.conditions.obsidian import CheckboxCondition

        # Create today's note with checked checkbox
        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("- [x] Workout done\n- [ ] Other task")

        context = ConditionContext(vault_path=temp_vault)
        condition = CheckboxCondition(context)

        met, desc = condition.check({"pattern": "- [x] Workout"})

        assert met is True
        assert "checked" in desc

    def test_checkbox_unchecked(self, temp_vault):
        """Should return False when checkbox is not checked."""
        from lib.conditions.obsidian import CheckboxCondition

        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("- [ ] Workout\n- [ ] Other task")

        context = ConditionContext(vault_path=temp_vault)
        condition = CheckboxCondition(context)

        met, desc = condition.check({"pattern": "- [x] Workout"})

        assert met is False
        assert "not checked" in desc

    def test_no_daily_note(self, temp_vault):
        """Should return False when daily note doesn't exist."""
        from lib.conditions.obsidian import CheckboxCondition

        context = ConditionContext(vault_path=temp_vault)
        condition = CheckboxCondition(context)

        met, desc = condition.check({"pattern": "- [x] Workout"})

        assert met is False
        assert "not found" in desc


class TestYamlCondition:
    """Tests for YamlCondition."""

    def test_yaml_field_set(self, temp_vault):
        """Should return True when YAML field is set."""
        from lib.conditions.obsidian import YamlCondition

        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("---\nworkout: true\n---\n\nContent")

        context = ConditionContext(vault_path=temp_vault)
        condition = YamlCondition(context)

        met, desc = condition.check({"field": "workout"})

        assert met is True
        assert "set" in desc

    def test_yaml_field_minimum(self, temp_vault):
        """Should check minimum value for numeric fields."""
        from lib.conditions.obsidian import YamlCondition

        today = date.today().strftime("%Y-%m-%d")
        note_path = temp_vault / "Daily" / f"{today}.md"
        note_path.write_text("---\nwords: 500\n---\n\nContent")

        context = ConditionContext(vault_path=temp_vault)
        condition = YamlCondition(context)

        # Meets minimum
        met, desc = condition.check({"field": "words", "minimum": 400})
        assert met is True

        # Doesn't meet minimum
        met, desc = condition.check({"field": "words", "minimum": 600})
        assert met is False


class TestConditionModeLogic:
    """Tests for AND/OR logic in check_all_conditions."""

    def test_any_mode_single_met(self, mock_config, mock_hosts, mock_obsidian,
                                  mock_remote_sync, temp_state_file):
        """In 'any' mode, single condition met should satisfy."""
        from lib.state import State
        from lib.unlock import UnlockManager

        state = State(state_path=temp_state_file)
        mock_config.conditions = {
            "cond1": {"type": "checkbox", "pattern": "- [x] A"},
            "cond2": {"type": "checkbox", "pattern": "- [x] B"},
        }
        mock_config.condition_mode = "any"

        # First condition met, second not
        mock_condition = MagicMock()
        mock_condition.check.side_effect = [
            (True, "A checked"),
            (False, "B not checked"),
        ]

        with patch("lib.unlock.ConditionRegistry.create", return_value=mock_condition):
            manager = UnlockManager(
                mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
            )
            satisfied, results = manager.check_all_conditions()

        assert satisfied is True
        assert len(results) == 2

    def test_all_mode_requires_all(self, mock_config, mock_hosts, mock_obsidian,
                                    mock_remote_sync, temp_state_file):
        """In 'all' mode, all conditions must be met."""
        from lib.state import State
        from lib.unlock import UnlockManager

        state = State(state_path=temp_state_file)
        mock_config.conditions = {
            "cond1": {"type": "checkbox", "pattern": "- [x] A"},
            "cond2": {"type": "checkbox", "pattern": "- [x] B"},
        }
        mock_config.condition_mode = "all"

        # First condition met, second not
        mock_condition = MagicMock()
        mock_condition.check.side_effect = [
            (True, "A checked"),
            (False, "B not checked"),
        ]

        with patch("lib.unlock.ConditionRegistry.create", return_value=mock_condition):
            manager = UnlockManager(
                mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
            )
            satisfied, results = manager.check_all_conditions()

        # Should NOT be satisfied in 'all' mode
        assert satisfied is False

    def test_all_mode_all_met(self, mock_config, mock_hosts, mock_obsidian,
                               mock_remote_sync, temp_state_file):
        """In 'all' mode, should satisfy when all conditions met."""
        from lib.state import State
        from lib.unlock import UnlockManager

        state = State(state_path=temp_state_file)
        mock_config.conditions = {
            "cond1": {"type": "checkbox", "pattern": "- [x] A"},
            "cond2": {"type": "checkbox", "pattern": "- [x] B"},
        }
        mock_config.condition_mode = "all"

        # Both conditions met
        mock_condition = MagicMock()
        mock_condition.check.side_effect = [
            (True, "A checked"),
            (True, "B checked"),
        ]

        with patch("lib.unlock.ConditionRegistry.create", return_value=mock_condition):
            manager = UnlockManager(
                mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
            )
            satisfied, results = manager.check_all_conditions()

        assert satisfied is True


class TestConditionErrorHandling:
    """Tests for fail-safe error handling in conditions."""

    def test_condition_error_counts_as_not_met(self, mock_config, mock_hosts,
                                                mock_obsidian, mock_remote_sync,
                                                temp_state_file):
        """Condition check errors should count as not met (fail-safe)."""
        from lib.state import State
        from lib.unlock import UnlockManager

        state = State(state_path=temp_state_file)

        # Condition that raises an error
        mock_condition = MagicMock()
        mock_condition.check.side_effect = Exception("API error")

        with patch("lib.unlock.ConditionRegistry.create", return_value=mock_condition):
            manager = UnlockManager(
                mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
            )
            satisfied, results = manager.check_all_conditions()

        # Should fail safe
        assert satisfied is False
        assert len(results) == 1
        name, met, desc = results[0]
        assert met is False
        assert "Error" in desc

    def test_unknown_condition_type_handled(self, mock_config, mock_hosts,
                                             mock_obsidian, mock_remote_sync,
                                             temp_state_file):
        """Unknown condition types should be handled gracefully."""
        from lib.state import State
        from lib.unlock import UnlockManager

        state = State(state_path=temp_state_file)
        mock_config.conditions = {
            "unknown": {"type": "nonexistent_type"},
        }

        # Don't patch registry - let it fail naturally
        manager = UnlockManager(
            mock_config, state, mock_hosts, mock_obsidian, mock_remote_sync
        )
        satisfied, results = manager.check_all_conditions()

        # Should handle gracefully
        assert satisfied is False
        name, met, desc = results[0]
        assert met is False
        assert "Unknown type" in desc
