#!/usr/bin/env python3
"""
Migrate JSON coach data to SQLite database.

Sources:
- coach-database/data/coaches.json (USA Today salaries)
- coaching-db/2025/coaches.json (CollegePressBox staff)
"""

import sqlite3
import json
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / 'coaches.db'
SCHEMA_PATH = Path(__file__).parent / 'schema.sql'

# Data sources
SALARY_JSON = Path(__file__).parent.parent / 'data' / 'coaches.json'
STAFF_JSON = Path(__file__).parent.parent.parent / 'coaching-db' / '2025' / 'coaches.json'

# Conference mapping
CONFERENCE_MAP = {
    'SEC': ('SEC', 'Southeastern Conference', 'FBS'),
    'Big 10': ('Big 10', 'Big Ten Conference', 'FBS'),
    'Big 12': ('Big 12', 'Big 12 Conference', 'FBS'),
    'ACC': ('ACC', 'Atlantic Coast Conference', 'FBS'),
    'Pac-12': ('Pac-12', 'Pac-12 Conference', 'FBS'),
    'AMER': ('AAC', 'American Athletic Conference', 'FBS'),
    'MWC': ('MWC', 'Mountain West Conference', 'FBS'),
    'SBC': ('SBC', 'Sun Belt Conference', 'FBS'),
    'MAC': ('MAC', 'Mid-American Conference', 'FBS'),
    'CUSA': ('CUSA', 'Conference USA', 'FBS'),
    'IndFBS': ('IND', 'FBS Independents', 'FBS'),
}

def init_db():
    """Create database and tables."""
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    return conn

def load_conferences(conn):
    """Load conferences into DB."""
    cursor = conn.cursor()
    for abbrev, (db_abbrev, name, division) in CONFERENCE_MAP.items():
        cursor.execute('''
            INSERT OR IGNORE INTO conferences (abbrev, name, division)
            VALUES (?, ?, ?)
        ''', (db_abbrev, name, division))
    conn.commit()
    
    # Return mapping of abbrev -> id
    cursor.execute('SELECT abbrev, id FROM conferences')
    return {row[0]: row[1] for row in cursor.fetchall()}

def normalize_school_name(name):
    """Normalize school names for matching."""
    name = name.lower().strip()
    # Common variations
    replacements = {
        'miami (fl)': 'miami',
        'miami (oh)': 'miami-oh',
        'ole miss': 'mississippi',
        'north carolina state': 'nc-state',
        'army west point': 'army',
    }
    return replacements.get(name, name.replace(' ', '-'))

def load_salary_data(conn, conf_map):
    """Load USA Today salary data."""
    if not SALARY_JSON.exists():
        print(f"Warning: {SALARY_JSON} not found")
        return {}
    
    with open(SALARY_JSON) as f:
        data = json.load(f)
    
    cursor = conn.cursor()
    school_map = {}  # school name -> id
    coach_map = {}   # (name, school) -> id
    
    for coach in data.get('coaches', []):
        school_name = coach['school']
        conf_abbrev = CONFERENCE_MAP.get(coach.get('conference', ''), ('IND', '', 'FBS'))[0]
        conf_id = conf_map.get(conf_abbrev)
        
        # Insert school
        slug = normalize_school_name(school_name)
        cursor.execute('''
            INSERT OR IGNORE INTO schools (name, slug, conference_id)
            VALUES (?, ?, ?)
        ''', (school_name, slug, conf_id))
        
        cursor.execute('SELECT id FROM schools WHERE slug = ?', (slug,))
        school_id = cursor.fetchone()[0]
        school_map[slug] = school_id
        
        # Insert head coach
        cursor.execute('''
            INSERT INTO coaches (name, school_id, position, is_head_coach, year)
            VALUES (?, ?, 'Head Coach', 1, 2025)
        ''', (coach['coach'], school_id))
        coach_id = cursor.lastrowid
        coach_map[(coach['coach'], school_name)] = coach_id
        
        # Insert salary
        cursor.execute('''
            INSERT INTO salaries (coach_id, year, total_pay, school_pay, max_bonus, bonuses_paid, buyout, source)
            VALUES (?, 2025, ?, ?, ?, ?, ?, 'usa_today')
        ''', (coach_id, coach.get('totalPay'), coach.get('schoolPay'), 
              coach.get('maxBonus'), coach.get('bonusesPaid'), coach.get('buyout')))
    
    conn.commit()
    print(f"Loaded {len(data.get('coaches', []))} head coaches with salaries")
    return school_map

def load_staff_data(conn, school_map):
    """Load CollegePressBox staff data."""
    if not STAFF_JSON.exists():
        print(f"Warning: {STAFF_JSON} not found")
        return
    
    with open(STAFF_JSON) as f:
        data = json.load(f)
    
    cursor = conn.cursor()
    staff_count = 0
    new_schools = 0
    
    for slug, team_data in data.items():
        if slug.startswith('_'):
            continue
            
        # Check if school exists
        if slug not in school_map:
            # Add new school (likely FCS or not in USA Today data)
            school_name = slug.replace('-', ' ').title()
            cursor.execute('''
                INSERT OR IGNORE INTO schools (name, slug)
                VALUES (?, ?)
            ''', (school_name, slug))
            cursor.execute('SELECT id FROM schools WHERE slug = ?', (slug,))
            result = cursor.fetchone()
            if result:
                school_map[slug] = result[0]
                new_schools += 1
        
        school_id = school_map.get(slug)
        if not school_id:
            continue
        
        scraped_at = team_data.get('scraped_at')
        
        # Check if we already have a head coach for this school
        cursor.execute('''
            SELECT id FROM coaches WHERE school_id = ? AND is_head_coach = 1 AND year = 2025
        ''', (school_id,))
        existing_hc = cursor.fetchone()
        
        # Add head coach if not exists
        hc_name = team_data.get('head_coach')
        if hc_name and not existing_hc:
            cursor.execute('''
                INSERT INTO coaches (name, school_id, position, is_head_coach, year, cpb_scraped_at)
                VALUES (?, ?, 'Head Coach', 1, 2025, ?)
            ''', (hc_name, school_id, scraped_at))
        
        # Add assistant coaches
        for coach in team_data.get('coaches', []):
            name = coach.get('name')
            position = coach.get('position')
            
            if not name or not position:
                continue
            
            # Skip if this looks like a head coach entry
            if 'Head Coach' in position and 'Assistant' not in position:
                continue
            
            cursor.execute('''
                INSERT INTO coaches (name, school_id, position, is_head_coach, year, cpb_scraped_at)
                VALUES (?, ?, ?, 0, 2025, ?)
            ''', (name, school_id, position, scraped_at))
            staff_count += 1
    
    conn.commit()
    print(f"Loaded {staff_count} assistant coaches")
    print(f"Added {new_schools} new schools (FCS/other)")

def print_stats(conn):
    """Print database statistics."""
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM schools')
    schools = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM coaches WHERE is_head_coach = 1')
    hcs = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM coaches WHERE is_head_coach = 0')
    assistants = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM salaries')
    salaries = cursor.fetchone()[0]
    
    print(f"\n📊 Database Stats:")
    print(f"   Schools: {schools}")
    print(f"   Head Coaches: {hcs}")
    print(f"   Assistant Coaches: {assistants}")
    print(f"   Salary Records: {salaries}")
    print(f"\n   Database: {DB_PATH}")

def main():
    print("🏈 Coach Database Migration")
    print("=" * 40)
    
    # Initialize
    print("\n1. Creating database schema...")
    conn = init_db()
    
    # Load conferences
    print("2. Loading conferences...")
    conf_map = load_conferences(conn)
    
    # Load USA Today salary data
    print("3. Loading USA Today salary data...")
    school_map = load_salary_data(conn, conf_map)
    
    # Load CollegePressBox staff data
    print("4. Loading CollegePressBox staff data...")
    load_staff_data(conn, school_map)
    
    # Stats
    print_stats(conn)
    
    conn.close()
    print("\n✅ Migration complete!")

if __name__ == '__main__':
    main()
