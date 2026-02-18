#!/usr/bin/env python3
"""
YR Game Prep Auto-Brief Generator
==================================
Generates a broadcast-ready one-pager game prep brief for a given football matchup.

Usage:
    python3 game_prep_brief.py "Oregon" "USC" --week 10 --season 2025
    python3 game_prep_brief.py "Georgia" "Alabama" --format markdown
    python3 game_prep_brief.py "Ohio State" "Michigan" --week 8 --print

Outputs markdown (Telegram-ready) and/or HTML (web/print) files.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import urllib.request
import urllib.error

# ── Paths ──────────────────────────────────────────────────────────────────────
CLAWD_DIR = Path.home() / "clawd"
COACH_DB   = CLAWD_DIR / "coach-database" / "db" / "coaches.db"
PBP_JSON   = CLAWD_DIR / "pbp-analysis" / "data.json"
OUTPUT_DIR = CLAWD_DIR / "scripts" / "output"

NCAA_SCOREBOARD = (
    "https://data.ncaa.com/casablanca/scoreboard/football/fbs/{year}/{week:02d}/scoreboard.json"
)


# ── Slug helpers ───────────────────────────────────────────────────────────────

SLUG_ALIASES: dict[str, str] = {
    "ole miss": "mississippi",
    "miami fl": "miami",
    "miami (fl)": "miami",
    "miami florida": "miami",
    "lsu": "lsu",
    "usc": "usc",
    "tcu": "tcu",
    "smu": "smu",
    "ucf": "ucf",
    "uab": "uab",
    "utsa": "utsa",
    "byu": "byu",
}


def slugify(name: str) -> str:
    """Convert a team display name to a URL-style slug."""
    lower = name.strip().lower()
    if lower in SLUG_ALIASES:
        return SLUG_ALIASES[lower]
    slug = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
    return slug


def fuzzy_find_school(db: sqlite3.Connection, team_name: str) -> dict | None:
    """Try to find a school by exact slug, then partial name match."""
    slug = slugify(team_name)
    base_q = """
        SELECT s.id, s.name, s.slug, c.name as conference
        FROM schools s
        LEFT JOIN conferences c ON s.conference_id = c.id
    """
    row = db.execute(base_q + " WHERE s.slug = ?", (slug,)).fetchone()
    if row:
        return dict(row)

    # Partial name match
    pattern = f"%{team_name.lower()}%"
    row = db.execute(base_q + " WHERE LOWER(s.name) LIKE ?", (pattern,)).fetchone()
    if row:
        return dict(row)

    # Try each word
    for word in team_name.split():
        if len(word) < 4:
            continue
        pattern = f"%{word.lower()}%"
        row = db.execute(
            base_q + " WHERE LOWER(s.name) LIKE ? OR s.slug LIKE ?",
            (pattern, f"%{word.lower()}%"),
        ).fetchone()
        if row:
            return dict(row)

    return None


# ── Coach DB queries ───────────────────────────────────────────────────────────

def get_coaching_staff(db: sqlite3.Connection, school_id: int) -> list[dict]:
    rows = db.execute(
        """
        SELECT name, position, is_head_coach
        FROM coaches
        WHERE school_id = ?
        ORDER BY is_head_coach DESC, name
        """,
        (school_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_play_caller(db: sqlite3.Connection, school_id: int, season: int) -> dict | None:
    row = db.execute(
        """
        SELECT primary_caller, primary_title, is_head_coach, notes, confidence
        FROM play_callers
        WHERE school_id = ? AND season = ?
        """,
        (school_id, season),
    ).fetchone()
    return dict(row) if row else None


def extract_key_coaches(staff: list[dict], play_caller: dict | None) -> dict:
    """Return head coach, OC, DC, and play caller from staff list."""
    head_coach = next((c for c in staff if c["is_head_coach"]), None)

    # Prefer primary OC over "co-" variants; also match pass game coord
    OC_KEYWORDS = ["offensive coordinator", "offensive coord", "play caller", "pass game coord"]
    oc_candidates = [
        c for c in staff
        if not c["is_head_coach"]
        and c["position"]
        and any(kw in c["position"].lower() for kw in OC_KEYWORDS)
    ]
    # Prefer non-"co-" coordinators
    oc = next(
        (c for c in oc_candidates if "co-offensive" not in c["position"].lower()),
        oc_candidates[0] if oc_candidates else None,
    )

    DC_KEYWORDS = ["defensive coordinator", "defensive coord"]
    dc_candidates = [
        c for c in staff
        if not c["is_head_coach"]
        and c["position"]
        and any(kw in c["position"].lower() for kw in DC_KEYWORDS)
    ]
    # Prefer non-"co-" coordinators
    dc = next(
        (c for c in dc_candidates if "co-defensive" not in c["position"].lower()),
        dc_candidates[0] if dc_candidates else None,
    )

    result = {
        "head_coach": head_coach["name"] if head_coach else "N/A",
        "oc": oc["name"] if oc else "N/A",
        "oc_title": oc["position"] if oc else "",
        "dc": dc["name"] if dc else "N/A",
        "dc_title": dc["position"] if dc else "",
        "play_caller": None,
        "play_caller_title": None,
    }

    if play_caller:
        result["play_caller"] = play_caller["primary_caller"]
        result["play_caller_title"] = play_caller["primary_title"]
        result["play_caller_is_hc"] = play_caller["is_head_coach"]

    return result


# ── PBP Analysis data ──────────────────────────────────────────────────────────

def load_pbp_data() -> dict:
    if not PBP_JSON.exists():
        return {}
    with open(PBP_JSON) as f:
        raw = json.load(f)
    return raw.get("teams", {})


def get_team_pbp(pbp_teams: dict, team_name: str, school_slug: str) -> dict | None:
    """Find team entry by slug or fuzzy name."""
    if school_slug in pbp_teams:
        return pbp_teams[school_slug]

    # Try slugified name
    slug = slugify(team_name)
    if slug in pbp_teams:
        return pbp_teams[slug]

    # Try partial match on stored team names
    name_lower = team_name.lower()
    for key, val in pbp_teams.items():
        stored = (val.get("name") or "").lower()
        if name_lower in stored or stored in name_lower:
            return val

    return None


def extract_pbp_stats(team_data: dict) -> dict:
    """Extract key stats from pbp-analysis team entry."""
    agg = team_data.get("aggregates", {})
    rankings = team_data.get("cfbstats", {}).get("rankings", {}).get("all", {})
    games = team_data.get("games", [])

    def rank(key: str) -> str:
        r = rankings.get(key, {})
        val = r.get("value", "")
        rnk = r.get("rank", "")
        return f"{val} (#{rnk})" if val and rnk else (val or "N/A")

    last_games = sorted(games, key=lambda g: g.get("game_number", 0))[-5:]
    recent = []
    for g in last_games:
        pf = g.get("points_for")
        pa = g.get("points_against")
        opp = g.get("opponent", "?")
        date = g.get("date", "")
        if pf is not None and pa is not None:
            result = "W" if pf > pa else ("L" if pf < pa else "T")
            recent.append(f"{result} {pf}-{pa} {'vs' if g.get('is_home', True) else '@'} {opp} ({date})")

    return {
        "record": agg.get("record", "N/A"),
        "conf_record": agg.get("conf_record", "N/A"),
        "ppg": agg.get("ppg", "N/A"),
        "opp_ppg": agg.get("opp_ppg", "N/A"),
        "explosives_per_game": agg.get("explosives_per_game", "N/A"),
        "turnover_margin": agg.get("turnover_margin", "N/A"),
        "red_zone_td_pct": agg.get("red_zone_td_pct", "N/A"),
        "penalties_per_game": agg.get("penalties_per_game", "N/A"),
        "scoring_offense": rank("scoring_offense"),
        "scoring_defense": rank("scoring_defense"),
        "total_offense": rank("total_offense"),
        "total_defense": rank("total_defense"),
        "rushing_offense": rank("rushing_offense"),
        "rushing_defense": rank("rushing_defense"),
        "passing_offense": rank("passing_offense"),
        "passing_defense": rank("passing_defense"),
        "explosives_rank": rank("explosives"),
        "third_down": rank("third_down"),
        "red_zone_rank": rank("red_zone"),
        "turnover_rank": rank("turnover_margin"),
        "recent_results": recent,
        "color": team_data.get("color", "#888888"),
        "conference": team_data.get("conference", ""),
        "abbr": team_data.get("abbr", ""),
    }


# ── NCAA API ───────────────────────────────────────────────────────────────────

def fetch_ncaa_scoreboard(year: int, week: int) -> list[dict]:
    url = NCAA_SCOREBOARD.format(year=year, week=week)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return [g["game"] for g in data.get("games", []) if "game" in g]
    except Exception as e:
        print(f"[warn] NCAA scoreboard unavailable: {e}", file=sys.stderr)
        return []


def find_ncaa_game(games: list[dict], slug1: str, slug2: str) -> dict | None:
    """Find a specific matchup in NCAA scoreboard data."""
    s1, s2 = slug1.lower(), slug2.lower()
    for g in games:
        away_seo = (g.get("away") or {}).get("names", {}).get("seo", "")
        home_seo = (g.get("home") or {}).get("names", {}).get("seo", "")
        if {away_seo, home_seo} & {s1, s2}:
            return g
    return None


# ── Team data assembly ─────────────────────────────────────────────────────────

def gather_team_data(
    db: sqlite3.Connection,
    pbp_teams: dict,
    team_name: str,
    season: int,
) -> dict:
    """Collect all data for one team."""
    school = fuzzy_find_school(db, team_name)
    coaches_data: dict = {}
    staff: list[dict] = []
    play_caller: dict | None = None

    if school:
        staff = get_coaching_staff(db, school["id"])
        play_caller = get_play_caller(db, school["id"], season)
        coaches_data = extract_key_coaches(staff, play_caller)
        school_slug = school["slug"]
        school_conf = school.get("conference") or ""
        school_name = school["name"]
    else:
        print(f"[warn] '{team_name}' not found in coach DB", file=sys.stderr)
        coaches_data = {
            "head_coach": "N/A",
            "oc": "N/A", "oc_title": "",
            "dc": "N/A", "dc_title": "",
            "play_caller": None, "play_caller_title": None,
        }
        school_slug = slugify(team_name)
        school_conf = ""
        school_name = team_name

    pbp_entry = get_team_pbp(pbp_teams, team_name, school_slug)
    pbp_stats = extract_pbp_stats(pbp_entry) if pbp_entry else {}

    # Use conference from pbp if not in DB
    if not school_conf and pbp_stats.get("conference"):
        school_conf = pbp_stats["conference"]

    return {
        "display_name": team_name,
        "school_name": school_name,
        "slug": school_slug,
        "conference": school_conf,
        "coaches": coaches_data,
        "full_staff": staff,
        "stats": pbp_stats,
        "has_pbp": pbp_entry is not None,
        "has_coaches": school is not None,
    }


# ── Markdown renderer ──────────────────────────────────────────────────────────

TEAM_EMOJIS = ["🟢", "🔴", "🔵", "🟡"]


def md_team_block(team: dict, emoji: str) -> str:
    d = team["display_name"].upper()
    conf = team["conference"]
    stats = team["stats"]
    coaches = team["coaches"]

    record = stats.get("record", "N/A")
    conf_rec = stats.get("conf_record", "")
    header_record = f"({record}"
    if conf_rec and conf_rec != "0-0":
        header_record += f", {conf_rec} {conf}"
    header_record += ")"

    lines = [
        f"━━━━━━━━━━━━━━━━━━",
        f"{emoji} *{d}* {header_record}",
        f"━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # Coaches
    lines.append("👤 *Coaching Staff*")
    lines.append(f"• Head Coach: {coaches['head_coach']}")

    pc = coaches.get("play_caller")
    pc_title = coaches.get("play_caller_title") or "Play Caller"
    if pc:
        lines.append(f"• Play Caller: {pc} ({pc_title})")
    elif coaches.get("oc") != "N/A":
        oc_title = coaches.get("oc_title") or "OC"
        lines.append(f"• Off. Coord: {coaches['oc']} ({oc_title})")

    if coaches.get("dc") != "N/A":
        dc_title = coaches.get("dc_title") or "DC"
        lines.append(f"• Def. Coord: {coaches['dc']} ({dc_title})")

    lines.append("")

    if team["has_pbp"]:
        lines.append("📊 *Season Stats (FBS Rankings)*")
        def s(key: str, label: str):
            val = stats.get(key, "N/A")
            if val and val != "N/A":
                lines.append(f"• {label}: {val}")

        s("scoring_offense", "Scoring Off")
        s("scoring_defense", "Scoring Def")
        s("total_offense", "Total Off")
        s("total_defense", "Total Def")
        s("explosives_rank", "Explosive Plays (20+)")
        s("third_down", "3rd Down %")
        s("red_zone_rank", "Red Zone TD%")
        s("turnover_rank", "Turnover Margin")

        ppg = stats.get("ppg", "N/A")
        opp_ppg = stats.get("opp_ppg", "N/A")
        if ppg != "N/A":
            lines.append(f"• Avg Score: {ppg} pts for / {opp_ppg} pts against")

        lines.append("")

        recent = stats.get("recent_results", [])
        if recent:
            lines.append("🔥 *Recent Results (last 5)*")
            for r in recent:
                lines.append(f"• {r}")
    else:
        lines.append("_Stats not available in PBP Analysis data_")

    lines.append("")
    return "\n".join(lines)


def render_markdown(team1: dict, team2: dict, week: int | None, season: int) -> str:
    now = datetime.now().strftime("%b %d, %Y %H:%M")
    week_str = f"Week {week} | " if week else ""

    header = [
        "🏈 *GAME PREP BRIEF*",
        f"📅 {week_str}{season} Season",
        f"*{team1['display_name']} vs {team2['display_name']}*",
        "",
    ]

    body = (
        md_team_block(team1, TEAM_EMOJIS[0])
        + "\n"
        + md_team_block(team2, TEAM_EMOJIS[1])
    )

    footer = [
        "━━━━━━━━━━━━━━━━━━",
        "📡 *Data Sources*",
        "• Coach DB (coaching staff + play callers)",
        "• PBP Analysis (cfbstats rankings)",
        f"• Generated: {now}",
        "",
    ]

    return "\n".join(header) + body + "\n".join(footer)


# ── HTML renderer ──────────────────────────────────────────────────────────────

def html_stat_row(label: str, value: str) -> str:
    if not value or value == "N/A":
        return ""
    return f"<tr><td>{label}</td><td><strong>{value}</strong></td></tr>"


def html_team_block(team: dict, color: str) -> str:
    d = team["display_name"]
    conf = team["conference"]
    stats = team["stats"]
    coaches = team["coaches"]
    record = stats.get("record", "N/A")
    conf_rec = stats.get("conf_record", "")

    record_str = record
    if conf_rec and conf_rec != "0-0":
        record_str += f" | {conf_rec} {conf}"

    pc = coaches.get("play_caller")
    pc_title = coaches.get("play_caller_title") or "Play Caller"
    oc = coaches.get("oc", "N/A")
    oc_title = coaches.get("oc_title") or "OC"
    dc = coaches.get("dc", "N/A")
    dc_title = coaches.get("dc_title") or "DC"

    play_caller_html = (
        f"<tr><td>Play Caller</td><td><strong>{pc}</strong> <em>({pc_title})</em></td></tr>"
        if pc
        else (
            f"<tr><td>Off. Coord</td><td><strong>{oc}</strong> <em>({oc_title})</em></td></tr>"
            if oc != "N/A" else ""
        )
    )
    dc_html = (
        f"<tr><td>Def. Coord</td><td><strong>{dc}</strong> <em>({dc_title})</em></td></tr>"
        if dc != "N/A" else ""
    )

    stats_rows = ""
    if team["has_pbp"]:
        def sr(key, label):
            return html_stat_row(label, stats.get(key, ""))

        stats_rows = f"""
        <h3>📊 Season Stats</h3>
        <table class="stats-table">
          <tr><th>Stat</th><th>Value (FBS Rank)</th></tr>
          {sr('scoring_offense', 'Scoring Offense')}
          {sr('scoring_defense', 'Scoring Defense')}
          {sr('total_offense', 'Total Offense')}
          {sr('total_defense', 'Total Defense')}
          {sr('explosives_rank', 'Explosive Plays (20+)')}
          {sr('third_down', '3rd Down %')}
          {sr('red_zone_rank', 'Red Zone TD%')}
          {sr('turnover_rank', 'Turnover Margin')}
        </table>
        """
        recent = stats.get("recent_results", [])
        if recent:
            items = "".join(f"<li>{r}</li>" for r in recent)
            stats_rows += f"""
            <h3>🔥 Recent Results</h3>
            <ul class="recent-list">{items}</ul>
            """
    else:
        stats_rows = "<p><em>Stats not available in PBP Analysis data.</em></p>"

    return f"""
    <div class="team-block" style="border-top: 5px solid {color};">
      <div class="team-header" style="background: {color}22; border-left: 6px solid {color};">
        <h2>{d}</h2>
        <div class="record">{record_str}</div>
        <div class="conference">{conf}</div>
      </div>

      <h3>👤 Coaching Staff</h3>
      <table class="coaches-table">
        <tr><td>Head Coach</td><td><strong>{coaches['head_coach']}</strong></td></tr>
        {play_caller_html}
        {dc_html}
      </table>

      {stats_rows}
    </div>
    """


def render_html(team1: dict, team2: dict, week: int | None, season: int) -> str:
    now = datetime.now().strftime("%B %d, %Y %H:%M")
    week_str = f"Week {week} · " if week else ""
    t1_color = team1["stats"].get("color", "#2563eb")
    t2_color = team2["stats"].get("color", "#dc2626")

    t1_block = html_team_block(team1, t1_color)
    t2_block = html_team_block(team2, t2_color)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Game Prep: {team1['display_name']} vs {team2['display_name']}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Helvetica Neue', Arial, sans-serif;
      font-size: 13px;
      color: #1a1a2e;
      background: #f8fafc;
      padding: 24px;
    }}
    .brief-header {{
      text-align: center;
      padding: 20px 0 16px;
      border-bottom: 3px solid #1a1a2e;
      margin-bottom: 24px;
    }}
    .brief-header h1 {{
      font-size: 22px;
      font-weight: 800;
      letter-spacing: 2px;
      text-transform: uppercase;
    }}
    .brief-header .subtitle {{
      color: #555;
      margin-top: 4px;
      font-size: 13px;
    }}
    .teams-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }}
    .team-block {{
      background: #fff;
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    .team-header {{
      padding: 14px 16px;
      border-radius: 6px;
      margin-bottom: 16px;
    }}
    .team-header h2 {{
      font-size: 18px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 1px;
    }}
    .team-header .record {{
      font-weight: 600;
      margin-top: 4px;
      font-size: 13px;
    }}
    .team-header .conference {{
      color: #555;
      font-size: 11px;
      margin-top: 2px;
    }}
    h3 {{
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: #444;
      margin: 14px 0 8px;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 4px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    table td, table th {{
      padding: 5px 8px;
      text-align: left;
      font-size: 12px;
      border-bottom: 1px solid #f0f4f8;
    }}
    table th {{
      font-weight: 700;
      font-size: 11px;
      text-transform: uppercase;
      color: #888;
      background: #f8fafc;
    }}
    table td:first-child {{
      color: #555;
      width: 45%;
    }}
    .recent-list {{
      list-style: none;
      padding: 0;
    }}
    .recent-list li {{
      padding: 4px 0;
      font-size: 12px;
      border-bottom: 1px solid #f0f4f8;
    }}
    .recent-list li::before {{
      content: "› ";
      color: #888;
    }}
    .brief-footer {{
      margin-top: 20px;
      padding-top: 12px;
      border-top: 1px solid #e2e8f0;
      text-align: center;
      font-size: 10px;
      color: #aaa;
    }}
    @media print {{
      body {{ background: white; padding: 10px; }}
      .team-block {{ box-shadow: none; border: 1px solid #ddd; }}
      @page {{ margin: 1cm; }}
    }}
  </style>
</head>
<body>
  <div class="brief-header">
    <h1>🏈 Game Prep Brief</h1>
    <div class="subtitle">{week_str}{season} Season &nbsp;|&nbsp; {team1['display_name']} vs {team2['display_name']}</div>
  </div>

  <div class="teams-grid">
    {t1_block}
    {t2_block}
  </div>

  <div class="brief-footer">
    Data: Coach DB · PBP Analysis · NCAA API &nbsp;|&nbsp; Generated {now}
  </div>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a broadcast-ready game prep brief for a football matchup."
    )
    p.add_argument("team1", help="First team name (e.g. 'Oregon')")
    p.add_argument("team2", help="Second team name (e.g. 'USC')")
    p.add_argument("--week", type=int, default=None, help="Week number")
    p.add_argument("--season", type=int, default=2025, help="Season year (default: 2025)")
    p.add_argument(
        "--format",
        choices=["markdown", "html", "both"],
        default="both",
        help="Output format (default: both)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory for output files",
    )
    p.add_argument(
        "--print",
        action="store_true",
        help="Print markdown to stdout",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not COACH_DB.exists():
        print(f"[error] Coach DB not found at {COACH_DB}", file=sys.stderr)
        sys.exit(1)

    db = sqlite3.connect(str(COACH_DB))
    db.row_factory = sqlite3.Row

    pbp_teams = load_pbp_data()
    if not pbp_teams:
        print("[warn] PBP analysis data not found — stats will be unavailable", file=sys.stderr)

    print(f"[info] Gathering data for: {args.team1} vs {args.team2} ({args.season})", file=sys.stderr)

    team1 = gather_team_data(db, pbp_teams, args.team1, args.season)
    team2 = gather_team_data(db, pbp_teams, args.team2, args.season)

    db.close()

    # Optional NCAA scoreboard lookup
    if args.week:
        games = fetch_ncaa_scoreboard(args.season, args.week)
        matchup = find_ncaa_game(games, team1["slug"], team2["slug"])
        if matchup:
            print(f"[info] Found this matchup in NCAA Week {args.week} scoreboard", file=sys.stderr)

    slug1 = team1["slug"]
    slug2 = team2["slug"]
    week_tag = f"_week{args.week}" if args.week else ""
    base_name = f"{slug1}_vs_{slug2}{week_tag}_{args.season}"

    if args.format in ("markdown", "both"):
        md_text = render_markdown(team1, team2, args.week, args.season)
        md_path = args.output_dir / f"{base_name}.md"
        md_path.write_text(md_text)
        print(f"[ok] Markdown saved → {md_path}", file=sys.stderr)
        if args.print:
            print(md_text)

    if args.format in ("html", "both"):
        html_text = render_html(team1, team2, args.week, args.season)
        html_path = args.output_dir / f"{base_name}.html"
        html_path.write_text(html_text)
        print(f"[ok] HTML saved → {html_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
