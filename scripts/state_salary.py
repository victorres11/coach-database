#!/usr/bin/env python3
"""
Fetch and match public state salary records to Phase 1 coaching staff rosters.

Usage:
  python scripts/state_salary.py download --state TX --force
  python scripts/state_salary.py match --roster data/staff_test.json --states TX,FL

This script keeps the ingestion minimal and configurable so new states can be
added without refactoring the matching logic.
"""

import argparse
import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

TARGET_STATES = ["TX", "FL", "OH", "CA", "MI", "PA"]

STATE_SOURCES = {
    "TX": {
        "name": "Texas Tribune - State of Texas Salaries",
        "download_url": "https://s3.amazonaws.com/raw.texastribune.org/state_of_texas/salaries/02_non_duplicated_employees/2026-01-01.csv",
        "format": "csv",
        "fiscal_year": 2026,
        "parser": "texas_tribune",
    },
    "FL": {
        "name": "Florida Has a Right to Know - State Employee Salaries",
        "download_url": "https://salaries.myflorida.com/?action=index&controller=salaries&format=csv",
        "format": "csv",
        "fiscal_year": 2025,
        "parser": "florida",
    },
    # Cloudflare blocks automated downloads for CA; keep the URL for manual fetch.
    "CA": {
        "name": "California State Controller - Government Compensation in CA",
        "download_url": "https://gcc.sco.ca.gov/RawExport/2024_CaliforniaStateUniversity.zip",
        "format": "zip_csv",
        "fiscal_year": 2024,
        "parser": "california_gcc",
        "manual": True,
    },
    # Placeholder sources for manual ingestion until stable public CSVs are added.
    "OH": {
        "name": "Ohio state employee salary data",
        "download_url": None,
        "format": "csv",
        "parser": "manual",
        "manual": True,
    },
    "MI": {
        "name": "Michigan state employee salary data",
        "download_url": None,
        "format": "csv",
        "parser": "manual",
        "manual": True,
    },
    "PA": {
        "name": "Pennsylvania state employee salary data",
        "download_url": None,
        "format": "csv",
        "parser": "manual",
        "manual": True,
    },
}

SCHOOL_STATE = {
    # Texas
    "Texas": "TX",
    "Texas A&M": "TX",
    "Texas Tech": "TX",
    "Houston": "TX",
    "UTSA": "TX",
    # Florida
    "Florida": "FL",
    "Florida State": "FL",
    "UCF": "FL",
    "USF": "FL",
    "FAU": "FL",
    "FIU": "FL",
    "Miami": "FL",
    # Ohio
    "Ohio State": "OH",
    "Cincinnati": "OH",
    "Ohio": "OH",
    "Toledo": "OH",
    "Akron": "OH",
    "Miami (OH)": "OH",
    # California
    "USC": "CA",
    "UCLA": "CA",
    "California": "CA",
    "Cal": "CA",
    "San Diego State": "CA",
    "Fresno State": "CA",
    "San Jose State": "CA",
    # Michigan
    "Michigan": "MI",
    "Michigan State": "MI",
    "Central Michigan": "MI",
    "Eastern Michigan": "MI",
    "Western Michigan": "MI",
    # Pennsylvania
    "Penn State": "PA",
    "Pittsburgh": "PA",
    "Pitt": "PA",
    "Temple": "PA",
}

SCHOOL_ALIASES = {
    "Cal": "California",
    "Pitt": "Pittsburgh",
}

SCHOOL_EMPLOYER_KEYWORDS = {
    "Texas": ["UNIVERSITY OF TEXAS", "UT AUSTIN"],
    "Texas A&M": ["TEXAS A&M"],
    "Texas Tech": ["TEXAS TECH"],
    "Houston": ["UNIVERSITY OF HOUSTON"],
    "UTSA": ["UT SAN ANTONIO", "UNIVERSITY OF TEXAS AT SAN ANTONIO"],
    "Florida": ["UNIVERSITY OF FLORIDA"],
    "Florida State": ["FLORIDA STATE"],
    "UCF": ["CENTRAL FLORIDA", "UCF"],
    "USF": ["SOUTH FLORIDA", "USF"],
    "FAU": ["FLORIDA ATLANTIC"],
    "FIU": ["FLORIDA INTERNATIONAL", "FIU"],
    "Miami": ["MIAMI"],
    "Ohio State": ["OHIO STATE"],
    "Cincinnati": ["CINCINNATI"],
    "Ohio": ["OHIO UNIVERSITY"],
    "Toledo": ["TOLEDO"],
    "Akron": ["AKRON"],
    "Miami (OH)": ["MIAMI UNIVERSITY"],
    "UCLA": ["UCLA", "CALIFORNIA, LOS ANGELES"],
    "California": ["BERKELEY", "CALIFORNIA"],
    "San Diego State": ["SAN DIEGO STATE"],
    "Fresno State": ["FRESNO STATE"],
    "San Jose State": ["SAN JOSE STATE"],
    "USC": ["SOUTHERN CALIFORNIA"],
    "Michigan": ["UNIVERSITY OF MICHIGAN"],
    "Michigan State": ["MICHIGAN STATE"],
    "Central Michigan": ["CENTRAL MICHIGAN"],
    "Eastern Michigan": ["EASTERN MICHIGAN"],
    "Western Michigan": ["WESTERN MICHIGAN"],
    "Penn State": ["PENN STATE"],
    "Pittsburgh": ["PITTSBURGH"],
    "Temple": ["TEMPLE"],
}

TEXAS_UNIVERSITY_EMPLOYER_KEYWORDS = [
    keyword
    for school, keywords in SCHOOL_EMPLOYER_KEYWORDS.items()
    if SCHOOL_STATE.get(school) == "TX"
    for keyword in keywords
]

TITLE_KEYWORDS = ["coach", "football", "athletic", "athletics"]


@dataclass
class SalaryRecord:
    name: str
    employer: str
    title: str | None
    base_salary: int | None
    total_comp: int | None
    state: str
    source: str
    fiscal_year: int | None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "employer": self.employer,
            "title": self.title,
            "baseSalary": self.base_salary,
            "totalComp": self.total_comp,
            "state": self.state,
            "source": self.source,
            "fiscalYear": self.fiscal_year,
        }


def parse_money(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", name)
    tokens = [t for t in cleaned.lower().split() if t not in {"jr", "sr", "ii", "iii", "iv"}]
    return " ".join(tokens)


def name_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def has_title_keyword(title: str | None) -> bool:
    if not title:
        return False
    lowered = title.lower()
    return any(keyword in lowered for keyword in TITLE_KEYWORDS)


def iter_csv_rows(text: str) -> Iterable[dict]:
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        yield row


def parse_texas_tribune(text: str, keep_all: bool = False) -> list[SalaryRecord]:
    records = []
    for row in iter_csv_rows(text):
        title = row.get("CLASS TITLE") or ""
        if not keep_all and not has_title_keyword(title):
            continue
        first = (row.get("FIRST NAME") or "").strip()
        last = (row.get("LAST NAME") or "").strip()
        name = f"{first.title()} {last.title()}".strip()
        employer = (row.get("AGENCY NAME") or "").strip()
        # Texas Tribune data contains many non-university agencies; keep only known university employers.
        employer_norm = employer.upper()
        if TEXAS_UNIVERSITY_EMPLOYER_KEYWORDS and not any(
            keyword in employer_norm for keyword in TEXAS_UNIVERSITY_EMPLOYER_KEYWORDS
        ):
            continue
        base_salary = parse_money(row.get("ANNUAL"))
        total_comp = parse_money(row.get("summed_annual_salary")) or base_salary
        records.append(
            SalaryRecord(
                name=name,
                employer=employer,
                title=title.strip() or None,
                base_salary=base_salary,
                total_comp=total_comp,
                state="TX",
                source=STATE_SOURCES["TX"]["name"],
                fiscal_year=STATE_SOURCES["TX"].get("fiscal_year"),
            )
        )
    return records


def parse_florida(text: str, keep_all: bool = False) -> list[SalaryRecord]:
    records = []
    for row in iter_csv_rows(text):
        title = row.get("Class Title") or ""
        if not keep_all and not has_title_keyword(title):
            continue
        first = (row.get("First Name") or "").strip()
        last = (row.get("Last Name") or "").strip()
        name = f"{first.title()} {last.title()}".strip()
        employer = (row.get("Agency Name") or "").strip()
        base_salary = parse_money(row.get("Salary"))
        records.append(
            SalaryRecord(
                name=name,
                employer=employer,
                title=title.strip() or None,
                base_salary=base_salary,
                total_comp=base_salary,
                state="FL",
                source=STATE_SOURCES["FL"]["name"],
                fiscal_year=STATE_SOURCES["FL"].get("fiscal_year"),
            )
        )
    return records


def parse_manual_csv(text: str, state: str) -> list[SalaryRecord]:
    records = []
    for row in iter_csv_rows(text):
        name = (row.get("name") or row.get("Name") or "").strip()
        employer = (row.get("employer") or row.get("Employer") or "").strip()
        title = (row.get("title") or row.get("Title") or "").strip() or None
        base_salary = parse_money(row.get("base_salary") or row.get("Base Salary") or row.get("Salary"))
        total_comp = parse_money(row.get("total_comp") or row.get("Total Comp")) or base_salary
        if not name:
            continue
        records.append(
            SalaryRecord(
                name=name,
                employer=employer,
                title=title,
                base_salary=base_salary,
                total_comp=total_comp,
                state=state,
                source=f"Manual import ({state})",
                fiscal_year=None,
            )
        )
    return records


def download_state_data(state: str, output_dir: Path, keep_all: bool, force: bool) -> Path:
    state = state.upper()
    if state not in STATE_SOURCES:
        raise ValueError(f"Unknown state: {state}")
    source = STATE_SOURCES[state]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{state.lower()}_state_salaries.json"

    if output_path.exists() and not force:
        return output_path

    if source.get("manual"):
        raise RuntimeError(
            f"{state} source requires manual download. See {source.get('download_url') or 'instructions in script'}"
        )

    if not source.get("download_url"):
        raise RuntimeError(f"{state} source missing download URL")

    headers = {"User-Agent": USER_AGENT}
    response = requests.get(source["download_url"], headers=headers, timeout=60)
    response.raise_for_status()

    if source["parser"] == "texas_tribune":
        records = parse_texas_tribune(response.text, keep_all=keep_all)
    elif source["parser"] == "florida":
        records = parse_florida(response.text, keep_all=keep_all)
    else:
        raise RuntimeError(f"Unsupported parser: {source['parser']}")

    payload = {
        "metadata": {
            "state": state,
            "source": source["name"],
            "downloadedAt": datetime.utcnow().strftime("%Y-%m-%d"),
            "totalRecords": len(records),
        },
        "records": [record.to_dict() for record in records],
    }

    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)

    return output_path


def load_state_records(state: str, input_dir: Path) -> list[SalaryRecord]:
    state = state.upper()
    path = input_dir / f"{state.lower()}_state_salaries.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing state salary file: {path}")
    with open(path) as f:
        data = json.load(f)
    records = []
    for row in data.get("records", []):
        records.append(
            SalaryRecord(
                name=row.get("name", ""),
                employer=row.get("employer", ""),
                title=row.get("title"),
                base_salary=row.get("baseSalary"),
                total_comp=row.get("totalComp"),
                state=row.get("state", state),
                source=row.get("source", data.get("metadata", {}).get("source", "")),
                fiscal_year=row.get("fiscalYear"),
            )
        )
    return records


def resolve_school_state(school: str) -> str | None:
    if school in SCHOOL_STATE:
        return SCHOOL_STATE[school]
    normalized = SCHOOL_ALIASES.get(school, school)
    return SCHOOL_STATE.get(normalized)


def match_coaches(
    roster: list[dict],
    state_records: dict[str, list[SalaryRecord]],
    min_score: float = 0.88,
) -> dict:
    matches = []
    unmatched = []

    for coach in roster:
        school = coach.get("school", "")
        coach_name = coach.get("name") or coach.get("coach") or ""
        state = resolve_school_state(school)
        if not state or state not in state_records:
            unmatched.append({"coach": coach_name, "school": school, "reason": "state not loaded"})
            continue

        employer_keywords = SCHOOL_EMPLOYER_KEYWORDS.get(school, [])
        candidates = state_records[state]
        if employer_keywords:
            filtered = []
            for record in candidates:
                employer_norm = record.employer.upper()
                if any(keyword in employer_norm for keyword in employer_keywords):
                    filtered.append(record)
            if filtered:
                candidates = filtered

        coach_norm = normalize_name(coach_name)
        best = None
        best_score = 0.0
        for record in candidates:
            record_norm = normalize_name(record.name)
            if not record_norm:
                continue
            score = name_score(coach_norm, record_norm)
            if score > best_score:
                best_score = score
                best = record

        if best and best_score >= min_score:
            matches.append(
                {
                    "coach": coach_name,
                    "school": school,
                    "state": state,
                    "position": coach.get("position"),
                    "baseSalary": best.base_salary,
                    "totalComp": best.total_comp,
                    "salaryYear": best.fiscal_year,
                    "salarySource": best.source,
                    "salaryEmployer": best.employer,
                    "salaryTitle": best.title,
                    "matchScore": round(best_score, 3),
                }
            )
        else:
            unmatched.append(
                {
                    "coach": coach_name,
                    "school": school,
                    "state": state,
                    "reason": "no match",
                }
            )

    return {
        "matches": matches,
        "unmatched": unmatched,
    }


def load_roster(roster_path: Path) -> list[dict]:
    with open(roster_path) as f:
        data = json.load(f)
    if isinstance(data, dict) and "coaches" in data:
        return data["coaches"]
    if isinstance(data, list):
        return data
    raise ValueError("Roster JSON must be a list or an object with 'coaches'")


def parse_manual_file(state: str, csv_path: Path, output_dir: Path) -> Path:
    with open(csv_path, "r", encoding="utf-8") as f:
        text = f.read()
    records = parse_manual_csv(text, state=state)
    payload = {
        "metadata": {
            "state": state,
            "source": f"Manual import ({state})",
            "downloadedAt": datetime.utcnow().strftime("%Y-%m-%d"),
            "totalRecords": len(records),
        },
        "records": [record.to_dict() for record in records],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{state.lower()}_state_salaries.json"
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="State salary ingestion and matching")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download and normalize state salaries")
    download_parser.add_argument("--state", required=True, help="State abbreviation (e.g., TX)")
    download_parser.add_argument("--output", default="data/state_salaries", help="Output directory")
    download_parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    download_parser.add_argument("--keep-all", action="store_true", help="Keep non-coach titles")

    manual_parser = subparsers.add_parser("import", help="Import manually downloaded CSV")
    manual_parser.add_argument("--state", required=True, help="State abbreviation (e.g., CA)")
    manual_parser.add_argument("--csv", required=True, help="Path to the CSV file")
    manual_parser.add_argument("--output", default="data/state_salaries", help="Output directory")

    match_parser = subparsers.add_parser("match", help="Match roster coaches to salary records")
    match_parser.add_argument("--roster", default="data/staff_test.json", help="Roster JSON file")
    match_parser.add_argument("--states", default=",".join(TARGET_STATES), help="Comma-separated states")
    match_parser.add_argument("--input", default="data/state_salaries", help="State salary input directory")
    match_parser.add_argument("--output", default="data/state_salary_matches.json", help="Output file")
    match_parser.add_argument("--min-score", type=float, default=0.88, help="Minimum name match score")

    args = parser.parse_args()
    repo_root = Path(__file__).parent.parent

    if args.command == "download":
        output_dir = repo_root / args.output
        output_path = download_state_data(
            args.state,
            output_dir=output_dir,
            keep_all=args.keep_all,
            force=args.force,
        )
        print(f"Saved {args.state} salaries to {output_path}")
    elif args.command == "import":
        output_dir = repo_root / args.output
        output_path = parse_manual_file(
            args.state.upper(),
            csv_path=repo_root / args.csv,
            output_dir=output_dir,
        )
        print(f"Imported {args.state} salaries to {output_path}")
    elif args.command == "match":
        roster = load_roster(repo_root / args.roster)
        state_records = {}
        for state in [s.strip().upper() for s in args.states.split(",") if s.strip()]:
            state_records[state] = load_state_records(state, repo_root / args.input)

        result = match_coaches(roster, state_records, min_score=args.min_score)

        payload = {
            "metadata": {
                "generatedAt": datetime.utcnow().strftime("%Y-%m-%d"),
                "states": list(state_records.keys()),
                "rosterCount": len(roster),
                "matched": len(result["matches"]),
                "unmatched": len(result["unmatched"]),
            },
            **result,
        }

        output_path = repo_root / args.output
        with open(output_path, "w") as f:
            json.dump(payload, f, indent=2)

        print(f"Matched {len(result['matches'])} coaches. Output: {output_path}")


if __name__ == "__main__":
    main()
