"""Obsidian-based condition implementations."""

from typing import Any

from ..obsidian import ObsidianParser
from ..wordcount import WordCounter
from .context import ConditionContext
from .registry import ConditionRegistry


class ObsidianCondition:
    """Base class for Obsidian-based conditions.

    Provides common initialization and daily note access.
    """

    def __init__(self, context: ConditionContext):
        """Initialize with vault path from context.

        Args:
            context: The condition context with vault configuration
        """
        if context.vault_path is None:
            raise ValueError("ObsidianCondition requires vault_path in context")

        self.parser = ObsidianParser(
            context.vault_path,
            context.daily_note_pattern,
        )

    def _read_note(self) -> str | None:
        """Read today's daily note content.

        Returns:
            The note content, or None if not found
        """
        return self.parser.read_daily_note()


class CheckboxCondition(ObsidianCondition):
    """Condition that checks for a checked checkbox in daily note.

    Config:
        pattern: The checkbox pattern to match (e.g., "- [x] Workout")
    """

    def check(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Check if the checkbox is checked in today's note."""
        content = self._read_note()
        if content is None:
            return False, "Daily note not found"

        pattern = config.get("pattern", "")
        met = self.parser.check_checkbox(content, pattern)
        return met, f"Checkbox '{pattern}'" + (" checked" if met else " not checked")


class YamlCondition(ObsidianCondition):
    """Condition that checks YAML frontmatter fields.

    Config:
        field: The YAML field name to check
        value: (optional) Expected value for equality check
        minimum: (optional) Minimum numeric value
    """

    def check(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Check if the YAML field meets criteria."""
        content = self._read_note()
        if content is None:
            return False, "Daily note not found"

        field = config.get("field", "")
        expected = config.get("value")
        minimum = config.get("minimum")
        met = self.parser.check_yaml_field(content, field, expected, minimum)

        if minimum is not None:
            if met:
                return True, f"YAML field '{field}' >= {minimum}"
            return False, f"YAML field '{field}' < {minimum}"
        return met, f"YAML field '{field}'" + (" set" if met else " not set")


class HeadingCondition(ObsidianCondition):
    """Condition that checks for heading with content below it.

    Config:
        section: The heading text to look for
        section_any_level: (optional) Match any heading level (default: True)
    """

    def check(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Check if the heading exists with content."""
        content = self._read_note()
        if content is None:
            return False, "Daily note not found"

        heading = config.get("section", "")
        any_level = config.get("section_any_level", True)
        met = self.parser.check_heading_exists(content, heading, any_level)
        return met, f"Heading '{heading}'" + (" has content" if met else " empty or missing")


class RegexCondition(ObsidianCondition):
    """Condition that checks for regex match in daily note.

    Config:
        pattern: The regex pattern to match
    """

    def check(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Check if the pattern matches anywhere in the note."""
        content = self._read_note()
        if content is None:
            return False, "Daily note not found"

        pattern = config.get("pattern", "")
        met = self.parser.check_regex(content, pattern)
        return met, f"Pattern '{pattern}'" + (" matched" if met else " not matched")


class LinkedWordcountCondition(ObsidianCondition):
    """Condition that counts words in linked files under a section.

    Config:
        section: The heading under which to find linked files
        section_any_level: (optional) Match any heading level (default: True)
        minimum: The minimum word count required
    """

    def check(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Check if word count in linked files meets minimum."""
        counter = WordCounter(self.parser)
        met, description, _ = counter.check_wordcount_condition(config)
        return met, description


# Register all Obsidian conditions
def _make_factory(cls: type) -> callable:
    """Create a factory function for a condition class."""

    def factory(context: ConditionContext):
        return cls(context)

    return factory


ConditionRegistry.register("checkbox")(_make_factory(CheckboxCondition))
ConditionRegistry.register("yaml")(_make_factory(YamlCondition))
ConditionRegistry.register("heading")(_make_factory(HeadingCondition))
ConditionRegistry.register("regex")(_make_factory(RegexCondition))
ConditionRegistry.register("linked_wordcount")(_make_factory(LinkedWordcountCondition))
