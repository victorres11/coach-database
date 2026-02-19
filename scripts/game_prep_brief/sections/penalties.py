from __future__ import annotations

import re
from collections import Counter, defaultdict


def _games(team: dict) -> list[dict]:
    pbp = team.get("pbp_entry") or {}
    return pbp.get("games", [])


def _simplify_penalty(pen: dict) -> str:
    desc = pen.get("description") or pen.get("type") or ""
    m = re.search(r"PENALTY\s+\w+\s+([^\d\.]+)", desc, re.IGNORECASE)
    if m:
        text = m.group(1)
    else:
        text = pen.get("type") or desc
    text = re.sub(r"Penalty\s+", "", text, flags=re.IGNORECASE)
    text = re.split(r"\s+\d", text)[0]
    text = text.replace("yards", "").replace("yard", "").strip()
    return text.title() if text else "Unknown"


def _aggregate(team: dict) -> dict:
    games = _games(team)
    total = 0
    yards = 0
    by_side = defaultdict(lambda: {"count": 0, "yards": 0})
    by_type_count = Counter()
    by_type_yards = Counter()
    by_quarter = Counter()

    for g in games:
        for p in g.get("penalty_details", []) or []:
            if not p.get("accepted", False):
                continue
            total += 1
            y = p.get("yards", 0) or 0
            yards += y
            side = p.get("offense_or_defense", "unknown") or "unknown"
            by_side[side]["count"] += 1
            by_side[side]["yards"] += y
            ptype = _simplify_penalty(p)
            by_type_count[ptype] += 1
            by_type_yards[ptype] += y
            q = p.get("quarter")
            if q is not None:
                by_quarter[q] += 1

    return {
        "total": total,
        "yards": yards,
        "by_side": by_side,
        "by_type_count": by_type_count,
        "by_type_yards": by_type_yards,
        "by_quarter": by_quarter,
    }


def _penalties_rank(team: dict) -> str:
    pbp = team.get("pbp_entry") or {}
    rankings = pbp.get("cfbstats", {}).get("rankings", {}).get("all", {})
    r = rankings.get("penalties", {})
    val = r.get("value", "")
    rnk = r.get("rank", "")
    if val != "" and rnk != "":
        return f"{val} (#{rnk})"
    return val or "N/A"


def _should_show_last_n(team: dict) -> bool:
    last_n = team.get("last_n", {}) or {}
    return last_n.get("actual_n", 0) >= last_n.get("required_n", 3)


def _team_html(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"<div class=\"team-card\"><h3>{team['display_name']}</h3><p><em>No PBP data.</em></p></div>"
    games = _games(team)
    agg = _aggregate(team)
    top_common = agg["by_type_count"].most_common(3)
    top_yards = agg["by_type_yards"].most_common(3)

    common_html = "".join(f"<li>{k}: {v}</li>" for k, v in top_common) or "<li>N/A</li>"
    yards_html = "".join(f"<li>{k}: {v} yds</li>" for k, v in top_yards) or "<li>N/A</li>"
    quarter_html = "".join(f"<li>Q{q}: {c}</li>" for q, c in sorted(agg["by_quarter"].items())) or "<li>N/A</li>"

    offense = agg["by_side"].get("offense", {"count": 0, "yards": 0})
    defense = agg["by_side"].get("defense", {"count": 0, "yards": 0})

    last_n_html = ""
    if _should_show_last_n(team):
        last_n = team.get("last_n", {}) or {}
        actual_n = last_n.get("actual_n", 0)
        l3_ppg = last_n.get("penalties_per_game", 0) or 0
        l3_offense = last_n.get("penalties_offense", 0) or 0
        l3_defense = last_n.get("penalties_defense", 0) or 0
        l3_st = last_n.get("penalties_special_teams", 0) or 0
        season_ppg = agg["total"] / max(len(games), 1)

        ppg_arrow = ""
        if l3_ppg < season_ppg:
            ppg_arrow = " <span style=\"color: #1b7f3a;\">↓</span>"
        elif l3_ppg > season_ppg:
            ppg_arrow = " <span style=\"color: #b3261e;\">↑</span>"

        last_n_html = f"""
      <div class="block">
        <h4>Last {actual_n} Trending</h4>
        <ul>
          <li>Penalties/Game: {l3_ppg:.1f} (Season: {season_ppg:.1f}){ppg_arrow}</li>
          <li>Offense: {l3_offense:.1f} / Defense: {l3_defense:.1f} / ST: {l3_st:.1f}</li>
        </ul>
      </div>
        """

    return f"""
    <div class="team-card">
      <h3>{team['display_name']}</h3>
      <div class="block">
        <h4>Totals</h4>
        <ul>
          <li>Penalties: {agg['total']} for {agg['yards']} yards</li>
          <li>Offense: {offense['count']} / {offense['yards']} yds</li>
          <li>Defense: {defense['count']} / {defense['yards']} yds</li>
          <li>CFBStats Rank: {_penalties_rank(team)}</li>
        </ul>
      </div>
      {last_n_html}
      <div class="block">
        <h4>Top Types (Count)</h4>
        <ul>{common_html}</ul>
      </div>
      <div class="block">
        <h4>Top Types (Yards)</h4>
        <ul>{yards_html}</ul>
      </div>
      <div class="block">
        <h4>Per-Quarter</h4>
        <ul>{quarter_html}</ul>
      </div>
    </div>
    """


def _team_md(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"*{team['display_name']}*\n- Penalties: N/A"
    games = _games(team)
    agg = _aggregate(team)
    top_common = agg["by_type_count"].most_common(1)
    worst = top_common[0][0] if top_common else "N/A"
    season_ppg = agg["total"] / max(len(games), 1)
    lines = [f"*{team['display_name']}*"]
    per_game_suffix = ""
    by_side_line = ""
    if _should_show_last_n(team):
        last_n = team.get("last_n", {}) or {}
        actual_n = last_n.get("actual_n", 0)
        l3_ppg = last_n.get("penalties_per_game", 0) or 0
        l3_offense = last_n.get("penalties_offense", 0) or 0
        l3_defense = last_n.get("penalties_defense", 0) or 0
        l3_st = last_n.get("penalties_special_teams", 0) or 0
        if abs(l3_ppg - season_ppg) >= 0.8:
            per_game_suffix = f" (L{actual_n}: {l3_ppg:.1f}/gm)"

        offense_count = agg["by_side"].get("offense", {}).get("count", 0) or 0
        defense_count = agg["by_side"].get("defense", {}).get("count", 0) or 0
        st_count = agg["by_side"].get("special_teams", {}).get("count", 0) or 0
        st_count = agg["by_side"].get("special teams", {}).get("count", st_count) or st_count
        season_offense = offense_count / max(len(games), 1)
        season_defense = defense_count / max(len(games), 1)
        season_st = st_count / max(len(games), 1)

        if (
            abs(l3_offense - season_offense) >= 0.8
            or abs(l3_defense - season_defense) >= 0.8
            or abs(l3_st - season_st) >= 0.8
        ):
            by_side_line = (
                f"- L{actual_n} By Side: Off {l3_offense:.1f}/gm, "
                f"Def {l3_defense:.1f}/gm, ST {l3_st:.1f}/gm"
            )

    lines.append(f"- Penalties per Game: {round(season_ppg,2)}{per_game_suffix}")
    if by_side_line:
        lines.append(by_side_line)
    lines.append(f"- Top Penalty Type: {worst}")
    return "\n".join(lines)


def build(team1: dict, team2: dict) -> dict:
    """Penalty breakdown section."""
    html_content = f"""
    <div class="section-grid">
      {_team_html(team1)}
      {_team_html(team2)}
    </div>
    """
    md_content = "\n\n".join([
        "*Penalties*",
        _team_md(team1),
        _team_md(team2),
    ])
    return {
        "title": "Penalties",
        "html_content": html_content,
        "md_content": md_content,
        "key": "penalties",
    }
