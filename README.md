# Block Distractions

A CLI tool that blocks distracting websites via `/etc/hosts` with proof-of-work and emergency unlock mechanisms.

## Features

- **System-level blocking** via `/etc/hosts` (blocks sites in all browsers)
- **Proof-of-work unlock** - Earn access by completing conditions tracked in Obsidian
- **Emergency unlock** - Limited bypass with escalating wait times and shame prompts
- **Background daemon** - Automatically checks conditions and unlocks when earned
- **Cross-platform** - Works on macOS (launchd) and Linux (systemd)

## Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) - Python package manager
- Obsidian (for condition tracking)

## Installation

```bash
# Clone/download the repo, then:
cd block_distractions

# Run setup (requires sudo for /etc/hosts access)
./setup.sh
```

This will:
1. Create a Python virtual environment and install dependencies
2. Install the `block` command to `/usr/local/bin`
3. Configure passwordless sudo for `/etc/hosts` modifications (see [Security](#passwordless-sudo))
4. Set up and start the background daemon
5. Enable initial blocking

## Usage

```bash
block status              # Show current status and conditions
block unlock              # Unlock via proof-of-work (checks Obsidian)
block emergency           # Emergency unlock with escalating waits
block on                  # Force enable blocking
block off                 # Temporarily disable (testing only)
block list                # List blocked sites
block add <site>          # Add a site to blocklist
block remove <site>       # Remove a site from blocklist
block daemon              # Run background daemon (usually auto-started)
block check               # Run a single condition check
```

## Configuration

Edit `config.yaml` to customize:

### Obsidian Settings

```yaml
obsidian:
  vault_path: "~/Documents/mateo-md"
  daily_note_pattern: "Daily/{date}.md"  # {date} = YYYY-MM-DD
```

### Conditions

Any ONE condition being met allows proof-of-work unlock:

```yaml
conditions:
  # Checkbox condition
  workout:
    type: checkbox
    pattern: "- [x] Workout"  # Matches checked checkbox

  # Word count from linked files
  writing:
    type: linked_wordcount
    section: "Writing"        # Heading to look under
    section_any_level: true   # Match #, ##, ###, etc.
    minimum: 500              # Minimum words required
```

**Condition types:**
- `checkbox` - Look for checked `- [x]` items
- `yaml` - Check YAML frontmatter values
- `heading` - Check if heading has content
- `regex` - Custom regex pattern
- `linked_wordcount` - Count words in `[[linked]]` files under a heading

### Unlock Settings

```yaml
unlock:
  proof_of_work_duration: 7200    # 2 hours
  emergency_duration: 300          # 5 minutes
  emergency_max_per_day: 3
  emergency_initial_wait: 30       # Doubles each use: 30s, 60s, 120s
  emergency_wait_multiplier: 2

auto_unlock:
  enabled: true
  earliest_time: "17:00"           # Won't auto-unlock before 5pm
  check_interval: 300              # Check every 5 minutes
```

### Blocked Sites

```yaml
blocked_sites:
  - twitter.com
  - youtube.com
  - reddit.com
  # ... add more as needed
```

## How It Works

1. **Blocking**: Sites are added to `/etc/hosts` pointing to `127.0.0.1`
2. **Proof-of-work**: Check your Obsidian daily note for completed conditions
3. **Emergency**: Escalating wait times (30s → 60s → 120s) + type "I CHOOSE DISTRACTION"
4. **Daemon**: Runs in background, auto-unlocks after `earliest_time` if conditions met

## Managing the Daemon

**macOS:**
```bash
launchctl start com.block.daemon    # Start
launchctl stop com.block.daemon     # Stop
launchctl unload ~/Library/LaunchAgents/com.block.daemon.plist  # Disable
```

**Linux:**
```bash
systemctl --user start block-daemon   # Start
systemctl --user stop block-daemon    # Stop
systemctl --user disable block-daemon # Disable
```

## Passwordless Sudo

The setup script configures passwordless sudo for specific commands needed to modify `/etc/hosts`. This allows the daemon and CLI to block/unblock sites without prompting for a password.

### What's configured

A file is created at `/etc/sudoers.d/block-distractions` with rules for:

**macOS:**
```
<username> ALL=(ALL) NOPASSWD: /bin/cp * /etc/hosts
<username> ALL=(ALL) NOPASSWD: /usr/bin/dscacheutil -flushcache
<username> ALL=(ALL) NOPASSWD: /usr/bin/killall -HUP mDNSResponder
```

**Linux:**
```
<username> ALL=(ALL) NOPASSWD: /bin/cp * /etc/hosts
<username> ALL=(ALL) NOPASSWD: /usr/bin/systemd-resolve --flush-caches
```

### Security implications

- **Minimal scope**: Only allows writing to `/etc/hosts` and flushing DNS cache
- **No shell escalation**: Cannot be used to gain full root access
- **Worst case**: Someone with access to your user account could redirect domains

### Manual setup (if needed)

If the automatic setup fails, create `/etc/sudoers.d/block-distractions` manually:

```bash
sudo visudo -f /etc/sudoers.d/block-distractions
```

Add the appropriate rules for your OS (see above), then:

```bash
sudo chmod 440 /etc/sudoers.d/block-distractions
```

### Removing passwordless sudo

```bash
sudo rm /etc/sudoers.d/block-distractions
```

## Uninstalling

```bash
# Stop daemon
launchctl bootout gui/$(id -u)/com.block.daemon  # macOS
# or
systemctl --user disable --now block-daemon  # Linux

# Remove daemon config
rm ~/Library/LaunchAgents/com.block.daemon.plist  # macOS
# or
rm ~/.config/systemd/user/block-daemon.service  # Linux

# Remove command
sudo rm /usr/local/bin/block

# Remove passwordless sudo
sudo rm /etc/sudoers.d/block-distractions

# Remove hosts entries
sudo sed -i '' '/BLOCK_DISTRACTIONS/,/END BLOCK_DISTRACTIONS/d' /etc/hosts  # macOS
# or
sudo sed -i '/BLOCK_DISTRACTIONS/,/END BLOCK_DISTRACTIONS/d' /etc/hosts  # Linux
```

## Files

```
block_distractions/
├── block              # CLI entry point
├── config.yaml        # Your configuration
├── setup.sh           # Installation script
├── pyproject.toml     # Python dependencies
├── .gitignore         # Git ignore rules
├── .logs/             # Log files (auto-created, rotated at 1MB)
│   └── daemon.log
├── state.json         # Runtime state (auto-created)
├── lib/               # Python modules
│   ├── config.py      # Configuration loading
│   ├── state.py       # Daily state tracking
│   ├── hosts.py       # /etc/hosts management
│   ├── obsidian.py    # Condition checking
│   ├── wordcount.py   # Word counting for linked files
│   ├── unlock.py      # Unlock logic + shame prompts
│   └── daemon.py      # Background checker
└── services/          # Daemon service files
    ├── com.block.daemon.plist     # macOS launchd
    └── block-daemon.service       # Linux systemd
```
