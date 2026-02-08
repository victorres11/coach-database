# Season Transition Runbook (Year-over-Year)

This project stores coaching data per-season using the `coaches.year` and `salaries.year` columns. A new season transition means *adding* rows for the new year (never overwriting prior years).

## Before the season (recommended: Week 1 snapshot)

1. Scrape CollegePressBox staff for the target year:
   - `python scripts/scrape_collegepressbox.py --year 2026 --update-db`
2. Scrape salary sources for the same year (optional / depends on availability):
   - `python scripts/scrape_salaries.py run --year 2026`
   - `python scripts/scrape_usatoday.py --year 2026 --update-db`
3. Review year-over-year diff:
   - `GET /api/changes?from=2025&to=2026`
4. Spot-check major programs:
   - `GET /api/schools/alabama/staff?year=2026`
5. Deploy DB with both years retained.

## During the carousel (typically Nov–Feb)

- Re-run scrapes with the same `--year` as hires/firings occur.
- Use `GET /api/changes?from=2025&to=2026` to detect staff turnover.

## Useful API endpoints

- Years:
  - `GET /api/years`
- Year-filtered coaches:
  - `GET /api/coaches?year=2026`
  - `GET /api/search?q=smart&year=2026`
- School staff (historical):
  - `GET /api/schools/{slug}/staff?year=2026`
- Coach history:
  - `GET /api/coaches/{id}/history`
- Year-over-year diff:
  - `GET /api/changes?from=2025&to=2026`

