# College Football Coach Contract Database
# College Football Coach Contract Database


A comprehensive database of FBS college football head coach salaries, contracts, and buyout information.
A comprehensive database of FBS college football head coach salaries, contracts, and buyout information.


## Data Sources
## Data Sources


1. **USA Today Coach Salary Database** (Primary)
1. **USA Today Coach Salary Database** (Primary)
   - URL: https://sportsdata.usatoday.com/ncaa/salaries/football/coach
   - URL: https://sportsdata.usatoday.com/ncaa/salaries/football/coach
   - Coverage: All 136 FBS head coaches
   - Coverage: All 136 FBS head coaches
   - Updated: October 2025 (annual updates)
   - Updated: October 2025 (annual updates)
   - Data includes: Total pay, school pay, bonuses, buyouts
   - Data includes: Total pay, school pay, bonuses, buyouts


2. **State Sunshine Laws / FOIA**
2. **State Sunshine Laws / FOIA**
   - Public university coach contracts are public records
   - Public university coach contracts are public records
   - Can be requested through state FOIA processes
   - Can be requested through state FOIA processes
   - Private schools (Notre Dame, BYU, USC, etc.) don't disclose
   - Private schools (Notre Dame, BYU, USC, etc.) don't disclose


3. **Sports Media**
3. **Sports Media**
   - ESPN, The Athletic report contract details
   - ESPN, The Athletic report contract details
   - Often first to report new contracts/extensions
   - Often first to report new contracts/extensions
   - Good for breaking news, less comprehensive
   - Good for breaking news, less comprehensive


4. **University Athletic Departments**
4. **University Athletic Departments**
   - Official press releases for new hires
   - Official press releases for new hires
   - Contract terms often disclosed
   - Contract terms often disclosed


## Data Structure
## Data Structure


### Schema (`data/coaches.json`)
### Schema (`data/coaches.json`)
```json
```json
{
{
  "coach": "string - Coach's full name",
  "coach": "string - Coach's full name",
  "school": "string - University name",
  "school": "string - University name",
  "conference": "string - Conference abbreviation",
  "conference": "string - Conference abbreviation",
  "sport": "string - Always 'football' for now",
  "sport": "string - Always 'football' for now",
  "totalPay": "number - Total annual compensation (null if undisclosed)",
  "totalPay": "number - Total annual compensation (null if undisclosed)",
  "schoolPay": "number - Base school salary",
  "schoolPay": "number - Base school salary",
  "maxBonus": "number - Maximum achievable bonus",
  "maxBonus": "number - Maximum achievable bonus",
  "bonusesPaid": "number - Bonuses paid in 2024-25",
  "bonusesPaid": "number - Bonuses paid in 2024-25",
  "buyout": "number - School buyout as of Dec 1, 2025",
  "buyout": "number - School buyout as of Dec 1, 2025",
  "contractTerm": "number - Total years (when available)",
  "contractTerm": "number - Total years (when available)",
  "contractEndYear": "number - Year contract expires (when available)",
  "contractEndYear": "number - Year contract expires (when available)",
  "dataSource": "string - Source of data",
  "dataSource": "string - Source of data",
  "lastUpdated": "string - ISO date of last update"
  "lastUpdated": "string - ISO date of last update"
}
}
```
```


### Conference Abbreviations
### Conference Abbreviations
- `SEC` - Southeastern Conference
- `SEC` - Southeastern Conference
- `Big 10` - Big Ten Conference
- `Big 10` - Big Ten Conference
- `Big 12` - Big 12 Conference
- `Big 12` - Big 12 Conference
- `ACC` - Atlantic Coast Conference
- `ACC` - Atlantic Coast Conference
- `Pac-12` - Pac-12 Conference (2 schools remaining)
- `Pac-12` - Pac-12 Conference (2 schools remaining)
- `MWC` - Mountain West Conference
- `MWC` - Mountain West Conference
- `AMER` - American Athletic Conference
- `AMER` - American Athletic Conference
- `SBC` - Sun Belt Conference
- `SBC` - Sun Belt Conference
- `MAC` - Mid-American Conference
- `MAC` - Mid-American Conference
- `CUSA` - Conference USA
- `CUSA` - Conference USA
- `IndFBS` - FBS Independents
- `IndFBS` - FBS Independents


## Files
## Files


```
```
coach-database/
coach-database/
├── README.md
├── README.md
├── data/
├── data/
│   ├── coaches.json          # Full dataset
│   ├── coaches.json          # Full dataset
│   ├── power_four.json       # SEC, Big 10, Big 12, ACC only
│   ├── power_four.json       # SEC, Big 10, Big 12, ACC only
│   └── by_conference/        # Split by conference
│   └── by_conference/        # Split by conference
├── scripts/
├── scripts/
│   ├── scrape_usatoday.py    # Fetch from USA Today
│   ├── scrape_usatoday.py    # Fetch from USA Today
│   ├── update_database.py    # Update and merge data
│   ├── update_database.py    # Update and merge data
│   └── analyze.py            # Analysis utilities
│   └── analyze.py            # Analysis utilities
└── historical/
└── historical/
    └── 2025-10-08.json       # Snapshots by date
    └── 2025-10-08.json       # Snapshots by date
```
```


## Usage
## Usage


### Fetch latest data
### Fetch latest data
```bash
```bash
python scripts/scrape_usatoday.py
python scripts/scrape_usatoday.py
```
```


### Pull state salary data (Phase 2)
### Pull state salary data (Phase 2)
```bash
```bash
python scripts/state_salary.py download --state TX
python scripts/state_salary.py download --state TX
python scripts/state_salary.py download --state FL
python scripts/state_salary.py download --state FL
python scripts/state_salary.py match --roster data/staff_test.json --states TX,FL
python scripts/state_salary.py match --roster data/staff_test.json --states TX,FL
```
```


Notes:
Notes:
- CA/OH/MI/PA sources currently require manual CSV downloads (see `scripts/state_salary.py`).
- CA/OH/MI/PA sources currently require manual CSV downloads (see `scripts/state_salary.py`).


### Track coaching changes
### Track coaching changes
```bash
```bash
python scripts/track_changes.py
python scripts/track_changes.py
```
```


The tracker runs weekly during the December–February carousel window and monthly otherwise. Use `--force` to bypass the schedule or `--skip-scrape` to diff existing snapshots.
The tracker runs weekly during the December–February carousel window and monthly otherwise. Use `--force` to bypass the schedule or `--skip-scrape` to diff existing snapshots.


### Run analysis
### Run analysis
```bash
```bash
python scripts/analyze.py --top 25 --by conference
python scripts/analyze.py --top 25 --by conference
```
```


### Enrich with media-reported assistant salaries
### Enrich with media-reported assistant salaries
```bash
```bash
python scripts/media_enrichment.py --staff data/staff_test.json --output data/media_reports.json --allow-edu
python scripts/media_enrichment.py --staff data/staff_test.json --output data/media_reports.json --allow-edu
```
```



## Staff Updates

Quickly update or verify staff lists in the database using the new script:

```bash
python scripts/update_staff.py --school <slug> --url <staff_page_url>
```

Or with local text:

```bash
python scripts/update_staff.py --school <slug> --text staff.txt
```

Options:
- `--year 2025` (default is 2025)
- `--ai-parse` Use Claude AI to extract names/positions if parsing fails (`ANTHROPIC_API_KEY` required)
- `--dry-run` Preview DB operations without writing
- `--verify` Fetch and print current staff from the production Fly.io API

Example verification (for a single school):

```bash
python scripts/update_staff.py --school ohio-state --verify
```

If blocked by Cloudflare on `--url`, copy/paste staff text to a file and use `--text`.

## Deployment

Set the following environment variables for the API:

- `WEBHOOK_API_KEY` - required for `POST /api/webhooks/staff-update` authentication

Local dev key generation:
```bash
openssl rand -hex 32
```

An example `.env.example` file is included with a generated local dev key.

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
