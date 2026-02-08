#!/usr/bin/env python3
"""
Scrape FBS head coach salary data from USA Today Sports Data.

Usage:
    python scrape_usatoday.py [--output FILE] [--historical]
    python scrape_usatoday.py --year 2026 --update-db
"""

import argparse
import json
import re
import sys
import sqlite3
import datetime as dt
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

URL = "https://sportsdata.usatoday.com/ncaa/salaries/football/coach"

def parse_number(text: str) -> int | None:
    """Parse a currency/number string to integer."""
    if not text or text == "-":
        return None
    # Remove everything except digits, dots, and minus
    cleaned = re.sub(r'[^0-9.\-]', '', text)
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None

def scrape_coaches():
    """Scrape coach data from USA Today."""
    coaches = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print(f"Loading {URL}...")
        page.goto(URL, wait_until="networkidle")
        
        # Wait for table to load
        page.wait_for_selector("table tbody tr")
        
        # Extract data
        rows = page.query_selector_all("table tbody tr")
        print(f"Found {len(rows)} coaches")
        
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) >= 9:
                coach = {
                    "rank": int(cells[0].inner_text().strip()),
                    "coach": cells[1].inner_text().strip(),
                    "school": cells[2].inner_text().strip(),
                    "totalPay": parse_number(cells[3].inner_text()),
                    "conference": cells[4].inner_text().strip(),
                    "schoolPay": parse_number(cells[5].inner_text()),
                    "maxBonus": parse_number(cells[6].inner_text()),
                    "bonusesPaid": parse_number(cells[7].inner_text()),
                    "buyout": parse_number(cells[8].inner_text()),
                }
                coaches.append(coach)
        
        browser.close()
    
    return coaches

def normalize_school_slug(name: str) -> str:
    """Normalize USA Today school display name into our DB slug style."""
    slug = (name or "").lower().strip()
    # Common variations / punctuation normalization
    slug = slug.replace("&", "and")
    slug = re.sub(r"[^a-z0-9\\s\\-]", "", slug)
    slug = re.sub(r"\\s+", "-", slug).strip("-")
    replacements = {
        "miami-fl": "miami-fl",
        "miami-oh": "miami-oh",
        "ole-miss": "mississippi",
        "army-west-point": "army",
    }
    return replacements.get(slug, slug)


def upsert_usatoday_db(coaches: list[dict], db_path: Path, year: int) -> None:
    """Insert/update USA Today salary rows for a given season year.

    This only writes rows for the provided `year` (never touches prior seasons).
    """
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found at {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    inserted_coaches = 0
    inserted_salaries = 0
    updated_salaries = 0
    source_date = dt.date.today().isoformat()

    for row in coaches:
        coach_name = row.get("coach")
        school_name = row.get("school")
        if not coach_name or not school_name:
            continue

        school_slug = normalize_school_slug(school_name)
        school = cur.execute("SELECT id FROM schools WHERE slug = ? LIMIT 1", (school_slug,)).fetchone()
        if not school:
            # If the school doesn't exist yet, insert it without conference linkage.
            cur.execute(
                "INSERT OR IGNORE INTO schools (name, slug) VALUES (?, ?)",
                (school_name, school_slug),
            )
            school = cur.execute("SELECT id FROM schools WHERE slug = ? LIMIT 1", (school_slug,)).fetchone()
        if not school:
            continue
        school_id = int(school["id"])

        coach = cur.execute(
            """
            SELECT id
            FROM coaches
            WHERE school_id = ? AND name = ? AND year = ?
            ORDER BY is_head_coach DESC, id DESC
            LIMIT 1
            """,
            (school_id, coach_name, year),
        ).fetchone()
        if not coach:
            cur.execute(
                """
                INSERT INTO coaches (name, school_id, position, is_head_coach, year)
                VALUES (?, ?, 'Head Coach', 1, ?)
                """,
                (coach_name, school_id, year),
            )
            coach_id = int(cur.lastrowid)
            inserted_coaches += 1
        else:
            coach_id = int(coach["id"])

        existing_salary = cur.execute(
            "SELECT id FROM salaries WHERE coach_id = ? AND year = ? AND source = 'usa_today' LIMIT 1",
            (coach_id, year),
        ).fetchone()

        payload = (
            row.get("totalPay"),
            row.get("schoolPay"),
            row.get("maxBonus"),
            row.get("bonusesPaid"),
            row.get("buyout"),
            source_date,
        )

        if existing_salary:
            cur.execute(
                """
                UPDATE salaries
                SET total_pay = ?, school_pay = ?, max_bonus = ?, bonuses_paid = ?, buyout = ?, source_date = ?
                WHERE id = ?
                """,
                (*payload, int(existing_salary["id"])),
            )
            updated_salaries += 1
        else:
            cur.execute(
                """
                INSERT INTO salaries (coach_id, year, total_pay, school_pay, max_bonus, bonuses_paid, buyout, source, source_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'usa_today', ?)
                """,
                (coach_id, year, *payload),
            )
            inserted_salaries += 1

    conn.commit()
    conn.close()
    print(
        f"\nDB updated for year={year}: "
        f"{inserted_coaches} coaches inserted, {inserted_salaries} salaries inserted, {updated_salaries} salaries updated"
    )


def save_data(coaches: list, output_path: Path, historical: bool = False):
    """Save coach data to JSON file."""
    data = {
        "metadata": {
            "source": "USA Today Sports Data",
            "sourceUrl": URL,
            "lastUpdated": datetime.now().strftime("%Y-%m-%d"),
            "totalCoaches": len(coaches),
            "sport": "football",
            "division": "FBS"
        },
        "coaches": coaches
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"Saved {len(coaches)} coaches to {output_path}")
    
    # Also save historical snapshot
    if historical:
        hist_path = output_path.parent.parent / "historical" / f"{datetime.now().strftime('%Y-%m-%d')}.json"
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(hist_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Saved historical snapshot to {hist_path}")

def main():
    parser = argparse.ArgumentParser(description="Scrape FBS coach salary data from USA Today")
    parser.add_argument("--output", "-o", default="data/coaches.json", help="Output file path")
    parser.add_argument("--historical", "-H", action="store_true", help="Also save historical snapshot")
    parser.add_argument("--year", type=int, default=None, help="Season year to write to DB (default: current year)")
    parser.add_argument("--update-db", action="store_true", help="Insert/update data into SQLite DB")
    parser.add_argument("--db", type=str, default="db/coaches.db", help="SQLite DB path (relative to repo root)")
    args = parser.parse_args()
    
    # Resolve path relative to script location
    script_dir = Path(__file__).parent.parent
    output_path = script_dir / args.output
    db_path = script_dir / args.db
    season_year = int(args.year or dt.date.today().year)
    
    coaches = scrape_coaches()
    save_data(coaches, output_path, historical=args.historical)
    if args.update_db:
        upsert_usatoday_db(coaches, db_path=db_path, year=season_year)
    
    # Print summary stats
    salaries = [c["totalPay"] for c in coaches if c["totalPay"]]
    if salaries:
        print(f"\n--- Summary ---")
        print(f"Coaches with salary data: {len(salaries)}/{len(coaches)}")
        print(f"Highest paid: {coaches[0]['coach']} ({coaches[0]['school']}) - ${coaches[0]['totalPay']:,}")
        print(f"Average salary: ${sum(salaries) // len(salaries):,}")
        print(f"Total salaries: ${sum(salaries):,}")

if __name__ == "__main__":
    main()
