#!/usr/bin/env python3
"""
Track coaching changes by scraping and diffing snapshots.

Usage:
    python scripts/track_changes.py [--force] [--skip-scrape]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from scrape_usatoday import scrape_coaches, save_data
except ImportError:
    print("Error: unable to import scrape_usatoday.py. Run from repo root.")
    sys.exit(1)

POWER_FOUR = {"SEC", "Big 10", "Big 12", "ACC"}
# TODO: Add Telegram notifications for alert-worthy changes.


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def parse_snapshot_date(path: Path) -> date | None:
    match = re.match(r"(\d{4}-\d{2}-\d{2})\.json$", path.name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def latest_snapshot(historical_dir: Path) -> tuple[date | None, Path | None]:
    if not historical_dir.exists():
        return None, None
    candidates = []
    for file_path in historical_dir.iterdir():
        if not file_path.is_file():
            continue
        snap_date = parse_snapshot_date(file_path)
        if snap_date:
            candidates.append((snap_date, file_path))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1]


def should_run(today: date, last_date: date | None) -> tuple[bool, str, int]:
    if last_date is None:
        return True, "no previous snapshot found", 0
    interval_days = 7 if today.month in {12, 1, 2} else 30
    days_since = (today - last_date).days
    return days_since >= interval_days, "interval reached" if days_since >= interval_days else "interval not reached", days_since


def load_snapshot(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def build_school_index(coaches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for coach in coaches:
        school = coach.get("school")
        if not school:
            continue
        key = normalize_text(school)
        index[key] = {
            "coach": coach.get("coach"),
            "school": school,
            "conference": coach.get("conference"),
        }
    return index


def build_coach_index(coaches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for coach in coaches:
        name = coach.get("coach")
        school = coach.get("school")
        if not name or not school:
            continue
        key = normalize_text(name)
        index[key] = {
            "coach": name,
            "school": school,
            "conference": coach.get("conference"),
        }
    return index


def is_power_four(conference: str | None) -> bool:
    return conference in POWER_FOUR


def detect_changes(previous: dict[str, Any], current: dict[str, Any], run_timestamp: str) -> list[dict[str, Any]]:
    prev_coaches = previous.get("coaches", [])
    curr_coaches = current.get("coaches", [])

    prev_by_school = build_school_index(prev_coaches)
    curr_by_school = build_school_index(curr_coaches)
    prev_by_coach = build_coach_index(prev_coaches)
    curr_by_coach = build_coach_index(curr_coaches)

    events: list[dict[str, Any]] = []

    # Detect new hires and departures by school
    for school_key, curr in curr_by_school.items():
        prev = prev_by_school.get(school_key)
        if not prev:
            events.append({
                "timestamp": run_timestamp,
                "changeType": "new_hire",
                "coach": curr.get("coach"),
                "school": curr.get("school"),
                "conference": curr.get("conference"),
                "previousCoach": None,
                "alert": is_power_four(curr.get("conference")),
            })
            continue
        if normalize_text(prev.get("coach")) != normalize_text(curr.get("coach")):
            events.append({
                "timestamp": run_timestamp,
                "changeType": "new_hire",
                "coach": curr.get("coach"),
                "school": curr.get("school"),
                "conference": curr.get("conference"),
                "previousCoach": prev.get("coach"),
                "alert": is_power_four(curr.get("conference")),
            })
            events.append({
                "timestamp": run_timestamp,
                "changeType": "departure",
                "coach": prev.get("coach"),
                "school": prev.get("school"),
                "conference": prev.get("conference"),
                "replacementCoach": curr.get("coach"),
                "alert": is_power_four(prev.get("conference")),
            })

    for school_key, prev in prev_by_school.items():
        if school_key not in curr_by_school:
            events.append({
                "timestamp": run_timestamp,
                "changeType": "departure",
                "coach": prev.get("coach"),
                "school": prev.get("school"),
                "conference": prev.get("conference"),
                "replacementCoach": None,
                "alert": is_power_four(prev.get("conference")),
            })

    # Detect position changes (coach moves to a different school)
    for coach_key, prev in prev_by_coach.items():
        curr = curr_by_coach.get(coach_key)
        if not curr:
            continue
        if normalize_text(prev.get("school")) != normalize_text(curr.get("school")):
            alert = is_power_four(curr.get("conference")) or is_power_four(prev.get("conference"))
            events.append({
                "timestamp": run_timestamp,
                "changeType": "position_change",
                "coach": curr.get("coach"),
                "previousSchool": prev.get("school"),
                "newSchool": curr.get("school"),
                "previousConference": prev.get("conference"),
                "newConference": curr.get("conference"),
                "alert": alert,
            })

    return events


def load_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"metadata": {"lastRun": None, "totalEvents": 0}, "events": []}
    with open(path) as f:
        return json.load(f)


def save_log(path: Path, log: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(log, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Track coaching changes with scheduled scraping")
    parser.add_argument("--data", default="data/coaches.json", help="Current data file path")
    parser.add_argument("--historical-dir", default="historical", help="Historical snapshot directory")
    parser.add_argument("--log", default="data/coaching_changes.json", help="Change log output path")
    parser.add_argument("--force", action="store_true", help="Force run regardless of schedule")
    parser.add_argument("--skip-scrape", action="store_true", help="Skip scraping and diff existing data")
    parser.add_argument("--today", help="Override today's date (YYYY-MM-DD)")
    args = parser.parse_args()

    script_root = Path(__file__).parent.parent
    data_path = script_root / args.data
    historical_dir = script_root / args.historical_dir
    log_path = script_root / args.log

    if args.today:
        today = date.fromisoformat(args.today)
    else:
        today = date.today()

    last_date, last_path = latest_snapshot(historical_dir)
    should_run_now, reason, days_since = should_run(today, last_date)

    if not args.force and not should_run_now:
        print(f"Skipping scrape: {reason} ({days_since} days since last snapshot on {last_date}).")
        return

    if not args.skip_scrape:
        coaches = scrape_coaches()
        save_data(coaches, data_path, historical=True)

    if not data_path.exists():
        print(f"Error: data file not found at {data_path}")
        sys.exit(1)

    current = load_snapshot(data_path)

    if last_path is None or not last_path.exists():
        print("No previous snapshot found; nothing to diff.")
        log = load_log(log_path)
        log["metadata"]["lastRun"] = datetime.now().isoformat(timespec="seconds")
        save_log(log_path, log)
        return

    previous = load_snapshot(last_path)

    run_timestamp = datetime.now().isoformat(timespec="seconds")
    events = detect_changes(previous, current, run_timestamp)

    log = load_log(log_path)
    log["events"].extend(events)
    log["metadata"]["lastRun"] = run_timestamp
    log["metadata"]["totalEvents"] = len(log["events"])
    save_log(log_path, log)

    alerts = [event for event in events if event.get("alert")]

    print(f"Detected {len(events)} changes.")
    if alerts:
        print(f"Alerts: {len(alerts)} major moves flagged.")
        for alert in alerts:
            change_type = alert.get("changeType")
            if change_type == "position_change":
                print(f"  {alert.get('coach')} moved from {alert.get('previousSchool')} to {alert.get('newSchool')}")
            elif change_type == "new_hire":
                print(f"  {alert.get('coach')} hired at {alert.get('school')}")
            elif change_type == "departure":
                print(f"  {alert.get('coach')} departed {alert.get('school')}")


if __name__ == "__main__":
    main()
