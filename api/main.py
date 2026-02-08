#!/usr/bin/env python3
"""
Coach Database API

FastAPI service for querying college football coaching data.
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import datetime as dt
import sqlite3
from pathlib import Path
from collections import defaultdict

# Database path - works locally and on Render
import os
DB_PATH = Path(os.environ.get('DATABASE_PATH', Path(__file__).parent.parent / 'db' / 'coaches.db'))

app = FastAPI(
    title="Coach Database API",
    description="College football coaching staff and salary data",
    version="1.0.0"
)

# CORS for web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ---

class Coach(BaseModel):
    id: int
    name: str
    school: Optional[str]
    school_slug: Optional[str]
    position: Optional[str]
    is_head_coach: bool
    year: Optional[int] = None
    conference: Optional[str]
    total_pay: Optional[int] = None
    salary_year: Optional[int] = None
    salary_school_pay: Optional[int] = None
    salary_source: Optional[str] = None
    salary_source_date: Optional[str] = None

class CareerStint(BaseModel):
    school: str
    school_slug: Optional[str] = None
    position: Optional[str] = None
    start_year: int
    end_year: int
    
class School(BaseModel):
    id: int
    name: str
    slug: str
    conference: Optional[str]
    head_coach: Optional[str] = None
    staff_count: int = 0

class Salary(BaseModel):
    coach_name: str
    school: str
    total_pay: Optional[int]
    school_pay: Optional[int]
    max_bonus: Optional[int]
    buyout: Optional[int]

# --- Database helpers ---

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def latest_year(conn: sqlite3.Connection) -> int:
    """Return the latest season year available in the coaches table."""
    row = conn.execute("SELECT MAX(year) FROM coaches WHERE year IS NOT NULL").fetchone()
    if row and row[0]:
        return int(row[0])
    return int(dt.date.today().year)


def effective_year(conn: sqlite3.Connection, year: Optional[int]) -> int:
    return int(year) if year is not None else latest_year(conn)

# --- Routes ---

@app.get("/")
def root():
    """API health check."""
    return {
        "status": "ok",
        "service": "Coach Database API",
        "version": "1.0.0"
    }

@app.get("/api/stats", include_in_schema=False)
@app.get("/stats")
def get_stats(
    year: Optional[int] = Query(None, description="Season year (default: latest available)")
):
    """Get database statistics for a season year (defaults to latest)."""
    conn = get_db()
    stats = {}

    y = effective_year(conn, year)
    stats["year"] = y

    stats['schools'] = conn.execute('SELECT COUNT(*) FROM schools').fetchone()[0]
    stats['head_coaches'] = conn.execute('SELECT COUNT(*) FROM coaches WHERE is_head_coach = 1 AND year = ?', (y,)).fetchone()[0]
    stats['assistants'] = conn.execute('SELECT COUNT(*) FROM coaches WHERE is_head_coach = 0 AND year = ?', (y,)).fetchone()[0]
    stats['salaries'] = conn.execute('SELECT COUNT(*) FROM salaries WHERE year = ?', (y,)).fetchone()[0]
    
    conn.close()
    return stats

@app.get("/api/coaches", response_model=List[Coach], include_in_schema=False)
@app.get("/coaches", response_model=List[Coach])
def list_coaches(
    school: Optional[str] = Query(None, description="Filter by school slug"),
    position: Optional[str] = Query(None, description="Filter by position (partial match)"),
    head_only: bool = Query(False, description="Only return head coaches"),
    year: Optional[int] = Query(None, description="Season year (default: latest available)"),
    limit: int = Query(2500, le=3000, description="Max results (default 2500 to include all coaches)")
):
    """List coaches with optional filters."""
    conn = get_db()
    y = effective_year(conn, year)
    
    query = '''
        SELECT c.id, c.name, s.name as school, s.slug as school_slug,
               c.position, c.is_head_coach, c.year, conf.abbrev as conference,
               sal.total_pay,
               sal.year as salary_year,
               sal.school_pay as salary_school_pay,
               sal.source as salary_source,
               sal.source_date as salary_source_date
        FROM coaches c
        LEFT JOIN schools s ON c.school_id = s.id
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        LEFT JOIN salaries sal ON sal.id = (
            SELECT id
            FROM salaries s2
            WHERE s2.coach_id = c.id
              AND s2.year = c.year
            ORDER BY s2.year DESC, COALESCE(s2.source_date, '') DESC, s2.id DESC
            LIMIT 1
        )
        WHERE 1=1
    '''
    params = []

    query += " AND c.year = ?"
    params.append(y)
    
    if school:
        query += ' AND s.slug = ?'
        params.append(school)
    
    if position:
        query += ' AND c.position LIKE ?'
        params.append(f'%{position}%')
    
    if head_only:
        query += ' AND c.is_head_coach = 1'
    
    # Order by: head coaches first, then by salary (if any), then alphabetically
    query += ' ORDER BY c.is_head_coach DESC, COALESCE(sal.total_pay, 0) DESC, s.name ASC, c.name ASC LIMIT ?'
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    return [Coach(**dict(row)) for row in rows]

@app.get("/api/coaches/{coach_id}", response_model=Coach, include_in_schema=False)
@app.get("/coaches/{coach_id}", response_model=Coach)
def get_coach(coach_id: int):
    """Get a specific coach by ID."""
    conn = get_db()
    
    row = conn.execute('''
        SELECT c.id, c.name, s.name as school, s.slug as school_slug,
               c.position, c.is_head_coach, c.year, conf.abbrev as conference,
               sal.total_pay,
               sal.year as salary_year,
               sal.school_pay as salary_school_pay,
               sal.source as salary_source,
               sal.source_date as salary_source_date
        FROM coaches c
        LEFT JOIN schools s ON c.school_id = s.id
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        LEFT JOIN salaries sal ON sal.id = (
            SELECT id
            FROM salaries s2
            WHERE s2.coach_id = c.id
              AND s2.year = c.year
            ORDER BY s2.year DESC, COALESCE(s2.source_date, '') DESC, s2.id DESC
            LIMIT 1
        )
        WHERE c.id = ?
    ''', (coach_id,)).fetchone()
    
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Coach not found")
    
    return Coach(**dict(row))

@app.get("/api/coaches/{coach_id}/career", response_model=List[CareerStint], include_in_schema=False)
@app.get("/coaches/{coach_id}/career", response_model=List[CareerStint])
def get_coach_career(coach_id: int):
    """Get a coach's career history (grouped stints) by coach ID.

    This relies on historical staff data being loaded into the `coaches` table
    across multiple seasons (`year`), and groups consecutive years for the same
    school + position into a single stint.
    """
    conn = get_db()

    coach_row = conn.execute('SELECT name FROM coaches WHERE id = ?', (coach_id,)).fetchone()
    if not coach_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Coach not found")

    name = coach_row['name']
    rows = conn.execute('''
        SELECT c.year, c.position, c.is_head_coach,
               s.name as school, s.slug as school_slug
        FROM coaches c
        LEFT JOIN schools s ON c.school_id = s.id
        WHERE c.name = ?
        ORDER BY c.year ASC, COALESCE(s.name, '') ASC, COALESCE(c.position, '') ASC
    ''', (name,)).fetchall()
    conn.close()

    # De-dupe identical entries (common when multiple sources load the same job).
    seen = set()
    records = []
    for r in rows:
        key = (r['year'], r['school_slug'], r['school'], r['position'], int(r['is_head_coach'] or 0))
        if key in seen:
            continue
        seen.add(key)
        records.append(dict(r))

    stints: list[dict] = []
    current = None
    for rec in records:
        year = rec.get('year')
        if year is None:
            continue
        school = rec.get('school') or 'Unknown'
        school_slug = rec.get('school_slug')
        position = rec.get('position')

        if current:
            same_place = (current['school_slug'], current['school'], current['position']) == (school_slug, school, position)
            consecutive = year == current['end_year'] + 1
            if same_place and consecutive:
                current['end_year'] = year
                continue
            stints.append(current)

        current = {
            "school": school,
            "school_slug": school_slug,
            "position": position,
            "start_year": year,
            "end_year": year,
        }

    if current:
        stints.append(current)

    stints.sort(key=lambda s: (s['end_year'], s['start_year']), reverse=True)
    return [CareerStint(**s) for s in stints]

@app.get("/api/schools", response_model=List[School], include_in_schema=False)
@app.get("/schools", response_model=List[School])
def list_schools(
    conference: Optional[str] = Query(None, description="Filter by conference abbrev"),
    year: Optional[int] = Query(None, description="Season year (default: latest available)"),
    limit: int = Query(100, le=500)
):
    """List schools with head coach and staff count."""
    conn = get_db()
    y = effective_year(conn, year)
    
    query = '''
        SELECT s.id, s.name, s.slug, conf.abbrev as conference,
               (SELECT name FROM coaches WHERE school_id = s.id AND is_head_coach = 1 AND year = ? LIMIT 1) as head_coach,
               (SELECT COUNT(*) FROM coaches WHERE school_id = s.id AND year = ?) as staff_count
        FROM schools s
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        WHERE 1=1
    '''
    params = [y, y]
    
    if conference:
        query += ' AND conf.abbrev = ?'
        params.append(conference)
    
    query += ' ORDER BY s.name LIMIT ?'
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    return [School(**dict(row)) for row in rows]

@app.get("/api/schools/{slug}", include_in_schema=False)
@app.get("/schools/{slug}")
def get_school(
    slug: str,
    year: Optional[int] = Query(None, description="Season year (default: latest available)"),
):
    """Get school details with full staff for a season year (defaults to latest)."""
    conn = get_db()
    y = effective_year(conn, year)
    
    school = conn.execute('''
        SELECT s.id, s.name, s.slug, conf.abbrev as conference
        FROM schools s
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        WHERE s.slug = ?
    ''', (slug,)).fetchone()
    
    if not school:
        conn.close()
        raise HTTPException(status_code=404, detail="School not found")
    
    staff = conn.execute('''
        SELECT c.id, c.name, c.position, c.is_head_coach,
               sal.total_pay,
               sal.year as salary_year,
               sal.school_pay as salary_school_pay,
               sal.source as salary_source,
               sal.source_date as salary_source_date
        FROM coaches c
        LEFT JOIN salaries sal ON sal.id = (
            SELECT id
            FROM salaries s2
            WHERE s2.coach_id = c.id
              AND s2.year = c.year
            ORDER BY s2.year DESC, COALESCE(s2.source_date, '') DESC, s2.id DESC
            LIMIT 1
        )
        WHERE c.school_id = ? AND c.year = ?
        ORDER BY c.is_head_coach DESC, c.position
    ''', (school['id'], y)).fetchall()
    
    conn.close()
    
    return {
        **dict(school),
        "year": y,
        "staff": [dict(row) for row in staff]
    }

@app.get("/api/salaries", response_model=List[Salary], include_in_schema=False)
@app.get("/salaries", response_model=List[Salary])
def list_salaries(
    min_pay: Optional[int] = Query(None, description="Minimum total pay"),
    conference: Optional[str] = Query(None, description="Filter by conference"),
    year: Optional[int] = Query(None, description="Season year (default: latest available)"),
    limit: int = Query(50, le=200)
):
    """List head coach salaries."""
    conn = get_db()
    y = effective_year(conn, year)
    
    query = '''
        SELECT c.name as coach_name, s.name as school, 
               sal.total_pay, sal.school_pay, sal.max_bonus, sal.buyout
        FROM salaries sal
        JOIN coaches c ON sal.coach_id = c.id
        JOIN schools s ON c.school_id = s.id
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        WHERE 1=1
    '''
    params = []

    query += " AND sal.year = ? AND c.year = ? AND c.is_head_coach = 1"
    params.extend([y, y])
    
    if min_pay:
        query += ' AND sal.total_pay >= ?'
        params.append(min_pay)
    
    if conference:
        query += ' AND conf.abbrev = ?'
        params.append(conference)
    
    query += ' ORDER BY sal.total_pay DESC LIMIT ?'
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    return [Salary(**dict(row)) for row in rows]

@app.get("/api/search", include_in_schema=False)
@app.get("/search")
def search(
    q: str = Query(..., min_length=2, description="Search query"),
    year: Optional[int] = Query(None, description="Season year (default: latest available)"),
    limit: int = Query(20, le=100)
):
    """Search coaches by name."""
    conn = get_db()
    y = effective_year(conn, year)
    
    rows = conn.execute('''
        SELECT c.id, c.name, s.name as school, c.position, c.is_head_coach
        FROM coaches c
        LEFT JOIN schools s ON c.school_id = s.id
        WHERE c.name LIKE ? AND c.year = ?
        ORDER BY c.is_head_coach DESC, c.name
        LIMIT ?
    ''', (f'%{q}%', y, limit)).fetchall()
    
    conn.close()
    
    return [dict(row) for row in rows]


@app.get("/api/years", include_in_schema=False)
@app.get("/years")
def get_years():
    """List available season years (from coaches table)."""
    conn = get_db()
    years = [int(r[0]) for r in conn.execute("SELECT DISTINCT year FROM coaches WHERE year IS NOT NULL ORDER BY year DESC").fetchall()]
    conn.close()
    return {"years": years, "latest": years[0] if years else None}


@app.get("/api/coaches/{coach_id}/history", response_model=List[Coach], include_in_schema=False)
@app.get("/coaches/{coach_id}/history", response_model=List[Coach])
def get_coach_history(coach_id: int):
    """Return all season rows for a coach, keyed by name."""
    conn = get_db()

    coach_row = conn.execute("SELECT name FROM coaches WHERE id = ?", (coach_id,)).fetchone()
    if not coach_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Coach not found")

    name = coach_row["name"]
    rows = conn.execute(
        """
        SELECT c.id, c.name, s.name as school, s.slug as school_slug,
               c.position, c.is_head_coach, c.year, conf.abbrev as conference,
               sal.total_pay,
               sal.year as salary_year,
               sal.school_pay as salary_school_pay,
               sal.source as salary_source,
               sal.source_date as salary_source_date
        FROM coaches c
        LEFT JOIN schools s ON c.school_id = s.id
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        LEFT JOIN salaries sal ON sal.id = (
            SELECT id
            FROM salaries s2
            WHERE s2.coach_id = c.id
              AND s2.year = c.year
            ORDER BY s2.year DESC, COALESCE(s2.source_date, '') DESC, s2.id DESC
            LIMIT 1
        )
        WHERE c.name = ?
        ORDER BY c.year DESC, c.is_head_coach DESC, COALESCE(s.name, '') ASC, c.name ASC
        """,
        (name,),
    ).fetchall()

    conn.close()
    return [Coach(**dict(r)) for r in rows]


@app.get("/api/schools/{slug}/staff", response_model=List[Coach], include_in_schema=False)
@app.get("/schools/{slug}/staff", response_model=List[Coach])
def get_school_staff(
    slug: str,
    year: Optional[int] = Query(None, description="Season year (default: latest available)"),
):
    """Historical staff lookup for a single school."""
    conn = get_db()
    y = effective_year(conn, year)

    school = conn.execute("SELECT id FROM schools WHERE slug = ? LIMIT 1", (slug,)).fetchone()
    if not school:
        conn.close()
        raise HTTPException(status_code=404, detail="School not found")

    staff = conn.execute(
        """
        SELECT c.id, c.name, s.name as school, s.slug as school_slug,
               c.position, c.is_head_coach, c.year, conf.abbrev as conference,
               sal.total_pay,
               sal.year as salary_year,
               sal.school_pay as salary_school_pay,
               sal.source as salary_source,
               sal.source_date as salary_source_date
        FROM coaches c
        JOIN schools s ON c.school_id = s.id
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        LEFT JOIN salaries sal ON sal.id = (
            SELECT id
            FROM salaries s2
            WHERE s2.coach_id = c.id
              AND s2.year = c.year
            ORDER BY s2.year DESC, COALESCE(s2.source_date, '') DESC, s2.id DESC
            LIMIT 1
        )
        WHERE s.slug = ? AND c.year = ?
        ORDER BY c.is_head_coach DESC, COALESCE(c.position, '') ASC, c.name ASC
        """,
        (slug, y),
    ).fetchall()
    conn.close()

    return [Coach(**dict(r)) for r in staff]


@app.get("/api/changes", include_in_schema=False)
@app.get("/changes")
def get_changes(
    from_year: int = Query(..., alias="from", description="Base year to diff from"),
    to_year: int = Query(..., alias="to", description="Target year to diff to"),
):
    """Year-over-year diff: hires, departures, promotions.

    Identity is based on exact coach name strings within each school.
    """
    conn = get_db()

    def load_year(y: int) -> list[sqlite3.Row]:
        return conn.execute(
            """
            SELECT s.slug as school_slug, s.name as school,
                   c.name, c.position, c.is_head_coach
            FROM coaches c
            JOIN schools s ON c.school_id = s.id
            WHERE c.year = ?
            """,
            (y,),
        ).fetchall()

    from_rows = load_year(from_year)
    to_rows = load_year(to_year)
    conn.close()

    def pick_best(existing: dict, row: sqlite3.Row) -> None:
        key = (row["school_slug"], row["name"])
        current = existing.get(key)
        cand = {
            "school": row["school"],
            "school_slug": row["school_slug"],
            "name": row["name"],
            "position": row["position"],
            "is_head_coach": bool(row["is_head_coach"]),
        }
        if not current:
            existing[key] = cand
            return
        # Prefer head coach rows, then prefer longer position strings (more specific).
        score = (1 if cand["is_head_coach"] else 0, len(cand["position"] or ""))
        cur_score = (1 if current["is_head_coach"] else 0, len(current["position"] or ""))
        if score > cur_score:
            existing[key] = cand

    from_map: dict[tuple[str, str], dict] = {}
    to_map: dict[tuple[str, str], dict] = {}
    for r in from_rows:
        pick_best(from_map, r)
    for r in to_rows:
        pick_best(to_map, r)

    new_hires = []
    departures = []
    promotions = []

    for key, to_rec in to_map.items():
        from_rec = from_map.get(key)
        if not from_rec:
            new_hires.append(to_rec)
            continue
        if (from_rec.get("position") or "") != (to_rec.get("position") or "") or bool(from_rec.get("is_head_coach")) != bool(to_rec.get("is_head_coach")):
            promotions.append(
                {
                    "school": to_rec["school"],
                    "school_slug": to_rec["school_slug"],
                    "name": to_rec["name"],
                    "from_position": from_rec.get("position"),
                    "to_position": to_rec.get("position"),
                    "from_is_head_coach": bool(from_rec.get("is_head_coach")),
                    "to_is_head_coach": bool(to_rec.get("is_head_coach")),
                }
            )

    for key, from_rec in from_map.items():
        if key not in to_map:
            departures.append(from_rec)

    # Optional convenience: detect obvious moves across schools by name.
    from_by_name: dict[str, set[str]] = defaultdict(set)
    to_by_name: dict[str, set[str]] = defaultdict(set)
    for rec in from_map.values():
        from_by_name[rec["name"]].add(rec["school_slug"])
    for rec in to_map.values():
        to_by_name[rec["name"]].add(rec["school_slug"])

    moves = []
    for name, from_schools in from_by_name.items():
        to_schools = to_by_name.get(name)
        if not to_schools:
            continue
        if from_schools == to_schools:
            continue
        # Only report unambiguous single-to-single moves.
        if len(from_schools) == 1 and len(to_schools) == 1:
            moves.append(
                {
                    "name": name,
                    "from_school_slug": next(iter(from_schools)),
                    "to_school_slug": next(iter(to_schools)),
                }
            )

    return {
        "from": from_year,
        "to": to_year,
        "new_hires": sorted(new_hires, key=lambda r: (r["school"], r["name"])),
        "departures": sorted(departures, key=lambda r: (r["school"], r["name"])),
        "promotions": sorted(promotions, key=lambda r: (r["school"], r["name"])),
        "moves": sorted(moves, key=lambda r: (r["name"], r["from_school_slug"], r["to_school_slug"])),
    }

# --- For YR Call Sheets integration ---

from fastapi.responses import PlainTextResponse

@app.get("/yr/{school_slug}/coaches")
def yr_coaches(
    school_slug: str,
    position: Optional[str] = Query(None, description="Filter to single position (OC, OL, TE, WR, RB, SC)"),
    format: Optional[str] = Query(None, description="Output format: 'text' for plain text lines"),
    year: Optional[int] = Query(None, description="Season year (default: latest available)"),
):
    """Get offensive coaches for YR Call Sheets integration."""
    conn = get_db()
    y = effective_year(conn, year)
    
    # Position mapping for YR
    position_map = {
        'OC': ['offensive coord', 'offensive coordinator', 'play caller'],
        'OL': ['offensive line'],
        'TE': ['tight end'],
        'WR': ['wide receiver', 'passing coord'],
        'RB': ['running back'],
        'SC': ['strength', 'conditioning']
    }
    
    staff = conn.execute('''
        SELECT c.name, c.position
        FROM coaches c
        JOIN schools s ON c.school_id = s.id
        WHERE s.slug = ? AND c.year = ?
    ''', (school_slug, y)).fetchall()
    
    conn.close()
    
    result = {}
    for label, keywords in position_map.items():
        for row in staff:
            pos_lower = (row['position'] or '').lower()
            if any(k in pos_lower for k in keywords):
                result[label] = row['name']
                break
    
    # If filtering to single position, return just that value
    if position:
        pos_upper = position.upper()
        value = result.get(pos_upper, "")
        if format == 'text':
            return PlainTextResponse(value)  # Just the name
        return {pos_upper: value} if value else {}
    
    # Return plain text if format=text
    if format == 'text':
        lines = [f"{k}: {v}" for k, v in result.items()]
        return PlainTextResponse("\n".join(lines))
    
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100)
