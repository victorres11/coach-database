from __future__ import annotations


def _games(team: dict) -> list[dict]:
    pbp = team.get("pbp_entry") or {}
    return pbp.get("games", [])


def _sum(games: list[dict], key: str) -> int:
    return sum(g.get(key, 0) or 0 for g in games)


def _should_show_last_n(team: dict) -> bool:
    last_n = team.get("last_n", {}) or {}
    return last_n.get("actual_n", 0) >= last_n.get("required_n", 3)


def _trend_arrow(current, l3, higher_is_better: bool = True) -> str:
    if current is None or l3 is None or current == l3:
        return ""
    if higher_is_better:
        is_up = l3 > current
    else:
        is_up = l3 < current
    color = "#1b7f3a" if is_up else "#b3261e"
    arrow = "↑" if is_up else "↓"
    return f" <span style=\"color: {color};\">{arrow}</span>"


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
    last_n = team.get("last_n", {}) or {}
    show_last_n = _should_show_last_n(team)
    l3_rz_trips = last_n.get("rz_trips")
    l3_rz_tds = last_n.get("rz_tds")
    l3_rz_td_pct = last_n.get("rz_td_pct")
    l3_trz_trips = last_n.get("tight_rz_trips")
    l3_trz_tds = last_n.get("tight_rz_tds")
    l3_trz_td_pct = last_n.get("tight_rz_td_pct")
    l3_gz_trips = last_n.get("green_zone_trips")
    l3_gz_tds = last_n.get("green_zone_tds")
    l3_gz_success = None
    if l3_gz_trips is not None and l3_gz_tds is not None:
        l3_gz_success = _rate(l3_gz_tds, l3_gz_trips)

    def _last_n_compare(current, l3_value, suffix: str = "", higher_is_better: bool = True, show_arrow: bool = False) -> str:
        if not show_last_n or l3_value is None:
            return ""
        arrow = _trend_arrow(current, l3_value, higher_is_better) if show_arrow else ""
        return f" →(L3) {l3_value}{suffix}{arrow}"

    return f"""
    <div class="team-card">
      <h3>{team['display_name']}</h3>
      <div class="block">
        <h4>Red Zone</h4>
        <ul>
          <li>Trips: {stats['rz_trips']}{_last_n_compare(stats['rz_trips'], l3_rz_trips)}</li>
          <li>TDs: {stats['rz_tds']}{_last_n_compare(stats['rz_tds'], l3_rz_tds)}</li>
          <li>FGs: {stats['rz_fgs']}</li>
          <li>TD%: {stats['rz_td_pct']}%{_last_n_compare(stats['rz_td_pct'], l3_rz_td_pct, suffix="%", show_arrow=True)}</li>
          <li>Efficiency: {stats['rz_eff']}%</li>
          <li>CFBStats Rank: {rz_rank}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Tight Red Zone (Inside 10)</h4>
        <ul>
          <li>Trips: {stats['trz_trips']}{_last_n_compare(stats['trz_trips'], l3_trz_trips)}</li>
          <li>TDs: {stats['trz_tds']}{_last_n_compare(stats['trz_tds'], l3_trz_tds)}</li>
          <li>FGs: {stats['trz_fgs']}</li>
          <li>TD%: {stats['trz_td_pct']}%{_last_n_compare(stats['trz_td_pct'], l3_trz_td_pct, suffix="%", show_arrow=True)}</li>
        </ul>
      </div>
      <div class="block">
        <h4>Green Zone (Inside 40)</h4>
        <ul>
          <li>Trips: {stats['gz_trips']}{_last_n_compare(stats['gz_trips'], l3_gz_trips)}</li>
          <li>TDs: {stats['gz_tds']}{_last_n_compare(stats['gz_tds'], l3_gz_tds)}</li>
          <li>FGs: {stats['gz_fgs']}</li>
          <li>Success: {stats['gz_success']}%{_last_n_compare(stats['gz_success'], l3_gz_success, suffix="%", show_arrow=True)}</li>
        </ul>
      </div>
    </div>
    """


def _team_md(team: dict) -> str:
    if not team.get("has_pbp"):
        return f"*{team['display_name']}*\n- Red Zone: N/A"
    stats = _team_zone_stats(team)
    rz_note = ""
    trz_note = ""
    gz_note = ""
    if _should_show_last_n(team):
        last_n = team.get("last_n", {}) or {}
        actual_n = last_n.get("actual_n", 0)
        l3_rz_td_pct = last_n.get("rz_td_pct")
        l3_trz_td_pct = last_n.get("tight_rz_td_pct")
        l3_gz_trips = last_n.get("green_zone_trips")
        l3_gz_tds = last_n.get("green_zone_tds")
        l3_gz_success = None
        if l3_gz_trips is not None and l3_gz_tds is not None:
            l3_gz_success = _rate(l3_gz_tds, l3_gz_trips)

        if l3_rz_td_pct is not None and abs(l3_rz_td_pct - stats["rz_td_pct"]) >= 8:
            rz_note = f" (L{actual_n}: {l3_rz_td_pct}%)"
        if l3_trz_td_pct is not None and abs(l3_trz_td_pct - stats["trz_td_pct"]) >= 8:
            trz_note = f" (L{actual_n}: {l3_trz_td_pct}%)"
        if l3_gz_success is not None and abs(l3_gz_success - stats["gz_success"]) >= 8:
            gz_note = f" (L{actual_n}: {l3_gz_success}%)"
    return "\n".join([
        f"*{team['display_name']}*",
        f"- Red Zone TD%: {stats['rz_td_pct']}%{rz_note}",
        f"- Tight RZ TD%: {stats['trz_td_pct']}%{trz_note}",
        f"- Green Zone Success: {stats['gz_success']}%{gz_note}",
    ])


def build(team1: dict, team2: dict) -> dict:
    """Red zone, tight red zone, green zone section."""
    t1_stats = _team_zone_stats(team1) if team1.get("has_pbp") else {"rz_td_pct": 0}
    t2_stats = _team_zone_stats(team2) if team2.get("has_pbp") else {"rz_td_pct": 0}
    t1_name = team1.get("display_name", "Team 1")
    t2_name = team2.get("display_name", "Team 2")
    t1_rz = t1_stats.get("rz_td_pct", 0)
    t2_rz = t2_stats.get("rz_td_pct", 0)

    html_content = f"""
    <div class="metric-compare"><p>{t1_name}: {t1_rz}% | {t2_name}: {t2_rz}% Red Zone TD%</p></div>
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
