# Coach DB (Shared Data Service)

Single source of truth for college football coaching staff + salary data, backed by SQLite and served via a FastAPI REST API.

- Local DB: `db/coaches.db`
- API service: `api/main.py`
- Production (example): `https://coach-database-api.fly.dev`

## Data Sources

1. **USA Today Coach Salary Database** (Primary)
   - URL: https://sportsdata.usatoday.com/ncaa/salaries/football/coach
   - Coverage: All 136 FBS head coaches
   - Updated: October 2025 (annual updates)
   - Data includes: Total pay, school pay, bonuses, buyouts

2. **State Sunshine Laws / FOIA**
   - Public university coach contracts are public records
   - Can be requested through state FOIA processes
   - Private schools (Notre Dame, BYU, USC, etc.) don't disclose

3. **Sports Media**
   - ESPN, The Athletic report contract details
   - Often first to report new contracts/extensions
   - Good for breaking news, less comprehensive

4. **University Athletic Departments**
   - Official press releases for new hires
   - Contract terms often disclosed

## Data Structure

### SQLite Schema
See `db/schema.sql` for the canonical schema:
- `conferences`, `schools`, `coaches`, `salaries`, `coaching_trees`, `salary_sources`

Legacy JSON snapshots still exist under `data/` and `historical/` for scraping/diffing, but the DB + API are the intended integration points.

### Conference Abbreviations
- `SEC` - Southeastern Conference
- `Big 10` - Big Ten Conference
- `Big 12` - Big 12 Conference
- `ACC` - Atlantic Coast Conference
- `Pac-12` - Pac-12 Conference (2 schools remaining)
- `MWC` - Mountain West Conference
- `AMER` - American Athletic Conference
- `SBC` - Sun Belt Conference
- `MAC` - Mid-American Conference
- `CUSA` - Conference USA
- `IndFBS` - FBS Independents

## Files

```
coach-database/
├── README.md
├── db/
│   ├── coaches.db            # SQLite database (source of truth)
│   ├── schema.sql            # DB schema
│   └── migrate.py            # JSON → SQLite migration
├── api/
│   ├── main.py               # FastAPI service
│   └── requirements.txt
├── scripts/
│   ├── scrape_usatoday.py    # Fetch USA Today salaries (writes JSON snapshots)
│   ├── track_changes.py      # Diff snapshots (can build from SQLite)
│   └── analyze.py            # Analysis (SQLite-first)
└── historical/
    └── 2025-10-08.json       # Snapshots by date
```

## Usage

### Build/refresh the SQLite DB
```bash
python db/migrate.py
```

### Run the API locally
```bash
uvicorn api.main:app --host 127.0.0.1 --port 8100
```

Optional API key auth:
- Set `COACHDB_API_KEY` to require `X-API-Key` (or `Authorization: Bearer ...`) on data endpoints.

### Query via API (consumer repos)
```bash
curl "http://127.0.0.1:8100/coaches?head_only=true&limit=25"
curl "http://127.0.0.1:8100/schools?q=georgia"
curl "http://127.0.0.1:8100/search?q=kirby"
```

Python client (optional):
```bash
pip install -e ./client
```

YR call-sheet helper (maps common offensive staff roles):
```bash
curl "http://127.0.0.1:8100/yr/georgia/coaches?format=text"
```

### Track changes (SQLite-first)
```bash
python scripts/track_changes.py --source db --force
```

### Run analysis (SQLite-first)
```bash
python scripts/analyze.py --source db --top 25
```

## Key Statistics (2025 Season)

- **Highest Paid**: Kirby Smart (Georgia) - $13,282,580
- **Largest Buyout**: Kirby Smart (Georgia) - $105,107,583
- **Average Power Four Salary**: ~$6.5M
- **Total FBS Coaches**: 136

## Notes

- Private schools (Notre Dame, USC, Miami, SMU, etc.) don't disclose salaries
- `*` in USA Today data indicates estimated/reported amounts
- Buyout figures assume termination without cause on Dec 1, 2025
- Contract terms/end years not included in USA Today data (requires FOIA)

## Future Enhancements

1. Add contract term/end year data via FOIA requests
2. Historical salary tracking over time
3. Assistant coach salaries
4. Basketball coach salaries
5. Buyout clause details (mitigation requirements, payment schedules)

## License

Data sourced from publicly available information. USA Today methodology available at:
https://www.usatoday.com/story/sports/ncaaf/2025/10/05/2025-ncaa-football-coach-salaries-methodology/86526058007/
