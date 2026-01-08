"""Base protocol for condition checkers."""

from typing import Any, Protocol


class Condition(Protocol):
    """Protocol for all condition checkers.

    Any class implementing this protocol can be used as a condition.
    The check method receives the condition config from config.yaml
    and returns (met: bool, description: str).
    """

    def check(self, config: dict[str, Any]) -> tuple[bool, str]:
        """Check if the condition is met.

        Args:
            config: The condition configuration dict from config.yaml
                   (e.g., {"type": "checkbox", "pattern": "- [x] Workout"})

        Returns:
            Tuple of (met, description) where:
            - met: True if condition is satisfied, False otherwise
            - description: Human-readable description of the result
        """
        ...
