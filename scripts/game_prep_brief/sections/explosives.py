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


def _should_show_last_n(team: dict) -> bool:
    last_n = team.get("last_n", {}) or {}
    return last_n.get("actual_n", 0) >= last_n.get("required_n", 3)


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


def _explosive_play_html(p):
    header = f"<strong>{p.get('yards','?')} yd {p.get('type','play')} — {p.get('player','?')}</strong>"
    desc = p.get('description') or p.get('play_text') or p.get('text') or ''
    if desc:
        return f"<li>{header}<br><span style=\"color:#555;font-size:0.9em;\">{desc}</span></li>"
    else:
        return f"<li>{header}</li>"


def _explosive_play_md(p):
    header = f"**{p.get('yards','?')} yd {p.get('type','play')} — {p.get('player','?')}**"
    desc = p.get('description') or p.get('play_text') or p.get('text') or ''
    if desc:
        return f"  • {header}\n    {desc}"
    else:
        return f"  • {header}"


def _team_html(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"<div class=\"team-card\"><h3>{team['display_name']}</h3><p><em>No PBP data.</em></p></div>"

    games = _games(team)
    totals = _aggregate_explosives(games)
    trend = _per_game_trend(games)
    top_plays = _top_explosive_plays(games)

    trend_html = "".join(f"<li>{t}</li>" for t in trend) if trend else "<li>N/A</li>"
    plays_html = "".join(_explosive_play_html(p) for p in top_plays) or "<li>N/A</li>"

    last_n_html = ""
    if _should_show_last_n(team):
        last_n = team.get("last_n", {}) or {}
        actual_n = last_n.get("actual_n", 0)
        l3_epg = last_n.get("explosives_per_game", 0) or 0
        l3_ppg = last_n.get("explosive_passes_per_game", 0) or 0
        l3_rpg = last_n.get("explosive_rushes_per_game", 0) or 0
        season_epg = totals["explosives"] / len(games) if games else 0

        epg_arrow = ""
        if l3_epg > season_epg:
            epg_arrow = " <span style=\"color: #1b7f3a;\">↑</span>"
        elif l3_epg < season_epg:
            epg_arrow = " <span style=\"color: #b3261e;\">↓</span>"

        last_n_html = f"""
      <div class="block">
        <h4>Last {actual_n} Trending</h4>
        <ul>
          <li>Explosives/Game: {l3_epg:.1f} (Season: {season_epg:.1f}){epg_arrow}</li>
          <li>Pass/Game: {l3_ppg:.1f} / Rush/Game: {l3_rpg:.1f}</li>
        </ul>
      </div>
        """

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
      {last_n_html}
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
    explosives_suffix = ""
    if _should_show_last_n(team):
        last_n = team.get("last_n", {}) or {}
        actual_n = last_n.get("actual_n", 0)
        l3_epg = last_n.get("explosives_per_game", 0) or 0
        season_epg = totals["explosives"] / len(games) if games else 0
        if abs(l3_epg - season_epg) >= 0.8:
            explosives_suffix = f" (L{actual_n}: {l3_epg:.1f}/gm)"
    lines.append(
        f"- Total Explosives: {totals['explosives']} (Pass {totals['explosive_passes']}, Rush {totals['explosive_rushes']}){explosives_suffix}"
    )
    if top_plays:
        lines.append("- Top Plays:")
        for p in top_plays:
            lines.append(_explosive_play_md(p))
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
