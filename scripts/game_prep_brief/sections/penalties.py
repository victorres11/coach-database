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


def _team_html(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"<div class=\"team-card\"><h3>{team['display_name']}</h3><p><em>No PBP data.</em></p></div>"
    agg = _aggregate(team)
    top_common = agg["by_type_count"].most_common(3)
    top_yards = agg["by_type_yards"].most_common(3)

    common_html = "".join(f"<li>{k}: {v}</li>" for k, v in top_common) or "<li>N/A</li>"
    yards_html = "".join(f"<li>{k}: {v} yds</li>" for k, v in top_yards) or "<li>N/A</li>"
    quarter_html = "".join(f"<li>Q{q}: {c}</li>" for q, c in sorted(agg["by_quarter"].items())) or "<li>N/A</li>"

    offense = agg["by_side"].get("offense", {"count": 0, "yards": 0})
    defense = agg["by_side"].get("defense", {"count": 0, "yards": 0})

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
    agg = _aggregate(team)
    top_common = agg["by_type_count"].most_common(1)
    worst = top_common[0][0] if top_common else "N/A"
    return "\n".join([
        f"*{team['display_name']}*",
        f"- Penalties per Game: {round(agg['total'] / max(len(_games(team)),1),2)}",
        f"- Top Penalty Type: {worst}",
    ])


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
