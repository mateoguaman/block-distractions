"""Word counting for linked files in Obsidian vault."""

import re
from pathlib import Path
from typing import Any

from .obsidian import ObsidianParser


class WordCounter:
    """Count words in files linked from Obsidian daily notes."""

    def __init__(self, obsidian_parser: ObsidianParser):
        self.parser = obsidian_parser

    def count_words(self, text: str) -> int:
        """Count words in text, excluding markdown syntax."""
        if not text:
            return 0

        # Remove YAML frontmatter
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                text = parts[2]

        # Remove code blocks
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"`[^`]+`", "", text)

        # Remove links but keep link text
        text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", r"\2" if r"\2" else r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

        # Remove images
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)

        # Remove headings markers but keep text
        text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)

        # Remove bold/italic markers
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"_([^_]+)_", r"\1", text)

        # Remove bullet points and task markers
        text = re.sub(r"^[-*]\s*(\[[xX ]\])?\s*", "", text, flags=re.MULTILINE)

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # Split on whitespace and count non-empty words
        words = text.split()
        return len([w for w in words if w.strip()])

    def get_linked_files_wordcount(
        self,
        section: str,
        any_level: bool = True,
    ) -> tuple[int, list[tuple[str, int]]]:
        """Get total word count from files linked under a section.

        Returns:
            Tuple of (total_words, list of (filename, word_count) pairs)
        """
        content = self.parser.read_daily_note()
        if content is None:
            return 0, []

        # Get content under the specified section
        section_content = self.parser.get_section_content(content, section, any_level)
        if section_content is None:
            return 0, []

        # Extract wiki-links from the section
        links = self.parser.extract_wiki_links(section_content)
        if not links:
            return 0, []

        # Count words in each linked file
        file_counts: list[tuple[str, int]] = []
        total = 0

        for link in links:
            file_path = self.parser.resolve_link_path(link)
            if file_path and file_path.exists():
                try:
                    file_content = file_path.read_text()
                    word_count = self.count_words(file_content)
                    file_counts.append((link, word_count))
                    total += word_count
                except Exception:
                    file_counts.append((link, 0))

        return total, file_counts

    def check_wordcount_condition(self, condition_config: dict[str, Any]) -> tuple[bool, str, int]:
        """Check if the word count condition is met.

        Returns:
            Tuple of (met, description, actual_count)
        """
        section = condition_config.get("section", "Writing")
        any_level = condition_config.get("section_any_level", True)
        minimum = condition_config.get("minimum", 500)

        total, file_counts = self.get_linked_files_wordcount(section, any_level)

        met = total >= minimum

        if not file_counts:
            description = f"No linked files found under '{section}' section"
        else:
            files_info = ", ".join([f"{name}: {count}" for name, count in file_counts])
            description = f"Word count: {total}/{minimum} ({files_info})"

        return met, description, total


def get_word_counter(obsidian_parser: ObsidianParser) -> WordCounter:
    """Get a WordCounter instance."""
    return WordCounter(obsidian_parser)
