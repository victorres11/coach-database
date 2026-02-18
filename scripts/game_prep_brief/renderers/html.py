from __future__ import annotations

from datetime import datetime

SECTION_ORDER = [
    "overview",
    "rankings",
    "explosives",
    "zones",
    "turnovers",
    "middle8",
    "situational",
    "special_teams",
    "penalties",
]


def _order_sections(sections: list[dict]) -> list[dict]:
    by_key = {s.get("key"): s for s in sections if s.get("key")}
    if not by_key:
        return sections
    ordered = []
    for key in SECTION_ORDER:
        if key in by_key:
            ordered.append(by_key[key])
    for s in sections:
        if s not in ordered:
            ordered.append(s)
    return ordered


def render(sections: list[dict], team1: dict, team2: dict, week: int | None, season: int) -> str:
    """Render full HTML with page breaks between sections."""
    now = datetime.now().strftime("%B %d, %Y %H:%M")
    week_str = f"Week {week} · " if week else ""
    t1_color = team1.get("stats", {}).get("color", "#2563eb")
    t2_color = team2.get("stats", {}).get("color", "#dc2626")

    section_html = []
    for s in _order_sections(sections):
        section_html.append(
            f"""
            <section class=\"section page-break\" id=\"{s.get('key','section')}\">
              <div class=\"section-header\">{s.get('title','Section')}</div>
              <div class=\"section-body\">{s.get('html_content','')}</div>
            </section>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Game Prep Brief v2</title>
  <style>
    :root {{
      --ink: #0f172a;
      --muted: #475569;
      --border: #e2e8f0;
      --bg: #f8fafc;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Helvetica Neue", Arial, sans-serif;
      color: var(--ink);
      background: var(--bg);
      padding: 24px;
    }}
    .header {{
      background: #0b1220;
      color: white;
      padding: 20px 24px;
      border-radius: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.15);
      margin-bottom: 18px;
      position: relative;
      overflow: hidden;
    }}
    .header::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(120deg, {t1_color}55, {t2_color}55);
      opacity: 0.7;
      pointer-events: none;
    }}
    .header-content {{ position: relative; z-index: 1; }}
    .header h1 {{ margin: 0; font-size: 22px; letter-spacing: 1.5px; text-transform: uppercase; }}
    .header .subtitle {{ margin-top: 6px; font-size: 13px; color: #d1d5db; }}

    .section {{
      background: white;
      border-radius: 12px;
      padding: 18px 20px 22px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
      margin-bottom: 18px;
    }}
    .section-header {{
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: var(--muted);
      border-bottom: 2px solid var(--border);
      padding-bottom: 6px;
      margin-bottom: 12px;
    }}
    .section-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .team-card {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 14px;
      background: #fbfdff;
    }}
    .team-card h3 {{ margin: 0 0 8px; font-size: 15px; text-transform: uppercase; letter-spacing: 1px; }}
    .block h4 {{ margin: 10px 0 6px; font-size: 12px; text-transform: uppercase; color: var(--muted); }}
    .block ul {{ margin: 0; padding-left: 16px; }}
    .block li {{ margin: 2px 0; font-size: 12px; }}
    .section-note {{ margin-top: 10px; font-size: 11px; color: #64748b; }}

    .rankings-table {{ width: 100%; border-collapse: collapse; margin-bottom: 12px; }}
    .rankings-table th, .rankings-table td {{ border-bottom: 1px solid var(--border); padding: 6px 8px; font-size: 12px; }}
    .rankings-table th {{ text-transform: uppercase; font-size: 11px; color: #64748b; text-align: left; }}

    .metric-compare {{ margin: 8px 0 12px; }}

    .page-break {{ page-break-before: always; }}
    .page-break:first-child {{ page-break-before: auto; }}

    @media print {{
      body {{ background: white; padding: 12px; }}
      .section {{ box-shadow: none; border: 1px solid #ddd; }}
      .header {{ box-shadow: none; }}
      @page {{ margin: 1cm; }}
    }}
    @media (max-width: 900px) {{
      .section-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header class="header">
    <div class="header-content">
      <h1>Game Prep Brief v2</h1>
      <div class="subtitle">{week_str}{season} Season · {team1['display_name']} vs {team2['display_name']} · Generated {now}</div>
    </div>
  </header>

  {"".join(section_html)}
</body>
</html>"""
