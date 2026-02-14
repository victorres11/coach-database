#!/usr/bin/env python3
"""
Import coordinator salary enrichment into SQLite.

Inputs:
  - State matches (authoritative payroll): data/state_salary_matches.json
  - Media reports (supplemental): data/media_salaries.json

This script merges both sources into `db/coaches.db` so the API/UI can display
assistant/coordinator salaries with a source indicator.

Usage:
  python scripts/import_enriched_salaries.py \
    --state data/state_salary_matches.json \
    --media data/media_salaries.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


DB_PATH_DEFAULT = Path(__file__).parent.parent / "db" / "coaches.db"


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z\\s]", " ", name or "")
    tokens = [t for t in cleaned.lower().split() if t and t not in {"jr", "sr", "ii", "iii", "iv"}]
    return " ".join(tokens)


def name_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def normalize_school_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def get_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def iter_state_matches(path: Path) -> Iterable[dict]:
    with path.open() as f:
        payload = json.load(f)
    for item in payload.get("matches", []):
        yield item


def iter_media_reports(path: Path) -> Iterable[dict]:
    with path.open() as f:
        payload = json.load(f)
    for item in payload.get("reports", []):
        yield item


def resolve_school_id(conn: sqlite3.Connection, school_name: str | None) -> int | None:
    if not school_name:
        return None
    row = conn.execute("SELECT id FROM schools WHERE lower(name) = lower(?)", (school_name,)).fetchone()
    if row:
        return int(row["id"])
    slug = normalize_school_slug(school_name)
    row = conn.execute("SELECT id FROM schools WHERE slug = ?", (slug,)).fetchone()
    if row:
        return int(row["id"])
    return None


def resolve_coach_id(conn: sqlite3.Connection, school_id: int, coach_name: str) -> int | None:
    candidates = conn.execute(
        "SELECT id, name FROM coaches WHERE school_id = ?",
        (school_id,),
    ).fetchall()
    if not candidates:
        return None

    coach_norm = normalize_name(coach_name)
    best_id = None
    best_score = 0.0
    for row in candidates:
        score = name_score(coach_norm, normalize_name(row["name"]))
        if score > best_score:
            best_score = score
            best_id = int(row["id"])

    if best_id is None or best_score < 0.9:
        return None
    return best_id


def salary_exists(conn: sqlite3.Connection, coach_id: int, year: int, source: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM salaries WHERE coach_id = ? AND year = ? AND source = ? LIMIT 1",
        (coach_id, year, source),
    ).fetchone()
    return row is not None


def insert_salary(
    conn: sqlite3.Connection,
    coach_id: int,
    year: int,
    total_pay: int | None,
    school_pay: int | None,
    source: str,
    source_date: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO salaries (coach_id, year, total_pay, school_pay, source, source_date)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (coach_id, year, total_pay, school_pay, source, source_date),
    )


def is_coordinator_position(position: str | None) -> bool:
    return bool(position) and "coordinator" in (position or "").lower()


@dataclass(frozen=True)
class Counters:
    inserted: int = 0
    skipped: int = 0
    unresolved: int = 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Import state + media coordinator salaries into SQLite")
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Path to SQLite database")
    parser.add_argument("--state", default="data/state_salary_matches.json", help="State match JSON")
    parser.add_argument("--media", default="data/media_salaries.json", help="Media salaries JSON")
    parser.add_argument("--media-year", type=int, default=2025, help="Salary year to use for media reports")
    parser.add_argument("--include-non-coordinators", action="store_true", help="Import all positions")
    parser.add_argument("--keep-media-when-state", action="store_true", help="Also import media when state exists")
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    db_path = Path(args.db)
    state_path = repo_root / args.state
    media_path = repo_root / args.media

    conn = get_db(db_path)
    inserted = skipped = unresolved = 0

    state_by_key: dict[tuple[str, str], dict] = {}
    if state_path.exists():
        for match in iter_state_matches(state_path):
            coach = (match.get("coach") or "").strip()
            school = (match.get("school") or "").strip()
            if coach and school:
                state_by_key[(coach, school)] = match

        for (coach, school), match in state_by_key.items():
            if not args.include_non_coordinators and not is_coordinator_position(match.get("position")):
                continue
            school_id = resolve_school_id(conn, school)
            if not school_id:
                unresolved += 1
                continue
            coach_id = resolve_coach_id(conn, school_id, coach)
            if not coach_id:
                unresolved += 1
                continue

            year = int(match.get("salaryYear") or 2025)
            total_pay = match.get("totalComp") or match.get("baseSalary")
            school_pay = match.get("baseSalary")
            source = "state_payroll"
            source_date = datetime.utcnow().strftime("%Y-%m-%d")
            if salary_exists(conn, coach_id, year, source):
                skipped += 1
                continue
            insert_salary(conn, coach_id, year, total_pay, school_pay, source, source_date)
            inserted += 1

    if media_path.exists():
        for report in iter_media_reports(media_path):
            coach = (report.get("coach") or "").strip()
            school = (report.get("school") or "").strip()
            if not coach or not school:
                continue
            if not args.include_non_coordinators and not is_coordinator_position(report.get("position")):
                continue
            if not args.keep_media_when_state and (coach, school) in state_by_key:
                continue

            school_id = resolve_school_id(conn, school)
            if not school_id:
                unresolved += 1
                continue
            coach_id = resolve_coach_id(conn, school_id, coach)
            if not coach_id:
                unresolved += 1
                continue

            year = int(args.media_year)
            total_pay = report.get("salary")
            source = "media_report"
            source_date = report.get("lastUpdated")
            if salary_exists(conn, coach_id, year, source):
                skipped += 1
                continue
            insert_salary(conn, coach_id, year, total_pay, None, source, source_date)
            inserted += 1

    conn.commit()
    conn.close()

    print(f"Imported salaries. inserted={inserted} skipped={skipped} unresolved={unresolved}")


if __name__ == "__main__":
    main()
