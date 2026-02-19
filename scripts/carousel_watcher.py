#!/usr/bin/env python3
"""
Weekly coaching carousel watcher.

Usage:
  python scripts/carousel_watcher.py
  python scripts/carousel_watcher.py --dry-run
  python scripts/carousel_watcher.py --fbs-only
  python scripts/carousel_watcher.py --team alabama
  python scripts/carousel_watcher.py --snapshot data/carousel_snapshot.json
  python scripts/carousel_watcher.py --delay 1.5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, date
from pathlib import Path

# Add scripts/ to sys.path so we can import sibling scripts
sys.path.insert(0, str(Path(__file__).parent))
from typing import Iterable, Optional
import sqlite3

import requests

from scrape_collegepressbox import get_team_slugs, load_cookie, scrape_team_staff


LOG_PATH = Path(__file__).parent.parent / "logs" / "carousel_watcher.log"
DEFAULT_SNAPSHOT = Path(__file__).parent.parent / "data" / "carousel_snapshot.json"
DB_PATH = Path(__file__).parent.parent / "db" / "coaches.db"

TELEGRAM_TOKEN = "8062029183:AAHfpLME0TcNXbJXfwPaxgGEELZHgaf8pm8"
TELEGRAM_CHAT_ID = "-1003393722321"
TELEGRAM_ENDPOINT = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("carousel_watcher")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)

    return logger


def escape_markdown(text: str) -> str:
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def load_fbs_slugs(logger: logging.Logger) -> set[str]:
    if not DB_PATH.exists():
        logger.warning("FBS-only requested but %s not found; skipping filter", DB_PATH)
        return set()

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.slug
            FROM schools s
            JOIN conferences c ON s.conference_id = c.id
            WHERE c.division = 'FBS' AND s.slug IS NOT NULL
            """
        )
        rows = cursor.fetchall()
        conn.close()
    except sqlite3.Error as exc:
        logger.warning("FBS-only requested but DB query failed: %s", exc)
        return set()

    slugs = {row[0] for row in rows if row and row[0]}
    if not slugs:
        logger.warning("FBS-only requested but no FBS slugs found in DB")
    return slugs


def normalize_team_list(
    teams: list[dict],
    fbs_only: bool,
    logger: logging.Logger,
) -> list[str]:
    slugs = [team["slug"] for team in teams if team.get("slug")]

    if not fbs_only:
        return slugs

    fbs_slugs = load_fbs_slugs(logger)
    if not fbs_slugs:
        return slugs

    return [slug for slug in slugs if slug in fbs_slugs]


def select_by_position(coaches: Iterable[dict], predicate) -> Optional[dict]:
    matches = [c for c in coaches if predicate(c)]
    if not matches:
        return None
    matches.sort(key=lambda c: c.get("name", "").casefold())
    coach = matches[0]
    return {"name": coach.get("name"), "position": coach.get("position")}


def build_school_snapshot(coaches: list[dict]) -> dict:
    if not coaches:
        return {}

    head_coach = select_by_position(
        coaches,
        lambda c: bool(c.get("is_head_coach"))
        or (c.get("position") or "").casefold() == "head coach",
    )
    offensive_coordinator = select_by_position(
        coaches,
        lambda c: "offensive coordinator" in (c.get("position") or "").casefold(),
    )
    defensive_coordinator = select_by_position(
        coaches,
        lambda c: "defensive coordinator" in (c.get("position") or "").casefold(),
    )
    explicit_play_caller = select_by_position(
        coaches,
        lambda c: "play caller" in (c.get("position") or "").casefold(),
    )
    play_caller = explicit_play_caller or offensive_coordinator

    school = coaches[0].get("school") or ""
    school_slug = coaches[0].get("school_slug") or ""

    return {
        "head_coach": head_coach,
        "offensive_coordinator": offensive_coordinator,
        "defensive_coordinator": defensive_coordinator,
        "play_caller": play_caller,
        "school": school,
        "school_slug": school_slug,
    }


def build_snapshot(by_slug: dict[str, list[dict]]) -> dict:
    snapshot = {
        "timestamp": datetime.now().replace(microsecond=0).isoformat(),
        "by_school": {},
    }
    for slug, coaches in by_slug.items():
        snapshot["by_school"][slug] = build_school_snapshot(coaches)
    return snapshot


def diff_entry(old: Optional[dict], new: Optional[dict]) -> bool:
    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    return (old.get("name"), old.get("position")) != (new.get("name"), new.get("position"))


def format_change(
    change_type: str,
    emoji: str,
    label: str,
    school: str,
    new_entry: Optional[dict],
    old_entry: Optional[dict],
) -> str:
    new_name = new_entry.get("name") if new_entry else "Unknown"
    old_name = old_entry.get("name") if old_entry else "Unknown"

    new_name = escape_markdown(new_name)
    old_name = escape_markdown(old_name)
    school = escape_markdown(school)

    if change_type == "head_coach":
        return (
            f"{emoji} *{label}* — {school}\n"
            f"➡️ New HC: {new_name}\n"
            f"⬅️ Previous HC: {old_name}"
        )
    if change_type == "offensive_coordinator":
        return (
            f"{emoji} *{label}* — {school}\n"
            f"➡️ New OC: {new_name}\n"
            f"⬅️ Previous OC: {old_name}"
        )
    if change_type == "defensive_coordinator":
        return (
            f"{emoji} *{label}* — {school}\n"
            f"➡️ New DC: {new_name}\n"
            f"⬅️ Previous DC: {old_name}"
        )
    return (
        f"{emoji} *{label}* — {school}\n"
        f"➡️ New Play Caller: {new_name}\n"
        f"⬅️ Previous Play Caller: {old_name}"
    )


def build_alert_message(changes: list[dict]) -> str:
    header = "🏈 *Coaching Carousel Alert*"
    blocks = [header, ""]

    for change in changes:
        blocks.append(
            format_change(
                change["type"],
                change["emoji"],
                change["label"],
                change["school"],
                change["new"],
                change["old"],
            )
        )
        blocks.append("")

    detected = date.today().isoformat()
    blocks.append(f"📅 Detected: {detected}")
    return "\n".join(blocks).strip()


def send_telegram(logger: logging.Logger, message: str) -> None:
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(TELEGRAM_ENDPOINT, json=payload, timeout=15)
        if response.status_code >= 400:
            logger.error("Telegram send failed: %s", response.text)
    except requests.RequestException as exc:
        logger.error("Telegram send failed: %s", exc)


def detect_cookie_expired(team_count: int, empty_count: int) -> bool:
    if team_count < 5:
        return False
    return empty_count / max(team_count, 1) >= 0.5


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly coaching carousel watcher")
    parser.add_argument("--dry-run", action="store_true", help="Print changes but don't send Telegram or save snapshot")
    parser.add_argument("--fbs-only", action="store_true", help="Only scrape FBS teams (uses scraper's get_team_slugs but filters to common FBS slugs)")
    parser.add_argument("--team", help="Only check a single team (by slug)")
    parser.add_argument("--snapshot", help="Path to snapshot file (default: data/carousel_snapshot.json)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between team requests in seconds (default: 1.0)")
    args = parser.parse_args()

    DEFAULT_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging()

    snapshot_path = Path(args.snapshot) if args.snapshot else DEFAULT_SNAPSHOT
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        cookie = load_cookie()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    if args.team:
        team_slugs = [args.team]
    else:
        teams = get_team_slugs()
        team_slugs = normalize_team_list(teams, args.fbs_only, logger)

    if not team_slugs:
        logger.error("No teams found to scrape")
        sys.exit(1)

    by_slug: dict[str, list[dict]] = {}
    empty_count = 0

    for idx, slug in enumerate(team_slugs, start=1):
        logger.info("[%s/%s] Scraping %s", idx, len(team_slugs), slug)
        coaches = scrape_team_staff(slug, cookie)
        if not coaches:
            empty_count += 1
        else:
            by_slug[slug] = coaches

        if idx < len(team_slugs):
            time.sleep(args.delay)

    if detect_cookie_expired(len(team_slugs), empty_count):
        logger.warning("Cookie may be expired; %s/%s teams returned 0 coaches", empty_count, len(team_slugs))
        sys.exit(1)

    if not snapshot_path.exists():
        snapshot = build_snapshot(by_slug)
        if not args.dry_run:
            snapshot_path.write_text(json.dumps(snapshot, indent=2))
        logger.info("First run - baseline snapshot saved")
        return

    previous = json.loads(snapshot_path.read_text())
    previous_by_school = previous.get("by_school", {})

    changes: list[dict] = []
    priority = [
        ("head_coach", "🚨", "HEAD COACH CHANGE"),
        ("offensive_coordinator", "📋", "OFFENSIVE COORDINATOR CHANGE"),
        ("defensive_coordinator", "🛡️", "DEFENSIVE COORDINATOR CHANGE"),
        ("play_caller", "🎯", "PLAY CALLER CHANGE"),
    ]

    for slug, coaches in by_slug.items():
        current = build_school_snapshot(coaches)
        if not current:
            continue
        old = previous_by_school.get(slug, {})
        school_name = current.get("school") or old.get("school") or slug

        for key, emoji, label in priority:
            if diff_entry(old.get(key), current.get(key)):
                changes.append(
                    {
                        "type": key,
                        "emoji": emoji,
                        "label": label,
                        "school": school_name,
                        "slug": slug,
                        "new": current.get(key),
                        "old": old.get(key),
                    }
                )

    if changes:
        oc_changes = {
            change["slug"]: change
            for change in changes
            if change["type"] == "offensive_coordinator"
        }

        def entry_name(entry: Optional[dict]) -> Optional[str]:
            return entry.get("name") if entry else None

        deduped_changes: list[dict] = []
        for change in changes:
            if change["type"] == "play_caller":
                oc_change = oc_changes.get(change.get("slug"))
                if oc_change:
                    if (
                        entry_name(change.get("old")) == entry_name(oc_change.get("old"))
                        and entry_name(change.get("new")) == entry_name(oc_change.get("new"))
                    ):
                        continue
            deduped_changes.append(change)

        changes = deduped_changes

    if changes:
        message = build_alert_message(changes)
        if args.dry_run:
            logger.info("Dry run - changes detected:\n%s", message)
        else:
            send_telegram(logger, message)
    else:
        logger.info("No priority changes detected")

    if not args.dry_run:
        new_snapshot = build_snapshot(by_slug)
        snapshot_path.write_text(json.dumps(new_snapshot, indent=2))


if __name__ == "__main__":
    main()
