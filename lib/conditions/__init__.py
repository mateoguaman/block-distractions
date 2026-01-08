"""Extensible condition system for block_distractions.

This module provides a plugin-based condition system that allows new
condition types to be added without modifying core code.

Usage:
    from lib.conditions import ConditionRegistry, ConditionContext

    # Create context
    context = ConditionContext(
        vault_path=Path("/path/to/vault"),
        secrets={"strava": {"api_key": "..."}},
    )

    # Create and check a condition
    condition = ConditionRegistry.create("checkbox", context)
    met, description = condition.check({"pattern": "- [x] Workout"})

Adding new condition types:
    1. Create a new module (e.g., lib/conditions/strava.py)
    2. Implement a class with check(config) -> (bool, str)
    3. Register it:
       @ConditionRegistry.register("strava")
       def create_strava(context):
           return StravaCondition(context)
    4. Import the module here to trigger registration
"""

from .base import Condition
from .context import ConditionContext
from .registry import ConditionRegistry

# Import condition modules to trigger registration
# Each module registers its conditions when imported
from . import obsidian  # checkbox, yaml, heading, regex, linked_wordcount

__all__ = [
    "Condition",
    "ConditionContext",
    "ConditionRegistry",
]
