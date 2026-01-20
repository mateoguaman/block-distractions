# Google Cloud VM Firewall Configuration

This documents the firewall rules on the DNS server VM (34.127.22.131).

## Problem Solved

The VM was being abused as an open DNS resolver by external IPs, causing:
- 2GB+ syslog files from dnsmasq query logging
- Disk filling to 100%
- SCP failures for blocklist sync

## Changes Made (2026-01-20)

### 1. Disabled dnsmasq query logging
```bash
# In /etc/dnsmasq.conf, commented out:
#log-queries
```

### 2. Improved log rotation
```bash
# /etc/logrotate.d/rsyslog - changed from weekly to:
rotate 3
daily
maxsize 100M

# Added /etc/logrotate.d/btmp:
/var/log/btmp {
    rotate 2
    monthly
    maxsize 10M
    create 0660 root utmp
    missingok
}
```

### 3. Installed iptables with rate limiting
```bash
sudo apt-get install iptables iptables-persistent
```

**Current rules** (rate limit, not block):
- DNS (53 UDP/TCP): 10 queries/sec, burst 20
- DNS-over-TLS (853): 10 queries/sec, burst 20
- Phone API (8080): 5 requests/sec, burst 10
- SSH (22): No limit (need reliable access)

## Current iptables Rules

```bash
# View current rules
sudo iptables -L INPUT -n -v

# Rules in /etc/iptables/rules.v4:
-A INPUT -i lo -j ACCEPT
-A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
-A INPUT -p tcp --dport 22 -j ACCEPT
-A INPUT -p udp --dport 53 -m limit --limit 10/sec --limit-burst 20 -j ACCEPT
-A INPUT -p udp --dport 53 -j DROP
-A INPUT -p tcp --dport 53 -m limit --limit 10/sec --limit-burst 20 -j ACCEPT
-A INPUT -p tcp --dport 53 -j DROP
-A INPUT -p tcp --dport 853 -m limit --limit 10/sec --limit-burst 20 -j ACCEPT
-A INPUT -p tcp --dport 853 -j DROP
-A INPUT -p tcp --dport 8080 -m limit --limit 5/sec --limit-burst 10 -j ACCEPT
-A INPUT -p tcp --dport 8080 -j DROP
-A INPUT -j ACCEPT
```

## How to Revert

### Remove all firewall rules (back to open):
```bash
ssh 34.127.22.131 "sudo iptables -F INPUT && sudo netfilter-persistent save"
```

### Re-enable dnsmasq logging (if needed for debugging):
```bash
ssh 34.127.22.131 "sudo sed -i 's/^#log-queries/log-queries/' /etc/dnsmasq.conf && sudo systemctl restart dnsmasq"
```

### Revert log rotation to weekly:
```bash
ssh 34.127.22.131 "sudo sed -i 's/daily/weekly/' /etc/logrotate.d/rsyslog && sudo sed -i '/maxsize/d' /etc/logrotate.d/rsyslog"
```

## Monitoring

Check disk usage:
```bash
ssh 34.127.22.131 "df -h /"
```

Check firewall stats (packets dropped):
```bash
ssh 34.127.22.131 "sudo iptables -L INPUT -n -v"
```

Check recent logs:
```bash
ssh 34.127.22.131 "sudo tail -50 /var/log/syslog"
```

## Notes

- Rate limiting allows legitimate use from any IP while stopping abuse
- Normal DNS usage is 1-2 queries/sec; 10/sec limit is generous
- Rules persist across reboots via `iptables-persistent`
