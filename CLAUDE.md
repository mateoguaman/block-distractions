# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Block Distractions is a CLI tool that blocks distracting websites via a remote DNS server (dnsmasq) with proof-of-work unlock (via Obsidian condition checking) and emergency unlock mechanisms. It supports blocking on Mac, iPhone, and other devices.

**Key insight:** Traditional `/etc/hosts` blocking doesn't work for Safari because Safari queries HTTPS DNS records (RFC 9460) which contain IP hints that bypass hosts file blocking. We use dnsmasq with `address=/domain/` directives which block ALL DNS record types.

## Development Rules

- **Always run Python commands with `uv run`** - never use `python` or `python3` directly. This ensures the correct virtual environment and dependencies are used.
- **Secrets are in `config.secrets.yaml`** - this file is git-ignored and contains personal settings (vault path, VM IP, SSH username). Template is in `config.secrets.example.yaml`.

## Common Commands

```bash
# Run any CLI command (uses uv for Python environment)
uv run ./block <command>

# Key commands
uv run ./block status      # Show status and conditions
uv run ./block unlock      # Proof-of-work unlock (checks Obsidian)
uv run ./block emergency   # Emergency unlock with wait timer
uv run ./block on          # Force enable blocking
uv run ./block off         # Disable blocking (1 hour, testing)
uv run ./block sync        # Sync blocklist to remote DNS server
uv run ./block daemon      # Run background daemon
uv run ./block check       # Run single daemon check cycle

# Manage blocked sites
uv run ./block list
uv run ./block add <site>
uv run ./block remove <site>

# Test blocking effectiveness
./test_blocking.sh

# Setup/reinstall
./setup.sh
```

## Architecture

### Multi-Machine Setup

The system runs across three types of machines:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ARCHITECTURE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐         ┌──────────────────┐         ┌──────────────┐ │
│  │   CLIENT DEVICES │         │   DAEMON SERVER  │         │  DNS SERVER  │ │
│  │   (Mac, iPhone)  │         │     (boss)       │         │ (Google VM)  │ │
│  ├──────────────────┤         ├──────────────────┤         ├──────────────┤ │
│  │ • Development    │         │ • Runs daemon    │         │ • dnsmasq    │ │
│  │ • DNS pointed    │   SSH   │ • Checks Obsidian│   SSH   │ • blocklist  │ │
│  │   to Google VM   │ ──────► │ • Manages state  │ ──────► │ • DNS-over-  │ │
│  │ • CLI commands   │         │ • Syncs blocklist│         │   TLS (853)  │ │
│  │ • Blocked sites  │         │ • Always-on      │         │ • Always-on  │ │
│  └──────────────────┘         └──────────────────┘         └──────────────┘ │
│           │                            │                          ▲         │
│           │                            │                          │         │
│           └────────────────────────────┴──────── DNS queries ─────┘         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Client Devices (Mac, iPhone, etc.)**:
- DNS configured to point to Google VM
- Development happens on Mac
- Run CLI commands (`block status`, `block unlock`, etc.)
- Experience blocking when sites are in blocklist

**Daemon Server (boss - boss.cs.washington.edu)**:
- Ubuntu machine that's always on
- Runs the `block-daemon` systemd service
- Checks Obsidian conditions every 5 minutes
- Manages state (local or remote via `remote_state` config)
- Syncs blocklist to DNS server via SSH
- Service: `systemctl --user restart block-daemon`

**DNS Server (Google Cloud VM - 34.127.22.131)**:
- Runs dnsmasq with `address=/domain/` blocking
- Receives blocklist updates via SSH/SCP
- Provides DNS-over-TLS on port 853 (for iPhone)
- Blocklist at `/etc/dnsmasq.d/blocklist.conf`

### Core Flow

1. **Blocking**: `lib/hosts.py` `RemoteSyncManager` syncs blocklist to remote dnsmasq server using `address=/domain/` format which blocks ALL DNS record types (A, AAAA, HTTPS, SVCB).

2. **State**: `lib/state.py` tracks daily state in `state.json` - unlock expiration timestamps, emergency unlock count, auto-resets on new day.

3. **Conditions**: `lib/conditions/` provides an extensible condition system. Built-in types (checkbox, yaml, heading, regex, linked_wordcount) use `lib/obsidian.py` for parsing. Custom conditions can be added via the registry pattern. `lib/wordcount.py` handles word counting in linked files.

4. **Unlocking**: `lib/unlock.py` orchestrates proof-of-work (check conditions → unblock for duration) and emergency unlocks (escalating wait times 30s→60s→120s, shame prompts, "I CHOOSE DISTRACTION" confirmation).

5. **Daemon**: `lib/daemon.py` runs in background via launchd (macOS) or systemd (Linux). Checks conditions every 5 minutes, auto-unlocks after `earliest_time` if conditions met.

### Key Design Patterns

- Factory functions (`get_config()`, `get_state()`, etc.) for dependency injection
- Configuration split: `config.yaml` (version controlled) + `config.secrets.yaml` (git-ignored)
- Config loading: defaults → config.yaml → config.secrets.yaml (deep merge)
- State persisted as JSON, auto-resets daily
- Remote sync via SSH/SCP to VM's `/etc/dnsmasq.d/blocklist.conf`
- **Retry with exponential backoff** for transient SSH failures (3 retries, 2s→4s→8s backoff)
- All sync operations log failures to daemon.log

### Extensible Conditions System

The `lib/conditions/` module provides a plugin-based condition system:

```
lib/conditions/
├── __init__.py    # Exports ConditionRegistry, ConditionContext; imports condition modules
├── base.py        # Condition protocol: check(config) -> (bool, str)
├── context.py     # ConditionContext: vault_path, secrets, get_secret()
├── registry.py    # ConditionRegistry: @register decorator, create()
└── obsidian.py    # Built-in conditions: checkbox, yaml, heading, regex, linked_wordcount
```

**To add a new condition type:**

1. Create `lib/conditions/yourtype.py`:
```python
from lib.conditions import ConditionRegistry, ConditionContext

class YourCondition:
    def __init__(self, context: ConditionContext):
        self.api_key = context.get_secret("yourtype.api_key")

    def check(self, config: dict) -> tuple[bool, str]:
        # Return (met: bool, description: str)
        return True, "Condition met"

@ConditionRegistry.register("yourtype")
def create_your_condition(context: ConditionContext):
    return YourCondition(context)
```

2. Import in `lib/conditions/__init__.py`:
```python
from . import yourtype
```

3. Use in `config.yaml`:
```yaml
conditions:
  my_check:
    type: yourtype
    custom_param: value
```

**ConditionContext fields:**
- `vault_path: Path | None` - Obsidian vault path
- `daily_note_pattern: str` - Pattern for daily notes
- `secrets: dict` - Full secrets from config.secrets.yaml
- `full_config: dict` - Merged config
- `get_secret(path)` - Get secret by dot-path (e.g., `"strava.api_key"`)

### Daemon Service Files

- macOS: `services/com.block.daemon.plist` - uses `{{SCRIPT_DIR}}`, `{{USER}}`, `{{HOME}}` placeholders
- Linux: `services/block-daemon.service`

### Phone Unlock API

The `remote_api/` directory contains a Flask web server for phone-based unlocks:

```
remote_api/
├── server.py         # Flask app with mobile-friendly UI
├── deploy.sh         # One-command deployment to VM
├── setup_vm.sh       # VM setup script
└── requirements.txt  # Flask + gunicorn
```

**How it works:**
1. Flask server runs on Google VM (port 8080)
2. Phone accesses web UI, queues unlock requests
3. Daemon on boss polls VM via SSH for pending requests
4. `lib/poll.py` `PollManager` handles the polling logic
5. Requests processed via existing `UnlockManager` methods

**Key files:**
- `lib/poll.py` - PollManager class (SSH-based polling)
- `lib/daemon.py` - `process_poll_requests()` method
- `lib/config.py` - `phone_api_settings` property

**Config:**
```yaml
phone_api:
  enabled: true
  data_dir: /var/lib/block_distractions  # Where requests.json lives on VM
  # host/user inherited from remote_sync
```

## Configuration

**config.yaml** (version controlled):
- `obsidian.daily_note_pattern`: Pattern with `{date}` placeholder (YYYY-MM-DD)
- `conditions`: Dict of condition configs (type: checkbox/yaml/heading/regex/linked_wordcount)
- `unlock.*`: Unlock timing settings
- `auto_unlock.*`: Auto-unlock settings
- `blocked_sites`: List of domains to block
- `remote_sync.blocklist_path`: Path on VM (default: `/etc/dnsmasq.d/blocklist.conf`)

**config.secrets.yaml** (git-ignored):
- `obsidian.vault_path`: Path to Obsidian vault
- `remote_sync.host`: VM IP address
- `remote_sync.user`: SSH username

## Testing

The project has a comprehensive test suite using pytest.

```bash
# Install test dependencies
uv pip install pytest pytest-mock freezegun

# Run all tests
uv run pytest tests/ -v

# Run specific test files
uv run pytest tests/test_state.py -v       # State management tests
uv run pytest tests/test_unlock.py -v      # Unlock logic tests
uv run pytest tests/test_daemon.py -v      # Daemon/auto-unlock tests
uv run pytest tests/test_integration.py -v # Integration tests

# Run bug-related tests
uv run pytest tests/test_daemon.py::TestAutoUnlockBug -v
uv run pytest tests/test_integration.py::TestBugScenarios -v
```

## Experiment Analysis

The project includes experiment logging and analysis tools:

```bash
# Analyze recent logs (default: 7 days)
uv run tools/analyze_experiment.py

# Analyze specific number of days with verbose output
uv run tools/analyze_experiment.py --days 10 -v

# Output as JSON
uv run tools/analyze_experiment.py --json > results.json
```

See `docs/EXPERIMENT_PROTOCOL.md` for the multi-day experiment protocol.

## Known Issues

### Repeated Auto-Unlock Bug (FIXED)

**Symptom**: Once unlocked, the system stayed effectively unlocked for the rest of the day.

**Root Cause**: When an unlock expired (after 2 hours), the daemon checked conditions again. If conditions were still met (e.g., workout checkbox still checked), auto-unlock triggered again.

**Fix**: Added `unlocked_via_conditions_today` flag in state that:
- Gets set when proof-of-work or auto-unlock succeeds
- Prevents any further auto-unlocks for the rest of the day
- Resets at midnight (with daily state reset)

**Files Changed**: `lib/state.py`, `lib/daemon.py`, `lib/unlock.py`

**Tests**: See `tests/test_daemon.py::TestAutoUnlockBug` and `tests/test_state.py::TestUnlockedViaConditionsToday`

### Manual Unlock Bypasses earliest_time

**Behavior**: The `block unlock` command (proof-of-work) does NOT check `earliest_time` - only the daemon's auto-unlock does. This means you can manually unlock before the earliest time by running `block unlock` if conditions are met.

**Status**: This may be intentional behavior (user explicitly requesting unlock).

## Platform Notes

- **Safari HTTPS bypass**: Safari queries HTTPS DNS records with IP hints - only dnsmasq `address=` blocking works
- **Mac DNS**: Point to VM via `sudo networksetup -setdnsservers Wi-Fi VM_IP`
- **iPhone DNS**: Uses DNS-over-TLS (port 853) via stunnel on VM with Let's Encrypt cert
- **Browser DoH**: Chrome/Firefox "Secure DNS" bypasses system DNS - must be disabled
- **Logs**: `.logs/daemon.log` with 1MB rotation, `.logs/experiment.log` for experiment data
