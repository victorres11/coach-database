import json
import re
import sqlite3
import sys
from pathlib import Path
import urllib.request
import urllib.error

# Constants
CLAWD_DIR = Path.home() / "clawd"
COACH_DB = CLAWD_DIR / "coach-database" / "db" / "coaches.db"
PBP_JSON = CLAWD_DIR / "pbp-analysis" / "data.json"
OUTPUT_DIR = CLAWD_DIR / "coach-database" / "output"

NCAA_SCOREBOARD = (
    "https://data.ncaa.com/casablanca/scoreboard/football/fbs/{year}/{week:02d}/scoreboard.json"
)

SLUG_ALIASES = {
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
    "arizona state": "asu",
}


def slugify(name: str) -> str:
    lower = name.strip().lower()
    if lower in SLUG_ALIASES:
        return SLUG_ALIASES[lower]
    return re.sub(r"[^a-z0-9]+", "-", lower).strip("-")


def _deep_merge(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for key, val in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def load_pbp_data(matchup_slug: str | None = None) -> dict:
    base = {}
    if PBP_JSON.exists():
        with open(PBP_JSON) as f:
            raw = json.load(f)
        base = raw.get("teams", {})

    if matchup_slug:
        matchup_path = COACH_DB.parent.parent / "matchups" / matchup_slug / "data.json"
        if matchup_path.exists():
            with open(matchup_path) as f:
                overlay_raw = json.load(f)
            overlay = overlay_raw.get("teams", {})
            if overlay:
                merged = dict(base)
                for slug, data in overlay.items():
                    if slug in merged and isinstance(merged[slug], dict):
                        merged[slug] = _deep_merge(merged[slug], data)
                    else:
                        merged[slug] = data
                base = merged
        else:
            print(f"[warn] Matchup data not found at {matchup_path}", file=sys.stderr)

    return base


def fuzzy_find_school(db: sqlite3.Connection, team_name: str) -> dict | None:
    slug = slugify(team_name)
    base_q = (
        "SELECT s.id, s.name, s.slug, c.name as conference "
        "FROM schools s "
        "LEFT JOIN conferences c ON s.conference_id = c.id"
    )
    row = db.execute(base_q + " WHERE s.slug = ?", (slug,)).fetchone()
    if row:
        return dict(row)

    pattern = f"%{team_name.lower()}%"
    row = db.execute(base_q + " WHERE LOWER(s.name) LIKE ?", (pattern,)).fetchone()
    if row:
        return dict(row)

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
    head_coach = next((c for c in staff if c.get("is_head_coach")), None)

    oc_keywords = [
        "offensive coordinator",
        "offensive coord",
        "play caller",
        "pass game coord",
    ]
    oc_candidates = [
        c
        for c in staff
        if not c.get("is_head_coach")
        and c.get("position")
        and any(kw in c["position"].lower() for kw in oc_keywords)
    ]
    oc = next(
        (c for c in oc_candidates if "co-offensive" not in c["position"].lower()),
        oc_candidates[0] if oc_candidates else None,
    )

    dc_keywords = ["defensive coordinator", "defensive coord"]
    dc_candidates = [
        c
        for c in staff
        if not c.get("is_head_coach")
        and c.get("position")
        and any(kw in c["position"].lower() for kw in dc_keywords)
    ]
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
        result["play_caller"] = play_caller.get("primary_caller")
        result["play_caller_title"] = play_caller.get("primary_title")
        result["play_caller_is_hc"] = play_caller.get("is_head_coach")

    return result


def get_team_pbp(pbp_teams: dict, team_name: str, school_slug: str) -> dict | None:
    if school_slug in pbp_teams:
        return pbp_teams[school_slug]

    slug = slugify(team_name)
    if slug in pbp_teams:
        return pbp_teams[slug]

    name_lower = team_name.lower()
    for _, val in pbp_teams.items():
        stored = (val.get("name") or "").lower()
        if name_lower in stored or stored in name_lower:
            return val

    return None


def _extract_pbp_stats(team_data: dict) -> dict:
    agg = team_data.get("aggregates", {})
    rankings = team_data.get("cfbstats", {}).get("rankings", {}).get("all", {})
    games = team_data.get("games", [])

    def rank(key: str) -> str:
        r = rankings.get(key, {})
        val = r.get("value", "")
        rnk = r.get("rank", "")
        if val != "" and rnk != "":
            return f"{val} (#{rnk})"
        return val or "N/A"

    last_games = sorted(games, key=lambda g: g.get("game_number", 0))[-5:]
    recent = []
    for g in last_games:
        pf = g.get("points_for")
        pa = g.get("points_against")
        opp = g.get("opponent", "?")
        date = g.get("date", "")
        if pf is not None and pa is not None:
            result = "W" if pf > pa else ("L" if pf < pa else "T")
            loc = "vs" if g.get("is_home", True) else "@"
            recent.append(f"{result} {pf}-{pa} {loc} {opp} ({date})")

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


def compute_last_n_stats(games: list[dict], n: int = 3) -> dict:
    sorted_games = sorted(games, key=lambda g: g.get("game_number", 0), reverse=True)
    last_games = sorted_games[:n]
    actual_n = len(last_games)

    def sum_stat(key: str) -> int:
        return sum(g.get(key) or 0 for g in last_games)

    def avg_stat(key: str) -> float:
        if actual_n == 0:
            return 0
        return sum_stat(key) / actual_n

    explosives_total = 0
    explosive_passes_total = 0
    explosive_rushes_total = 0
    penalties_total = 0
    penalties_offense = 0
    penalties_defense = 0
    penalties_special_teams = 0

    for g in last_games:
        explosive_passes = g.get("explosive_passes") or 0
        explosive_rushes = g.get("explosive_rushes") or 0
        explosive_passes_total += explosive_passes
        explosive_rushes_total += explosive_rushes
        explosives = g.get("explosives")
        if explosives is None:
            explosives_total += explosive_passes + explosive_rushes
        else:
            explosives_total += explosives

        for p in g.get("penalty_details") or []:
            if not p.get("accepted"):
                continue
            penalties_total += 1
            side = (p.get("offense_or_defense") or "").lower()
            if side == "offense":
                penalties_offense += 1
            elif side == "defense":
                penalties_defense += 1
            elif side in {"special_teams", "special"}:
                penalties_special_teams += 1

    rz_trips = sum_stat("red_zone_trips")
    rz_tds = sum_stat("red_zone_tds")
    tight_rz_trips = sum_stat("tight_red_zone_trips")
    tight_rz_tds = sum_stat("tight_red_zone_tds")

    if actual_n == 0:
        explosives_per_game = 0
        explosive_passes_per_game = 0
        explosive_rushes_per_game = 0
        penalties_per_game = 0
        ppg = 0
        opp_ppg = 0
    else:
        explosives_per_game = explosives_total / actual_n
        explosive_passes_per_game = explosive_passes_total / actual_n
        explosive_rushes_per_game = explosive_rushes_total / actual_n
        penalties_per_game = penalties_total / actual_n
        ppg = avg_stat("points_for")
        opp_ppg = avg_stat("points_against")

    return {
        "actual_n": actual_n,
        "required_n": n,
        "ppg": round(ppg, 1),
        "opp_ppg": round(opp_ppg, 1),
        "explosives_per_game": round(explosives_per_game, 1),
        "explosive_passes_per_game": round(explosive_passes_per_game, 1),
        "explosive_rushes_per_game": round(explosive_rushes_per_game, 1),
        "rz_trips": rz_trips,
        "rz_tds": rz_tds,
        "rz_td_pct": round((rz_tds / rz_trips * 100), 1) if rz_trips else 0,
        "tight_rz_trips": tight_rz_trips,
        "tight_rz_tds": tight_rz_tds,
        "tight_rz_td_pct": round((tight_rz_tds / tight_rz_trips * 100), 1)
        if tight_rz_trips
        else 0,
        "green_zone_trips": sum_stat("green_zone_trips"),
        "green_zone_tds": sum_stat("green_zone_tds"),
        "turnover_margin": sum_stat("turnovers_gained") - sum_stat("turnovers_lost"),
        "turnovers_gained": sum_stat("turnovers_gained"),
        "turnovers_lost": sum_stat("turnovers_lost"),
        "points_off_turnovers_for": sum_stat("points_off_turnovers_for"),
        "points_off_turnovers_against": sum_stat("points_off_turnovers_against"),
        "middle8_margin": sum_stat("middle8_points_for") - sum_stat("middle8_points_against"),
        "middle8_points_for": sum_stat("middle8_points_for"),
        "middle8_points_against": sum_stat("middle8_points_against"),
        "fourth_down_attempts": sum_stat("4th_down_attempts"),
        "fourth_down_conversions": sum_stat("4th_down_conversions"),
        "penalties_per_game": penalties_per_game,
        "penalties_offense": penalties_offense,
        "penalties_defense": penalties_defense,
        "penalties_special_teams": penalties_special_teams,
    }


def gather_team_data(
    db: sqlite3.Connection,
    pbp_teams: dict,
    team_name: str,
    season: int,
    last_n: int = 3,
) -> dict:
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
            "oc": "N/A",
            "oc_title": "",
            "dc": "N/A",
            "dc_title": "",
            "play_caller": None,
            "play_caller_title": None,
        }
        school_slug = slugify(team_name)
        school_conf = ""
        school_name = team_name

    pbp_entry = get_team_pbp(pbp_teams, team_name, school_slug)
    pbp_stats = _extract_pbp_stats(pbp_entry) if pbp_entry else {}
    games = pbp_entry.get("games", []) if pbp_entry else []
    last_n_stats = compute_last_n_stats(games, last_n)

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
        "last_n": last_n_stats,
        "pbp_entry": pbp_entry,
        "has_pbp": pbp_entry is not None,
        "has_coaches": school is not None,
    }


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
    s1, s2 = slug1.lower(), slug2.lower()
    for g in games:
        away_seo = (g.get("away") or {}).get("names", {}).get("seo", "")
        home_seo = (g.get("home") or {}).get("names", {}).get("seo", "")
        if {away_seo, home_seo} & {s1, s2}:
            return g
    return None
