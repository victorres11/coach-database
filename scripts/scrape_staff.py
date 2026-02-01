#!/usr/bin/env python3
"""
Scrape D1 football coaching staff from school athletic pages.
Phase 1: Scrapes all FBS/FCS if --full specified.
Usage:
  python scripts/scrape_staff.py --full --csv data/full_roster.csv
"""

import json
import time
import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# Sample schools for testing (Power 4 + G5)
TEST_SCHOOLS = [
    {"name": "Georgia", "url": "https://georgiadogs.com/sports/football/coaches", "conference": "SEC"},
    {"name": "Ohio State", "url": "https://ohiostatebuckeyes.com/sports/football/coaches/", "conference": "Big Ten"},
    {"name": "USC", "url": "https://usctrojans.com/sports/football/coaches", "conference": "Big Ten"},
    {"name": "Boise State", "url": "https://broncosports.com/sports/football/coaches", "conference": "Mountain West"},
    {"name": "Memphis", "url": "https://gotigersgo.com/sports/football/coaches", "conference": "American"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Utility: Load full FBS+FCS school list
def load_school_list(path=None):
    """Load FBS+FCS schools [{name, url, conference}, ...]."""
    import json
    from pathlib import Path
    if path is None:
        path = Path(__file__).parent.parent / "data" / "fbs_fcs_schools.json"
    with open(path, "r") as f:
        return json.load(f)

def resolve_nuxt_value(data, idx):
    if idx is None or not isinstance(idx, int):
        return idx
    if idx < 0 or idx >= len(data):
        return None
    return data[idx]

def extract_coaches_from_nuxt(html, school_name, conference):
    coaches = []
    soup = BeautifulSoup(html, 'html.parser')
    nuxt_script = soup.find('script', {'id': '__NUXT_DATA__'})
    if not nuxt_script:
        print(f"  No __NUXT_DATA__ found for {school_name}")
        return coaches
    try:
        data = json.loads(nuxt_script.string)
        for i, item in enumerate(data):
            if isinstance(item, dict):
                if 'firstName' in item and 'lastName' in item:
                    first_name = resolve_nuxt_value(data, item.get('firstName'))
                    last_name = resolve_nuxt_value(data, item.get('lastName'))
                    title = resolve_nuxt_value(data, item.get('title'))
                    if isinstance(first_name, str) and isinstance(last_name, str):
                        full_name = f"{first_name.strip()} {last_name.strip()}".strip()
                        if full_name and full_name != " ":
                            coach = {
                                "school": school_name,
                                "conference": conference,
                                "name": full_name,
                            }
                            if title and isinstance(title, str):
                                coach['position'] = title.strip()
                            if item.get('isHeadCoach'):
                                coach['is_head_coach'] = True
                            coaches.append(coach)
        print(f"  Found {len(coaches)} coaches at {school_name}")
    except Exception as e:
        print(f"  Error extracting coaches for {school_name}: {e}")
    return coaches

def scrape_sidearm_staff(url, school_name, conference):
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        coaches = extract_coaches_from_nuxt(response.text, school_name, conference)
        if coaches:
            return coaches
        print(f"  Falling back to HTML parsing for {school_name}")
        return scrape_html_fallback(response.text, school_name, conference)
    except Exception as e:
        print(f"  Error scraping {school_name}: {e}")
        return []

def scrape_html_fallback(html, school_name, conference):
    coaches = []
    soup = BeautifulSoup(html, 'html.parser')
    selectors = [
        '.sidearm-coaches-coach',
        '.coach-card',
        '.staff-member',
        'article.coach',
        '.c-coaches__list-item',
    ]
    coach_elements = []
    for selector in selectors:
        coach_elements = soup.select(selector)
        if coach_elements:
            break
    if not coach_elements:
        coach_elements = soup.find_all(['article', 'div'], class_=lambda x: x and 'coach' in x.lower()) if soup else []
    for elem in coach_elements:
        coach = extract_coach_from_html(elem, school_name, conference)
        if coach and coach.get('name'):
            coaches.append(coach)
    print(f"  Found {len(coaches)} coaches at {school_name} (HTML)")
    return coaches

def extract_coach_from_html(elem, school, conference):
    coach = {
        "school": school,
        "conference": conference,
    }
    name_selectors = [
        '.sidearm-coaches-coach-name',
        '.coach-name',
        '.staff-name',
        'h3', 'h4',
        '.name',
        'a[href*="coaches"]',
    ]
    for selector in name_selectors:
        name_elem = elem.select_one(selector)
        if name_elem:
            text = name_elem.get_text(strip=True)
            if text and len(text) > 2 and not text.lower().startswith('coach'):
                coach['name'] = text
                break
    title_selectors = [
        '.sidearm-coaches-coach-title',
        '.coach-title',
        '.staff-title',
        '.position',
        '.title',
    ]
    for selector in title_selectors:
        title_elem = elem.select_one(selector)
        if title_elem:
            coach['position'] = title_elem.get_text(strip=True)
            break
    return coach

def run_test():
    """Test scraper on subset of schools."""
    all_coaches = []
    print("Testing staff scraper on 5 schools...\n")
    for school in TEST_SCHOOLS:
        print(f"Scraping {school['name']}...")
        coaches = scrape_sidearm_staff(school['url'], school['name'], school['conference'])
        all_coaches.extend(coaches)
        time.sleep(1)
    print(f"\n{'='*50}")
    print(f"Total coaches found: {len(all_coaches)}")
    print(f"{'='*50}\n")
    seen = set()
    unique_coaches = []
    for coach in all_coaches:
        key = (coach.get('name'), coach.get('school'))
        if key not in seen:
            unique_coaches.append(coach)
            seen.add(key)
    print(f"Unique coaches: {len(unique_coaches)}\n")
    print("Sample results:")
    for coach in unique_coaches[:15]:
        pos = coach.get('position', 'Unknown')
        print(f"  {coach.get('name', 'Unknown')} - {pos[:50]} ({coach['school']})")
    output_path = Path(__file__).parent.parent / "data" / "staff_test.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump({
            "metadata": {
                "source": "School athletic websites",
                "testRun": True,
                "schoolsScraped": len(TEST_SCHOOLS),
                "totalCoaches": len(unique_coaches)
            },
            "coaches": unique_coaches
        }, f, indent=2)
    print(f"\nSaved to {output_path}")
    return unique_coaches

# Full FBS/FCS scrape
def run_full_scrape(schools_path=None, out_json=None, out_csv=None):
    """Scrape every FBS/FCS school. Writes JSON/CSV to data/."""
    all_schools = load_school_list(schools_path)
    print(f"Scraping staff for {len(all_schools)} schools...")
    all_coaches = []
    for school in all_schools:
        print(f"Scraping {school['name']}...")
        try:
            coaches = scrape_sidearm_staff(school['url'], school['name'], school['conference'])
        except Exception as e:
            print(f"  ERROR scraping {school['name']}: {e}")
            coaches = []
        all_coaches.extend(coaches)
        time.sleep(0.7)
    seen = set()
    unique_coaches = []
    for coach in all_coaches:
        key = (coach.get('name'), coach.get('school'))
        if key not in seen:
            unique_coaches.append(coach)
            seen.add(key)
    print(f"Scraped {len(unique_coaches)} unique coaches.")
    output_json = Path(out_json or Path(__file__).parent.parent / "data" / "full_roster.json")
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, 'w') as f:
        json.dump({
            "metadata": {
                "source": "School athletic websites",
                "schoolsScraped": len(all_schools),
                "totalCoaches": len(unique_coaches)
            },
            "coaches": unique_coaches
        }, f, indent=2)
    print(f"  Saved JSON: {output_json}")
    if out_csv:
        import csv
        with open(out_csv, 'w', newline='') as fcsv:
            writer = csv.DictWriter(fcsv, fieldnames=["name", "position", "school", "conference"])
            writer.writeheader()
            for c in unique_coaches:
                writer.writerow({
                    "name": c.get("name"),
                    "position": c.get("position", ""),
                    "school": c.get("school"),
                    "conference": c.get("conference"),
                })
        print(f"  Saved CSV: {out_csv}")
    return unique_coaches

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scrape all D1 football coaching staff for FBS/FCS")
    parser.add_argument("--full", action="store_true", help="Scrape all FBS+FCS schools (default: sample test)")
    parser.add_argument("--txfl", action="store_true", help="Scrape just target TX/FL FBS schools")
    parser.add_argument("--schools", type=str, default=str(Path(__file__).parent.parent / "data" / "fbs_fcs_schools.json"), help="School JSON list path")
    parser.add_argument("--json", type=str, default=str(Path(__file__).parent.parent / "data" / "full_roster.json"), help="Path to save JSON output")
    parser.add_argument("--csv", type=str, default=None, help="Optionally also export to CSV")
    args = parser.parse_args()

    if args.txfl:
        # Scrape only TX/FL FBS schools to data/tx_fl_staff.json
        txfl_path = Path(__file__).parent.parent / "data" / "tx_fl_fbs_schools.json"
        out_json = Path(__file__).parent.parent / "data" / "tx_fl_staff.json"
        out_csv = Path(__file__).parent.parent / "data" / "tx_fl_staff.csv"
        print("Scraping TX/FL FBS schools...")
        run_full_scrape(str(txfl_path), str(out_json), str(out_csv))
    elif args.full:
        run_full_scrape(args.schools, args.json, args.csv)
    else:
        print("(For full FBS+FCS scrape, pass --full. Only sample/test mode will run otherwise.)")
        run_test()
