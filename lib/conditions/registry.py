"""Registry for condition types."""

from typing import Any, Callable

from .base import Condition
from .context import ConditionContext

# Type alias for condition factory functions
# A factory takes a ConditionContext and returns a Condition instance
ConditionFactory = Callable[[ConditionContext], Condition]


class ConditionRegistry:
    """Registry for condition type handlers.

    This registry maps condition type names (e.g., "checkbox", "strava")
    to factory functions that create condition instances.

    Usage:
        # Register a condition type
        @ConditionRegistry.register("my_condition")
        def create_my_condition(context: ConditionContext) -> Condition:
            return MyCondition(context)

        # Create an instance
        condition = ConditionRegistry.create("my_condition", context)
        met, desc = condition.check(config)
    """

    _conditions: dict[str, ConditionFactory] = {}

    @classmethod
    def register(cls, condition_type: str) -> Callable[[ConditionFactory], ConditionFactory]:
        """Decorator to register a condition factory.

        Args:
            condition_type: The type identifier (e.g., "checkbox", "strava")

        Returns:
            Decorator function

        Example:
            @ConditionRegistry.register("strava")
            def create_strava_condition(context):
                return StravaCondition(context)
        """

        def decorator(factory: ConditionFactory) -> ConditionFactory:
            cls._conditions[condition_type] = factory
            return factory

        return decorator

    @classmethod
    def get(cls, condition_type: str) -> ConditionFactory | None:
        """Get a condition factory by type.

        Args:
            condition_type: The type identifier

        Returns:
            The factory function, or None if not found
        """
        return cls._conditions.get(condition_type)

    @classmethod
    def create(cls, condition_type: str, context: ConditionContext) -> Condition:
        """Create a condition instance.

        Args:
            condition_type: The type identifier
            context: The condition context for initialization

        Returns:
            A Condition instance

        Raises:
            ValueError: If condition_type is not registered
        """
        factory = cls.get(condition_type)
        if factory is None:
            raise ValueError(f"Unknown condition type: {condition_type}")
        return factory(context)

    @classmethod
    def list_types(cls) -> list[str]:
        """List all registered condition types.

        Returns:
            List of registered type identifiers
        """
        return list(cls._conditions.keys())

    @classmethod
    def is_registered(cls, condition_type: str) -> bool:
        """Check if a condition type is registered.

        Args:
            condition_type: The type identifier

        Returns:
            True if registered, False otherwise
        """
        return condition_type in cls._conditions

    @classmethod
    def clear(cls) -> None:
        """Clear all registered conditions.

        Primarily useful for testing.
        """
        cls._conditions.clear()
