from __future__ import annotations


def _games(team: dict) -> list[dict]:
    pbp = team.get("pbp_entry") or {}
    return pbp.get("games", [])


def _aggregate_explosives(games: list[dict]) -> dict:
    totals = {
        "explosives": 0,
        "explosive_passes": 0,
        "explosive_rushes": 0,
    }
    for g in games:
        totals["explosive_passes"] += g.get("explosive_passes", 0) or 0
        totals["explosive_rushes"] += g.get("explosive_rushes", 0) or 0
        if g.get("explosives") is not None:
            totals["explosives"] += g.get("explosives", 0) or 0
        else:
            totals["explosives"] += (g.get("explosive_passes", 0) or 0) + (
                g.get("explosive_rushes", 0) or 0
            )
    return totals


def _per_game_trend(games: list[dict]) -> list[str]:
    trend = []
    for g in sorted(games, key=lambda x: x.get("game_number", 0)):
        opp = g.get("opponent", "?")
        count = g.get("explosives")
        if count is None:
            count = (g.get("explosive_passes", 0) or 0) + (g.get("explosive_rushes", 0) or 0)
        trend.append(f"G{g.get('game_number', '?')} vs {opp}: {count}")
    return trend


def _top_explosive_plays(games: list[dict]) -> list[dict]:
    plays = []
    for g in games:
        for p in g.get("explosive_details", []) or []:
            plays.append(p)
    plays.sort(key=lambda p: p.get("yards", 0), reverse=True)
    return plays[:10]


def _team_html(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"<div class=\"team-card\"><h3>{team['display_name']}</h3><p><em>No PBP data.</em></p></div>"

    games = _games(team)
    totals = _aggregate_explosives(games)
    trend = _per_game_trend(games)
    top_plays = _top_explosive_plays(games)

    trend_html = "".join(f"<li>{t}</li>" for t in trend) if trend else "<li>N/A</li>"
    plays_html = "".join(
        f"<li>{p.get('yards','?')} yd {p.get('type','play')} — {p.get('player','?')}</li>"
        for p in top_plays
    ) or "<li>N/A</li>"

    return f"""
    <div class="team-card">
      <h3>{team['display_name']}</h3>
      <div class="block">
        <h4>Totals</h4>
        <ul>
          <li>Total Explosives: {totals['explosives']}</li>
          <li>Explosive Passes: {totals['explosive_passes']}</li>
          <li>Explosive Rushes: {totals['explosive_rushes']}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Per-Game Trend</h4>
        <ul>{trend_html}</ul>
      </div>
      <div class="block">
        <h4>Top Explosive Plays</h4>
        <ul>{plays_html}</ul>
      </div>
    </div>
    """


def _team_md(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"*{team['display_name']}*\n- Explosives: N/A"
    games = _games(team)
    totals = _aggregate_explosives(games)
    top_plays = _top_explosive_plays(games)[:3]
    lines = [f"*{team['display_name']}*"]
    lines.append(
        f"- Total Explosives: {totals['explosives']} (Pass {totals['explosive_passes']}, Rush {totals['explosive_rushes']})"
    )
    if top_plays:
        lines.append("- Top Plays:")
        for p in top_plays:
            desc = p.get("player") or "?"
            lines.append(f"  • {p.get('yards','?')} yd {p.get('type','play')} — {desc}")
    return "\n".join(lines)


def build(team1: dict, team2: dict) -> dict:
    """Explosive plays section."""
    html_content = f"""
    <div class="section-grid">
      {_team_html(team1)}
      {_team_html(team2)}
    </div>
    """
    md_content = "\n\n".join([
        "*Explosive Plays*",
        _team_md(team1),
        _team_md(team2),
    ])
    return {
        "title": "Explosive Plays",
        "html_content": html_content,
        "md_content": md_content,
        "key": "explosives",
    }
