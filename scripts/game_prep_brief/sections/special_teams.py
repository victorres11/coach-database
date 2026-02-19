from __future__ import annotations


def _games(team: dict) -> list[dict]:
    pbp = team.get("pbp_entry") or {}
    return pbp.get("games", [])


def _sum(values: list[float]) -> float:
    return sum(v for v in values if v is not None)


def _avg(values: list[float]) -> float:
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 2)


def _team_stats(team: dict) -> dict:
    games = _games(team)
    st_list = [g.get("special_teams", {}) or {} for g in games]

    fg_made = _sum([st.get("field_goals_made") for st in st_list])
    fg_att = _sum([st.get("field_goals_attempts") for st in st_list])
    fg_pct = round((fg_made / fg_att) * 100, 1) if fg_att else 0.0
    fg_long = max([st.get("field_goal_long", 0) or 0 for st in st_list] or [0])

    punts = _sum([st.get("punts") for st in st_list])
    punt_yards = _sum([st.get("punt_yards") for st in st_list])
    punt_net = _sum([st.get("punt_net_yards") for st in st_list])
    punt_avg = round(punt_yards / punts, 2) if punts else _avg([st.get("punt_avg") for st in st_list])
    punt_net_avg = round(punt_net / punts, 2) if punts else _avg([st.get("punt_net_avg") for st in st_list])
    punt_long = max([st.get("punt_long", 0) or 0 for st in st_list] or [0])
    punts_inside_20 = _sum([st.get("punts_inside_20") for st in st_list])
    punt_touchbacks = _sum([st.get("punt_touchbacks") for st in st_list])

    punt_returns = _sum([st.get("punt_returns") for st in st_list])
    punt_return_yards = _sum([st.get("punt_return_yards") for st in st_list])
    punt_return_avg = round(punt_return_yards / punt_returns, 2) if punt_returns else _avg([st.get("punt_return_avg") for st in st_list])
    punt_return_long = max([st.get("punt_return_long", 0) or 0 for st in st_list] or [0])
    punt_20_plus = _sum([st.get("punt_return_20_plus") for st in st_list])

    kick_returns = _sum([st.get("kickoff_returns") for st in st_list])
    kick_return_yards = _sum([st.get("kickoff_return_yards") for st in st_list])
    kick_return_avg = round(kick_return_yards / kick_returns, 2) if kick_returns else _avg([st.get("kickoff_return_avg") for st in st_list])
    kick_return_long = max([st.get("kickoff_return_long", 0) or 0 for st in st_list] or [0])
    kick_30_plus = _sum([st.get("kick_return_30_plus") for st in st_list])

    return {
        "fg_made": int(fg_made),
        "fg_att": int(fg_att),
        "fg_pct": fg_pct,
        "fg_long": fg_long,
        "punts": int(punts),
        "punt_avg": punt_avg,
        "punt_net_avg": punt_net_avg,
        "punt_long": punt_long,
        "punts_inside_20": int(punts_inside_20),
        "punt_touchbacks": int(punt_touchbacks),
        "punt_return_avg": punt_return_avg,
        "punt_return_long": punt_return_long,
        "punt_20_plus": int(punt_20_plus),
        "kick_return_avg": kick_return_avg,
        "kick_return_long": kick_return_long,
        "kick_30_plus": int(kick_30_plus),
        "special_teams_tds": int(_sum([st.get("special_teams_tds") for st in st_list])),
        "fg_blocks": int(_sum([st.get("fg_blocks") for st in st_list])),
        "punt_blocks": int(_sum([st.get("punt_blocks") for st in st_list])),
        "onside_attempts": int(_sum([st.get("onside_kicks_attempted") for st in st_list])),
        "onside_recovered": int(_sum([st.get("onside_kicks_recovered") for st in st_list])),
    }


def _team_html(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"<div class=\"team-card\"><h3>{team['display_name']}</h3><p><em>No PBP data.</em></p></div>"
    stats = _team_stats(team)

    return f"""
    <div class="team-card">
      <h3>{team['display_name']}</h3>
      <div class="block">
        <h4>Field Goals</h4>
        <ul>
          <li>Made/Att: {stats['fg_made']} / {stats['fg_att']} ({stats['fg_pct']}%)</li>
          <li>Long: {stats['fg_long']}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Punting</h4>
        <ul>
          <li>Avg / Net: {stats['punt_avg']} / {stats['punt_net_avg']}</li>
          <li>Long: {stats['punt_long']}</li>
          <li>Inside 20: {stats['punts_inside_20']} · TB: {stats['punt_touchbacks']}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Returns</h4>
        <ul>
          <li>Punt Return Avg/Long: {stats['punt_return_avg']} / {stats['punt_return_long']} (20+ {stats['punt_20_plus']})</li>
          <li>KO Return Avg/Long: {stats['kick_return_avg']} / {stats['kick_return_long']} (30+ {stats['kick_30_plus']})</li>
        </ul>
      </div>
      <div class="block">
        <h4>Impact Plays</h4>
        <ul>
          <li>ST TDs: {stats['special_teams_tds']}</li>
          <li>FG Blocks: {stats['fg_blocks']} · Punt Blocks: {stats['punt_blocks']}</li>
          <li>Onside: {stats['onside_recovered']} / {stats['onside_attempts']}</li>
        </ul>
      </div>
    </div>
    """


def _team_md(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"*{team['display_name']}*\n- Special Teams: N/A"
    stats = _team_stats(team)
    return "\n".join([
        f"*{team['display_name']}*",
        f"- FG%: {stats['fg_pct']}% (Long {stats['fg_long']})",
        f"- Punt Avg: {stats['punt_avg']} (Net {stats['punt_net_avg']})",
        f"- Return TDs: {stats['special_teams_tds']}",
    ])


def build(team1: dict, team2: dict) -> dict:
    """Special teams deep-dive section."""
    html_content = f"""
    <div class="section-grid">
      {_team_html(team1)}
      {_team_html(team2)}
    </div>
    """
    md_content = "\n\n".join([
        "*Special Teams*",
        _team_md(team1),
        _team_md(team2),
    ])
    return {
        "title": "Special Teams",
        "html_content": html_content,
        "md_content": md_content,
        "key": "special_teams",
    }
