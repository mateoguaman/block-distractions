"""Obsidian vault parsing and condition checking."""

import re
import yaml
from datetime import date
from pathlib import Path
from typing import Any


class ObsidianParser:
    """Parse Obsidian vault for condition checking."""

    def __init__(self, vault_path: Path | str, daily_note_pattern: str = "Daily/{date}.md"):
        self.vault_path = Path(vault_path)
        self.daily_note_pattern = daily_note_pattern

    def get_today_note_path(self) -> Path:
        """Get the path to today's daily note."""
        today = date.today().strftime("%Y-%m-%d")
        pattern = self.daily_note_pattern.replace("{date}", today)
        return self.vault_path / pattern

    def read_daily_note(self) -> str | None:
        """Read today's daily note content."""
        note_path = self.get_today_note_path()
        if note_path.exists():
            return note_path.read_text()
        return None

    def parse_frontmatter(self, content: str) -> dict[str, Any]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}

        try:
            return yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return {}

    def check_checkbox(self, content: str, pattern: str) -> bool:
        """Check if a checkbox pattern is checked.

        Pattern example: "- [x] Workout"
        Matches:
          - [x] Workout
          - [X] Workout
          - [x] Workout done
          * [x] Workout
        """
        # Extract the text after the checkbox pattern
        if pattern.startswith("- [x] ") or pattern.startswith("- [X] "):
            text = pattern[6:]
        elif pattern.startswith("* [x] ") or pattern.startswith("* [X] "):
            text = pattern[6:]
        else:
            text = pattern

        # Build regex to find checked checkbox with this text
        # Matches: - [x] text or * [x] text, case insensitive for x
        regex = rf"[-*]\s*\[[xX]\]\s*{re.escape(text)}"
        return bool(re.search(regex, content, re.IGNORECASE))

    def check_yaml_field(
        self, content: str, field: str, expected: Any = None, minimum: int | None = None
    ) -> bool:
        """Check a YAML frontmatter field."""
        frontmatter = self.parse_frontmatter(content)

        if field not in frontmatter:
            return False

        value = frontmatter[field]

        if minimum is not None:
            # Check if value is a number >= minimum
            try:
                return float(value) >= minimum
            except (ValueError, TypeError):
                return False

        if expected is not None:
            return value == expected

        # Just check if field exists and is truthy
        return bool(value)

    def check_heading_exists(
        self, content: str, heading: str, any_level: bool = True
    ) -> bool:
        """Check if a heading exists with content below it."""
        if any_level:
            # Match any heading level
            regex = rf"^#+\s*{re.escape(heading)}\s*$"
        else:
            # Match exact heading (count # symbols)
            level = heading.count("#")
            text = heading.lstrip("#").strip()
            regex = rf"^{'#' * level}\s*{re.escape(text)}\s*$"

        match = re.search(regex, content, re.MULTILINE | re.IGNORECASE)
        if not match:
            return False

        # Check if there's content after the heading
        after_heading = content[match.end():]
        lines = after_heading.split("\n")

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # If we hit another heading, no content was found
            if stripped.startswith("#"):
                return False
            # Found non-empty, non-heading content
            return True

        return False

    def check_regex(self, content: str, pattern: str) -> bool:
        """Check if a regex pattern matches anywhere in the content."""
        try:
            return bool(re.search(pattern, content, re.IGNORECASE | re.MULTILINE))
        except re.error:
            return False

    def get_section_content(
        self, content: str, heading: str, any_level: bool = True
    ) -> str | None:
        """Get all content under a specific heading until the next heading."""
        if any_level:
            regex = rf"^(#+)\s*{re.escape(heading)}\s*$"
        else:
            level = heading.count("#") if heading.startswith("#") else 1
            text = heading.lstrip("#").strip()
            regex = rf"^({'#' * level})\s*{re.escape(text)}\s*$"

        match = re.search(regex, content, re.MULTILINE | re.IGNORECASE)
        if not match:
            return None

        heading_level = len(match.group(1))
        after_heading = content[match.end():]
        lines = []

        for line in after_heading.split("\n"):
            # Check if this is a heading of same or higher level
            heading_match = re.match(r"^(#+)\s", line)
            if heading_match and len(heading_match.group(1)) <= heading_level:
                break
            lines.append(line)

        return "\n".join(lines)

    def extract_wiki_links(self, content: str) -> list[str]:
        """Extract all [[wiki-links]] from content."""
        # Match [[link]] or [[link|alias]]
        pattern = r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]"
        matches = re.findall(pattern, content)
        return matches

    def resolve_link_path(self, link: str) -> Path | None:
        """Resolve a wiki-link to an actual file path."""
        # Handle both with and without .md extension
        if not link.endswith(".md"):
            link = link + ".md"

        # Try direct path
        direct_path = self.vault_path / link
        if direct_path.exists():
            return direct_path

        # Search for the file in the vault
        link_name = Path(link).name
        for path in self.vault_path.rglob(link_name):
            if path.is_file():
                return path

        return None

    def check_condition(self, condition_config: dict[str, Any]) -> tuple[bool, str]:
        """Check a single condition and return (met, description)."""
        content = self.read_daily_note()
        if content is None:
            return False, "Daily note not found"

        condition_type = condition_config.get("type", "checkbox")

        if condition_type == "checkbox":
            pattern = condition_config.get("pattern", "")
            met = self.check_checkbox(content, pattern)
            return met, f"Checkbox '{pattern}'" + (" checked" if met else " not checked")

        elif condition_type == "yaml":
            field = condition_config.get("field", "")
            expected = condition_config.get("value")
            minimum = condition_config.get("minimum")
            met = self.check_yaml_field(content, field, expected, minimum)
            if minimum is not None:
                return met, f"YAML field '{field}' >= {minimum}" if met else f"YAML field '{field}' < {minimum}"
            return met, f"YAML field '{field}'" + (" set" if met else " not set")

        elif condition_type == "heading":
            heading = condition_config.get("section", "")
            any_level = condition_config.get("section_any_level", True)
            met = self.check_heading_exists(content, heading, any_level)
            return met, f"Heading '{heading}'" + (" has content" if met else " empty or missing")

        elif condition_type == "regex":
            pattern = condition_config.get("pattern", "")
            met = self.check_regex(content, pattern)
            return met, f"Pattern '{pattern}'" + (" matched" if met else " not matched")

        elif condition_type == "linked_wordcount":
            # This will be handled by wordcount.py
            return False, "Word count check (handled separately)"

        return False, f"Unknown condition type: {condition_type}"


def get_obsidian_parser(vault_path: Path | str, daily_note_pattern: str = "Daily/{date}.md") -> ObsidianParser:
    """Get an ObsidianParser instance."""
    return ObsidianParser(vault_path, daily_note_pattern)
