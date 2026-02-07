#!/usr/bin/env python3
"""
Research play callers for Power 4 teams using Perplexity API.
Updates coach-database with is_play_caller flag and source.
"""

import sqlite3
import json
import os
import time
import requests
from pathlib import Path

# Config
DB_PATH = Path(__file__).parent.parent / "db" / "coaches.db"
PERPLEXITY_KEY_PATH = Path.home() / ".openclaw" / "credentials" / "perplexity_api_key"
POWER_4_CONF_IDS = [1, 2, 3, 4]  # SEC, Big Ten, Big 12, ACC

def get_perplexity_key():
    return PERPLEXITY_KEY_PATH.read_text().strip()

def query_perplexity(prompt: str) -> dict:
    """Query Perplexity API for play caller info."""
    api_key = get_perplexity_key()
    
    response = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "sonar",
            "messages": [
                {"role": "system", "content": "You are a college football research assistant. Answer concisely with facts only."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500
        }
    )
    return response.json()

def get_power4_teams(conn) -> list:
    """Get all Power 4 teams with their OCs."""
    cur = conn.cursor()
    cur.execute('''
        SELECT 
            s.id as school_id,
            s.name as school,
            conf.name as conference,
            c.id as coach_id,
            c.name as coach,
            c.position
        FROM coaches c
        JOIN schools s ON c.school_id = s.id
        JOIN conferences conf ON s.conference_id = conf.id
        WHERE conf.id IN (1, 2, 3, 4)
        AND (c.position LIKE '%Offensive Coordinator%' 
             OR c.position LIKE '%OC%'
             OR c.is_head_coach = 1)
        ORDER BY conf.name, s.name, c.is_head_coach DESC
    ''')
    return cur.fetchall()

def research_play_caller(school: str, oc_name: str, hc_name: str = None) -> tuple:
    """
    Research who calls plays for a team.
    Returns (is_oc_play_caller: bool, source: str, notes: str)
    """
    prompt = f"""For {school} college football in the 2025 season, who calls the offensive plays during games? 
Is it the head coach or the offensive coordinator ({oc_name})?
Answer with just: "HC calls plays" or "OC calls plays" or "Unknown", followed by a brief source."""

    try:
        result = query_perplexity(prompt)
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        citations = result.get("citations", [])
        
        # Parse response
        content_lower = content.lower()
        if "oc calls plays" in content_lower or oc_name.lower() in content_lower:
            return (True, citations[0] if citations else "Perplexity search", content[:200])
        elif "hc calls plays" in content_lower or "head coach" in content_lower:
            return (False, citations[0] if citations else "Perplexity search", content[:200])
        else:
            return (None, "", content[:200])  # Unknown
    except Exception as e:
        return (None, "", f"Error: {e}")

def main():
    conn = sqlite3.connect(DB_PATH)
    
    # Get all Power 4 teams and staff
    teams_data = get_power4_teams(conn)
    
    # Group by school
    schools = {}
    for row in teams_data:
        school_id, school, conference, coach_id, coach, position = row
        if school not in schools:
            schools[school] = {"school_id": school_id, "conference": conference, "hc": None, "ocs": []}
        
        if "Head Coach" in position:
            schools[school]["hc"] = {"id": coach_id, "name": coach}
        elif "Offensive Coordinator" in position or "OC" in position:
            schools[school]["ocs"].append({"id": coach_id, "name": coach, "position": position})
    
    print(f"Found {len(schools)} Power 4 teams")
    print("=" * 80)
    
    results = []
    cur = conn.cursor()
    
    for school, data in schools.items():
        hc = data.get("hc")
        ocs = data.get("ocs", [])
        
        if not ocs:
            print(f"⚠️  {school}: No OC found in database")
            results.append({
                "school": school,
                "conference": data["conference"],
                "oc": "MISSING",
                "play_caller": "Unknown",
                "source": ""
            })
            continue
        
        # Get primary OC (first one, usually has "Offensive Coordinator" in title)
        primary_oc = ocs[0]
        for oc in ocs:
            if "Offensive Coordinator" in oc["position"] and "Co-" not in oc["position"]:
                primary_oc = oc
                break
        
        print(f"\n🔍 {school} ({data['conference']})")
        print(f"   OC: {primary_oc['name']} ({primary_oc['position']})")
        
        # Research play caller
        is_oc_caller, source, notes = research_play_caller(
            school, 
            primary_oc["name"],
            hc["name"] if hc else None
        )
        
        # Update database
        if is_oc_caller is True:
            cur.execute(
                "UPDATE coaches SET is_play_caller = 1, play_caller_source = ? WHERE id = ?",
                (source, primary_oc["id"])
            )
            play_caller = primary_oc["name"]
            print(f"   ✅ Play Caller: {play_caller} (OC)")
        elif is_oc_caller is False and hc:
            cur.execute(
                "UPDATE coaches SET is_play_caller = 1, play_caller_source = ? WHERE id = ?",
                (source, hc["id"])
            )
            play_caller = hc["name"]
            print(f"   ✅ Play Caller: {play_caller} (HC)")
        else:
            play_caller = f"{primary_oc['name']} (assumed)"
            print(f"   ❓ Play Caller: Unknown, assuming OC")
            # Default to OC as play caller
            cur.execute(
                "UPDATE coaches SET is_play_caller = 1, play_caller_source = 'Assumed - OC default' WHERE id = ?",
                (primary_oc["id"],)
            )
        
        results.append({
            "school": school,
            "conference": data["conference"],
            "oc": primary_oc["name"],
            "play_caller": play_caller,
            "source": source
        })
        
        # Rate limit
        time.sleep(1)
    
    conn.commit()
    conn.close()
    
    # Output CSV
    print("\n" + "=" * 80)
    print("RESULTS CSV:")
    print("=" * 80)
    print("Conference,School,OC,Play Caller,Source")
    for r in sorted(results, key=lambda x: (x["conference"], x["school"])):
        print(f"{r['conference']},{r['school']},{r['oc']},{r['play_caller']},{r['source']}")
    
    # Save to file
    csv_path = Path(__file__).parent.parent / "data" / "play_callers.csv"
    csv_path.parent.mkdir(exist_ok=True)
    with open(csv_path, "w") as f:
        f.write("Conference,School,OC,Play Caller,Source\n")
        for r in sorted(results, key=lambda x: (x["conference"], x["school"])):
            f.write(f"{r['conference']},{r['school']},{r['oc']},{r['play_caller']},{r['source']}\n")
    print(f"\n✅ Saved to {csv_path}")

if __name__ == "__main__":
    main()
