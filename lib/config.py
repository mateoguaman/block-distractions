"""Configuration loading and management for block_distractions."""

import os
import yaml
from pathlib import Path
from typing import Any

# Default configuration location
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

# Default configuration values
DEFAULT_CONFIG = {
    "obsidian": {
        "vault_path": "~/Documents/mateo-md",
        "daily_note_pattern": "Daily/{date}.md",
    },
    "conditions": {
        "workout": {
            "type": "checkbox",
            "pattern": "- [x] Workout",
        },
        "writing": {
            "type": "linked_wordcount",
            "section": "Writing",
            "section_any_level": True,
            "minimum": 500,
        },
    },
    "auto_unlock": {
        "enabled": True,
        "earliest_time": "17:00",
        "check_interval": 300,
    },
    "unlock": {
        "proof_of_work_duration": 7200,  # 2 hours
        "emergency_duration": 300,  # 5 minutes
        "emergency_max_per_day": 3,
        "emergency_initial_wait": 30,
        "emergency_wait_multiplier": 2,
    },
    "blocked_sites": [
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "reddit.com",
        "youtube.com",
        "tiktok.com",
        "news.ycombinator.com",
        "threads.net",
        "snapchat.com",
        "pinterest.com",
        "tumblr.com",
        "linkedin.com",
        "twitch.tv",
        "netflix.com",
        "hulu.com",
        "disneyplus.com",
        "primevideo.com",
        "cnn.com",
        "foxnews.com",
        "bbc.com",
        "nytimes.com",
        "washingtonpost.com",
        "theguardian.com",
        "buzzfeed.com",
        "9gag.com",
    ],
}


class Config:
    """Configuration manager for block_distractions."""

    def __init__(self, config_path: Path | str | None = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from file, merging with defaults."""
        self._config = DEFAULT_CONFIG.copy()

        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                user_config = yaml.safe_load(f) or {}
            self._deep_merge(self._config, user_config)

        # Expand paths
        if "obsidian" in self._config:
            vault_path = self._config["obsidian"].get("vault_path", "")
            self._config["obsidian"]["vault_path"] = os.path.expanduser(vault_path)

    def _deep_merge(self, base: dict, override: dict) -> None:
        """Deep merge override into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def save(self) -> None:
        """Save current configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            yaml.dump(self._config, f, default_flow_style=False, sort_keys=False)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by dot-separated key path."""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value by dot-separated key path."""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    @property
    def obsidian_vault_path(self) -> Path:
        """Get the Obsidian vault path."""
        return Path(self.get("obsidian.vault_path", ""))

    @property
    def daily_note_pattern(self) -> str:
        """Get the daily note pattern."""
        return self.get("obsidian.daily_note_pattern", "Daily/{date}.md")

    @property
    def conditions(self) -> dict[str, dict]:
        """Get the conditions configuration."""
        return self.get("conditions", {})

    @property
    def blocked_sites(self) -> list[str]:
        """Get the list of blocked sites."""
        return self.get("blocked_sites", [])

    @property
    def unlock_settings(self) -> dict[str, Any]:
        """Get unlock settings."""
        return self.get("unlock", {})

    @property
    def auto_unlock_settings(self) -> dict[str, Any]:
        """Get auto-unlock settings."""
        return self.get("auto_unlock", {})

    def add_blocked_site(self, site: str) -> None:
        """Add a site to the blocklist."""
        sites = self.blocked_sites
        if site not in sites:
            sites.append(site)
            self.set("blocked_sites", sites)
            self.save()

    def remove_blocked_site(self, site: str) -> None:
        """Remove a site from the blocklist."""
        sites = self.blocked_sites
        if site in sites:
            sites.remove(site)
            self.set("blocked_sites", sites)
            self.save()


def get_config(config_path: Path | str | None = None) -> Config:
    """Get a Config instance."""
    return Config(config_path)
