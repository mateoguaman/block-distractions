# Block Distractions

A CLI tool that blocks distracting websites with proof-of-work and emergency unlock mechanisms. Supports blocking on Mac, iPhone, and other devices via a remote DNS server.

## Features

- **Cross-device blocking** via remote DNS server (Mac, iPhone, any device)
- **Proof-of-work unlock** - Earn access by completing conditions tracked in Obsidian
- **Emergency unlock** - Limited bypass with escalating wait times and shame prompts
- **Background daemon** - Automatically checks conditions and unlocks when earned
- **Safari-proof blocking** - Uses DNS-level blocking that Safari cannot bypass

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│   Mac           │         │   iPhone        │
│   Safari ───────┤         │   Safari ───────┤
│   Chrome ───────┤         │                 │
│   All apps ─────┤         └────────┬────────┘
└────────┬────────┘                  │
         │                           │
         │ DNS queries               │ DNS-over-TLS
         │ (port 53)                 │ (port 853)
         └───────────┬───────────────┘
                     ▼
            ┌─────────────────────┐
            │ Google Cloud VM     │
            │ dnsmasq             │
            │                     │
            │ Blocks ALL DNS      │
            │ record types        │
            │ (A, AAAA, HTTPS)    │
            └─────────────────────┘
```

## Why DNS-Level Blocking?

### The Problem with /etc/hosts

Traditional `/etc/hosts` blocking only works for A (IPv4) and AAAA (IPv6) DNS records. Modern browsers, especially **Safari on macOS and iOS**, query **HTTPS DNS records (RFC 9460)** which contain IP address hints directly in the DNS response:

```
$ dig people.com HTTPS +short
1 . alpn="h3,h2" ipv4hint=162.159.141.224 ipv6hint=2606:4700:7::1d8
```

Safari uses these embedded IP hints to connect directly, completely bypassing `/etc/hosts`. This is why some sites load in Safari even when blocked in the hosts file.

### The Solution

We use **dnsmasq** with `address=/domain/` directives, which block **ALL** DNS record types for a domain (A, AAAA, HTTPS, SVCB, etc.). The dnsmasq server runs on a cloud VM, and all devices point their DNS to this server.

## Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) - Python package manager
- Obsidian (for condition tracking)
- Google Cloud account (for remote DNS server)
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) (for VM management)

## Quick Start

If you already have a VM set up, just configure your devices:

**Mac:**
```bash
sudo networksetup -setdnsservers Wi-Fi YOUR_VM_IP
```

**Ubuntu:**
```bash
sudo resolvectl dns eth0 YOUR_VM_IP
# or use NetworkManager - see full setup guide
```

**iPhone:** Install the DNS profile (see [iPhone Setup](#iphone-dns-configuration))

---

## Full Setup Guide

### Part 1: Local Setup (Mac/Ubuntu)

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/block_distractions.git
cd block_distractions

# Create your secrets file from the template
cp config.secrets.example.yaml config.secrets.yaml

# Run setup (installs dependencies, creates block command, configures daemon)
./setup.sh
```

The setup script automatically detects your OS and configures the appropriate daemon (launchd on macOS, systemd on Ubuntu).

**Important:** The `config.secrets.yaml` file contains your personal settings (Obsidian vault path, VM IP, SSH username) and is git-ignored. You'll fill in the values as you complete the setup.

### Part 2: Create Google Cloud VM

1. **Create a Google Cloud account** at https://cloud.google.com
   - Free $300 credit for 90 days
   - After trial: ~$5/month for e2-micro instance

2. **Install gcloud CLI:**
   ```bash
   # macOS
   brew install google-cloud-sdk

   # Ubuntu
   sudo apt-get install apt-transport-https ca-certificates gnupg curl
   curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
   echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
   sudo apt-get update && sudo apt-get install google-cloud-cli

   # Then authenticate
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```

3. **Create VM instance:**
   - Go to Compute Engine → VM instances → Create Instance
   - Name: `dns-server`
   - Region: Choose one close to you (e.g., `us-west1-b`)
   - Machine type: `e2-micro` (free tier eligible)
   - Boot disk: Ubuntu 22.04 LTS, 10GB
   - Click Create

4. **Note the External IP** (e.g., `34.127.22.131`)

5. **Open firewall ports:**
   - Go to VPC Network → Firewall → Create Firewall Rule
   - Create two rules:

   | Name | Direction | Targets | Source | Protocols |
   |------|-----------|---------|--------|-----------|
   | `allow-dns` | Ingress | All instances | `0.0.0.0/0` | `tcp:53`, `udp:53` |
   | `allow-dns-tls` | Ingress | All instances | `0.0.0.0/0` | `tcp:853` |

### Part 3: Configure dnsmasq on VM

SSH into your VM:
```bash
gcloud compute ssh dns-server --zone=YOUR_ZONE
```

Run these commands on the VM:

```bash
# Install dnsmasq
sudo apt-get update
sudo apt-get install -y dnsmasq

# Disable systemd-resolved (conflicts with dnsmasq on port 53)
sudo sed -i 's/#DNSStubListener=yes/DNSStubListener=no/' /etc/systemd/resolved.conf
sudo systemctl restart systemd-resolved

# Remove --local-service flag (allows external DNS queries)
sudo sed -i 's/DNSMASQ_OPTS="${DNSMASQ_OPTS} --local-service"/#DNSMASQ_OPTS="${DNSMASQ_OPTS} --local-service"/' /etc/init.d/dnsmasq

# Configure dnsmasq
sudo tee /etc/dnsmasq.conf << 'EOF'
# Forward to upstream DNS
no-resolv
server=8.8.8.8
server=8.8.4.4

# Logging (optional - comment out for production)
log-queries

# Cache
cache-size=1000

# Include blocklist (uses address=// format to block ALL record types)
conf-dir=/etc/dnsmasq.d/,*.conf
EOF

# Create blocklist directory and empty blocklist
sudo mkdir -p /etc/dnsmasq.d
sudo touch /etc/dnsmasq.d/blocklist.conf

# Restart dnsmasq
sudo systemctl restart dnsmasq
sudo systemctl enable dnsmasq

# Verify it's running
sudo systemctl status dnsmasq
```

### Part 4: Set Up SSH Access

The `block sync` command uses SSH to upload the blocklist. Set up SSH access:

**On your Mac:**
```bash
# This creates SSH keys and adds them to the VM automatically
gcloud compute ssh dns-server --zone=YOUR_ZONE --command="echo 'SSH works'"
```

**Find your SSH username:**
```bash
gcloud compute ssh dns-server --zone=YOUR_ZONE --command="whoami"
# This will output your username (e.g., "mateo")
```

**Add SSH config for easier access:**
```bash
cat >> ~/.ssh/config << EOF

# Block Distractions DNS Server
Host YOUR_VM_IP
    User YOUR_USERNAME
    IdentityFile ~/.ssh/google_compute_engine
EOF
```

**Test direct SSH:**
```bash
ssh YOUR_USERNAME@YOUR_VM_IP "echo 'Direct SSH works'"
```

### Part 5: Configure Passwordless Sudo on VM

The sync command needs sudo access on the VM. SSH into the VM and run:

```bash
sudo tee /etc/sudoers.d/block-sync << 'EOF'
YOUR_USERNAME ALL=(ALL) NOPASSWD: /bin/mv /tmp/blocklist.conf.tmp /etc/dnsmasq.d/blocklist.conf
YOUR_USERNAME ALL=(ALL) NOPASSWD: /bin/chmod 644 /etc/dnsmasq.d/blocklist.conf
YOUR_USERNAME ALL=(ALL) NOPASSWD: /bin/chown root\:root /etc/dnsmasq.d/blocklist.conf
YOUR_USERNAME ALL=(ALL) NOPASSWD: /bin/systemctl restart dnsmasq
EOF

sudo chmod 440 /etc/sudoers.d/block-sync
```

### Part 6: Configure Block Distractions

Edit `config.secrets.yaml` on your Mac with your personal settings:

```yaml
obsidian:
  vault_path: /full/path/to/your/obsidian/vault

remote_sync:
  host: YOUR_VM_IP           # e.g., 34.127.22.131
  user: YOUR_USERNAME        # e.g., mateo (from gcloud whoami)
```

The non-sensitive settings (blocklist, conditions, unlock timing) are in `config.yaml` which is version-controlled.

**Test the sync:**
```bash
block sync
# Should output: "Synced X sites to YOUR_VM_IP"
```

**Verify blocking on VM:**
```bash
dig @YOUR_VM_IP twitter.com A +short
# Should return nothing (blocked)

dig @YOUR_VM_IP twitter.com HTTPS +short
# Should return nothing (blocked)

dig @YOUR_VM_IP google.com A +short
# Should return real IP (not blocked)
```

### Part 7: Point Your DNS to VM

**macOS:**
```bash
sudo networksetup -setdnsservers Wi-Fi YOUR_VM_IP
```

**Ubuntu (using systemd-resolved):**
```bash
# Set DNS server (temporary, resets on reboot)
sudo resolvectl dns eth0 YOUR_VM_IP

# Or edit netplan config for permanent change
sudo nano /etc/netplan/01-netcfg.yaml
# Add under your interface:
#   nameservers:
#     addresses: [YOUR_VM_IP]
sudo netplan apply
```

**Ubuntu (using NetworkManager):**
```bash
# Find your connection name
nmcli connection show
# Set DNS (replace "Wired connection 1" with your connection name)
nmcli connection modify "Wired connection 1" ipv4.dns YOUR_VM_IP
nmcli connection modify "Wired connection 1" ipv4.ignore-auto-dns yes
nmcli connection up "Wired connection 1"
```

**Test:** Try loading a blocked site - it should fail.

**To revert (use automatic DNS):**
```bash
# macOS
sudo networksetup -setdnsservers Wi-Fi empty

# Ubuntu (systemd-resolved)
sudo resolvectl revert eth0

# Ubuntu (NetworkManager)
nmcli connection modify "Wired connection 1" ipv4.ignore-auto-dns no
nmcli connection up "Wired connection 1"
```

---

## iPhone DNS Configuration

iOS requires **encrypted DNS** (DNS-over-TLS) for system-wide configuration. This requires a valid TLS certificate.

### Step 1: Get a Domain with Let's Encrypt Certificate

**Create DuckDNS subdomain (free):**
1. Go to https://www.duckdns.org/ and sign in
2. Create a subdomain (e.g., `myblock` → `myblock.duckdns.org`)
3. Set the IP to your VM's external IP
4. Copy your **token**

**Get Let's Encrypt certificate on VM:**
```bash
# Install certbot with DuckDNS plugin
sudo apt-get install -y certbot python3-pip
sudo pip3 install certbot-dns-duckdns

# Create credentials file
echo "dns_duckdns_token = YOUR_TOKEN" | sudo tee /etc/letsencrypt/duckdns.ini
sudo chmod 600 /etc/letsencrypt/duckdns.ini

# Get certificate
sudo certbot certonly \
  --non-interactive \
  --agree-tos \
  --email your-email@example.com \
  --preferred-challenges dns \
  --authenticator dns-duckdns \
  --dns-duckdns-credentials /etc/letsencrypt/duckdns.ini \
  --dns-duckdns-propagation-seconds 60 \
  -d YOUR_SUBDOMAIN.duckdns.org
```

### Step 2: Set Up stunnel for DNS-over-TLS

```bash
# Install stunnel
sudo apt-get install -y stunnel4

# Create combined certificate
sudo bash -c 'cat /etc/letsencrypt/live/YOUR_SUBDOMAIN.duckdns.org/fullchain.pem \
              /etc/letsencrypt/live/YOUR_SUBDOMAIN.duckdns.org/privkey.pem \
              > /etc/stunnel/server.pem'
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
```

### Step 3: Create iOS Configuration Profile

Create your profile from the template:
```bash
cp dns-blocker.mobileconfig.example dns-blocker.mobileconfig
```

Edit `dns-blocker.mobileconfig` and replace the placeholders:
```xml
<key>ServerAddresses</key>
<array>
    <string>YOUR_VM_IP</string>          <!-- Replace with your VM's IP -->
</array>
<key>ServerName</key>
<string>YOUR_SUBDOMAIN.duckdns.org</string>  <!-- Replace with your DuckDNS domain -->
```

### Step 4: Install on iPhone

1. Transfer `dns-blocker.mobileconfig` to iPhone (AirDrop or email)
2. Settings → General → VPN & Device Management → Install profile
3. The profile will be "Not Verified" but this is normal for self-created profiles

### Step 5: Verify iPhone Blocking

1. Clear Safari cache: Settings → Safari → Clear History and Website Data
2. Try loading a blocked site in Safari
3. It should fail to load

---

## Usage

```bash
block status              # Show current status and conditions
block unlock              # Unlock via proof-of-work (checks Obsidian)
block emergency           # Emergency unlock with escalating waits
block on                  # Force enable blocking
block off                 # Temporarily disable (testing only)
block list                # List blocked sites
block add <site>          # Add a site to blocklist (syncs to VM)
block remove <site>       # Remove a site from blocklist (syncs to VM)
block sync                # Manually sync blocklist to VM
block daemon              # Run background daemon (usually auto-started)
block check               # Run a single condition check
```

## Configuration

Edit `config.yaml` to customize:

### Obsidian Settings

```yaml
obsidian:
  vault_path: "~/Documents/your-vault"
  daily_note_pattern: "Daily/{date}.md"  # {date} = YYYY-MM-DD
```

### Conditions

Any ONE condition being met allows proof-of-work unlock:

```yaml
conditions:
  workout:
    type: checkbox
    pattern: "- [x] Workout"

  writing:
    type: linked_wordcount
    section: "Writing"
    section_any_level: true
    minimum: 500
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
  # Add more as needed
```

### Remote Sync

```yaml
remote_sync:
  enabled: true
  host: 34.127.22.131              # Your VM's external IP
  user: mateo                       # SSH username (from gcloud whoami)
  blocklist_path: /etc/dnsmasq.d/blocklist.conf
```

---

## How It Works

1. **Blocking**: `block add` adds sites to `config.yaml` and syncs to VM's dnsmasq
2. **DNS Resolution**: All devices query the VM, which returns NXDOMAIN for blocked domains
3. **Proof-of-work**: Check Obsidian daily note for completed conditions to unlock
4. **Emergency**: Escalating wait times (30s → 60s → 120s) + type "I CHOOSE DISTRACTION"
5. **Daemon**: Runs in background, auto-unlocks after `earliest_time` if conditions met

---

## Gotchas and Troubleshooting

### Browser still loads blocked sites

**Cause:** Browser is using cached DNS or the DNS change hasn't propagated.

**Fix:**
```bash
# Flush DNS cache (macOS)
sudo dscacheutil -flushcache && sudo killall -9 mDNSResponder

# Flush DNS cache (Ubuntu)
sudo resolvectl flush-caches
# or on older systems:
sudo systemd-resolve --flush-caches

# Clear browser cache (Safari)
# Safari → Settings → Privacy → Manage Website Data → Remove All

# Verify DNS is pointing to VM (macOS)
scutil --dns | grep nameserver

# Verify DNS is pointing to VM (Ubuntu)
resolvectl status | grep "DNS Servers"
# or
cat /etc/resolv.conf
# Should show your VM IP
```

### iPhone blocking not working for some sites

**Cause:** HTTPS DNS records were not being blocked (old hosts-file format).

**Fix:** Ensure VM uses `address=/domain/` format (not `addn-hosts`):
```bash
# On VM - check blocklist format
cat /etc/dnsmasq.d/blocklist.conf
# Should show: address=/twitter.com/

# If it shows "127.0.0.1 twitter.com", re-sync:
block sync
```

### SSH permission denied

**Cause:** SSH key not set up for direct access.

**Fix:**
```bash
# Use gcloud to set up SSH keys automatically
gcloud compute ssh dns-server --zone=YOUR_ZONE --command="whoami"

# Add to SSH config
cat >> ~/.ssh/config << EOF
Host YOUR_VM_IP
    User YOUR_USERNAME
    IdentityFile ~/.ssh/google_compute_engine
EOF
```

### "block sync" fails with sudo error

**Cause:** Passwordless sudo not configured on VM.

**Fix:** On the VM, create `/etc/sudoers.d/block-sync` (see [Part 5](#part-5-configure-passwordless-sudo-on-vm)).

### Remote sync intermittently fails

**Cause:** SSH connections to Google Cloud VMs can occasionally be reset by peer.

**Behavior:** The tool automatically retries transient SSH failures up to 3 times with exponential backoff (2s, 4s, 8s delays). Failures are logged to `.logs/daemon.log`.

**Check logs:**
```bash
tail -f .logs/daemon.log | grep -i "sync"
```

**Transient errors that trigger retry:**
- "Connection reset by peer"
- "Connection refused"
- "Connection timed out"
- "Network is unreachable"
- "No route to host"

### DNS not working at all (can't load any sites)

**Cause:** VM is down, dnsmasq crashed, or firewall blocking.

**Fix:**
```bash
# Check VM status
gcloud compute instances list

# Check dnsmasq on VM
gcloud compute ssh dns-server --zone=YOUR_ZONE --command="sudo systemctl status dnsmasq"

# Temporarily revert to automatic DNS (macOS)
sudo networksetup -setdnsservers Wi-Fi empty

# Temporarily revert to automatic DNS (Ubuntu)
sudo resolvectl revert eth0
```

### Let's Encrypt certificate expired

**Cause:** Certificates expire after 90 days.

**Fix:** On VM:
```bash
sudo certbot renew

# Rebuild stunnel certificate
sudo bash -c 'cat /etc/letsencrypt/live/YOUR_SUBDOMAIN.duckdns.org/fullchain.pem \
              /etc/letsencrypt/live/YOUR_SUBDOMAIN.duckdns.org/privkey.pem \
              > /etc/stunnel/server.pem'
sudo systemctl restart stunnel4
```

**Automate renewal:** Add to crontab:
```bash
0 0 1 * * certbot renew --quiet && cat /etc/letsencrypt/live/YOUR_SUBDOMAIN.duckdns.org/fullchain.pem /etc/letsencrypt/live/YOUR_SUBDOMAIN.duckdns.org/privkey.pem > /etc/stunnel/server.pem && systemctl restart stunnel4
```

### Browser using DNS-over-HTTPS (DoH) bypassing your DNS

**Cause:** Chrome/Firefox have built-in DoH that bypasses system DNS.

**Fix:**
- Chrome: `chrome://settings/security` → disable "Use secure DNS"
- Firefox: `about:preferences#privacy` → Network Settings → disable "Enable DNS over HTTPS"

---

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

---

## Uninstalling

**macOS:**
```bash
# Revert DNS to automatic
sudo networksetup -setdnsservers Wi-Fi empty

# Stop and remove daemon
launchctl bootout gui/$(id -u)/com.block.daemon
rm ~/Library/LaunchAgents/com.block.daemon.plist

# Remove command
sudo rm /usr/local/bin/block

# Remove passwordless sudo
sudo rm /etc/sudoers.d/block-distractions

# Remove hosts entries (legacy, may not exist)
sudo sed -i '' '/BLOCK_DISTRACTIONS/,/END BLOCK_DISTRACTIONS/d' /etc/hosts
```

**Ubuntu:**
```bash
# Revert DNS to automatic
sudo resolvectl revert eth0
# or with NetworkManager:
nmcli connection modify "Wired connection 1" ipv4.ignore-auto-dns no

# Stop and remove daemon
systemctl --user stop block-daemon
systemctl --user disable block-daemon
rm ~/.config/systemd/user/block-daemon.service
systemctl --user daemon-reload

# Remove command
sudo rm /usr/local/bin/block

# Remove passwordless sudo
sudo rm /etc/sudoers.d/block-distractions

# Remove hosts entries (legacy, may not exist)
sudo sed -i '/BLOCK_DISTRACTIONS/,/END BLOCK_DISTRACTIONS/d' /etc/hosts
```

**Both platforms:**
```bash
# Optional: Delete VM to stop charges
gcloud compute instances delete dns-server --zone=YOUR_ZONE
```

---

## Files

```
block_distractions/
├── block                  # CLI entry point
├── config.yaml            # Non-sensitive configuration (version controlled)
├── config.secrets.yaml    # Your secrets: vault path, VM IP, username (git-ignored)
├── config.secrets.example.yaml  # Template for secrets file
├── setup.sh               # Installation script
├── pyproject.toml         # Python dependencies
├── lib/                   # Python modules
│   ├── config.py          # Configuration loading
│   ├── state.py           # Daily state tracking
│   ├── hosts.py           # /etc/hosts + remote sync (address=// format)
│   ├── obsidian.py        # Condition checking
│   ├── wordcount.py       # Word counting for linked files
│   ├── unlock.py          # Unlock logic + shame prompts
│   └── daemon.py          # Background checker
├── services/              # Daemon service files
│   ├── com.block.daemon.plist     # macOS launchd
│   └── block-daemon.service       # Linux systemd
├── dns-blocker.mobileconfig.example  # iOS DNS profile template
└── dns-blocker.mobileconfig       # Your iOS profile (git-ignored)
```

---

## Security Considerations

- **VM exposure**: Your DNS server is publicly accessible. Consider restricting source IPs in firewall rules if you have a static IP.
- **DNS privacy**: All your DNS queries go through your VM. The VM logs are only accessible to you.
- **Bypassing**: Determined users can change DNS settings. This tool is for self-control, not enforced restriction.
