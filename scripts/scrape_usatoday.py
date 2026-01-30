#!/usr/bin/env python3
"""
Scrape FBS head coach salary data from USA Today Sports Data.

Usage:
    python scrape_usatoday.py [--output FILE] [--historical]
"""

import argparse
import json
import re
import sys
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
    args = parser.parse_args()
    
    # Resolve path relative to script location
    script_dir = Path(__file__).parent.parent
    output_path = script_dir / args.output
    
    coaches = scrape_coaches()
    save_data(coaches, output_path, historical=args.historical)
    
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
