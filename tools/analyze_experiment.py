#!/usr/bin/env python3
"""
Analyze experiment logs to detect anomalies and verify correct behavior.

Usage:
    uv run tools/analyze_experiment.py [--days N] [--verbose]

This script analyzes the experiment.log file to:
1. Detect repeated auto-unlocks (the "permanent unlock" bug)
2. Verify earliest_time is respected
3. Check for unlock expiry behavior
4. Generate a daily summary report
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any


LOG_PATH = Path(__file__).parent.parent / ".logs" / "experiment.log"


def parse_log_line(line: str) -> dict[str, Any] | None:
    """Parse a JSON log line."""
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None


def load_log_entries(log_path: Path = LOG_PATH, days: int | None = None) -> list[dict]:
    """Load log entries, optionally filtering by recent days."""
    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        return []

    entries = []
    cutoff = None
    if days:
        cutoff = datetime.now() - timedelta(days=days)

    with open(log_path) as f:
        for line in f:
            entry = parse_log_line(line)
            if entry:
                if cutoff:
                    try:
                        ts = datetime.fromisoformat(entry.get("ts", ""))
                        if ts < cutoff:
                            continue
                    except (ValueError, TypeError):
                        continue
                entries.append(entry)

    return entries


def group_by_day(entries: list[dict]) -> dict[str, list[dict]]:
    """Group entries by date."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        ts = entry.get("ts", "")
        if ts:
            day = ts.split("T")[0]
            by_day[day].append(entry)
    return dict(by_day)


def analyze_auto_unlocks(entries: list[dict]) -> dict[str, Any]:
    """Analyze auto-unlock events for anomalies."""
    auto_unlocks = []
    for entry in entries:
        if entry.get("event") == "daemon_check":
            auto_info = entry.get("auto_unlock", {})
            if auto_info.get("any_conditions_met"):
                # Check if this led to an actual unlock
                state_after = entry.get("state_after_sync", {})
                if not state_after.get("is_blocked", True):
                    auto_unlocks.append({
                        "ts": entry.get("ts"),
                        "conditions": auto_info.get("conditions", []),
                        "earliest_time": auto_info.get("earliest_time"),
                        "earliest_passed": auto_info.get("earliest_passed"),
                        "state": state_after,
                    })

    # Detect repeated unlocks in same day
    by_day = defaultdict(list)
    for unlock in auto_unlocks:
        day = unlock["ts"].split("T")[0]
        by_day[day].append(unlock)

    anomalies = []
    for day, unlocks in by_day.items():
        if len(unlocks) > 1:
            anomalies.append({
                "type": "repeated_auto_unlock",
                "day": day,
                "count": len(unlocks),
                "times": [u["ts"] for u in unlocks],
                "description": f"Auto-unlock triggered {len(unlocks)} times on {day}",
            })

    # Check for early unlocks (before earliest_time)
    for unlock in auto_unlocks:
        if unlock.get("earliest_passed") is False:
            anomalies.append({
                "type": "early_unlock",
                "ts": unlock["ts"],
                "earliest_time": unlock["earliest_time"],
                "description": f"Unlock at {unlock['ts']} before earliest_time {unlock['earliest_time']}",
            })

    return {
        "total_auto_unlocks": len(auto_unlocks),
        "unlocks_by_day": {k: len(v) for k, v in by_day.items()},
        "anomalies": anomalies,
    }


def analyze_unlock_expiry(entries: list[dict]) -> dict[str, Any]:
    """Analyze unlock expiry behavior."""
    # Look for state transitions from unlocked to blocked
    state_changes = []
    prev_state = None

    for entry in entries:
        if entry.get("event") in ("daemon_check", "daemon_check_complete"):
            state = entry.get("state", entry.get("state_after_sync", {}))
            is_blocked = state.get("is_blocked", True)
            unlocked_until = state.get("unlocked_until", 0)

            if prev_state is not None:
                prev_blocked = prev_state.get("is_blocked", True)

                # Transition: unlocked -> blocked (expiry)
                if not prev_blocked and is_blocked:
                    state_changes.append({
                        "type": "expiry",
                        "ts": entry.get("ts"),
                        "prev_unlock_until": prev_state.get("unlocked_until"),
                        "description": "Unlock expired, now blocked",
                    })

                # Transition: blocked -> unlocked
                elif prev_blocked and not is_blocked:
                    state_changes.append({
                        "type": "unlock",
                        "ts": entry.get("ts"),
                        "unlocked_until": unlocked_until,
                        "description": "Transitioned from blocked to unlocked",
                    })

            prev_state = state

    return {
        "state_changes": state_changes,
        "total_expiries": len([c for c in state_changes if c["type"] == "expiry"]),
        "total_unlocks": len([c for c in state_changes if c["type"] == "unlock"]),
    }


def analyze_daemon_health(entries: list[dict]) -> dict[str, Any]:
    """Analyze daemon operation health."""
    checks = []
    errors = []

    for entry in entries:
        if entry.get("event") == "daemon_check":
            checks.append(entry.get("ts"))
        if "error" in entry.get("event", "").lower():
            errors.append({
                "ts": entry.get("ts"),
                "message": entry.get("message", entry.get("error", "Unknown")),
            })

    # Calculate check frequency
    if len(checks) >= 2:
        intervals = []
        for i in range(1, len(checks)):
            try:
                t1 = datetime.fromisoformat(checks[i - 1])
                t2 = datetime.fromisoformat(checks[i])
                intervals.append((t2 - t1).total_seconds())
            except (ValueError, TypeError):
                continue

        avg_interval = sum(intervals) / len(intervals) if intervals else 0
    else:
        avg_interval = 0

    return {
        "total_checks": len(checks),
        "total_errors": len(errors),
        "avg_check_interval_seconds": round(avg_interval, 1),
        "errors": errors[:10],  # First 10 errors
    }


def generate_daily_summary(day: str, entries: list[dict]) -> dict[str, Any]:
    """Generate summary for a single day."""
    # Find unlock events
    unlocks = []
    blocks = []
    conditions_met = []

    for entry in entries:
        state = entry.get("state", entry.get("state_after_sync", {}))
        auto_info = entry.get("auto_unlock", {})

        if auto_info.get("any_conditions_met"):
            conditions_met.append(entry.get("ts"))

        if entry.get("event") == "daemon_check_complete":
            action = entry.get("action", "")
            if action == "auto_unlock":
                unlocks.append(entry.get("ts"))
            elif action == "reblock_hosts":
                blocks.append(entry.get("ts"))

    return {
        "day": day,
        "events_count": len(entries),
        "conditions_met_times": conditions_met,
        "unlock_times": unlocks,
        "reblock_times": blocks,
        "unlock_count": len(unlocks),
    }


def print_report(analysis: dict[str, Any], verbose: bool = False):
    """Print the analysis report."""
    print("\n" + "=" * 60)
    print("BLOCK DISTRACTIONS - EXPERIMENT ANALYSIS REPORT")
    print("=" * 60)

    # Auto-unlock analysis
    auto = analysis.get("auto_unlocks", {})
    print(f"\n## Auto-Unlock Analysis")
    print(f"Total auto-unlocks detected: {auto.get('total_auto_unlocks', 0)}")
    print(f"Unlocks by day: {auto.get('unlocks_by_day', {})}")

    # Collect all anomalies including from daily summaries
    all_anomalies = list(auto.get("anomalies", []))

    # Check daily summaries for multiple unlocks
    for summary in analysis.get("daily_summaries", []):
        if summary.get("unlock_count", 0) > 1:
            all_anomalies.append({
                "type": "repeated_unlock",
                "day": summary["day"],
                "count": summary["unlock_count"],
                "times": summary.get("unlock_times", []),
                "description": f"Multiple unlocks ({summary['unlock_count']}) on {summary['day']}",
            })

    if all_anomalies:
        print(f"\n### ANOMALIES DETECTED ({len(all_anomalies)})")
        for anomaly in all_anomalies:
            print(f"  - [{anomaly['type']}] {anomaly['description']}")
            if anomaly.get("times"):
                print(f"    Times: {', '.join(anomaly['times'])}")
    else:
        print("\n### No anomalies detected")

    # Expiry analysis
    expiry = analysis.get("unlock_expiry", {})
    print(f"\n## Unlock Expiry Analysis")
    print(f"Total unlock events: {expiry.get('total_unlocks', 0)}")
    print(f"Total expiry events: {expiry.get('total_expiries', 0)}")

    if verbose and expiry.get("state_changes"):
        print("\n### State Changes:")
        for change in expiry["state_changes"][:20]:  # First 20
            print(f"  - [{change['ts']}] {change['type']}: {change['description']}")

    # Daemon health
    health = analysis.get("daemon_health", {})
    print(f"\n## Daemon Health")
    print(f"Total daemon checks: {health.get('total_checks', 0)}")
    print(f"Average check interval: {health.get('avg_check_interval_seconds', 0)}s")
    print(f"Errors: {health.get('total_errors', 0)}")

    if verbose and health.get("errors"):
        print("\n### Recent Errors:")
        for err in health["errors"]:
            print(f"  - [{err['ts']}] {err['message']}")

    # Daily summaries
    if analysis.get("daily_summaries"):
        print(f"\n## Daily Summaries")
        for summary in analysis["daily_summaries"]:
            day = summary["day"]
            unlocks = summary["unlock_count"]
            events = summary["events_count"]
            print(f"\n### {day}")
            print(f"  Events: {events}")
            print(f"  Unlocks: {unlocks}")
            if unlocks > 1:
                print(f"  *** WARNING: Multiple unlocks in one day! ***")
            if summary["unlock_times"]:
                print(f"  Unlock times: {', '.join(summary['unlock_times'])}")

    # Verdict
    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)

    issues = []

    # Check for anomalies
    if all_anomalies:
        for anomaly in all_anomalies:
            if anomaly["type"] in ("repeated_auto_unlock", "repeated_unlock"):
                issues.append(
                    f"REPEATED UNLOCK BUG: {anomaly.get('count', 'Multiple')} unlocks "
                    f"on {anomaly['day']} - auto-unlock is re-triggering after expiry"
                )
            elif anomaly["type"] == "early_unlock":
                issues.append(f"Early unlock (before earliest_time) at {anomaly.get('ts', 'unknown')}")

    if issues:
        print("\nISSUES FOUND:")
        for issue in issues:
            print(f"  - {issue}")
        print("\nDIAGNOSIS:")
        print("  The 'repeated unlock' bug occurs when:")
        print("  1. Conditions are met (e.g., workout checked)")
        print("  2. Auto-unlock triggers, unlocking for 2 hours")
        print("  3. After 2 hours, unlock expires")
        print("  4. Daemon checks conditions - still met - auto-unlock triggers AGAIN")
        print("  5. Result: effective permanent unlock once conditions are met")
        print("\nRecommendation: Implement 'unlocked_today' tracking to prevent re-unlock")
    else:
        print("\nNo issues detected. System appears to be functioning correctly.")

    print()


def main():
    parser = argparse.ArgumentParser(description="Analyze experiment logs")
    parser.add_argument("--days", type=int, default=7, help="Days of logs to analyze")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Load entries
    entries = load_log_entries(days=args.days)
    if not entries:
        print("No log entries found.")
        sys.exit(1)

    print(f"Loaded {len(entries)} log entries from the past {args.days} days")

    # Run analysis
    analysis = {
        "auto_unlocks": analyze_auto_unlocks(entries),
        "unlock_expiry": analyze_unlock_expiry(entries),
        "daemon_health": analyze_daemon_health(entries),
    }

    # Generate daily summaries
    by_day = group_by_day(entries)
    analysis["daily_summaries"] = [
        generate_daily_summary(day, day_entries)
        for day, day_entries in sorted(by_day.items())
    ]

    if args.json:
        print(json.dumps(analysis, indent=2))
    else:
        print_report(analysis, verbose=args.verbose)


if __name__ == "__main__":
    main()
