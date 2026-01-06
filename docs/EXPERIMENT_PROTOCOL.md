# Multi-Day Experiment Protocol

This document describes how to run and analyze a multi-day experiment to verify the block_distractions tool is working correctly.

## Overview

The experiment aims to:
1. Verify unlock expiry works correctly (unlock for 2 hours, then re-block)
2. Detect the "permanent unlock" bug (repeated auto-unlocks keeping you unlocked all day)
3. Confirm earliest_time is respected
4. Identify any other anomalies

## Prerequisites

1. **Experiment logging enabled** in `config.yaml`:
   ```yaml
   experiment:
     enabled: true
     days: 7  # How long to run the experiment
     started_at: 2026-01-06  # Today's date
   ```

2. **Daemon running** to generate logs:
   ```bash
   # Check if daemon is running
   launchctl list | grep block

   # Start if needed
   launchctl start com.block.daemon
   ```

3. **Test dependencies installed**:
   ```bash
   uv pip install pytest pytest-mock freezegun
   ```

## Running the Experiment

### Phase 1: Reset and Configure (Day 0)

1. **Update experiment start date**:
   ```yaml
   # In config.yaml
   experiment:
     enabled: true
     days: 7
     started_at: YYYY-MM-DD  # Today's date
   ```

2. **Clear old experiment logs** (optional):
   ```bash
   rm .logs/experiment.log*
   rm .logs/experiment.meta.json
   ```

3. **Force block to start fresh**:
   ```bash
   block on
   ```

4. **Verify daemon is running and logging**:
   ```bash
   tail -f .logs/experiment.log
   # Should see daemon_check events every 5 minutes
   ```

### Phase 2: Daily Monitoring (Days 1-7)

Each day, perform these checks:

1. **Morning check** (before earliest_time):
   ```bash
   block status
   # Should show: BLOCKED
   ```

2. **Complete your conditions** (e.g., workout, writing)

3. **After earliest_time** (e.g., after 5 PM):
   - The daemon should auto-unlock if conditions are met
   - Check status:
     ```bash
     block status
     # Should show: UNLOCKED with time remaining
     ```

4. **Monitor for re-unlock** (optional):
   - If you want to verify the bug, wait for unlock to expire
   - After 2 hours, check if it re-unlocks automatically
   - This is the bug we're investigating

5. **End of day check**:
   ```bash
   # Analyze today's activity
   uv run tools/analyze_experiment.py --days 1 -v
   ```

### Phase 3: Analysis (End of Experiment)

Run the full analysis:

```bash
# Full analysis of experiment period
uv run tools/analyze_experiment.py --days 7 -v

# JSON output for further processing
uv run tools/analyze_experiment.py --days 7 --json > experiment_results.json
```

## What to Look For

### Expected Behavior (No Bugs)

- **One unlock per day** after completing conditions
- **Unlock expires after 2 hours** (or configured duration)
- **No unlocks before earliest_time** (e.g., before 5 PM)
- **After expiry, stays blocked** until next day

### Bug Indicators

1. **Repeated Auto-Unlock Bug** (stays unlocked all day):
   - Multiple unlock events on the same day
   - Pattern: unlock → 2 hours → re-unlock → 2 hours → re-unlock...
   - Analysis output: "WARNING: Multiple unlocks in one day!"

2. **Early Unlock Bug**:
   - Unlock events before `earliest_time`
   - Analysis output: "early_unlock" anomaly

3. **Expiry Not Working**:
   - No state transitions from unlocked → blocked
   - `unlock_remaining` never reaching 0

## Interpreting Results

### Analysis Report Sections

1. **Auto-Unlock Analysis**:
   - `total_auto_unlocks`: How many times auto-unlock fired
   - `unlocks_by_day`: Unlocks per day (should be 0 or 1)
   - `anomalies`: Any detected issues

2. **Unlock Expiry Analysis**:
   - `total_unlock_events`: Times you got unlocked
   - `total_expiry_events`: Times unlock expired correctly

3. **Daemon Health**:
   - `total_checks`: Daemon check count
   - `avg_check_interval_seconds`: Should be ~300s (5 min)
   - `errors`: Any errors during operation

### Sample Output Interpretation

```
## Auto-Unlock Analysis
Total auto-unlocks detected: 14
Unlocks by day: {'2026-01-01': 3, '2026-01-02': 2, '2026-01-03': 3, ...}

### ANOMALIES DETECTED (3)
  - [repeated_auto_unlock] Auto-unlock triggered 3 times on 2026-01-01
  - [repeated_auto_unlock] Auto-unlock triggered 2 times on 2026-01-02
```

This would indicate the "permanent unlock" bug is present.

## Running Automated Tests

In addition to the experiment, run the test suite:

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific bug-related tests
uv run pytest tests/test_daemon.py::TestAutoUnlockBug -v
uv run pytest tests/test_integration.py::TestBugScenarios -v
```

Key tests to watch:
- `test_bug_repro_re_unlock_after_expiry`: Reproduces the repeated unlock bug
- `test_scenario_permanent_unlock`: Integration test for the bug

## Fixing Issues

If bugs are confirmed, potential fixes include:

1. **Track daily unlock count** in state (like emergency_count)
2. **Add "unlocked_today" flag** that prevents re-unlock after expiry
3. **Configurable behavior**: Option to allow or prevent re-unlock

See `docs/BUG_ANALYSIS.md` (if created) for detailed fix proposals.

## Data Files

- `.logs/experiment.log`: Raw JSON event log (main data source)
- `.logs/experiment.meta.json`: Experiment metadata
- `.logs/daemon.log`: Daemon operational log (errors, info)
