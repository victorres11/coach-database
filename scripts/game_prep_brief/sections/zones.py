from __future__ import annotations

from ..renderers.svg import comparison_bars


def _games(team: dict) -> list[dict]:
    pbp = team.get("pbp_entry") or {}
    return pbp.get("games", [])


def _sum(games: list[dict], key: str) -> int:
    return sum(g.get(key, 0) or 0 for g in games)


def _rate(n: int, d: int) -> float:
    if not d:
        return 0.0
    return round((n / d) * 100.0, 1)


def _team_zone_stats(team: dict) -> dict:
    games = _games(team)
    rz_trips = _sum(games, "red_zone_trips")
    rz_tds = _sum(games, "red_zone_tds")
    rz_fgs = _sum(games, "red_zone_fgs")

    trz_trips = _sum(games, "tight_red_zone_trips")
    trz_tds = _sum(games, "tight_red_zone_tds")
    trz_fgs = _sum(games, "tight_red_zone_fgs")

    gz_trips = _sum(games, "green_zone_trips")
    gz_tds = _sum(games, "green_zone_tds")
    gz_fgs = _sum(games, "green_zone_fgs")
    gz_failed = _sum(games, "green_zone_failed")

    return {
        "rz_trips": rz_trips,
        "rz_tds": rz_tds,
        "rz_fgs": rz_fgs,
        "rz_td_pct": _rate(rz_tds, rz_trips),
        "rz_eff": _rate(rz_tds + rz_fgs, rz_trips),
        "trz_trips": trz_trips,
        "trz_tds": trz_tds,
        "trz_fgs": trz_fgs,
        "trz_td_pct": _rate(trz_tds, trz_trips),
        "gz_trips": gz_trips,
        "gz_tds": gz_tds,
        "gz_fgs": gz_fgs,
        "gz_success": _rate(gz_tds + gz_fgs, gz_trips),
        "gz_failed": gz_failed,
    }


def _team_html(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"<div class=\"team-card\"><h3>{team['display_name']}</h3><p><em>No PBP data.</em></p></div>"
    stats = _team_zone_stats(team)
    rz_rank = team.get("stats", {}).get("red_zone_rank", "N/A")

    return f"""
    <div class="team-card">
      <h3>{team['display_name']}</h3>
      <div class="block">
        <h4>Red Zone</h4>
        <ul>
          <li>Trips: {stats['rz_trips']}</li>
          <li>TDs / FGs: {stats['rz_tds']} / {stats['rz_fgs']}</li>
          <li>TD%: {stats['rz_td_pct']}%</li>
          <li>Efficiency: {stats['rz_eff']}%</li>
          <li>CFBStats Rank: {rz_rank}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Tight Red Zone (Inside 10)</h4>
        <ul>
          <li>Trips: {stats['trz_trips']}</li>
          <li>TDs / FGs: {stats['trz_tds']} / {stats['trz_fgs']}</li>
          <li>TD%: {stats['trz_td_pct']}%</li>
        </ul>
      </div>
      <div class="block">
        <h4>Green Zone (Inside 40)</h4>
        <ul>
          <li>Trips: {stats['gz_trips']}</li>
          <li>TDs / FGs: {stats['gz_tds']} / {stats['gz_fgs']}</li>
          <li>Success: {stats['gz_success']}%</li>
        </ul>
      </div>
    </div>
    """


def _team_md(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"*{team['display_name']}*\n- Red Zone: N/A"
    stats = _team_zone_stats(team)
    return "\n".join([
        f"*{team['display_name']}*",
        f"- Red Zone TD%: {stats['rz_td_pct']}%",
        f"- Tight RZ TD%: {stats['trz_td_pct']}%",
        f"- Green Zone Success: {stats['gz_success']}%",
    ])


def build(team1: dict, team2: dict) -> dict:
    """Red zone, tight red zone, green zone section."""
    t1_stats = _team_zone_stats(team1) if team1.get("has_pbp") else {"rz_td_pct": 0}
    t2_stats = _team_zone_stats(team2) if team2.get("has_pbp") else {"rz_td_pct": 0}
    color1 = team1.get("stats", {}).get("color", "#2563eb")
    color2 = team2.get("stats", {}).get("color", "#dc2626")
    rz_svg = comparison_bars(
        "Red Zone TD%",
        t1_stats.get("rz_td_pct", 0),
        t2_stats.get("rz_td_pct", 0),
        color1,
        color2,
    )

    html_content = f"""
    <div class="metric-compare">{rz_svg}</div>
    <div class="section-grid">
      {_team_html(team1)}
      {_team_html(team2)}
    </div>
    """

    md_content = "\n\n".join([
        "*Scoring Zones*",
        _team_md(team1),
        _team_md(team2),
    ])

    return {
        "title": "Scoring Zones",
        "html_content": html_content,
        "md_content": md_content,
        "key": "zones",
    }
