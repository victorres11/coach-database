from __future__ import annotations


def _games(team: dict) -> list[dict]:
    pbp = team.get("pbp_entry") or {}
    return pbp.get("games", [])


def _sum(games: list[dict], key: str) -> int:
    return sum(g.get(key, 0) or 0 for g in games)


def _post_turnover_drives(games: list[dict]) -> list[str]:
    items = []
    for g in sorted(games, key=lambda x: x.get("game_number", 0))[-3:]:
        opp = g.get("opponent", "?")
        drives = g.get("post_turnover_drives", []) or []
        if not drives:
            continue
        items.append(f"G{g.get('game_number', '?')} vs {opp}: {len(drives)} drives")
    return items


def _avg_pts_after_turnover(games: list[dict]) -> float:
    total_pts = _sum(games, "points_off_turnovers_for")
    total_drives = 0
    for g in games:
        total_drives += len(g.get("post_turnover_drives", []) or [])
    if not total_drives:
        return 0.0
    return round(total_pts / total_drives, 2)


def _team_html(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"<div class=\"team-card\"><h3>{team['display_name']}</h3><p><em>No PBP data.</em></p></div>"

    games = _games(team)
    totals = {
        "gained": _sum(games, "turnovers_gained"),
        "lost": _sum(games, "turnovers_lost"),
        "int_gained": _sum(games, "interceptions_gained"),
        "int_lost": _sum(games, "interceptions_lost"),
        "fum_gained": _sum(games, "fumbles_gained"),
        "fum_lost": _sum(games, "fumbles_lost"),
        "pts_for": _sum(games, "points_off_turnovers_for"),
        "pts_against": _sum(games, "points_off_turnovers_against"),
    }
    margin = team.get("pbp_entry", {}).get("aggregates", {}).get("turnover_margin")
    drives_list = _post_turnover_drives(games)
    drives_html = "".join(f"<li>{d}</li>" for d in drives_list) or "<li>N/A</li>"

    return f"""
    <div class="team-card">
      <h3>{team['display_name']}</h3>
      <div class="block">
        <h4>Season Totals</h4>
        <ul>
          <li>Turnovers Gained/Lost: {totals['gained']} / {totals['lost']}</li>
          <li>Margin: {margin if margin is not None else 'N/A'}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Breakdown</h4>
        <ul>
          <li>INT Gained/Lost: {totals['int_gained']} / {totals['int_lost']}</li>
          <li>Fumbles Gained/Lost: {totals['fum_gained']} / {totals['fum_lost']}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Points Off Turnovers</h4>
        <ul>
          <li>For / Against: {totals['pts_for']} / {totals['pts_against']}</li>
          <li>Avg Points per Post-TO Drive: {_avg_pts_after_turnover(games)}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Post-Turnover Drives (Recent)</h4>
        <ul>{drives_html}</ul>
      </div>
    </div>
    """


def _team_md(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"*{team['display_name']}*\n- Turnovers: N/A"
    games = _games(team)
    gained = _sum(games, "turnovers_gained")
    lost = _sum(games, "turnovers_lost")
    margin = team.get("pbp_entry", {}).get("aggregates", {}).get("turnover_margin", "N/A")
    pts_for = _sum(games, "points_off_turnovers_for")
    pts_against = _sum(games, "points_off_turnovers_against")
    return "\n".join([
        f"*{team['display_name']}*",
        f"- Margin: {margin} (Gained {gained}, Lost {lost})",
        f"- Points Off TO: {pts_for} for / {pts_against} against",
    ])


def build(team1: dict, team2: dict) -> dict:
    """Turnover chain section."""
    html_content = f"""
    <div class="section-grid">
      {_team_html(team1)}
      {_team_html(team2)}
    </div>
    """
    md_content = "\n\n".join([
        "*Turnovers*",
        _team_md(team1),
        _team_md(team2),
    ])
    return {
        "title": "Turnovers",
        "html_content": html_content,
        "md_content": md_content,
        "key": "turnovers",
    }
