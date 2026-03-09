#!/usr/bin/env python3
"""
Sweep 2026 FBS head coach salary/contract updates using Perplexity sonar-pro.

Features:
- Loads 2025 head coaches from db/coaches.db (schools join when available).
- Calls Perplexity API with a fixed salary/contract prompt per coach.
- Extracts 2026 total pay, first citation URL, and contract/extension notes.
- Writes JSON results to /tmp/salary_sweep_2026.json.
- Prints summary table sorted by 2026 salary descending.
- Optional `--import` writes verified 2026 salaries into salaries table.
- Optional `--dry-run` prints prompts without making API calls.
- Optional `--conference` filters by conference (e.g., SEC).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "db" / "coaches.db"
OUTPUT_PATH_DEFAULT = Path("/tmp/salary_sweep_2026.json")
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar-pro"
PERPLEXITY_SOURCE = "perplexity_sonar_pro"
API_DELAY_SECONDS = 2.0
ANNUAL_SALARY_CEILING = 25_000_000


@dataclass
class CoachRow:
    coach_id: int
    coach_name: str
    school_name: str
    conference_abbrev: str | None = None
    conference_name: str | None = None
    total_pay_2025: int | None = None


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(r[1]) for r in rows}


def normalize_money(value: str) -> int | None:
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def money_to_str(value: int | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.0f}"


def extract_total_pay(content: str) -> int | None:
    # Prefer money amounts near salary/annual language.
    patterns = [
        r"(?:annual|base)?\s*salary[^$\n]{0,60}\$([0-9][0-9,]*(?:\.[0-9]+)?)\s*(million|billion|m|k)?",
        r"\$([0-9][0-9,]*(?:\.[0-9]+)?)\s*(million|billion|m|k)?[^.\n]{0,60}(?:annual|per year|salary|compensation)",
    ]
    text = content.lower()
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = match.group(1)
            unit = (match.group(2) or "").lower()
            numeric = normalize_money(amount)
            if numeric is None:
                continue
            if unit in {"million", "m"}:
                return int(round(float(amount.replace(",", "")) * 1_000_000))
            if unit == "billion":
                return int(round(float(amount.replace(",", "")) * 1_000_000_000))
            if unit == "k":
                return int(round(float(amount.replace(",", "")) * 1_000))
            return numeric

    # Fallback: prefer likely annual salary amounts over buyouts/total contract values.
    candidates: list[int] = []
    for match in re.finditer(
        r"\$([0-9][0-9,]*(?:\.[0-9]+)?)\s*(million|billion|m|k)?",
        content,
        re.IGNORECASE,
    ):
        amount = match.group(1)
        unit = (match.group(2) or "").lower()
        try:
            value = float(amount.replace(",", ""))
        except ValueError:
            continue
        if unit in {"million", "m"}:
            candidates.append(int(round(value * 1_000_000)))
        elif unit == "billion":
            candidates.append(int(round(value * 1_000_000_000)))
        elif unit == "k":
            candidates.append(int(round(value * 1_000)))
        else:
            candidates.append(int(round(value)))
    if candidates:
        under_cap = [value for value in candidates if value <= ANNUAL_SALARY_CEILING]
        if under_cap:
            return max(under_cap)
        return min(candidates)
    return None


def extract_notes(content: str) -> str:
    keywords = ("contract", "extension", "extended", "signed", "through", "2025", "2026")
    fragments = re.split(r"(?<=[.!?])\s+|\n+", content.strip())
    picked: list[str] = []
    for frag in fragments:
        low = frag.lower()
        if any(k in low for k in keywords):
            picked.append(frag.strip())
        if len(picked) >= 2:
            break
    return " ".join(picked)


def extract_first_citation(payload: dict[str, Any], content: str) -> str | None:
    citations = payload.get("citations")
    if isinstance(citations, list) and citations:
        first = citations[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            url = first.get("url")
            if isinstance(url, str) and url.strip():
                return url

    search_results = payload.get("search_results")
    if isinstance(search_results, list) and search_results:
        first = search_results[0]
        if isinstance(first, dict):
            url = first.get("url")
            if isinstance(url, str) and url.strip():
                return url

    url_match = re.search(r"https?://[^\s)\]]+", content)
    if url_match:
        return url_match.group(0)
    return None


def perplexity_query(prompt: str, api_key: str, timeout: int = 90) -> tuple[str, str | None]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": PERPLEXITY_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }

    response = requests.post(
        PERPLEXITY_URL,
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()

    content = ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        if isinstance(message, dict):
            content = str(message.get("content", "")).strip()
    if not content:
        content = json.dumps(data, ensure_ascii=True)

    citation = extract_first_citation(data, content)
    return content, citation


def load_salary_2025_map(conn: sqlite3.Connection) -> dict[int, int]:
    if not table_exists(conn, "salaries"):
        return {}
    rows = conn.execute(
        """
        SELECT coach_id, MAX(total_pay) AS total_pay_2025
        FROM salaries
        WHERE year = 2025 AND total_pay IS NOT NULL
        GROUP BY coach_id
        """
    ).fetchall()
    out: dict[int, int] = {}
    for r in rows:
        coach_id = int(r[0])
        total_pay = r[1]
        if total_pay is not None:
            out[coach_id] = int(total_pay)
    return out


def load_head_coaches(conn: sqlite3.Connection, conference_filter: str | None) -> list[CoachRow]:
    coaches_columns = get_table_columns(conn, "coaches")
    has_schools = table_exists(conn, "schools")
    has_conferences = table_exists(conn, "conferences")
    salary_2025 = load_salary_2025_map(conn)

    rows: list[sqlite3.Row] = []
    params: list[Any] = []

    if has_schools:
        query = """
        WITH ranked AS (
            SELECT
                c.id AS coach_id,
                c.name AS coach_name,
                c.school_id AS school_id,
                s.name AS school_name,
                co.abbrev AS conference_abbrev,
                co.name AS conference_name,
                ROW_NUMBER() OVER (PARTITION BY c.school_id ORDER BY c.id ASC) AS rn
            FROM coaches c
            JOIN schools s ON c.school_id = s.id
            LEFT JOIN conferences co ON s.conference_id = co.id
            WHERE c.year = 2025
              AND c.is_head_coach = 1
        )
        SELECT coach_id, coach_name, school_name, conference_abbrev, conference_name
        FROM ranked
        WHERE rn = 1
        """
        if conference_filter:
            if has_conferences:
                query += """
                AND (
                    UPPER(COALESCE(conference_abbrev, '')) = UPPER(?)
                    OR UPPER(COALESCE(conference_name, '')) LIKE '%' || UPPER(?) || '%'
                )
                """
                params.extend([conference_filter, conference_filter])
            else:
                print(
                    "Warning: --conference provided but conferences table not found; ignoring conference filter.",
                    file=sys.stderr,
                )
        query += " ORDER BY school_name"
        rows = conn.execute(query, tuple(params)).fetchall()
    else:
        school_col_map = {
            "school": '"school"',
            "school_name": '"school_name"',
            "team": '"team"',
            "program": '"program"',
            "name": '"name"',
        }
        school_col = None
        for candidate in ("school", "school_name", "team", "program"):
            if candidate in coaches_columns:
                school_col = candidate
                break
        if school_col is None:
            school_col = "name"
            print(
                "Warning: schools table missing and no school name column found on coaches; using coach name as school fallback.",
                file=sys.stderr,
            )
        school_col_sql = school_col_map[school_col]

        conference_col_map = {
            "conference": '"conference"',
            "conference_name": '"conference_name"',
            "conf": '"conf"',
        }
        conference_col = None
        for candidate in ("conference", "conference_name", "conf"):
            if candidate in coaches_columns:
                conference_col = candidate
                break
        conference_col_sql = f'c.{conference_col_map[conference_col]}' if conference_col else "NULL"

        query = f"""
        WITH ranked AS (
            SELECT
                c.id AS coach_id,
                c.name AS coach_name,
                c.{school_col_sql} AS school_name,
                {conference_col_sql} AS conference_name,
                ROW_NUMBER() OVER (PARTITION BY c.{school_col_sql} ORDER BY c.id ASC) AS rn
            FROM coaches c
            WHERE c.year = 2025
              AND c.is_head_coach = 1
        )
        SELECT coach_id, coach_name, school_name, NULL AS conference_abbrev, conference_name
        FROM ranked
        WHERE rn = 1
        """
        if conference_filter:
            if conference_col:
                query += " AND UPPER(COALESCE(conference_name, '')) LIKE '%' || UPPER(?) || '%'"
                params.append(conference_filter)
            else:
                print(
                    "Warning: --conference provided but conference column not found on coaches; ignoring conference filter.",
                    file=sys.stderr,
                )
        query += " ORDER BY school_name"
        rows = conn.execute(query, tuple(params)).fetchall()

    result: list[CoachRow] = []
    for r in rows:
        coach_id = int(r["coach_id"])
        coach_name = str(r["coach_name"]).strip()
        school_name = str(r["school_name"]).strip()
        conference_abbrev = r["conference_abbrev"]
        conference_name = r["conference_name"]
        result.append(
            CoachRow(
                coach_id=coach_id,
                coach_name=coach_name,
                school_name=school_name,
                conference_abbrev=str(conference_abbrev) if conference_abbrev else None,
                conference_name=str(conference_name) if conference_name else None,
                total_pay_2025=salary_2025.get(coach_id),
            )
        )
    return result


def import_results(conn: sqlite3.Connection, results: list[dict[str, Any]]) -> int:
    if not table_exists(conn, "salaries"):
        raise RuntimeError("salaries table does not exist in the database.")

    source_date = dt.date.today().isoformat()
    imported = 0
    for row in results:
        coach_id = row.get("coach_id")
        total_pay_2026 = row.get("total_pay_2026")
        source_url = row.get("source_url")

        # Treat a parsed salary + citation as verified.
        if coach_id is None or total_pay_2026 is None or not source_url:
            continue

        existing = conn.execute(
            """
            SELECT id
            FROM salaries
            WHERE coach_id = ? AND year = 2026 AND source = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (coach_id, PERPLEXITY_SOURCE),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE salaries
                SET total_pay = ?, source_date = ?
                WHERE id = ?
                """,
                (int(total_pay_2026), source_date, int(existing["id"])),
            )
        else:
            conn.execute(
                """
                INSERT INTO salaries (
                    coach_id, year, total_pay, school_pay, max_bonus, bonuses_paid, buyout, source, source_date
                )
                VALUES (?, 2026, ?, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (int(coach_id), int(total_pay_2026), PERPLEXITY_SOURCE, source_date),
            )
        imported += 1

    conn.commit()
    return imported


def print_summary(results: list[dict[str, Any]]) -> None:
    sorted_results = sorted(
        results,
        key=lambda r: (r.get("total_pay_2026") is None, -(r.get("total_pay_2026") or 0)),
    )

    show_notes = any(bool(str(row.get("notes", "")).strip()) for row in sorted_results)
    headers = ["Rank", "Coach", "School", "2025 Salary", "2026 Salary", "Delta"]
    widths = [5, 24, 24, 14, 14, 14]
    if show_notes:
        headers.append("Notes")
        widths.append(48)
    line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print("\n" + line)
    print("-" * len(line))

    for idx, row in enumerate(sorted_results, start=1):
        pay_2025 = row.get("total_pay_2025")
        pay_2026 = row.get("total_pay_2026")
        delta = row.get("delta")
        cols = [
            str(idx).ljust(widths[0]),
            str(row["coach"])[: widths[1]].ljust(widths[1]),
            str(row["school"])[: widths[2]].ljust(widths[2]),
            money_to_str(pay_2025).rjust(widths[3]),
            money_to_str(pay_2026).rjust(widths[4]),
            money_to_str(delta).rjust(widths[5]),
        ]
        if show_notes:
            notes = str(row.get("notes", "")).replace("\n", " ").strip()
            cols.append(notes[: widths[6]].ljust(widths[6]))
        print(" | ".join(cols))


def build_prompt(coach_name: str, school_name: str) -> str:
    return (
        f"What is {coach_name} at {school_name} college football head coach salary and contract for 2026? "
        "Give the exact annual salary amount and any contract extension details signed in 2025 or 2026. "
        "Include citations."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep 2026 head coach salaries via Perplexity sonar-pro.")
    parser.add_argument("--db", type=Path, default=DB_PATH_DEFAULT, help=f"Path to SQLite DB (default: {DB_PATH_DEFAULT})")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH_DEFAULT,
        help=f"JSON output path (default: {OUTPUT_PATH_DEFAULT})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print prompts only; do not call Perplexity API.")
    parser.add_argument("--conference", type=str, help="Conference filter (e.g. SEC).")
    parser.add_argument("--import", dest="do_import", action="store_true", help="Import verified 2026 salary results into salaries table.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.db.exists():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 1

    api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        print("PERPLEXITY_API_KEY is required unless --dry-run is used.", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    try:
        coaches = load_head_coaches(conn, args.conference)
        if not coaches:
            print("No 2025 head coaches found for the requested filter.")
            return 0

        results: list[dict[str, Any]] = []
        for idx, coach in enumerate(coaches, start=1):
            prompt = build_prompt(coach.coach_name, coach.school_name)
            if args.dry_run:
                print(f"[DRY-RUN {idx}/{len(coaches)}] {coach.coach_name} ({coach.school_name})")
                print(f"Prompt: {prompt}\n")
                raw_response = ""
                source_url = None
                total_pay_2026 = None
                _notes = ""
            else:
                if idx > 1:
                    time.sleep(API_DELAY_SECONDS)

                try:
                    raw_response, source_url = perplexity_query(prompt, api_key=api_key)
                    total_pay_2026 = extract_total_pay(raw_response)
                    _notes = extract_notes(raw_response)
                except requests.RequestException as exc:
                    raw_response = f"API_ERROR: {exc}"
                    source_url = None
                    total_pay_2026 = None
                    _notes = ""

                print(
                    f"[{idx}/{len(coaches)}] {coach.coach_name} ({coach.school_name}) -> "
                    f"{money_to_str(total_pay_2026)} | {source_url or 'no citation'}"
                )

            pay_2025 = coach.total_pay_2025
            delta = None
            if total_pay_2026 is not None and pay_2025 is not None:
                delta = int(total_pay_2026) - int(pay_2025)

            results.append(
                {
                    "coach_id": coach.coach_id,
                    "coach": coach.coach_name,
                    "school": coach.school_name,
                    "total_pay_2026": total_pay_2026,
                    "total_pay_2025": pay_2025,
                    "delta": delta,
                    "source_url": source_url,
                    "notes": _notes,
                    "raw_response": raw_response,
                }
            )

        # Persist requested output structure (without internal coach_id).
        output_rows = [
            {
                "coach": r["coach"],
                "school": r["school"],
                "total_pay_2026": r["total_pay_2026"],
                "total_pay_2025": r["total_pay_2025"],
                "delta": r["delta"],
                "source_url": r["source_url"],
                "notes": r["notes"],
                "raw_response": r["raw_response"],
            }
            for r in results
        ]
        args.output.write_text(json.dumps(output_rows, indent=2), encoding="utf-8")
        print(f"\nSaved {len(output_rows)} rows to {args.output}")

        print_summary(results)

        if args.do_import:
            imported = import_results(conn, results)
            print(f"\nImported {imported} verified rows into salaries (year=2026, source={PERPLEXITY_SOURCE}).")

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
