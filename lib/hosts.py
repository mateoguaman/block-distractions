"""Hosts file management for blocking sites."""

import subprocess
import tempfile
import shutil
from pathlib import Path

HOSTS_FILE = Path("/etc/hosts")
BEGIN_MARKER = "# BEGIN BLOCK_DISTRACTIONS"
END_MARKER = "# END BLOCK_DISTRACTIONS"
BLOCK_IP = "127.0.0.1"


class HostsManager:
    """Manages the /etc/hosts file for blocking sites."""

    def __init__(self, hosts_path: Path | str | None = None):
        self.hosts_path = Path(hosts_path) if hosts_path else HOSTS_FILE

    def _read_hosts(self) -> str:
        """Read the current hosts file content."""
        if self.hosts_path.exists():
            return self.hosts_path.read_text()
        return ""

    def _write_hosts(self, content: str) -> bool:
        """Write content to hosts file using sudo."""
        try:
            # Write to a temp file first
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".hosts") as f:
                f.write(content)
                temp_path = f.name

            # Use sudo to copy the temp file to /etc/hosts
            result = subprocess.run(
                ["sudo", "cp", temp_path, str(self.hosts_path)],
                capture_output=True,
                text=True,
            )

            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

            if result.returncode != 0:
                print(f"Error updating hosts file: {result.stderr}")
                return False

            # Flush DNS cache
            self._flush_dns_cache()
            return True

        except Exception as e:
            print(f"Error updating hosts file: {e}")
            return False

    def _flush_dns_cache(self) -> None:
        """Flush the DNS cache (platform-specific)."""
        import platform

        system = platform.system()

        try:
            if system == "Darwin":  # macOS
                subprocess.run(
                    ["sudo", "dscacheutil", "-flushcache"],
                    capture_output=True,
                )
                subprocess.run(
                    ["sudo", "killall", "-HUP", "mDNSResponder"],
                    capture_output=True,
                )
            elif system == "Linux":
                # Try systemd-resolved first
                subprocess.run(
                    ["sudo", "systemd-resolve", "--flush-caches"],
                    capture_output=True,
                )
        except Exception:
            pass  # DNS flush is best-effort

    def _get_block_entries(self, sites: list[str]) -> str:
        """Generate hosts file entries for blocking sites."""
        lines = [BEGIN_MARKER]
        for site in sites:
            # Add both bare domain and www subdomain
            lines.append(f"{BLOCK_IP} {site}")
            if not site.startswith("www."):
                lines.append(f"{BLOCK_IP} www.{site}")
        lines.append(END_MARKER)
        return "\n".join(lines)

    def _remove_block_section(self, content: str) -> str:
        """Remove the block section from hosts content."""
        lines = content.split("\n")
        result = []
        in_block = False

        for line in lines:
            if line.strip() == BEGIN_MARKER:
                in_block = True
                continue
            if line.strip() == END_MARKER:
                in_block = False
                continue
            if not in_block:
                result.append(line)

        # Remove trailing empty lines
        while result and result[-1].strip() == "":
            result.pop()

        return "\n".join(result)

    def get_blocked_sites(self) -> list[str]:
        """Get list of currently blocked sites from hosts file."""
        content = self._read_hosts()
        sites = []
        in_block = False

        for line in content.split("\n"):
            if line.strip() == BEGIN_MARKER:
                in_block = True
                continue
            if line.strip() == END_MARKER:
                in_block = False
                continue
            if in_block and line.strip():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == BLOCK_IP:
                    site = parts[1]
                    if not site.startswith("www."):
                        sites.append(site)

        return sites

    def is_blocking_active(self) -> bool:
        """Check if blocking is currently active in hosts file."""
        content = self._read_hosts()
        return BEGIN_MARKER in content

    def block_sites(self, sites: list[str]) -> bool:
        """Block the given sites in the hosts file."""
        content = self._read_hosts()

        # Remove existing block section
        content = self._remove_block_section(content)

        # Ensure content ends with newline
        if content and not content.endswith("\n"):
            content += "\n"

        # Add new block section
        content += "\n" + self._get_block_entries(sites) + "\n"

        return self._write_hosts(content)

    def unblock_sites(self) -> bool:
        """Remove all site blocks from hosts file."""
        content = self._read_hosts()
        content = self._remove_block_section(content)

        # Ensure proper ending
        if content and not content.endswith("\n"):
            content += "\n"

        return self._write_hosts(content)

    def sync_with_config(self, sites: list[str], should_block: bool) -> bool:
        """Sync hosts file with desired state."""
        if should_block:
            return self.block_sites(sites)
        else:
            return self.unblock_sites()


def get_hosts_manager(hosts_path: Path | str | None = None) -> HostsManager:
    """Get a HostsManager instance."""
    return HostsManager(hosts_path)


class RemoteSyncManager:
    """Manages syncing hosts.block to a remote DNS server."""

    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.host = config.get("host", "")
        self.user = config.get("user", "")
        self.remote_path = config.get("hosts_path", "/etc/hosts.block")

    def sync(self, sites: list[str]) -> tuple[bool, str]:
        """Sync blocked sites to remote server.

        Returns:
            Tuple of (success, message)
        """
        if not self.enabled:
            return True, "Remote sync disabled"

        if not self.host or not self.user:
            return False, "Remote sync not configured (missing host or user)"

        # Generate hosts.block content
        lines = []
        for site in sites:
            lines.append(f"127.0.0.1 {site}")
            if not site.startswith("www."):
                lines.append(f"127.0.0.1 www.{site}")
        content = "\n".join(lines) + "\n" if lines else ""

        try:
            # Write to temp file
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".hosts") as f:
                f.write(content)
                temp_path = f.name

            # Copy to remote server
            remote = f"{self.user}@{self.host}"
            result = subprocess.run(
                ["scp", temp_path, f"{remote}:/tmp/hosts.block.tmp"],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, f"Failed to copy to remote: {result.stderr}"

            # Move to final location, fix permissions, and reload dnsmasq
            result = subprocess.run(
                ["ssh", remote,
                 "sudo mv /tmp/hosts.block.tmp /etc/hosts.block && "
                 "sudo chmod 644 /etc/hosts.block && "
                 "sudo chown root:root /etc/hosts.block && "
                 "sudo killall -HUP dnsmasq"],
                capture_output=True,
                text=True,
            )

            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

            if result.returncode != 0:
                return False, f"Failed to update remote: {result.stderr}"

            return True, f"Synced {len(sites)} sites to {self.host}"

        except Exception as e:
            return False, f"Sync error: {e}"


def get_remote_sync_manager(config: dict) -> RemoteSyncManager:
    """Get a RemoteSyncManager instance."""
    return RemoteSyncManager(config)
