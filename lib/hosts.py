"""Hosts file management for blocking sites."""

import logging
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

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
                # Use -9 to force restart mDNSResponder (HUP doesn't always reload hosts)
                subprocess.run(
                    ["sudo", "killall", "-9", "mDNSResponder"],
                    capture_output=True,
                )
            elif system == "Linux":
                # Try resolvectl first (Ubuntu 20.04+), fall back to systemd-resolve
                result = subprocess.run(
                    ["sudo", "resolvectl", "flush-caches"],
                    capture_output=True,
                )
                if result.returncode != 0:
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
            # Add both IPv4 and IPv6 blocking for each domain
            # IPv6 is needed because some sites have AAAA records and Safari prefers IPv6
            lines.append(f"{BLOCK_IP} {site}")
            lines.append(f"::1 {site}")
            if not site.startswith("www."):
                lines.append(f"{BLOCK_IP} www.{site}")
                lines.append(f"::1 www.{site}")
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
        current_content = self._read_hosts()

        # Build new content
        base_content = self._remove_block_section(current_content)
        if base_content and not base_content.endswith("\n"):
            base_content += "\n"
        new_content = base_content + "\n" + self._get_block_entries(sites) + "\n"

        # Only write if content actually changed (avoid unnecessary DNS flushes)
        if new_content.strip() == current_content.strip():
            return True  # Already up to date

        return self._write_hosts(new_content)

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
    """Manages syncing blocklist to a remote dnsmasq server.

    Uses dnsmasq address=// format which blocks ALL DNS record types
    (A, AAAA, HTTPS, SVCB, etc.) to prevent Safari's HTTPS record bypass.

    Includes retry logic with exponential backoff for SSH connection failures.
    """

    # Retry settings
    MAX_RETRIES = 3
    INITIAL_BACKOFF = 2  # seconds
    BACKOFF_MULTIPLIER = 2

    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.host = config.get("host", "")
        self.user = config.get("user", "")
        # Default to new dnsmasq.d location for address= format
        self.remote_path = config.get("blocklist_path", "/etc/dnsmasq.d/blocklist.conf")

    def _run_with_retry(self, cmd: list[str], description: str) -> tuple[bool, str]:
        """Run a command with retry logic for transient SSH failures.

        Returns:
            Tuple of (success, error_message or empty string)
        """
        backoff = self.INITIAL_BACKOFF
        last_error = ""

        for attempt in range(self.MAX_RETRIES):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                return True, ""

            last_error = result.stderr.strip()

            # Check if it's a transient SSH error worth retrying
            transient_errors = [
                "Connection reset by peer",
                "Connection refused",
                "Connection timed out",
                "Network is unreachable",
                "No route to host",
            ]
            is_transient = any(err in last_error for err in transient_errors)

            if not is_transient or attempt == self.MAX_RETRIES - 1:
                # Non-transient error or final attempt
                break

            logger.warning(
                f"Remote sync {description} failed (attempt {attempt + 1}/{self.MAX_RETRIES}): "
                f"{last_error}. Retrying in {backoff}s..."
            )
            time.sleep(backoff)
            backoff *= self.BACKOFF_MULTIPLIER

        return False, last_error

    def sync(self, sites: list[str]) -> tuple[bool, str]:
        """Sync blocked sites to remote server.

        Includes retry logic with exponential backoff for transient SSH failures.

        Returns:
            Tuple of (success, message)
        """
        if not self.enabled:
            return True, "Remote sync disabled"

        if not self.host or not self.user:
            return False, "Remote sync not configured (missing host or user)"

        # Generate dnsmasq address= format
        # This blocks ALL record types (A, AAAA, HTTPS, SVCB, etc.)
        # which prevents Safari's HTTPS record IP hint bypass
        lines = []
        for site in sites:
            lines.append(f"address=/{site}/")
            if not site.startswith("www."):
                lines.append(f"address=/www.{site}/")
        content = "\n".join(sorted(set(lines))) + "\n" if lines else ""

        temp_path = None
        try:
            # Write to temp file
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".conf") as f:
                f.write(content)
                temp_path = f.name

            # Copy to remote server with retry
            remote = f"{self.user}@{self.host}"
            success, error = self._run_with_retry(
                ["scp", temp_path, f"{remote}:/tmp/blocklist.conf.tmp"],
                "scp"
            )
            if not success:
                return False, f"Failed to copy to remote: {error}"

            # Move to final location, fix permissions, and restart dnsmasq with retry
            success, error = self._run_with_retry(
                ["ssh", remote,
                 f"sudo mv /tmp/blocklist.conf.tmp {self.remote_path} && "
                 f"sudo chmod 644 {self.remote_path} && "
                 f"sudo chown root:root {self.remote_path} && "
                 "sudo systemctl restart dnsmasq"],
                "ssh"
            )
            if not success:
                return False, f"Failed to update remote: {error}"

            logger.info(f"Remote sync successful: {len(sites)} sites to {self.host}")
            return True, f"Synced {len(sites)} sites to {self.host}"

        except subprocess.TimeoutExpired:
            return False, "Remote sync timed out"
        except Exception as e:
            logger.error(f"Remote sync error: {e}")
            return False, f"Sync error: {e}"
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)


def get_remote_sync_manager(config: dict) -> RemoteSyncManager:
    """Get a RemoteSyncManager instance."""
    return RemoteSyncManager(config)
