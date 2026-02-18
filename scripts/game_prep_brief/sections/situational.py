from __future__ import annotations


def _games(team: dict) -> list[dict]:
    pbp = team.get("pbp_entry") or {}
    return pbp.get("games", [])


def _sum(games: list[dict], key: str) -> int:
    return sum(g.get(key, 0) or 0 for g in games)


def _fourth_down_rank(team: dict) -> str:
    pbp = team.get("pbp_entry") or {}
    rankings = pbp.get("cfbstats", {}).get("rankings", {}).get("all", {})
    r = rankings.get("fourth_down", {})
    val = r.get("value", "")
    rnk = r.get("rank", "")
    if val != "" and rnk != "":
        return f"{val} (#{rnk})"
    return val or "N/A"


def _team_html(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"<div class=\"team-card\"><h3>{team['display_name']}</h3><p><em>No PBP data.</em></p></div>"
    games = _games(team)
    attempts = _sum(games, "4th_down_attempts")
    conversions = _sum(games, "4th_down_conversions")
    pct = round((conversions / attempts) * 100, 1) if attempts else 0.0
    per_game = [
        f"G{g.get('game_number','?')} vs {g.get('opponent','?')}: {g.get('4th_down_attempts',0)} att"
        for g in sorted(games, key=lambda x: x.get("game_number", 0))
    ]
    per_game_html = "".join(f"<li>{l}</li>" for l in per_game) or "<li>N/A</li>"
    third_down = team.get("stats", {}).get("third_down", "N/A")

    return f"""
    <div class="team-card">
      <h3>{team['display_name']}</h3>
      <div class="block">
        <h4>3rd Down</h4>
        <ul>
          <li>CFBStats: {third_down}</li>
        </ul>
      </div>
      <div class="block">
        <h4>4th Down</h4>
        <ul>
          <li>Attempts / Conversions: {attempts} / {conversions}</li>
          <li>Conversion %: {pct}%</li>
          <li>CFBStats: {_fourth_down_rank(team)}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Per-Game Attempts</h4>
        <ul>{per_game_html}</ul>
      </div>
    </div>
    """


def _team_md(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"*{team['display_name']}*\n- 3rd/4th Down: N/A"
    games = _games(team)
    attempts = _sum(games, "4th_down_attempts")
    conversions = _sum(games, "4th_down_conversions")
    pct = round((conversions / attempts) * 100, 1) if attempts else 0.0
    third_down = team.get("stats", {}).get("third_down", "N/A")
    return "\n".join([
        f"*{team['display_name']}*",
        f"- 3rd Down: {third_down}",
        f"- 4th Down: {conversions}/{attempts} ({pct}%)",
    ])


def build(team1: dict, team2: dict) -> dict:
    """3rd and 4th down tendencies section."""
    html_content = f"""
    <div class="section-grid">
      {_team_html(team1)}
      {_team_html(team2)}
    </div>
    """
    md_content = "\n\n".join([
        "*Situational (3rd/4th Down)*",
        _team_md(team1),
        _team_md(team2),
    ])
    return {
        "title": "Situational",
        "html_content": html_content,
        "md_content": md_content,
        "key": "situational",
    }
