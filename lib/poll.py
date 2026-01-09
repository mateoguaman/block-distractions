"""Poll manager for checking phone unlock requests from remote API."""

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PollManager:
    """Manages polling for unlock requests from the remote API.

    Uses SSH to check the request queue on the Google VM and
    mark requests as completed after processing.
    """

    # Retry settings (same as RemoteSyncManager)
    MAX_RETRIES = 3
    INITIAL_BACKOFF = 2
    BACKOFF_MULTIPLIER = 2

    def __init__(self, config: dict):
        """Initialize the poll manager.

        Args:
            config: The phone_api configuration dict with:
                - enabled: bool
                - host: VM IP address
                - user: SSH username
                - data_dir: Remote data directory (default /var/lib/block_distractions)
                - auth_token: Optional auth token for API calls
        """
        self.enabled = config.get("enabled", False)
        self.host = config.get("host", "")
        self.user = config.get("user", "")
        self.data_dir = config.get("data_dir", "/var/lib/block_distractions")
        self.auth_token = config.get("auth_token", "")

    def _run_ssh(self, command: str, description: str) -> tuple[bool, str]:
        """Run a command over SSH with retry logic.

        Returns:
            Tuple of (success, output_or_error)
        """
        if not self.host or not self.user:
            return False, "SSH not configured"

        remote = f"{self.user}@{self.host}"
        cmd = ["ssh", remote, command]

        backoff = self.INITIAL_BACKOFF
        last_error = ""

        for attempt in range(self.MAX_RETRIES):
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30
                )

                if result.returncode == 0:
                    return True, result.stdout.strip()

                last_error = result.stderr.strip()

                # Check if it's a transient SSH error
                transient_errors = [
                    "Connection reset by peer",
                    "Connection refused",
                    "Connection timed out",
                    "Network is unreachable",
                    "No route to host",
                ]
                is_transient = any(err in last_error for err in transient_errors)

                if not is_transient or attempt == self.MAX_RETRIES - 1:
                    break

                logger.warning(
                    f"Poll {description} failed (attempt {attempt + 1}/{self.MAX_RETRIES}): "
                    f"{last_error}. Retrying in {backoff}s..."
                )
                time.sleep(backoff)
                backoff *= self.BACKOFF_MULTIPLIER

            except subprocess.TimeoutExpired:
                last_error = "Command timed out"
                if attempt == self.MAX_RETRIES - 1:
                    break
                time.sleep(backoff)
                backoff *= self.BACKOFF_MULTIPLIER

        return False, last_error

    def check_pending_requests(self) -> list[dict]:
        """Check for pending unlock requests.

        Returns:
            List of pending request dicts, each with 'id' and 'type' keys.
            Returns empty list on error or if disabled.
        """
        if not self.enabled:
            return []

        requests_file = f"{self.data_dir}/requests.json"
        cmd = f"cat {requests_file} 2>/dev/null || echo '[]'"

        success, output = self._run_ssh(cmd, "check pending")
        if not success:
            logger.error(f"Failed to check pending requests: {output}")
            return []

        try:
            requests = json.loads(output)
            # Filter to only pending requests
            pending = [r for r in requests if r.get("status") == "pending"]
            return pending
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse requests JSON: {e}")
            return []

    def mark_completed(self, request_id: str, result: dict[str, Any]) -> bool:
        """Mark a request as completed.

        Args:
            request_id: The request ID to mark complete
            result: The result dict to store with the request

        Returns:
            True if successful
        """
        if not self.enabled:
            return False

        requests_file = f"{self.data_dir}/requests.json"
        # Base64 encode the result to avoid shell escaping issues
        import base64
        result_b64 = base64.b64encode(json.dumps(result).encode()).decode()
        completed_at = time.time()

        # Use a Python one-liner to update the request in place
        python_script = f"""
import json, base64
try:
    result = json.loads(base64.b64decode('{result_b64}').decode())
    with open('{requests_file}', 'r') as f:
        requests = json.load(f)
    for r in requests:
        if r['id'] == '{request_id}':
            r['status'] = 'completed'
            r['result'] = result
            r['completed_at'] = {completed_at}
            break
    completed = [r for r in requests if r.get('status') == 'completed']
    pending = [r for r in requests if r.get('status') == 'pending']
    requests = pending + completed[-10:]
    with open('{requests_file}', 'w') as f:
        json.dump(requests, f, indent=2)
    print('ok')
except Exception as e:
    print(f'error: {{e}}')
"""
        cmd = f"python3 -c \"{python_script}\""
        success, output = self._run_ssh(cmd, "mark completed")

        if success and output.strip() == "ok":
            return True

        logger.error(f"Failed to mark request completed: {output}")
        return False

    def update_status(self, status: dict[str, Any]) -> bool:
        """Update the cached status on the remote server.

        This is called after processing requests so the phone UI
        can show updated status.

        Args:
            status: The status dict from UnlockManager.get_status()

        Returns:
            True if successful
        """
        if not self.enabled:
            return False

        status_file = f"{self.data_dir}/status.json"
        # Base64 encode to avoid shell escaping issues
        import base64
        status_b64 = base64.b64encode(json.dumps(status).encode()).decode()

        cmd = f"python3 -c \"import base64; print(base64.b64decode('{status_b64}').decode())\" > {status_file}"

        success, output = self._run_ssh(cmd, "update status")
        if not success:
            logger.error(f"Failed to update remote status: {output}")
            return False

        return True


def get_poll_manager(config: dict) -> PollManager:
    """Get a PollManager instance."""
    return PollManager(config)
