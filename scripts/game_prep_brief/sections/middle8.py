from __future__ import annotations


def _games(team: dict) -> list[dict]:
    pbp = team.get("pbp_entry") or {}
    return pbp.get("games", [])


def _sum(games: list[dict], key: str) -> int:
    return sum(g.get(key, 0) or 0 for g in games)


def _scoring_plays(games: list[dict]) -> list[str]:
    plays = []
    for g in games:
        for p in g.get("middle8_scoring_plays", []) or []:
            plays.append(p)
    return plays


def _should_show_last_n(team: dict) -> bool:
    last_n = team.get("last_n", {}) or {}
    return last_n.get("actual_n", 0) >= last_n.get("required_n", 3)


def _team_html(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"<div class=\"team-card\"><h3>{team['display_name']}</h3><p><em>No PBP data.</em></p></div>"
    games = _games(team)
    pts_for = _sum(games, "middle8_points_for")
    pts_against = _sum(games, "middle8_points_against")
    margin = pts_for - pts_against
    per_game = [
        f"G{g.get('game_number','?')} vs {g.get('opponent','?')}: {g.get('middle8_points_for',0)}-{g.get('middle8_points_against',0)}"
        for g in sorted(games, key=lambda x: x.get("game_number", 0))
    ]
    per_game_html = "".join(f"<li>{l}</li>" for l in per_game) or "<li>N/A</li>"
    plays = _scoring_plays(games)
    plays_html = "".join(f"<li>{p}</li>" for p in plays[:6]) or "<li>N/A</li>"
    last_n_html = ""
    if _should_show_last_n(team):
        last_n = team.get("last_n", {}) or {}
        actual_n = last_n.get("actual_n", 0)
        l3_pts_for = last_n.get("middle8_points_for", 0)
        l3_pts_against = last_n.get("middle8_points_against", 0)
        l3_margin = last_n.get("middle8_margin", 0)
        trend_color = ""
        if l3_margin > margin:
            trend_color = " style=\"color: #1b7f2a;\""
        elif l3_margin < margin:
            trend_color = " style=\"color: #b42318;\""
        last_n_html = f"""
      <div class="block">
        <h4>Last {actual_n} Trending</h4>
        <ul>
          <li>Points For / Against: {l3_pts_for} / {l3_pts_against}</li>
          <li>Margin: <span{trend_color}>{l3_margin}</span> (Season: {margin})</li>
        </ul>
      </div>
        """

    return f"""
    <div class="team-card">
      <h3>{team['display_name']}</h3>
      <div class="block">
        <h4>Season Totals</h4>
        <ul>
          <li>Points For / Against: {pts_for} / {pts_against}</li>
          <li>Margin: {margin}</li>
        </ul>
      </div>
      {last_n_html}
      <div class="block">
        <h4>Per-Game Breakdown</h4>
        <ul>{per_game_html}</ul>
      </div>
      <div class="block">
        <h4>Notable Scoring Plays</h4>
        <ul>{plays_html}</ul>
      </div>
    </div>
    """


def _team_md(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"*{team['display_name']}*\n- Middle 8: N/A"
    games = _games(team)
    pts_for = _sum(games, "middle8_points_for")
    pts_against = _sum(games, "middle8_points_against")
    margin = pts_for - pts_against
    last_n_note = ""
    if _should_show_last_n(team):
        last_n = team.get("last_n", {}) or {}
        actual_n = last_n.get("actual_n", 0)
        l3_margin = last_n.get("middle8_margin", 0)
        if l3_margin != margin:
            last_n_note = f" (L{actual_n}: {l3_margin})"
    return "\n".join([
        f"*{team['display_name']}*",
        f"- Middle 8 Margin: {margin} ({pts_for} for / {pts_against} against){last_n_note}",
    ])


def build(team1: dict, team2: dict) -> dict:
    """Middle 8 momentum section."""
    html_content = f"""
    <div class="section-grid">
      {_team_html(team1)}
      {_team_html(team2)}
    </div>
    """
    md_content = "\n\n".join([
        "*Middle 8*",
        _team_md(team1),
        _team_md(team2),
    ])
    return {
        "title": "Middle 8",
        "html_content": html_content,
        "md_content": md_content,
        "key": "middle8",
    }
