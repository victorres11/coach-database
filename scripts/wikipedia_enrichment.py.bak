#!/usr/bin/env python3
"""
Wikipedia Enrichment for Coach Database
Fetches coaching lineage, career history, and photos from Wikipedia.
"""

import json
import requests
import re
import time
from pathlib import Path

WIKI_API = "https://en.wikipedia.org/api/rest_v1/page/summary"
WIKI_HTML_API = "https://en.wikipedia.org/api/rest_v1/page/html"

# Wikipedia requires a User-Agent header
HEADERS = {
    "User-Agent": "CoachDatabase/1.0 (https://github.com/victorres11/coach-database; contact@example.com)"
}

def fetch_wiki_summary(coach_name: str) -> dict | None:
    """Fetch Wikipedia summary for a coach."""
    # Convert name to Wikipedia title format
    wiki_title = coach_name.replace(" ", "_")
    
    try:
        resp = requests.get(f"{WIKI_API}/{wiki_title}", headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        # Try with "(American football)" suffix for disambiguation
        resp = requests.get(f"{WIKI_API}/{wiki_title}_(American_football)", headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        # Try with "coach" suffix
        resp = requests.get(f"{WIKI_API}/{wiki_title}_(American_football_coach)", headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error fetching {coach_name}: {e}")
    return None

def extract_coaching_tree(extract: str) -> dict:
    """Extract coaching tree info from Wikipedia extract."""
    tree = {
        "mentors": [],  # Who they worked under
        "proteges": [], # Who worked under them (if mentioned)
        "career_stops": []
    }
    
    # Common patterns for career progression
    ga_pattern = r"graduate assistant[s]? (?:at|for) ([A-Z][a-z]+(?: [A-Z][a-z]+)*)"
    assistant_pattern = r"assistant (?:coach )?\s*(?:at|for) ([A-Z][a-z]+(?: [A-Z][a-z]+)*)"
    coordinator_pattern = r"(?:offensive|defensive) coordinator (?:at|for) ([A-Z][a-z]+(?: [A-Z][a-z]+)*)"
    head_coach_pattern = r"head coach (?:of |at |for )?(?:the )?([A-Z][a-z]+(?: [A-Z][a-z]+)*)"
    
    # Extract career stops
    for pattern, role in [
        (ga_pattern, "GA"),
        (assistant_pattern, "Assistant"),
        (coordinator_pattern, "Coordinator"),
        (head_coach_pattern, "Head Coach")
    ]:
        matches = re.findall(pattern, extract, re.IGNORECASE)
        for match in matches:
            if match not in [s["school"] for s in tree["career_stops"]]:
                tree["career_stops"].append({"school": match, "role": role})
    
    # Look for "under [Coach Name]" patterns
    under_pattern = r"under (?:head coach )?([A-Z][a-z]+ [A-Z][a-z]+)"
    mentors = re.findall(under_pattern, extract)
    tree["mentors"] = list(set(mentors))
    
    return tree

def enrich_coach(coach_name: str) -> dict:
    """Enrich a single coach with Wikipedia data."""
    wiki_data = fetch_wiki_summary(coach_name)
    
    if not wiki_data:
        return {
            "name": coach_name,
            "wikipedia": None,
            "enriched": False
        }
    
    extract = wiki_data.get("extract", "")
    coaching_tree = extract_coaching_tree(extract)
    
    return {
        "name": coach_name,
        "wikipedia": {
            "title": wiki_data.get("title"),
            "description": wiki_data.get("description"),
            "extract": extract,
            "thumbnail": wiki_data.get("thumbnail", {}).get("source"),
            "page_url": wiki_data.get("content_urls", {}).get("desktop", {}).get("page")
        },
        "coaching_tree": coaching_tree,
        "enriched": True
    }

def enrich_all_coaches(input_file: str, output_file: str):
    """Enrich all coaches from input JSON file."""
    with open(input_file) as f:
        coaches = json.load(f)
    
    enriched = []
    for i, coach in enumerate(coaches):
        name = coach.get("coach") or coach.get("name")
        if not name:
            continue
        
        print(f"[{i+1}/{len(coaches)}] Enriching {name}...")
        data = enrich_coach(name)
        
        # Merge with existing data
        enriched_coach = {**coach, **data}
        enriched.append(enriched_coach)
        
        # Rate limit: 1 request per second
        time.sleep(1)
    
    with open(output_file, "w") as f:
        json.dump(enriched, f, indent=2)
    
    print(f"\nEnriched {len(enriched)} coaches -> {output_file}")
    success = sum(1 for c in enriched if c.get("enriched"))
    print(f"Success rate: {success}/{len(enriched)} ({100*success/len(enriched):.1f}%)")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Enrich coach data with Wikipedia info")
    parser.add_argument("--input", default="data/coaches.json", help="Input JSON file")
    parser.add_argument("--output", default="data/coaches_enriched.json", help="Output JSON file")
    parser.add_argument("--single", help="Enrich a single coach by name")
    args = parser.parse_args()
    
    if args.single:
        result = enrich_coach(args.single)
        print(json.dumps(result, indent=2))
    else:
        enrich_all_coaches(args.input, args.output)
