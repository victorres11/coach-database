#!/usr/bin/env python3
"""
Coach Database API

FastAPI service for querying college football coaching data.
"""

from fastapi import FastAPI, Query, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
from pathlib import Path
from datetime import datetime
import logging

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

class StaffUpdate(BaseModel):
    """Payload for staff update webhook"""
    school: str  # School name (will normalize to slug)
    coach_name: str
    position: Optional[str]
    hire_date: Optional[str] = None  # YYYY-MM-DD format
    departure_date: Optional[str] = None  # YYYY-MM-DD format
    source_url: Optional[str] = None  # Citation URL
    notes: Optional[str] = None  # Additional context

    class Config:
        json_schema_extra = {
            "example": {
                "school": "Michigan State",
                "coach_name": "John Smith",
                "position": "Offensive Coordinator",
                "hire_date": "2026-01-15",
                "source_url": "https://example.com/news/hiring"
            }
        }

logger = logging.getLogger("coachdb.webhooks")
logging.basicConfig(level=logging.INFO)

# --- Database helpers ---

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def normalize_school_name(name: str) -> str:
    """Normalize school names to slugs."""
    name = name.lower().strip()
    replacements = {
        'miami (fl)': 'miami',
        'miami (oh)': 'miami-oh',
        'ole miss': 'mississippi',
        'north carolina state': 'nc-state',
        'army west point': 'army',
    }
    return replacements.get(name, name.replace(' ', '-'))

def normalize_person_name(name: str) -> str:
    """Normalize coach names for consistent comparisons."""
    return " ".join(name.strip().split())

def standardize_position(position: Optional[str]) -> Optional[str]:
    """Standardize position labels where possible."""
    if not position:
        return None
    cleaned = " ".join(position.strip().split())
    key = cleaned.lower()
    mapping = {
        "hc": "Head Coach",
        "head coach": "Head Coach",
        "oc": "Offensive Coordinator",
        "dc": "Defensive Coordinator",
        "st": "Special Teams Coordinator",
        "stc": "Special Teams Coordinator",
        "co-oc": "Co-Offensive Coordinator",
        "co-dc": "Co-Defensive Coordinator",
    }
    return mapping.get(key, cleaned)

def parse_iso_date(value: Optional[str], field_name: str) -> None:
    if value is None:
        return
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format (YYYY-MM-DD)") from exc

def is_head_coach_position(position: Optional[str]) -> bool:
    if not position:
        return False
    pos_lower = position.lower()
    if pos_lower in {"hc", "head coach"}:
        return True
    if "head coach" in pos_lower and "assistant" not in pos_lower:
        return True
    return False

# --- Routes ---

@app.get("/")
def root():
    """API health check."""
    return {
        "status": "ok",
        "service": "Coach Database API",
        "version": "1.0.0"
    }

@app.post("/api/webhooks/staff-update")
async def webhook_staff_update(
    update: StaffUpdate,
    api_key: str = Header(..., alias="X-API-Key")
):
    """
    Webhook endpoint for external services to push coaching staff updates.
    
    Requires authentication via X-API-Key header.
    Validates payload, deduplicates, and updates database.
    """
    received_at = datetime.utcnow().isoformat() + "Z"
    logger.info("Webhook staff update received at %s", received_at)

    expected_key = os.environ.get("WEBHOOK_API_KEY", "")
    if not expected_key or api_key != expected_key:
        logger.warning("Webhook staff update rejected: invalid API key at %s", received_at)
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not update.school or not update.school.strip():
        logger.warning("Webhook staff update rejected: missing school at %s", received_at)
        raise HTTPException(status_code=400, detail="School is required")

    if not update.coach_name or not update.coach_name.strip():
        logger.warning("Webhook staff update rejected: missing coach_name at %s", received_at)
        raise HTTPException(status_code=400, detail="Coach name is required")

    parse_iso_date(update.hire_date, "hire_date")
    parse_iso_date(update.departure_date, "departure_date")

    school_slug = normalize_school_name(update.school)
    coach_name = normalize_person_name(update.coach_name)
    position = standardize_position(update.position)
    is_head_coach = is_head_coach_position(position)
    current_year = datetime.utcnow().year

    conn = None
    try:
        conn = get_db()
        school_row = conn.execute(
            "SELECT id, name, slug FROM schools WHERE slug = ?",
            (school_slug,)
        ).fetchone()
        if not school_row:
            school_row = conn.execute(
                "SELECT id, name, slug FROM schools WHERE LOWER(name) = LOWER(?)",
                (update.school.strip(),)
            ).fetchone()
        if not school_row:
            logger.warning("Webhook staff update rejected: school not found (%s)", school_slug)
            raise HTTPException(status_code=404, detail="School not found")

        school_id = school_row["id"]

        if position is None:
            existing = conn.execute(
                """
                SELECT * FROM coaches
                WHERE school_id = ? AND LOWER(name) = LOWER(?) AND position IS NULL
                ORDER BY year DESC, id DESC
                LIMIT 1
                """,
                (school_id, coach_name)
            ).fetchone()
        else:
            existing = conn.execute(
                """
                SELECT * FROM coaches
                WHERE school_id = ? AND LOWER(name) = LOWER(?) AND LOWER(position) = LOWER(?)
                ORDER BY year DESC, id DESC
                LIMIT 1
                """,
                (school_id, coach_name, position)
            ).fetchone()

        if existing:
            existing_name = normalize_person_name(existing["name"])
            existing_position = existing["position"] if existing["position"] is not None else None
            matches = (
                existing_name == coach_name
                and existing_position == position
                and int(existing["is_head_coach"] or 0) == int(is_head_coach)
                and (existing["year"] or current_year) == current_year
            )
            if matches:
                logger.info(
                    "Webhook staff update no_change for %s (%s) at %s",
                    coach_name,
                    school_slug,
                    received_at
                )
                return {
                    "status": "no_change",
                    "message": "Coach already in database",
                    "details": {
                        "school_slug": school_slug,
                        "position": position,
                        "year": current_year
                    }
                }

            conn.execute(
                """
                UPDATE coaches
                SET name = ?, position = ?, is_head_coach = ?, year = ?
                WHERE id = ?
                """,
                (coach_name, position, int(is_head_coach), current_year, existing["id"])
            )
            conn.commit()
            logger.info(
                "Webhook staff update updated coach_id=%s at %s",
                existing["id"],
                received_at
            )
            return {
                "status": "updated",
                "message": "Coach record updated",
                "coach_id": existing["id"],
                "details": {
                    "school_slug": school_slug,
                    "position": position,
                    "year": current_year
                }
            }

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO coaches (name, school_id, position, is_head_coach, year)
            VALUES (?, ?, ?, ?, ?)
            """,
            (coach_name, school_id, position, int(is_head_coach), current_year)
        )
        conn.commit()
        coach_id = cursor.lastrowid
        logger.info(
            "Webhook staff update created coach_id=%s at %s",
            coach_id,
            received_at
        )
        return {
            "status": "created",
            "message": "Coach record created",
            "coach_id": coach_id,
            "details": {
                "school_slug": school_slug,
                "position": position,
                "year": current_year
            }
        }
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.exception("Webhook staff update failed due to database error at %s", received_at)
        raise HTTPException(status_code=500, detail="Database error") from exc
    finally:
        if conn:
            conn.close()

@app.get("/stats")
def get_stats():
    """Get database statistics."""
    conn = get_db()
    stats = {}
    
    stats['schools'] = conn.execute('SELECT COUNT(*) FROM schools').fetchone()[0]
    stats['head_coaches'] = conn.execute('SELECT COUNT(*) FROM coaches WHERE is_head_coach = 1').fetchone()[0]
    stats['assistants'] = conn.execute('SELECT COUNT(*) FROM coaches WHERE is_head_coach = 0').fetchone()[0]
    stats['salaries'] = conn.execute('SELECT COUNT(*) FROM salaries').fetchone()[0]
    
    conn.close()
    return stats

@app.get("/coaches", response_model=List[Coach])
def list_coaches(
    school: Optional[str] = Query(None, description="Filter by school slug"),
    position: Optional[str] = Query(None, description="Filter by position (partial match)"),
    head_only: bool = Query(False, description="Only return head coaches"),
    limit: int = Query(2500, le=3000, description="Max results (default 2500 to include all coaches)")
):
    """List coaches with optional filters."""
    conn = get_db()
    
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
            ORDER BY s2.year DESC, COALESCE(s2.source_date, '') DESC, s2.id DESC
            LIMIT 1
        )
        WHERE 1=1
    '''
    params = []
    
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
            ORDER BY s2.year DESC, COALESCE(s2.source_date, '') DESC, s2.id DESC
            LIMIT 1
        )
        WHERE c.id = ?
    ''', (coach_id,)).fetchone()
    
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Coach not found")
    
    return Coach(**dict(row))

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

@app.get("/schools", response_model=List[School])
def list_schools(
    conference: Optional[str] = Query(None, description="Filter by conference abbrev"),
    limit: int = Query(100, le=500)
):
    """List schools with head coach and staff count."""
    conn = get_db()
    
    query = '''
        SELECT s.id, s.name, s.slug, conf.abbrev as conference,
               (SELECT name FROM coaches WHERE school_id = s.id AND is_head_coach = 1 LIMIT 1) as head_coach,
               (SELECT COUNT(*) FROM coaches WHERE school_id = s.id) as staff_count
        FROM schools s
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        WHERE 1=1
    '''
    params = []
    
    if conference:
        query += ' AND conf.abbrev = ?'
        params.append(conference)
    
    query += ' ORDER BY s.name LIMIT ?'
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    return [School(**dict(row)) for row in rows]

@app.get("/schools/{slug}")
def get_school(slug: str):
    """Get school details with full staff."""
    conn = get_db()
    
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
            ORDER BY s2.year DESC, COALESCE(s2.source_date, '') DESC, s2.id DESC
            LIMIT 1
        )
        WHERE c.school_id = ?
        ORDER BY c.is_head_coach DESC, c.position
    ''', (school['id'],)).fetchall()
    
    conn.close()
    
    return {
        **dict(school),
        "staff": [dict(row) for row in staff]
    }

@app.get("/salaries", response_model=List[Salary])
def list_salaries(
    min_pay: Optional[int] = Query(None, description="Minimum total pay"),
    conference: Optional[str] = Query(None, description="Filter by conference"),
    limit: int = Query(50, le=200)
):
    """List head coach salaries."""
    conn = get_db()
    
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

@app.get("/search")
def search(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, le=100)
):
    """Search coaches by name."""
    conn = get_db()
    
    rows = conn.execute('''
        SELECT c.id, c.name, s.name as school, c.position, c.is_head_coach
        FROM coaches c
        LEFT JOIN schools s ON c.school_id = s.id
        WHERE c.name LIKE ?
        ORDER BY c.is_head_coach DESC, c.name
        LIMIT ?
    ''', (f'%{q}%', limit)).fetchall()
    
    conn.close()
    
    return [dict(row) for row in rows]

# --- For YR Call Sheets integration ---

from fastapi.responses import PlainTextResponse

@app.get("/yr/{school_slug}/coaches")
def yr_coaches(
    school_slug: str,
    position: Optional[str] = Query(None, description="Filter to single position (OC, OL, TE, WR, RB, SC)"),
    format: Optional[str] = Query(None, description="Output format: 'text' for plain text lines")
):
    """Get offensive coaches for YR Call Sheets integration."""
    conn = get_db()
    
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
        WHERE s.slug = ?
    ''', (school_slug,)).fetchall()
    
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
