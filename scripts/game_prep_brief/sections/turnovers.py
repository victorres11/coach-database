from __future__ import annotations


def _games(team: dict) -> list[dict]:
    pbp = team.get("pbp_entry") or {}
    return pbp.get("games", [])


def _sum(games: list[dict], key: str) -> int:
    return sum(g.get(key, 0) or 0 for g in games)


def _should_show_last_n(team: dict) -> bool:
    last_n = team.get("last_n", {}) or {}
    return last_n.get("actual_n", 0) >= last_n.get("required_n", 3)


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

    last_n_html = ""
    if _should_show_last_n(team):
        last_n = team.get("last_n", {}) or {}
        actual_n = last_n.get("actual_n", 0)
        l3_margin = last_n.get("turnover_margin")
        l3_gained = last_n.get("turnovers_gained", 0)
        l3_lost = last_n.get("turnovers_lost", 0)
        l3_pts_for = last_n.get("points_off_turnovers_for", 0)
        l3_pts_against = last_n.get("points_off_turnovers_against", 0)
        l3_margin_display = l3_margin if l3_margin is not None else "N/A"

        margin_color = ""
        if l3_margin is not None and margin is not None:
            if l3_margin > margin:
                margin_color = " style=\"color: #1b7f3a;\""
            elif l3_margin < margin:
                margin_color = " style=\"color: #b3261e;\""

        pts_for_arrow = ""
        if l3_pts_for > totals["pts_for"]:
            pts_for_arrow = " <span style=\"color: #1b7f3a;\">↑</span>"
        elif l3_pts_for < totals["pts_for"]:
            pts_for_arrow = " <span style=\"color: #b3261e;\">↓</span>"

        pts_against_arrow = ""
        if l3_pts_against < totals["pts_against"]:
            pts_against_arrow = " <span style=\"color: #1b7f3a;\">↓</span>"
        elif l3_pts_against > totals["pts_against"]:
            pts_against_arrow = " <span style=\"color: #b3261e;\">↑</span>"

        last_n_html = f"""
      <div class="block">
        <h4>Last {actual_n} Games Trending</h4>
        <ul>
          <li>Margin: <span{margin_color}>{l3_margin_display}</span> (was {margin if margin is not None else 'N/A'})</li>
          <li>Gained/Lost: {l3_gained} / {l3_lost}</li>
          <li>Points Off TO: {l3_pts_for} for{pts_for_arrow} / {l3_pts_against} against{pts_against_arrow}</li>
        </ul>
      </div>
        """

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
      {last_n_html}
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
    margin_note = ""
    points_note = ""
    if _should_show_last_n(team):
        last_n = team.get("last_n", {}) or {}
        actual_n = last_n.get("actual_n", 0)
        l3_margin = last_n.get("turnover_margin")
        l3_pts_for = last_n.get("points_off_turnovers_for", 0)
        l3_pts_against = last_n.get("points_off_turnovers_against", 0)
        if l3_margin is not None and margin != "N/A" and l3_margin != margin:
            margin_note = f" (L{actual_n}: {l3_margin})"

        season_games = len(games)
        season_for_pg = (pts_for / season_games) if season_games else 0
        season_against_pg = (pts_against / season_games) if season_games else 0
        last_for_pg = (l3_pts_for / actual_n) if actual_n else 0
        last_against_pg = (l3_pts_against / actual_n) if actual_n else 0
        delta_for = last_for_pg - season_for_pg
        delta_against = last_against_pg - season_against_pg
        total_delta_for = l3_pts_for - (season_for_pg * actual_n)
        total_delta_against = l3_pts_against - (season_against_pg * actual_n)
        if (
            abs(delta_for) >= 0.8
            or abs(delta_against) >= 0.8
            or abs(total_delta_for) >= 4
            or abs(total_delta_against) >= 4
        ):
            points_note = f" (L{actual_n}: {l3_pts_for} for / {l3_pts_against} against)"
    return "\n".join([
        f"*{team['display_name']}*",
        f"- Margin: {margin}{margin_note} (Gained {gained}, Lost {lost})",
        f"- Points Off TO: {pts_for} for / {pts_against} against{points_note}",
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
