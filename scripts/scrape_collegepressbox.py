#!/usr/bin/env python3
"""
Scrape coaching staff from CollegePressbox.com.

Requires a valid subscription cookie stored at:
  ~/.clawdbot/credentials/collegepressbox_cookie

Usage:
  python scripts/scrape_collegepressbox.py                    # Scrape all teams
  python scripts/scrape_collegepressbox.py --team alabama     # Single team
  python scripts/scrape_collegepressbox.py --fbs-only         # FBS only
  python scripts/scrape_collegepressbox.py --output data/staff.json
"""

import argparse
import json
import re
import time
import sqlite3
from pathlib import Path
from typing import Optional
import requests
from bs4 import BeautifulSoup

# Paths
COOKIE_PATH = Path.home() / ".clawdbot" / "credentials" / "collegepressbox_cookie"
DB_PATH = Path(__file__).parent.parent / "db" / "coaches.db"

# Map collegepressbox slugs to our database slugs where they differ
SLUG_MAPPING = {
    'app-state': 'appalachian-state',
    'jax-state': 'jacksonville-state',
    'miami': 'miami-fl',
    'miami-ohio': 'miami-oh',
    'nc-state': 'north-carolina-state',
    'niu': 'northern-illinois',
    'ole-miss': 'mississippi',
    'pitt': 'pittsburgh',
    'uconn': 'connecticut',
    'umass': 'massachusetts',
    'unlv': 'nevada-las-vegas',
    'usc': 'southern-california',
    'wku': 'western-kentucky',
    # Add more as needed
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# FBS conferences (to filter FBS-only)
FBS_CONFERENCES = {
    'SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12',  # Power conferences
    'American', 'Mountain West', 'Sun Belt', 'MAC', 'C-USA',  # Group of 5
    'Independent'  # Notre Dame, etc.
}


def load_cookie() -> str:
    """Load collegepressbox cookie from credentials."""
    if not COOKIE_PATH.exists():
        raise FileNotFoundError(f"Cookie not found at {COOKIE_PATH}")
    return COOKIE_PATH.read_text().strip()


def get_team_slugs() -> list[dict]:
    """Fetch all team slugs from collegepressbox homepage."""
    cookie = load_cookie()
    resp = requests.get(
        "https://collegepressbox.com/",
        headers={**HEADERS, "Cookie": cookie},
        timeout=30
    )
    resp.raise_for_status()
    
    # Extract team slugs from links
    slugs = re.findall(r'/teams/([a-z0-9-]+)/', resp.text)
    unique_slugs = sorted(set(slugs))
    
    print(f"Found {len(unique_slugs)} teams")
    return [{"slug": s} for s in unique_slugs]


def scrape_team_staff(slug: str, cookie: str) -> list[dict]:
    """Scrape coaching staff for a single team."""
    url = f"https://collegepressbox.com/teams/{slug}/team-staff/"
    
    try:
        resp = requests.get(
            url,
            headers={**HEADERS, "Cookie": cookie},
            timeout=30
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Error fetching {slug}: {e}")
        return []
    
    # Check for paywall
    if "YOU'RE MISSING OUT" in resp.text or "staff-blur" in resp.text:
        print(f"  ⚠️  Paywall detected for {slug} - cookie may be expired")
        return []
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    coaches = []
    
    # Extract team name from page
    title_tag = soup.find('h1')
    team_name = slug.replace('-', ' ').title()
    if title_tag:
        # "App State Mountaineers Coaching Staff" -> "App State"
        title_text = title_tag.get_text()
        if 'Coaching Staff' in title_text:
            team_name = title_text.replace('Coaching Staff', '').strip()
            # Remove mascot if present (e.g., "Mountaineers")
            team_name = re.sub(r'\s+\w+$', '', team_name).strip() or team_name
    
    # Find head coach - displayed in a separate div above the table
    # Pattern: <strong>Head Coach</strong> ... <div>Name</div>
    head_coach_match = re.search(
        r'Head Coach\s*</strong>\s*<div>([^<]+)</div>',
        str(soup),
        re.IGNORECASE | re.DOTALL
    )
    if head_coach_match:
        hc_name = head_coach_match.group(1).strip()
        if hc_name:
            coaches.append({
                "name": hc_name,
                "position": "Head Coach",
                "school": team_name,
                "school_slug": slug,
                "is_head_coach": True
            })
    
    # Parse staff table rows
    # Format: <tr><td><span class="display-none">LastName</span>Full Name</td><td>Position</td><td></td></tr>
    for row in soup.find_all('tr'):
        cells = row.find_all('td')
        if len(cells) >= 2:
            name_cell = cells[0]
            position_cell = cells[1]
            
            # Extract name (remove the hidden span)
            hidden_span = name_cell.find('span', class_='display-none')
            if hidden_span:
                hidden_span.decompose()
            
            name = name_cell.get_text(strip=True)
            position = position_cell.get_text(strip=True)
            
            # Skip empty or header rows
            if not name or not position or name.lower() == 'name' or position.lower() == 'position':
                continue
            
            # Skip if we already have this as head coach
            if position.lower() == 'head coach':
                if not any(c['position'].lower() == 'head coach' for c in coaches):
                    coaches.append({
                        "name": name,
                        "position": position,
                        "school": team_name,
                        "school_slug": slug,
                        "is_head_coach": True
                    })
            else:
                coaches.append({
                    "name": name,
                    "position": position,
                    "school": team_name,
                    "school_slug": slug,
                    "is_head_coach": False
                })
    
    return coaches


def update_database(coaches: list[dict], db_path: Path = DB_PATH):
    """Update the SQLite database with scraped coaches."""
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Group by school
    schools = {}
    for coach in coaches:
        slug = coach['school_slug']
        if slug not in schools:
            schools[slug] = []
        schools[slug].append(coach)
    
    updated = 0
    inserted = 0
    
    for slug, staff in schools.items():
        # Map slug if needed
        db_slug = SLUG_MAPPING.get(slug, slug)
        
        # Find school ID
        cursor.execute("SELECT id FROM schools WHERE slug = ?", (db_slug,))
        row = cursor.fetchone()
        if not row:
            # Try original slug as fallback
            cursor.execute("SELECT id FROM schools WHERE slug = ?", (slug,))
            row = cursor.fetchone()
        if not row:
            print(f"  School not found in DB: {slug} (tried {db_slug})")
            continue
        school_id = row[0]
        
        for coach in staff:
            # Check if coach exists
            cursor.execute(
                "SELECT id FROM coaches WHERE school_id = ? AND name = ?",
                (school_id, coach['name'])
            )
            existing = cursor.fetchone()
            
            if existing:
                # Update position
                cursor.execute(
                    "UPDATE coaches SET position = ?, is_head_coach = ? WHERE id = ?",
                    (coach['position'], coach['is_head_coach'], existing[0])
                )
                updated += 1
            else:
                # Insert new coach
                cursor.execute(
                    "INSERT INTO coaches (name, school_id, position, is_head_coach) VALUES (?, ?, ?, ?)",
                    (coach['name'], school_id, coach['position'], coach['is_head_coach'])
                )
                inserted += 1
    
    conn.commit()
    conn.close()
    
    print(f"\nDatabase updated: {inserted} inserted, {updated} updated")


def main():
    parser = argparse.ArgumentParser(description="Scrape CollegePressbox coaching staff")
    parser.add_argument("--team", help="Scrape single team by slug")
    parser.add_argument("--fbs-only", action="store_true", help="Only scrape FBS teams")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--update-db", action="store_true", help="Update SQLite database")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests (seconds)")
    args = parser.parse_args()
    
    cookie = load_cookie()
    all_coaches = []
    
    if args.team:
        # Single team
        print(f"Scraping {args.team}...")
        coaches = scrape_team_staff(args.team, cookie)
        all_coaches.extend(coaches)
        print(f"  Found {len(coaches)} coaches")
    else:
        # All teams
        teams = get_team_slugs()
        
        for i, team in enumerate(teams):
            slug = team['slug']
            print(f"[{i+1}/{len(teams)}] Scraping {slug}...")
            
            coaches = scrape_team_staff(slug, cookie)
            all_coaches.extend(coaches)
            print(f"  Found {len(coaches)} coaches")
            
            if i < len(teams) - 1:
                time.sleep(args.delay)
    
    print(f"\nTotal: {len(all_coaches)} coaches from {len(set(c['school_slug'] for c in all_coaches))} teams")
    
    # Output
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(all_coaches, indent=2))
        print(f"Saved to {output_path}")
    
    if args.update_db:
        update_database(all_coaches)
    
    if not args.output and not args.update_db:
        # Print sample
        print("\nSample output:")
        for coach in all_coaches[:10]:
            print(f"  {coach['name']} - {coach['position']} ({coach['school']})")


if __name__ == "__main__":
    main()
