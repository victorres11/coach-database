# Salary Sources (Assistant Coach / Staff)

This doc tracks *accessible* public salary databases we can scrape without GovSalaries.com (Cloudflare-blocked).

## Source Types

### `osu_hr` (Ohio State HR Salary Search)
- Base: `https://apps.hr.osu.edu/salaries/Home/Salaries`
- Access: Public, simple HTTP GET
- Query: `costCenter=CC12637 Athletics | Football`
- Output: HTML table (`Preferred Name`, `Title`, `Salary / Hourly Rate`, `FTE`, etc.)
- Notes:
  - Names appear as `Last, First`
  - Titles are HR position titles (often generic like `Assistant Coach 2`)
  - Includes non-coaching roles; filter by `Title` containing `Coach`

### `transparent_ca` (Transparent California)
- Base: `https://transparentcalifornia.com/salaries/search/`
- Access: Public, simple HTTP GET
- Query: `a=university-of-california&q={name-or-keyword}`
- Output: HTML table with links to year/person pages
- Notes:
  - UC data is under the agency slug `university-of-california` (campus not always explicit)
  - Best strategy: search per-coach name (from roster) and match exact name + job title contains `Coach`
  - Provides year + pay breakdown (`Regular pay`, `Other pay`, `Total pay`)

### `unc_system` (UNC Salary Information Database)
- Base: `https://uncdm.northcarolina.edu/salaries/`
- Access: Public, requires accepting terms (`POST index.php action=agree`) to establish session
- Query: `POST ajax.php` with `type=json`, `campus`, filters (`department`, `position`, etc.)
- Output: JSON payload with `totalRecords`, `names`, `data`, `count`
- Notes:
  - Campus codes include `UNC-CH` (UNC) and `NCSU` (NC State)
  - Department fields often include `...Football...`; filter locally to football-related departments and coaching titles

## Phase 1 Mapping (Initial 3–4 teams)

These are the first schools wired into `salary_sources` (seeded in `db/coaches.db` and used by `scripts/scrape_salaries.py`).

| School | Conference | Source Type | Status | Notes |
|---|---|---:|---:|---|
| Ohio State | Big Ten | `osu_hr` | ✅ working | Football cost center `CC12637` |
| UCLA | Big Ten | `transparent_ca` | ✅ working | UC agency; scrape per-coach |
| California | ACC | `transparent_ca` | ✅ working | UC agency; scrape per-coach |
| North Carolina | ACC | `unc_system` | ✅ working | Campus `UNC-CH`; filter football depts |
| NC State | ACC | `unc_system` | ✅ working | Campus `NCSU`; dept `Football` works |

## Next Schools to Research (Backlog)

### Big Ten
- Penn State (PA), Michigan (MI), Michigan State (MI), Wisconsin (WI), Minnesota (MN), Iowa (IA), Nebraska (NE), Purdue (IN), Indiana (IN), Illinois (IL), Northwestern (IL), Rutgers (NJ), Maryland (MD), Oregon (OR), Washington (WA)
- USC (private; likely no public DB)

### SEC
- Texas (TX), Texas A&M (TX), Georgia (GA), Alabama (AL), Florida (FL), LSU (LA), Auburn (AL), Tennessee (TN), Kentucky (KY), South Carolina (SC), Missouri (MO), Arkansas (AR), Ole Miss (MS), Mississippi State (MS), Oklahoma (OK)
- Vanderbilt (private; likely no public DB)

### ACC
- Duke (private), Virginia (VA), Virginia Tech (VA), Clemson (SC), Florida State (FL), Miami (private), Georgia Tech (GA), Louisville (KY), Pittsburgh (PA), Syracuse (NY), Boston College (private)
- Stanford (private), SMU (private)

### Big 12
- Arizona, Utah, Colorado, Kansas, Kansas State, Iowa State, Texas Tech, Oklahoma State, West Virginia, Cincinnati, UCF, Houston
- Arizona State (GovSalaries historically; likely needs fallback)
- BYU/Baylor/TCU (private)

