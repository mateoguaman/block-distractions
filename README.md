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

## Remote DNS Sync (for iPhone/Mobile Blocking)

Block Distractions can sync your blocklist to a remote DNS server, enabling blocking on mobile devices like iPhones.

### Architecture

```
┌──────────────┐         ┌──────────────┐         ┌─────────────────────────┐
│   iPhone     │         │   Your Mac   │         │   Google Cloud VM       │
│              │         │              │         │   (always on)           │
│ DNS: VM IP   │────┐    │ block CLI    │────┐    │                         │
└──────────────┘    │    └──────────────┘    │    │  /etc/hosts.block:      │
                    │                        │    │  127.0.0.1 twitter.com  │
                    │    DNS queries         │    │  127.0.0.1 reddit.com   │
                    └───────────────────────────▶│                         │
                                             │    │  dnsmasq:               │
                         scp /etc/hosts.block┘    │  (answers DNS using     │
                                                  │   the hosts file)       │
                                                  └─────────────────────────┘
```

### How It Works

1. **Your Mac** has `/etc/hosts` blocking sites (local blocking)
2. **Google Cloud VM** runs `dnsmasq` reading `/etc/hosts.block`
3. **Your Mac** syncs the blocklist to the VM via SSH/SCP
4. **Your iPhone** uses the VM as its DNS server
5. When you `block add twitter.com`, it updates Mac AND syncs to VM

### Remote Sync Commands

```bash
block sync               # Manually sync blocklist to remote server
block add <site>         # Add site locally AND sync to remote
block remove <site>      # Remove site locally AND sync to remote
```

### Configuration

Add to `config.yaml`:

```yaml
remote_sync:
  enabled: true
  host: YOUR_VM_IP        # e.g., 34.127.22.131
  user: YOUR_USERNAME     # SSH username
  hosts_path: /etc/hosts.block
```

---

## Setting Up Remote DNS Server (Google Cloud VM)

### Part 1: Create Google Cloud VM

1. **Create a Google Cloud account** at https://cloud.google.com (free $300 credit for 90 days)

2. **Create a VM instance:**
   - Go to Compute Engine → VM instances → Create Instance
   - Name: `dns-server`
   - Region: Choose one close to you (e.g., `us-west1`)
   - Machine type: `e2-micro` (free tier eligible, ~$5/mo after trial)
   - Boot disk: Ubuntu 22.04 LTS, 10GB
   - Firewall: Allow HTTP (not strictly needed but useful)
   - Click Create

3. **Note the External IP** (e.g., `34.127.22.131`)

4. **Open firewall ports for DNS:**
   - Go to VPC Network → Firewall → Create Firewall Rule
   - Name: `allow-dns`
   - Direction: Ingress
   - Targets: All instances in the network
   - Source IP ranges: `0.0.0.0/0`
   - Protocols and ports: `tcp:53` and `udp:53`
   - Click Create

### Part 2: Install dnsmasq on VM

SSH into your VM (via Google Cloud Console or `gcloud compute ssh dns-server`):

```bash
# Update and install dnsmasq
sudo apt-get update
sudo apt-get install -y dnsmasq

# Disable systemd-resolved (conflicts with dnsmasq on port 53)
sudo sed -i 's/#DNSStubListener=yes/DNSStubListener=no/' /etc/systemd/resolved.conf
sudo systemctl restart systemd-resolved

# Fix dnsmasq init script (remove --local-service flag that blocks external queries)
sudo sed -i 's/DNSMASQ_OPTS="${DNSMASQ_OPTS} --local-service"/#DNSMASQ_OPTS="${DNSMASQ_OPTS} --local-service"/' /etc/init.d/dnsmasq

# Configure dnsmasq
sudo tee /etc/dnsmasq.conf << 'EOF'
no-resolv
server=8.8.8.8
server=8.8.4.4
no-hosts
addn-hosts=/etc/hosts.block
log-queries
cache-size=1000
EOF

# Create empty hosts.block file
sudo touch /etc/hosts.block
sudo chmod 644 /etc/hosts.block

# Restart dnsmasq
sudo systemctl restart dnsmasq
sudo systemctl enable dnsmasq

# Verify it's running
sudo systemctl status dnsmasq
ss -ulnp | grep 53
```

### Part 3: Set Up SSH Key for Passwordless Sync

On your Mac:

```bash
# Generate SSH key if you don't have one
ssh-keygen -t ed25519 -C "block-distractions"

# Copy public key to VM
# Option 1: Via gcloud
gcloud compute ssh dns-server --command "mkdir -p ~/.ssh"
cat ~/.ssh/id_ed25519.pub | gcloud compute ssh dns-server --command "cat >> ~/.ssh/authorized_keys"

# Option 2: Manually add to VM's ~/.ssh/authorized_keys via Google Cloud Console

# Test SSH connection
ssh YOUR_USER@YOUR_VM_IP
```

### Part 4: Configure Passwordless Sudo on VM

On the VM, create a sudoers file for the sync commands:

```bash
sudo tee /etc/sudoers.d/block-sync << 'EOF'
YOUR_USERNAME ALL=(ALL) NOPASSWD: /bin/mv /tmp/hosts.block.tmp /etc/hosts.block
YOUR_USERNAME ALL=(ALL) NOPASSWD: /bin/chmod 644 /etc/hosts.block
YOUR_USERNAME ALL=(ALL) NOPASSWD: /bin/chown root\:root /etc/hosts.block
YOUR_USERNAME ALL=(ALL) NOPASSWD: /usr/bin/killall -HUP dnsmasq
EOF

sudo chmod 440 /etc/sudoers.d/block-sync
```

### Part 5: Test the Setup

From your Mac:

```bash
# Sync blocklist to VM
./block sync

# Verify blocking works
dig @YOUR_VM_IP twitter.com +short
# Should return: 127.0.0.1
```

---

## iPhone DNS Configuration

### The Challenge

iOS requires **encrypted DNS** (DNS over TLS or DNS over HTTPS) for system-wide DNS configuration via profiles. Cleartext DNS is not supported in iOS configuration profiles.

### Current Status: DNS over TLS (DoT) Setup

We have DoT working on the VM using stunnel, but iOS rejects self-signed certificates for DoT connections. The "Certificate Trust Settings" on iOS only applies to web browsing, not system services like DNS.

#### DoT Setup on VM (Already Configured)

```bash
# Install stunnel
sudo apt-get install -y stunnel4

# Create/copy TLS certificate (from certs/ directory)
sudo cp server.pem /etc/stunnel/
sudo chown stunnel4:stunnel4 /etc/stunnel/server.pem
sudo chmod 600 /etc/stunnel/server.pem

# Configure stunnel
sudo tee /etc/stunnel/dns-tls.conf << 'EOF'
pid = /var/run/stunnel4/dns-tls.pid
setuid = stunnel4
setgid = stunnel4

[dns-tls]
accept = 853
connect = 127.0.0.1:53
cert = /etc/stunnel/server.pem
EOF

# Create pid directory
sudo mkdir -p /var/run/stunnel4
sudo chown stunnel4:stunnel4 /var/run/stunnel4

# Enable and start stunnel
sudo sed -i 's/ENABLED=0/ENABLED=1/' /etc/default/stunnel4
sudo systemctl restart stunnel4
sudo systemctl enable stunnel4

# Open port 853 in Google Cloud Firewall
# (Create rule: allow-dns-tls, tcp:853, 0.0.0.0/0)
```

### Solution: Use a Real Domain with Let's Encrypt

For iOS to trust the DoT connection, you need a certificate from a trusted CA like Let's Encrypt.

**Requirements:**
1. A domain name you control
2. DNS A record pointing to your VM's IP

**Steps (TODO):**
1. Point domain to VM IP (e.g., `dns.yourdomain.com` → `34.127.22.131`)
2. Install certbot and get Let's Encrypt certificate
3. Update stunnel to use the Let's Encrypt certificate
4. Update iOS profile to use the domain name as ServerName

### Alternative: Per-WiFi DNS (No Profile Needed)

For WiFi-only blocking without a profile:

1. Go to **Settings → WiFi**
2. Tap the **(i)** next to your network
3. Tap **Configure DNS → Manual**
4. Delete existing servers, add your VM IP
5. Repeat for each WiFi network

**Limitations:** Only works on WiFi, not cellular.

---

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
│   ├── hosts.py       # /etc/hosts management + remote sync
│   ├── obsidian.py    # Condition checking
│   ├── wordcount.py   # Word counting for linked files
│   ├── unlock.py      # Unlock logic + shame prompts
│   └── daemon.py      # Background checker
├── services/          # Daemon service files
│   ├── com.block.daemon.plist     # macOS launchd
│   └── block-daemon.service       # Linux systemd
├── certs/             # TLS certificates for DoT (git-ignored)
│   ├── ca.crt         # Self-signed CA certificate
│   ├── ca.key         # CA private key
│   ├── server.crt     # Server certificate
│   ├── server.key     # Server private key
│   └── server.pem     # Combined cert+key for stunnel
└── dns-blocker.mobileconfig  # iOS DNS profile (DoT)
```

---

## Development Notes

### What Works

- ✅ Mac `/etc/hosts` blocking
- ✅ Proof-of-work unlock via Obsidian
- ✅ Emergency unlock with escalating waits
- ✅ Background daemon
- ✅ Remote sync to Google Cloud VM via SSH/SCP
- ✅ dnsmasq DNS blocking on VM
- ✅ DNS over TLS (stunnel) on VM
- ✅ TLS certificate generation

### What Doesn't Work (Yet)

- ❌ iOS DNS profile with self-signed certificate
  - iOS rejects self-signed certs for DoT even with CA trusted in Certificate Trust Settings
  - Need Let's Encrypt certificate with real domain

### Next Steps for iPhone Blocking

1. **Get a domain name** (or use existing one)
2. **Point DNS to VM IP** (A record: `dns.yourdomain.com` → VM IP)
3. **Install certbot on VM:**
   ```bash
   sudo apt-get install certbot
   sudo certbot certonly --standalone -d dns.yourdomain.com
   ```
4. **Update stunnel config to use Let's Encrypt cert:**
   ```bash
   sudo cat /etc/letsencrypt/live/dns.yourdomain.com/fullchain.pem \
            /etc/letsencrypt/live/dns.yourdomain.com/privkey.pem \
            > /etc/stunnel/server.pem
   ```
5. **Update iOS profile** (`dns-blocker.mobileconfig`):
   - Change `ServerName` to `dns.yourdomain.com`
   - Remove the CA certificate payload (not needed with Let's Encrypt)
6. **Set up auto-renewal** for Let's Encrypt certificate

### Domain Options

If you need a domain:
- **Free:** Freenom (.tk, .ml, etc.) - unreliable
- **Cheap:** Namecheap, Porkbun (~$10/year for .com)
- **Free subdomains:** DuckDNS, No-IP (dynamic DNS services)

**Note:** GitHub Pages cannot be used for this - it only serves static websites, not DNS records.
