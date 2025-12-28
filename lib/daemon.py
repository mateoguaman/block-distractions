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
from .hosts import get_hosts_manager
from .obsidian import get_obsidian_parser
from .unlock import get_unlock_manager

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
        self.state = get_state()
        self.hosts = get_hosts_manager()
        self.obsidian = get_obsidian_parser(
            self.config.obsidian_vault_path,
            self.config.daily_note_pattern,
        )
        self.unlock_manager = get_unlock_manager(
            self.config, self.state, self.hosts, self.obsidian
        )
        self.running = False

    def should_auto_unlock(self) -> bool:
        """Check if auto-unlock should happen now."""
        auto_settings = self.config.auto_unlock_settings

        if not auto_settings.get("enabled", True):
            return False

        # Check if we're past the earliest time
        earliest = auto_settings.get("earliest_time", "17:00")
        try:
            earliest_hour, earliest_minute = map(int, earliest.split(":"))
            now = datetime.now()
            if now.hour < earliest_hour or (
                now.hour == earliest_hour and now.minute < earliest_minute
            ):
                return False
        except ValueError:
            logger.warning(f"Invalid earliest_time format: {earliest}")

        # Check if already unlocked
        if not self.state.is_blocked:
            return False

        # Check conditions
        any_met, _ = self.unlock_manager.check_all_conditions()
        return any_met

    def run_check(self) -> None:
        """Run a single check cycle."""
        try:
            # Reload state from file to pick up changes from CLI
            self.state.load()

            # Always sync blocking state first
            self.unlock_manager.sync_blocking_state()

            # Check if auto-unlock should happen
            if self.should_auto_unlock():
                logger.info("Conditions met for auto-unlock, unlocking...")
                duration = self.config.unlock_settings.get("proof_of_work_duration", 7200)
                self.state.set_unlocked(duration)
                self.hosts.unblock_sites()
                logger.info(f"Auto-unlocked for {duration} seconds")
            else:
                # Make sure blocking is in sync with state
                if self.state.is_blocked:
                    if not self.hosts.is_blocking_active():
                        logger.info("Re-enabling blocking...")
                        self.hosts.block_sites(self.config.blocked_sites)
                else:
                    if self.hosts.is_blocking_active():
                        logger.info("Removing blocks (unlocked)...")
                        self.hosts.unblock_sites()

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
