"""Hosts file management for blocking sites.

NOTE: Local /etc/hosts blocking is disabled because Safari bypasses it via
HTTPS DNS records (RFC 9460). Actual blocking is done via remote dnsmasq
using the RemoteSyncManager class below. The HostsManager class remains as
a no-op stub for interface compatibility.
"""

import logging
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class HostsManager:
    """No-op stub for local hosts file management.

    Local /etc/hosts blocking doesn't work for Safari (which uses HTTPS DNS
    records with IP hints that bypass hosts file). Actual blocking is handled
    by RemoteSyncManager syncing to a remote dnsmasq server.

    This class remains for interface compatibility but does nothing.
    """

    def __init__(self, hosts_path: Path | str | None = None):
        pass

    def get_blocked_sites(self) -> list[str]:
        """Return empty list - local hosts not used."""
        return []

    def is_blocking_active(self) -> bool:
        """Return False - local hosts not used."""
        return False

    def block_sites(self, sites: list[str]) -> bool:
        """No-op - blocking handled by RemoteSyncManager."""
        logger.debug(f"HostsManager.block_sites called (no-op): {len(sites)} sites")
        return True

    def unblock_sites(self) -> bool:
        """No-op - blocking handled by RemoteSyncManager."""
        logger.debug("HostsManager.unblock_sites called (no-op)")
        return True

    def sync_with_config(self, sites: list[str], should_block: bool) -> bool:
        """No-op - blocking handled by RemoteSyncManager."""
        logger.debug(f"HostsManager.sync_with_config called (no-op): should_block={should_block}")
        return True


def get_hosts_manager(hosts_path: Path | str | None = None) -> HostsManager:
    """Get a HostsManager instance (no-op stub)."""
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
