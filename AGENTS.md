# Repository Guidelines

## Project Structure & Module Organization
- `block` is the CLI entry point.
- `lib/` contains core Python modules (config, state, hosts/remote sync, Obsidian parsing, unlock logic, daemon).
- `services/` holds service definitions for macOS `launchd` and Linux `systemd`.
- `config.yaml` is versioned defaults; `config.secrets.yaml` is local secrets (git-ignored) with a template at `config.secrets.example.yaml`.
- `dns-blocker.mobileconfig.example` is the iOS DNS profile template; local profiles live in `dns-blocker.mobileconfig`.

## Build, Test, and Development Commands
- `./setup.sh` installs dependencies and configures the daemon for your OS.
- `uv run ./block <command>` runs the CLI inside the project’s Python environment.
  - Example: `uv run ./block status` or `uv run ./block sync`.
- `./test_blocking.sh` checks DNS blocking behavior end-to-end.

## Coding Style & Naming Conventions
- Python uses 4-space indentation and standard PEP 8 conventions.
- Module names in `lib/` are lowercase with underscores (e.g., `wordcount.py`).
- CLI subcommands are short verbs (`status`, `unlock`, `sync`).
- No formatter or linter is configured; keep diffs small and readable.

## Testing Guidelines
- There is no unit test suite yet; testing is primarily via `./test_blocking.sh`.
- When adding features, include a manual verification note in your PR describing how you tested (command and expected output).

## Commit & Pull Request Guidelines
- Commit messages are short, imperative sentences (e.g., “Add Ubuntu/Linux compatibility”, “Fix Safari HTTPS bypass”).
- Do not include references to Codex, LLMs, or AI tooling in commit messages or PR descriptions.
- PRs should include a concise description, steps to test, and any config changes. Include screenshots or logs only if they clarify behavior.

## Security & Configuration Tips
- Do not commit `config.secrets.yaml` or personal VM details.
- Remote DNS sync assumes SSH access and passwordless sudo for dnsmasq reloads; document any changes to this flow.
- Remote state is enabled: state lives on the VM at `/etc/block_distractions/state.json` (uses SSH + sudo). Day rollover follows `remote_state.timezone` if set (e.g., `America/Los_Angeles`), otherwise the VM’s local TZ. Unlock expiry rewrites state to `blocked: true` immediately.

## Agent-Specific Instructions
- Always run Python commands with `uv run` (never `python`/`python3` directly); treat this as a hard requirement for local development and automation.
- Treat `config.secrets.yaml` as sensitive and keep edits local.
- Use the `block` wrapper in `/usr/local/bin` that `cd`s to the repo and runs `uv run ./block`; this ensures the correct config/state are used on both macOS and Ubuntu.
- Auto-unlock may reapply unlocks on each check if conditions are met; disable `auto_unlock` temporarily when testing expiry behavior.
- Phone/web caching can mask state changes briefly; force new DNS lookups when validating block/unblock.

## Next Steps / Gotchas
- If you test unlock expiry, consider temporarily disabling `auto_unlock` or shortening `emergency_duration` to observe the expiration without re-unlock.
- Keep VM sudoers entries in sync with state/blocklist paths (`/etc/block_distractions/state.json`, `/etc/dnsmasq.d/blocklist.conf`).
- VM timezone/`remote_state.timezone` matters for daily reset; set it to your preferred TZ if you want a specific rollover time.
