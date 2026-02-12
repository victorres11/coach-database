#!/usr/bin/env python3
"""
Play Caller Pipeline — Automated identification of offensive play callers.

Data model:
- play_callers: primary play caller per team per season (set by annual sweep)
- play_caller_changes: mid-season changes detected by incremental runs

Pipeline stages:
1. Web Search — query for coaching staff, play-calling assignments
2. Citation Extraction — pull sources from search results
3. Confidence Scoring — rate reliability of each data point
4. DB Update — write verified updates to Coach Database

Usage:
    # Annual sweep (set primary callers)
    python play_caller_pipeline.py --all-teams --apply -v -o results.json

    # Single team lookup
    python play_caller_pipeline.py "Michigan State" -v

    # Incremental update (detects changes vs primary)
    python play_caller_pipeline.py --all-teams --incremental --apply -v

    # Show current data
    python play_caller_pipeline.py --show "Auburn"
    python play_caller_pipeline.py --show-all
"""

import argparse
import json
import os
import sys
import time
import sqlite3
import requests
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
COACH_DB_API = os.environ.get("COACH_DB_API", "https://coach-database-api.fly.dev")
LOCAL_DB = Path(__file__).parent.parent / "db" / "coaches.db"

# ── Web Search ──────────────────────────────────────────────────────────────

def search_play_caller(team_name: str, year: int = 2025) -> list[dict]:
    """Search for play-calling information about a team."""
    queries = [
        f"{team_name} offensive play caller {year} football",
        f"{team_name} who calls plays {year} college football",
        f"{team_name} offensive coordinator {year}",
    ]

    all_results = []
    for query in queries:
        results = brave_search(query)
        all_results.extend(results)
        time.sleep(1)  # Rate limit between queries

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in all_results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    return unique


def brave_search(query: str, count: int = 5) -> list[dict]:
    """Execute a Brave Search API call."""
    if not BRAVE_API_KEY:
        print("⚠️  No BRAVE_API_KEY set, falling back to mock results")
        return []

    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": count},
        headers={"X-Subscription-Token": BRAVE_API_KEY, "Accept": "application/json"},
        timeout=10,
    )
    if resp.status_code == 429:
        print("   ⏳ Rate limited, waiting 5s...")
        time.sleep(5)
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": count},
            headers={"X-Subscription-Token": BRAVE_API_KEY, "Accept": "application/json"},
            timeout=10,
        )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("web", {}).get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
            "source": item.get("meta_url", {}).get("hostname", ""),
        })

    return results


# ── LLM Analysis ────────────────────────────────────────────────────────────

def analyze_results(team_name: str, search_results: list[dict], year: int = 2025) -> dict:
    """Use OpenAI to extract play-caller info with citations and confidence."""
    if not OPENAI_API_KEY:
        print("⚠️  No OPENAI_API_KEY set")
        return {}

    search_context = "\n\n".join([
        f"Source: {r['source']} ({r['url']})\nTitle: {r['title']}\nSnippet: {r['snippet']}"
        for r in search_results
    ])

    prompt = f"""Analyze the following search results to determine who calls offensive plays for {team_name} in the {year} college football season.

IMPORTANT DISTINCTIONS:
- The Offensive Coordinator (OC) does NOT always call plays
- Some Head Coaches call their own plays (e.g., Lane Kiffin, Josh Heupel)
- Some teams split play-calling duties
- Co-OC situations exist where one OC calls plays and the other doesn't
- Mid-season changes happen (firings, promotions)

Search Results:
{search_context}

Respond in JSON format:
{{
    "team": "{team_name}",
    "primary_play_caller": {{
        "name": "Full Name of whoever was calling plays at the START of the {year} season",
        "title": "Official Title (HC/OC/Co-OC)",
        "is_head_coach": true/false,
        "notes": "Any relevant context"
    }},
    "mid_season_changes": [
        {{
            "new_caller": "Name",
            "new_title": "Title",
            "is_head_coach": true/false,
            "effective_date": "YYYY-MM-DD or approximate",
            "week_number": null,
            "reason": "Why the change happened"
        }}
    ],
    "citations": [
        {{
            "url": "source URL",
            "source_name": "publication name",
            "claim": "what this source says",
            "reliability": "high/medium/low"
        }}
    ],
    "confidence": {{
        "score": 0.0-1.0,
        "reasoning": "Why this confidence level",
        "conflicting_info": "Any contradictions found"
    }}
}}

RULES:
- "primary_play_caller" = who was calling plays at the START of the season
- If there were mid-season changes, list them in "mid_season_changes" 
- If no changes occurred, "mid_season_changes" should be an empty array
- If the HC calls plays, set is_head_coach=true and use the HC's name (not OC)
- If it's a committee/shared approach, name the primary voice and explain in notes"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a college football research assistant. Extract accurate play-caller information from search results. Be precise about the distinction between OC and play-caller."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        },
        timeout=30,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


# ── DB Operations ───────────────────────────────────────────────────────────

def get_school_id(conn: sqlite3.Connection, team_name: str) -> int | None:
    """Look up school ID by name."""
    cursor = conn.cursor()
    # Try exact match first
    cursor.execute("SELECT id FROM schools WHERE name = ?", (team_name,))
    row = cursor.fetchone()
    if row:
        return row[0]
    # Try LIKE match
    cursor.execute("SELECT id, name FROM schools WHERE name LIKE ?", (f"%{team_name}%",))
    rows = cursor.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    if len(rows) > 1:
        print(f"   ⚠️  Multiple matches for '{team_name}': {[r[1] for r in rows]}")
    return None


def get_existing_primary(conn: sqlite3.Connection, school_id: int, season: int) -> dict | None:
    """Get existing primary play caller for a team/season."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT primary_caller, primary_title, is_head_coach, confidence FROM play_callers WHERE school_id = ? AND season = ?",
        (school_id, season)
    )
    row = cursor.fetchone()
    if row:
        return {
            "name": row[0],
            "title": row[1],
            "is_head_coach": bool(row[2]),
            "confidence": row[3],
        }
    return None


def set_primary_caller(conn: sqlite3.Connection, school_id: int, season: int, analysis: dict) -> dict:
    """Set or update the primary play caller for a team/season."""
    caller = analysis.get("primary_play_caller", {})
    confidence = analysis.get("confidence", {}).get("score", 0)
    citations = [c["url"] for c in analysis.get("citations", [])]

    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO play_callers (school_id, season, primary_caller, primary_title, is_head_coach, notes, confidence, citations, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(school_id, season) DO UPDATE SET
            primary_caller = excluded.primary_caller,
            primary_title = excluded.primary_title,
            is_head_coach = excluded.is_head_coach,
            notes = excluded.notes,
            confidence = excluded.confidence,
            citations = excluded.citations,
            updated_at = datetime('now')
    """, (
        school_id, season,
        caller.get("name", "Unknown"),
        caller.get("title", ""),
        caller.get("is_head_coach", False),
        caller.get("notes", ""),
        confidence,
        json.dumps(citations),
    ))

    # Also insert any mid-season changes
    changes = analysis.get("mid_season_changes", [])
    for change in changes:
        if not change.get("new_caller"):
            continue
        cursor.execute("""
            INSERT INTO play_caller_changes (school_id, season, new_caller, new_title, is_head_coach, effective_date, week_number, reason, confidence, citations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            school_id, season,
            change["new_caller"],
            change.get("new_title", ""),
            change.get("is_head_coach", False),
            change.get("effective_date"),
            change.get("week_number"),
            change.get("reason", ""),
            confidence,
            json.dumps(citations),
        ))

    conn.commit()
    return {
        "status": "updated",
        "primary": caller.get("name"),
        "changes_added": len(changes),
    }


def detect_change(conn: sqlite3.Connection, school_id: int, season: int, analysis: dict) -> dict:
    """Compare current analysis against existing primary — detect mid-season changes."""
    existing = get_existing_primary(conn, school_id, season)
    if not existing:
        return {"status": "no_primary", "action": "run sweep first"}

    caller = analysis.get("primary_play_caller", {})
    new_name = caller.get("name", "").strip().lower()
    existing_name = existing["name"].strip().lower()

    # Check if the latest caller differs from existing primary
    # Also check mid_season_changes from analysis
    changes = analysis.get("mid_season_changes", [])

    if new_name == existing_name and not changes:
        return {"status": "no_change", "primary": existing["name"]}

    # There's a difference — log changes
    cursor = conn.cursor()
    added = 0
    for change in changes:
        if not change.get("new_caller"):
            continue
        # Check if this change is already recorded
        cursor.execute("""
            SELECT id FROM play_caller_changes
            WHERE school_id = ? AND season = ? AND new_caller = ?
        """, (school_id, season, change["new_caller"]))
        if cursor.fetchone():
            continue  # Already recorded

        confidence = analysis.get("confidence", {}).get("score", 0)
        citations = [c["url"] for c in analysis.get("citations", [])]
        cursor.execute("""
            INSERT INTO play_caller_changes (school_id, season, new_caller, new_title, is_head_coach, effective_date, week_number, reason, confidence, citations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            school_id, season,
            change["new_caller"],
            change.get("new_title", ""),
            change.get("is_head_coach", False),
            change.get("effective_date"),
            change.get("week_number"),
            change.get("reason", ""),
            confidence,
            json.dumps(citations),
        ))
        added += 1

    conn.commit()
    return {
        "status": "changes_detected",
        "primary": existing["name"],
        "new_changes_added": added,
        "total_changes_in_analysis": len(changes),
    }


def show_team(conn: sqlite3.Connection, team_name: str):
    """Display play-caller data for a team."""
    school_id = get_school_id(conn, team_name)
    if not school_id:
        print(f"❌ Team '{team_name}' not found in database")
        return

    cursor = conn.cursor()

    # Get school name
    cursor.execute("SELECT name FROM schools WHERE id = ?", (school_id,))
    school_name = cursor.fetchone()[0]

    # Get all seasons
    cursor.execute("""
        SELECT season, primary_caller, primary_title, is_head_coach, confidence, notes, citations
        FROM play_callers WHERE school_id = ? ORDER BY season DESC
    """, (school_id,))
    seasons = cursor.fetchall()

    if not seasons:
        print(f"📭 No play-caller data for {school_name}")
        return

    print(f"\n🏈 {school_name} — Play Callers")
    print("=" * 50)

    for season in seasons:
        yr, caller, title, is_hc, conf, notes, citations = season
        hc_flag = " 👑 (HC)" if is_hc else ""
        print(f"\n  {yr} Season:")
        print(f"    Primary: {caller} ({title}){hc_flag}")
        print(f"    Confidence: {conf:.0%}" if conf else "    Confidence: N/A")
        if notes:
            print(f"    Notes: {notes}")

        # Get changes
        cursor.execute("""
            SELECT new_caller, new_title, effective_date, week_number, reason
            FROM play_caller_changes WHERE school_id = ? AND season = ? ORDER BY id
        """, (school_id, yr))
        changes = cursor.fetchall()
        if changes:
            print(f"    Changes:")
            for ch in changes:
                new_c, new_t, eff_date, week, reason = ch
                when = f"Week {week}" if week else (eff_date or "Unknown date")
                print(f"      → {when}: {new_c} ({new_t}) — {reason}")

    print()


def show_all(conn: sqlite3.Connection, season: int = 2025):
    """Show all teams with play-caller data for a season."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.name, pc.primary_caller, pc.primary_title, pc.is_head_coach, pc.confidence
        FROM play_callers pc
        JOIN schools s ON s.id = pc.school_id
        WHERE pc.season = ?
        ORDER BY s.name
    """, (season,))
    rows = cursor.fetchall()

    if not rows:
        print(f"📭 No play-caller data for {season}")
        return

    print(f"\n🏈 Play Callers — {season} Season ({len(rows)} teams)")
    print("=" * 70)
    print(f"  {'Team':<25} {'Play Caller':<25} {'Title':<15} {'Conf':>5}")
    print("-" * 70)
    for school, caller, title, is_hc, conf in rows:
        hc = "👑" if is_hc else "  "
        conf_str = f"{conf:.0%}" if conf else "N/A"
        print(f"  {hc} {school:<23} {caller:<25} {title:<15} {conf_str:>5}")

    # Count changes
    cursor.execute("""
        SELECT COUNT(*) FROM play_caller_changes WHERE season = ?
    """, (season,))
    change_count = cursor.fetchone()[0]
    if change_count:
        print(f"\n  ⚡ {change_count} mid-season change(s) recorded")
    print()


# ── Pipeline Orchestrator ───────────────────────────────────────────────────

def run_pipeline(team_name: str, year: int = 2025, dry_run: bool = True,
                 incremental: bool = False, verbose: bool = False) -> dict:
    """Run the full play-caller identification pipeline for a team."""
    result = {
        "team": team_name,
        "year": year,
        "timestamp": datetime.now().isoformat(),
        "stages": {},
    }

    # Stage 1: Web Search
    if verbose:
        print(f"\n🔍 Stage 1: Searching for {team_name} play caller...")
    search_results = search_play_caller(team_name, year)
    result["stages"]["search"] = {
        "results_count": len(search_results),
        "sources": list(set(r["source"] for r in search_results)),
    }
    if verbose:
        print(f"   Found {len(search_results)} results from {len(result['stages']['search']['sources'])} sources")

    if not search_results:
        result["status"] = "no_results"
        return result

    # Stage 2 & 3: LLM Analysis
    if verbose:
        print(f"🧠 Stage 2-3: Analyzing results with GPT-4o...")
    analysis = analyze_results(team_name, search_results, year)
    result["stages"]["analysis"] = analysis
    if verbose and analysis:
        caller = analysis.get("primary_play_caller", {})
        conf = analysis.get("confidence", {})
        changes = analysis.get("mid_season_changes", [])
        print(f"   Primary Play Caller: {caller.get('name', 'Unknown')} ({caller.get('title', '?')})")
        if caller.get("is_head_coach"):
            print(f"   👑 Head Coach calls plays")
        print(f"   Confidence: {conf.get('score', 0):.0%} — {conf.get('reasoning', '')[:80]}")
        if changes:
            print(f"   ⚡ {len(changes)} mid-season change(s):")
            for ch in changes:
                print(f"      → {ch.get('new_caller')} ({ch.get('reason', 'unknown reason')})")
        citations = analysis.get("citations", [])
        print(f"   Citations: {len(citations)} sources")
        for c in citations:
            print(f"     • [{c.get('reliability', '?')}] {c.get('source_name', '?')}: {c.get('claim', '')[:60]}")

    # Stage 4: DB Update
    if verbose:
        mode = "DRY RUN" if dry_run else ("INCREMENTAL" if incremental else "SWEEP")
        print(f"💾 Stage 4: [{mode}] Updating database...")

    confidence = analysis.get("confidence", {}).get("score", 0)
    if confidence < 0.5:
        result["stages"]["db_update"] = {
            "status": "skipped",
            "reason": f"confidence too low ({confidence:.0%})",
            "needs_manual_review": True,
        }
        if verbose:
            print(f"   ⚠️  Skipped — confidence {confidence:.0%} < 50%")
        result["status"] = "low_confidence"
        return result

    if dry_run:
        result["stages"]["db_update"] = {"status": "dry_run", "would_update": analysis}
        result["status"] = "complete_dry_run"
    else:
        conn = sqlite3.connect(str(LOCAL_DB))
        school_id = get_school_id(conn, team_name)
        if not school_id:
            result["stages"]["db_update"] = {"status": "team_not_found"}
            if verbose:
                print(f"   ❌ Team '{team_name}' not found in DB")
            conn.close()
            result["status"] = "team_not_found"
            return result

        if incremental:
            db_result = detect_change(conn, school_id, year, analysis)
        else:
            db_result = set_primary_caller(conn, school_id, year, analysis)

        result["stages"]["db_update"] = db_result
        conn.close()
        if verbose:
            print(f"   Status: {db_result.get('status')}")

    result["status"] = "complete"
    return result


def get_all_teams() -> list[str]:
    """Get all team names from local DB."""
    if not LOCAL_DB.exists():
        print(f"⚠️  Local DB not found at {LOCAL_DB}")
        return []

    conn = sqlite3.connect(str(LOCAL_DB))
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT name FROM schools WHERE name IS NOT NULL ORDER BY name")
    teams = [row[0] for row in cursor.fetchall()]
    conn.close()
    return teams


def get_conference_teams(conference: str) -> list[str]:
    """Get teams by conference abbreviation."""
    if not LOCAL_DB.exists():
        return []

    conn = sqlite3.connect(str(LOCAL_DB))
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.name FROM schools s
        JOIN conferences c ON s.conference_id = c.id
        WHERE c.abbrev LIKE ? OR c.name LIKE ?
        ORDER BY s.name
    """, (f"%{conference}%", f"%{conference}%"))
    teams = [row[0] for row in cursor.fetchall()]
    conn.close()
    return teams


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Play Caller Identification Pipeline")
    parser.add_argument("team", nargs="?", help="Team name to research")
    parser.add_argument("--all-teams", action="store_true", help="Run for all teams in DB")
    parser.add_argument("--conference", help="Run for teams in a conference (e.g., SEC)")
    parser.add_argument("--year", type=int, default=2025, help="Season year (default: 2025)")
    parser.add_argument("--apply", action="store_true", help="Actually update DB (default is dry run)")
    parser.add_argument("--incremental", action="store_true", help="Incremental mode: detect changes vs existing primary")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--output", "-o", help="Save results to JSON file")
    parser.add_argument("--show", metavar="TEAM", help="Show existing play-caller data for a team")
    parser.add_argument("--show-all", action="store_true", help="Show all play-caller data")
    args = parser.parse_args()

    # Show modes
    if args.show or args.show_all:
        conn = sqlite3.connect(str(LOCAL_DB))
        if args.show:
            show_team(conn, args.show)
        else:
            show_all(conn, args.year)
        conn.close()
        return

    if not args.team and not args.all_teams and not args.conference:
        parser.print_help()
        sys.exit(1)

    dry_run = not args.apply
    if dry_run and args.verbose:
        print("ℹ️  DRY RUN mode (use --apply to update DB)\n")
    if args.incremental and args.verbose:
        print("🔄 INCREMENTAL mode — detecting changes vs existing primaries\n")

    teams = []
    if args.team:
        teams = [args.team]
    elif args.conference:
        teams = get_conference_teams(args.conference)
        if not teams:
            print(f"❌ No teams found for conference '{args.conference}'")
            sys.exit(1)
        if args.verbose:
            print(f"📋 Found {len(teams)} teams in {args.conference}\n")
    elif args.all_teams:
        teams = get_all_teams()
        if args.verbose:
            print(f"📋 Running for all {len(teams)} teams\n")

    all_results = []
    for i, team in enumerate(teams, 1):
        if len(teams) > 1:
            print(f"\n{'='*60}")
            print(f"[{i}/{len(teams)}] {team}")
            print(f"{'='*60}")

        try:
            result = run_pipeline(
                team, year=args.year, dry_run=dry_run,
                incremental=args.incremental, verbose=args.verbose
            )
            all_results.append(result)
        except Exception as e:
            print(f"   ❌ Error: {e}")
            all_results.append({"team": team, "status": "error", "error": str(e)})

        # Rate limit between teams
        if i < len(teams):
            time.sleep(2)

    # Summary
    if len(teams) > 1:
        print(f"\n{'='*60}")
        print("📊 SUMMARY")
        print(f"{'='*60}")
        complete = sum(1 for r in all_results if r.get("status", "").startswith("complete"))
        errors = sum(1 for r in all_results if r.get("status") == "error")
        low_conf = sum(1 for r in all_results if r.get("status") == "low_confidence")
        no_results = sum(1 for r in all_results if r.get("status") == "no_results")
        print(f"  Total: {len(all_results)} | Complete: {complete} | Low Confidence: {low_conf} | Errors: {errors} | No Results: {no_results}")

        # Show low confidence teams
        lc_teams = []
        for r in all_results:
            analysis = r.get("stages", {}).get("analysis", {})
            conf = analysis.get("confidence", {}).get("score", 0)
            if conf < 0.7 and r.get("status", "").startswith("complete"):
                lc_teams.append((r["team"], conf))
        if lc_teams:
            print(f"\n  ⚠️  Low confidence ({len(lc_teams)}):")
            for team, conf in lc_teams:
                print(f"    • {team}: {conf:.0%}")

    # Save results
    if args.output:
        with open(args.output, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\n💾 Results saved to {args.output}")

    return all_results


if __name__ == "__main__":
    main()
