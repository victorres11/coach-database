#!/usr/bin/env python3
"""
Small helpers for reading Coach DB snapshots from SQLite.

These utilities keep the legacy "USA Today-style" JSON shape so existing scripts
can move to SQLite without a big rewrite.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Snapshot:
    metadata: dict[str, Any]
    coaches: list[dict[str, Any]]


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def snapshot_from_sqlite(db_path: Path, *, year: int | None = None) -> Snapshot:
    """Build a minimal snapshot for head-coach change tracking and salary analysis."""
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    conn = _connect(db_path)
    params: list[Any] = []

    where = ["c.is_head_coach = 1"]
    if year is not None:
        where.append("c.year = ?")
        params.append(year)

    where_sql = " AND ".join(where)

    rows = conn.execute(
        f"""
        SELECT
            c.name as coach,
            s.name as school,
            conf.abbrev as conference,
            sal.total_pay as totalPay,
            sal.school_pay as schoolPay,
            sal.max_bonus as maxBonus,
            sal.bonuses_paid as bonusesPaid,
            sal.buyout as buyout
        FROM coaches c
        JOIN schools s ON c.school_id = s.id
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        LEFT JOIN salaries sal ON sal.id = (
            SELECT id
            FROM salaries s2
            WHERE s2.coach_id = c.id
            ORDER BY s2.year DESC, COALESCE(s2.source_date, '') DESC, s2.id DESC
            LIMIT 1
        )
        WHERE {where_sql}
        """,
        params,
    ).fetchall()
    conn.close()

    coaches = [dict(r) for r in rows]
    coaches.sort(key=lambda c: (c.get("totalPay") or 0), reverse=True)
    for i, coach in enumerate(coaches, 1):
        coach["rank"] = i

    metadata = {
        "source": "Coach DB (SQLite)",
        "sourceUrl": None,
        "lastUpdated": date.today().isoformat(),
        "totalCoaches": len(coaches),
        "sport": "football",
        "division": "FBS",
    }
    return Snapshot(metadata=metadata, coaches=coaches)

