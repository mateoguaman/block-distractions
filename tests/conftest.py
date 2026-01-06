"""Shared test fixtures for block_distractions tests."""

import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_state_file():
    """Create a temporary state file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write('{}')
        temp_path = Path(f.name)
    yield temp_path
    temp_path.unlink(missing_ok=True)


@pytest.fixture
def temp_config_file():
    """Create a temporary config file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write('')
        temp_path = Path(f.name)
    yield temp_path
    temp_path.unlink(missing_ok=True)


@pytest.fixture
def temp_hosts_file():
    """Create a temporary hosts file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.hosts', delete=False) as f:
        f.write("127.0.0.1 localhost\n::1 localhost\n")
        temp_path = Path(f.name)
    yield temp_path
    temp_path.unlink(missing_ok=True)


@pytest.fixture
def temp_vault(tmp_path):
    """Create a temporary Obsidian vault structure."""
    vault = tmp_path / "vault"
    vault.mkdir()
    daily_dir = vault / "Daily"
    daily_dir.mkdir()
    return vault


@pytest.fixture
def mock_config():
    """Create a mock config object."""
    config = MagicMock()
    config.blocked_sites = ["twitter.com", "reddit.com", "youtube.com"]
    config.unlock_settings = {
        "proof_of_work_duration": 7200,
        "emergency_duration": 300,
        "emergency_max_per_day": 3,
        "emergency_initial_wait": 30,
        "emergency_wait_multiplier": 2,
    }
    config.auto_unlock_settings = {
        "enabled": True,
        "earliest_time": "17:00",
        "check_interval": 300,
    }
    config.conditions = {
        "workout": {
            "type": "checkbox",
            "pattern": "- [x] Workout",
        }
    }
    config.obsidian_vault_path = Path("/tmp/vault")
    config.daily_note_pattern = "Daily/{date}.md"
    config.remote_sync_settings = {"enabled": False}
    config.get = lambda key, default=None: getattr(config, key.replace(".", "_"), default)
    return config


@pytest.fixture
def mock_state(temp_state_file):
    """Create a real State object with temporary file."""
    from lib.state import State
    return State(state_path=temp_state_file)


@pytest.fixture
def mock_hosts():
    """Create a mock hosts manager."""
    hosts = MagicMock()
    hosts.is_blocking_active.return_value = True
    hosts.block_sites.return_value = True
    hosts.unblock_sites.return_value = True
    return hosts


@pytest.fixture
def mock_obsidian():
    """Create a mock obsidian parser."""
    obsidian = MagicMock()
    obsidian.check_condition.return_value = (False, "Not checked")
    obsidian.read_daily_note.return_value = None
    return obsidian


@pytest.fixture
def mock_remote_sync():
    """Create a mock remote sync manager."""
    sync = MagicMock()
    sync.enabled = False
    sync.sync.return_value = (True, "Sync disabled")
    return sync


def create_state_data(
    blocked: bool = True,
    unlocked_until: float = 0,
    emergency_count: int = 0,
    last_emergency_wait: int = 0,
    date_str: str | None = None,
    tz: str = "local",
) -> dict[str, Any]:
    """Helper to create state data for tests."""
    return {
        "date": date_str or date.today().isoformat(),
        "tz": tz,
        "blocked": blocked,
        "unlocked_until": unlocked_until,
        "emergency_count": emergency_count,
        "last_emergency_wait": last_emergency_wait,
    }
