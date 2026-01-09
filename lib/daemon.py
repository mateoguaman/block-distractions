"""Background daemon for automated condition checking and unlocking."""

import time
import signal
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path

from .config import get_config
from .state import get_state
from .hosts import get_hosts_manager, get_remote_sync_manager
from .obsidian import get_obsidian_parser
from .unlock import get_unlock_manager
from .experiment import get_experiment_logger
from .poll import get_poll_manager

# Set up logging with rotation
LOG_DIR = Path(__file__).parent.parent / ".logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / "daemon.log"
LOG_MAX_BYTES = 1024 * 1024  # 1 MB
LOG_BACKUP_COUNT = 2  # Keep 2 backup files (daemon.log.1, daemon.log.2)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Rotating file handler
file_handler = RotatingFileHandler(
    LOG_PATH,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(file_handler)

# Also log to stderr for launchd/systemd
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(stream_handler)


class BlockDaemon:
    """Background daemon for automated blocking/unblocking."""

    def __init__(self, config_path: Path | str | None = None):
        self.config = get_config(config_path)
        self.state = get_state(self.config)
        self.hosts = get_hosts_manager()
        self.obsidian = get_obsidian_parser(
            self.config.obsidian_vault_path,
            self.config.daily_note_pattern,
        )
        self.remote_sync = get_remote_sync_manager(self.config.remote_sync_settings)
        self.unlock_manager = get_unlock_manager(
            self.config, self.state, self.hosts, self.obsidian, self.remote_sync
        )
        self.experiment = get_experiment_logger(self.config)
        self.poll_manager = get_poll_manager(self.config.phone_api_settings)
        self.running = False

    def _note_info(self) -> dict[str, object]:
        """Collect metadata about today's daily note."""
        note_path = self.obsidian.get_today_note_path()
        info: dict[str, object] = {"path": str(note_path), "exists": note_path.exists()}
        if info["exists"]:
            stat = note_path.stat()
            info["mtime"] = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            info["size"] = stat.st_size
        return info

    def _state_context(self) -> dict[str, object]:
        """Collect detailed state and remote settings."""
        snapshot = self.state.get_debug_snapshot()
        remote = self.state.remote_store
        remote_info = {
            "enabled": bool(remote and remote.enabled),
            "host": remote.host if remote else "",
            "state_path": remote.state_path if remote else "",
            "timezone": remote.timezone if remote else "",
            "use_sudo": remote.use_sudo if remote else False,
        }
        return {"state": snapshot, "remote_state": remote_info}

    def sync_phone_status(self) -> None:
        """Sync current status to phone API so UI shows accurate data."""
        if not self.poll_manager.enabled:
            return

        try:
            status = self.unlock_manager.get_status()
            self.poll_manager.update_status(status)
        except Exception as e:
            logger.error(f"Error syncing phone status: {e}")

    def process_poll_requests(self) -> None:
        """Check for and process any pending phone unlock requests."""
        if not self.poll_manager.enabled:
            return

        try:
            pending = self.poll_manager.check_pending_requests()
            if not pending:
                return

            for request in pending:
                req_id = request.get("id", "unknown")
                req_type = request.get("type", "")
                logger.info(f"Processing phone request: {req_type} (id={req_id})")

                result = {"success": False, "message": "Unknown request type"}

                if req_type == "unlock":
                    # Proof-of-work unlock (checks conditions)
                    success, message = self.unlock_manager.proof_of_work_unlock()
                    result = {"success": success, "message": message}
                    if success:
                        logger.info(f"Phone unlock successful: {message}")
                    else:
                        logger.info(f"Phone unlock failed: {message}")

                elif req_type == "emergency":
                    # Emergency unlock (non-interactive)
                    success, message = self.unlock_manager.emergency_unlock(interactive=False)
                    result = {"success": success, "message": message}
                    if success:
                        logger.info(f"Phone emergency unlock successful: {message}")
                    else:
                        logger.info(f"Phone emergency unlock failed: {message}")

                # Mark the request as completed
                self.poll_manager.mark_completed(req_id, result)

                # Log the event
                self.experiment.log_event(
                    "phone_request_processed",
                    request_id=req_id,
                    request_type=req_type,
                    result=result,
                )

            # Update the remote status so phone UI reflects changes
            status = self.unlock_manager.get_status()
            self.poll_manager.update_status(status)

        except Exception as e:
            logger.error(f"Error processing phone requests: {e}")

    def evaluate_auto_unlock(self) -> tuple[bool, dict[str, object]]:
        """Check if auto-unlock should happen now, with context."""
        auto_settings = self.config.auto_unlock_settings
        info: dict[str, object] = {
            "enabled": bool(auto_settings.get("enabled", True)),
            "earliest_time": auto_settings.get("earliest_time", "17:00"),
            "check_interval": auto_settings.get("check_interval", 300),
            "now": datetime.now().isoformat(timespec="seconds"),
            "earliest_passed": None,
            "earliest_parse_error": None,
            "blocked": None,
            "unlocked_via_conditions_today": None,
            "any_conditions_met": False,
            "conditions": [],
        }

        if not info["enabled"]:
            return False, info

        # Check if we're past the earliest time
        earliest = info["earliest_time"]
        try:
            earliest_hour, earliest_minute = map(int, earliest.split(":"))
            now = datetime.now()
            if now.hour < earliest_hour or (
                now.hour == earliest_hour and now.minute < earliest_minute
            ):
                info["earliest_passed"] = False
                return False, info
            info["earliest_passed"] = True
        except ValueError:
            info["earliest_parse_error"] = f"Invalid earliest_time format: {earliest}"
            logger.warning(info["earliest_parse_error"])
            return False, info

        # Check if already unlocked via conditions today (prevents re-unlock after expiry)
        already_unlocked_today = self.state.unlocked_via_conditions_today
        info["unlocked_via_conditions_today"] = already_unlocked_today
        if already_unlocked_today:
            logger.debug("Skipping auto-unlock: already unlocked via conditions today")
            return False, info

        # Check if already unlocked
        blocked = self.state.is_blocked
        info["blocked"] = blocked
        if not blocked:
            return False, info

        # Check conditions
        any_met, conditions = self.unlock_manager.check_all_conditions()
        info["any_conditions_met"] = any_met
        info["conditions"] = [
            {"name": name, "met": met, "description": desc}
            for name, met, desc in conditions
        ]
        return any_met, info

    def run_check(self) -> None:
        """Run a single check cycle."""
        try:
            # Reload state from file to pick up changes from CLI
            self.state.load()

            # Check for phone unlock requests first (polling)
            self.process_poll_requests()

            # Reload state again in case phone request modified it
            self.state.load()

            pre_state = self._state_context()
            pre_hosts_blocking = self.hosts.is_blocking_active()

            # Always sync blocking state first
            self.unlock_manager.sync_blocking_state()

            # Check if auto-unlock should happen
            should_unlock, auto_info = self.evaluate_auto_unlock()
            self.experiment.log_event(
                "daemon_check",
                note=self._note_info(),
                hosts_blocking_before_sync=pre_hosts_blocking,
                hosts_blocking_after_sync=self.hosts.is_blocking_active(),
                auto_unlock=auto_info,
                config={
                    "obsidian_vault_path": str(self.config.obsidian_vault_path),
                    "daily_note_pattern": self.config.daily_note_pattern,
                    "unlock": self.config.unlock_settings,
                },
                state_before_sync=pre_state.get("state"),
                remote_state=pre_state.get("remote_state"),
                state_after_sync=self._state_context().get("state"),
            )

            action = "no_change"
            if should_unlock:
                logger.info("Conditions met for auto-unlock, unlocking...")
                duration = self.config.unlock_settings.get("proof_of_work_duration", 7200)
                self.state.set_unlocked(duration)
                self.state.mark_unlocked_via_conditions()  # Prevent re-unlock after expiry
                self.hosts.unblock_sites()
                # Sync to remote (unblock all)
                if self.remote_sync.enabled:
                    success, msg = self.remote_sync.sync([])
                    if not success:
                        logger.error(f"Remote sync failed during auto-unlock: {msg}")
                logger.info(f"Auto-unlocked for {duration} seconds")
                action = "auto_unlock"
            else:
                # Make sure blocking is in sync with state
                if self.state.is_blocked:
                    if not self.hosts.is_blocking_active():
                        logger.info("Re-enabling blocking...")
                        self.hosts.block_sites(self.config.blocked_sites)
                        if self.remote_sync.enabled:
                            success, msg = self.remote_sync.sync(self.config.blocked_sites)
                            if not success:
                                logger.error(f"Remote sync failed during re-block: {msg}")
                        action = "reblock_hosts"
                else:
                    if self.hosts.is_blocking_active():
                        logger.info("Removing blocks (unlocked)...")
                        self.hosts.unblock_sites()
                        if self.remote_sync.enabled:
                            success, msg = self.remote_sync.sync([])
                            if not success:
                                logger.error(f"Remote sync failed during unblock: {msg}")
                        action = "unblock_hosts"

            self.experiment.log_event(
                "daemon_check_complete",
                action=action,
                note=self._note_info(),
                hosts_blocking=self.hosts.is_blocking_active(),
                **self._state_context(),
            )

            # Sync status to phone API every cycle
            self.sync_phone_status()

        except Exception as e:
            logger.error(f"Error during check: {e}")

    def run(self) -> None:
        """Run the daemon loop."""
        interval = self.config.auto_unlock_settings.get("check_interval", 300)
        logger.info(f"Starting daemon with {interval}s check interval")

        self.running = True

        # Set up signal handlers
        def handle_signal(signum, frame):
            logger.info("Received shutdown signal")
            self.running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        while self.running:
            self.run_check()
            time.sleep(interval)

        logger.info("Daemon stopped")

    def run_once(self) -> None:
        """Run a single check (for testing or one-shot usage)."""
        self.run_check()


def run_daemon(config_path: Path | str | None = None) -> None:
    """Entry point for running the daemon."""
    daemon = BlockDaemon(config_path)
    daemon.run()


def run_check_once(config_path: Path | str | None = None) -> None:
    """Run a single check cycle."""
    daemon = BlockDaemon(config_path)
    daemon.run_once()


if __name__ == "__main__":
    run_daemon()
