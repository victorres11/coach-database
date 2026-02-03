#!/usr/bin/env python3
"""
Coach Database API

FastAPI service for querying college football coaching data.
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
from pathlib import Path

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
    conference: Optional[str]
    total_pay: Optional[int] = None
    
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

# --- Routes ---

@app.get("/")
def root():
    """API health check."""
    return {
        "status": "ok",
        "service": "Coach Database API",
        "version": "1.0.0"
    }

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
               c.position, c.is_head_coach, conf.abbrev as conference,
               sal.total_pay
        FROM coaches c
        LEFT JOIN schools s ON c.school_id = s.id
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        LEFT JOIN salaries sal ON c.id = sal.coach_id
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
               c.position, c.is_head_coach, conf.abbrev as conference,
               sal.total_pay
        FROM coaches c
        LEFT JOIN schools s ON c.school_id = s.id
        LEFT JOIN conferences conf ON s.conference_id = conf.id
        LEFT JOIN salaries sal ON c.id = sal.coach_id
        WHERE c.id = ?
    ''', (coach_id,)).fetchone()
    
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Coach not found")
    
    return Coach(**dict(row))

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
        SELECT c.id, c.name, c.position, c.is_head_coach, sal.total_pay
        FROM coaches c
        LEFT JOIN salaries sal ON c.id = sal.coach_id
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
