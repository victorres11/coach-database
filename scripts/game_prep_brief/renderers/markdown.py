from __future__ import annotations

from datetime import datetime


def _order_sections(sections: list[dict]) -> list[dict]:
    keys = [s.get("key") for s in sections]
    if "overview" in keys:
        ordered = [s for s in sections if s.get("key") == "overview"]
        ordered += [s for s in sections if s.get("key") != "overview"]
        return ordered
    return sections


def render(sections: list[dict], team1: dict, team2: dict, week: int | None, season: int) -> str:
    """Render condensed Telegram markdown."""
    now = datetime.now().strftime("%b %d, %Y %H:%M")
    week_str = f"Week {week} | " if week else ""

    header = [
        "🏈 *GAME PREP BRIEF v2*",
        f"📅 {week_str}{season} Season",
        f"*{team1['display_name']} vs {team2['display_name']}*",
        "",
    ]

    parts = []
    for s in _order_sections(sections):
        parts.append(s.get("md_content", ""))

    footer = [
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📡 *Data Sources*",
        "• Coach DB (coaching staff + play callers)",
        "• PBP Analysis (cfbstats + play-by-play aggregates)",
        f"• Generated: {now}",
    ]

    return "\n".join(header) + "\n\n".join(parts) + "\n" + "\n".join(footer)
