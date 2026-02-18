from __future__ import annotations

from ..renderers.svg import comparison_bars

CATEGORIES = [
    "scoring_offense",
    "scoring_defense",
    "total_offense",
    "total_defense",
    "rushing_offense",
    "rushing_defense",
    "passing_offense",
    "passing_defense",
    "scoring_margin",
    "turnover_margin",
    "red_zone",
    "third_down",
    "fourth_down",
    "explosives",
    "penalties",
    "time_of_possession",
    "sacks_offense",
    "sacks_defense",
]

LABELS = {
    "scoring_offense": "Scoring Offense",
    "scoring_defense": "Scoring Defense",
    "total_offense": "Total Offense",
    "total_defense": "Total Defense",
    "rushing_offense": "Rushing Offense",
    "rushing_defense": "Rushing Defense",
    "passing_offense": "Passing Offense",
    "passing_defense": "Passing Defense",
    "scoring_margin": "Scoring Margin",
    "turnover_margin": "Turnover Margin",
    "red_zone": "Red Zone TD%",
    "third_down": "3rd Down %",
    "fourth_down": "4th Down %",
    "explosives": "Explosive Plays",
    "penalties": "Penalties",
    "time_of_possession": "Time of Possession",
    "sacks_offense": "Sacks Allowed",
    "sacks_defense": "Sacks",
}


def _rank(rankings: dict, key: str) -> dict:
    r = rankings.get(key, {}) if rankings else {}
    return {
        "value": r.get("value"),
        "rank": r.get("rank"),
    }


def _fmt(rank_data: dict) -> str:
    val = rank_data.get("value")
    rnk = rank_data.get("rank")
    if val is None and rnk is None:
        return "N/A"
    if val is not None and rnk is not None:
        return f"{val} (#{rnk})"
    return str(val) if val is not None else "N/A"


def _table_html(team1: dict, team2: dict, scope: str) -> str:
    r1 = (team1.get("pbp_entry") or {}).get("cfbstats", {}).get("rankings", {}).get(scope, {})
    r2 = (team2.get("pbp_entry") or {}).get("cfbstats", {}).get("rankings", {}).get(scope, {})
    rows = []
    for key in CATEGORIES:
        rows.append(
            f"<tr><td>{LABELS.get(key, key)}</td><td>{_fmt(_rank(r1, key))}</td><td>{_fmt(_rank(r2, key))}</td></tr>"
        )
    rows_html = "".join(rows)
    return f"""
    <h4>{scope.title()} Rankings</h4>
    <table class="rankings-table">
      <tr><th>Category</th><th>{team1['display_name']}</th><th>{team2['display_name']}</th></tr>
      {rows_html}
    </table>
    """


def _top_bottom_md(team: dict) -> str:
    rankings = (team.get("pbp_entry") or {}).get("cfbstats", {}).get("rankings", {}).get("all", {})
    parsed = []
    for key in CATEGORIES:
        r = rankings.get(key, {})
        rank = r.get("rank")
        if rank is None:
            continue
        parsed.append((key, rank, r.get("value")))

    top = sorted(parsed, key=lambda x: x[1])[:5]
    bottom = sorted(parsed, key=lambda x: x[1], reverse=True)[:3]

    lines = [f"*{team['display_name']}*"]
    if top:
        lines.append("- Top 10s:")
        for key, rank, value in top:
            if rank <= 10:
                lines.append(f"  • {LABELS.get(key, key)}: {value} (#{rank})")
    if bottom:
        lines.append("- Bottom 3:")
        for key, rank, value in bottom:
            lines.append(f"  • {LABELS.get(key, key)}: {value} (#{rank})")
    return "\n".join(lines)


def _metric_svg(team1: dict, team2: dict) -> str:
    color1 = team1.get("stats", {}).get("color", "#2563eb")
    color2 = team2.get("stats", {}).get("color", "#dc2626")
    rankings1 = (team1.get("pbp_entry") or {}).get("cfbstats", {}).get("rankings", {}).get("all", {})
    rankings2 = (team2.get("pbp_entry") or {}).get("cfbstats", {}).get("rankings", {}).get("all", {})

    def val(rankings: dict, key: str) -> float:
        v = rankings.get(key, {}).get("value")
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    blocks = []
    for key in ["scoring_offense", "scoring_defense", "total_offense", "total_defense"]:
        blocks.append(
            comparison_bars(
                LABELS.get(key, key),
                val(rankings1, key),
                val(rankings2, key),
                color1,
                color2,
            )
        )
    return "".join(f"<div class=\"metric-compare\">{b}</div>" for b in blocks)


def build(team1: dict, team2: dict) -> dict:
    """Full 18-category rankings section with all/conf/nonconf splits."""
    html_content = (
        f"{_metric_svg(team1, team2)}"
        f"{_table_html(team1, team2, 'all')}"
        f"{_table_html(team1, team2, 'conf')}"
        f"{_table_html(team1, team2, 'nonconf')}"
    )

    md_content = "\n\n".join([
        "*Rankings Highlights*",
        _top_bottom_md(team1),
        _top_bottom_md(team2),
    ])

    return {
        "title": "Rankings",
        "html_content": html_content,
        "md_content": md_content,
        "key": "rankings",
    }
