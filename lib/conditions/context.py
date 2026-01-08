"""Context object for condition initialization."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ConditionContext:
    """Context passed to condition factories for initialization.

    This provides conditions with access to:
    - Obsidian vault configuration (for obsidian-based conditions)
    - Secrets from config.secrets.yaml (for external API conditions)
    - Full config for advanced use cases
    """

    # Obsidian vault access (for obsidian-based conditions)
    vault_path: Path | None = None
    daily_note_pattern: str = "Daily/{date}.md"

    # Credentials from config.secrets.yaml
    secrets: dict[str, Any] = field(default_factory=dict)

    # Full config for advanced conditions
    full_config: dict[str, Any] = field(default_factory=dict)

    def get_secret(self, path: str, default: Any = None) -> Any:
        """Get a secret by dot-separated path.

        Args:
            path: Dot-separated path to secret (e.g., 'strava.client_id')
            default: Value to return if secret not found

        Returns:
            The secret value, or default if not found

        Example:
            context.get_secret('strava.client_id')
            context.get_secret('whatsapp.api_key', default='')
        """
        keys = path.split(".")
        value = self.secrets
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
