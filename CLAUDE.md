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

```
Mac/iPhone → DNS queries → Google Cloud VM (dnsmasq) → blocks via address=/domain/
```

### Core Flow

1. **Blocking**: `lib/hosts.py` `RemoteSyncManager` syncs blocklist to remote dnsmasq server using `address=/domain/` format which blocks ALL DNS record types (A, AAAA, HTTPS, SVCB).

2. **State**: `lib/state.py` tracks daily state in `state.json` - unlock expiration timestamps, emergency unlock count, auto-resets on new day.

3. **Conditions**: `lib/obsidian.py` parses Obsidian daily notes to check unlock conditions (checkbox, yaml, heading, regex, linked_wordcount). `lib/wordcount.py` handles word counting in linked files.

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

### Daemon Service Files

- macOS: `services/com.block.daemon.plist` - uses `{{SCRIPT_DIR}}`, `{{USER}}`, `{{HOME}}` placeholders
- Linux: `services/block-daemon.service`

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

## Platform Notes

- **Safari HTTPS bypass**: Safari queries HTTPS DNS records with IP hints - only dnsmasq `address=` blocking works
- **Mac DNS**: Point to VM via `sudo networksetup -setdnsservers Wi-Fi VM_IP`
- **iPhone DNS**: Uses DNS-over-TLS (port 853) via stunnel on VM with Let's Encrypt cert
- **Browser DoH**: Chrome/Firefox "Secure DNS" bypasses system DNS - must be disabled
- **Logs**: `.logs/daemon.log` with 1MB rotation
