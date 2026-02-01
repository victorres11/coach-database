#!/usr/bin/env python3
"""
Aggregate assistant coach salary info from media reports.

Usage:
  python scripts/media_enrichment.py \
    --staff data/staff_test.json \
    --output data/media_reports.json
"""

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

DEFAULT_ALLOWED_DOMAINS = [
    "espn.com",
    "theathletic.com",
]

# Match salary-style dollar amounts like "$1.2 million" or "$750,000".
MONEY_PATTERN = re.compile(
    r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(million|m|thousand|k)?",
    re.IGNORECASE,
)

SALARY_CONTEXT = re.compile(
    r"salary|contract|deal|extension|per year|annually|annual|buyout|base",
    re.IGNORECASE,
)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    domain: str


def is_coordinator(position: str | None) -> bool:
    if not position:
        return False
    return "coordinator" in position.lower()


def load_staff(path: Path) -> list[dict]:
    with path.open() as f:
        data = json.load(f)
    coaches = data.get("coaches", [])
    return [
        {
            "coach": c.get("name") or c.get("coach"),
            "school": c.get("school"),
            "conference": c.get("conference"),
            "position": c.get("position"),
        }
        for c in coaches
        if c.get("name") or c.get("coach")
    ]


def duckduckgo_search(query: str, max_results: int = 10) -> list[SearchResult]:
    response = requests.get(
        "https://duckduckgo.com/html/",
        params={"q": query},
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for result in soup.select("div.result"):
        link = result.select_one("a.result__a")
        snippet = result.select_one("a.result__snippet")
        if not link:
            continue
        url = link.get("href") or ""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        results.append(
            SearchResult(
                title=link.get_text(strip=True),
                url=url,
                snippet=snippet.get_text(" ", strip=True) if snippet else "",
                domain=domain,
            )
        )
        if len(results) >= max_results:
            break
    return results


def normalize_money(amount_text: str, unit: str | None) -> int | None:
    try:
        value = float(amount_text.replace(",", ""))
    except ValueError:
        return None

    if unit:
        unit = unit.lower()
        if unit in {"million", "m"}:
            value *= 1_000_000
        elif unit in {"thousand", "k"}:
            value *= 1_000

    return int(value)


def extract_salary(text: str) -> tuple[int | None, str | None]:
    if not SALARY_CONTEXT.search(text):
        return None, None

    matches = []
    for match in MONEY_PATTERN.finditer(text):
        amount = normalize_money(match.group(1), match.group(2))
        if amount:
            matches.append((amount, match.group(0).strip()))

    if not matches:
        return None, None

    # Prefer the largest figure in context; reporters often note annual pay.
    matches.sort(key=lambda x: x[0], reverse=True)
    return matches[0]


def domain_allowed(domain: str, allowed_domains: list[str], allow_edu: bool) -> bool:
    if allow_edu and domain.endswith(".edu"):
        return True
    return any(domain == d or domain.endswith(f".{d}") for d in allowed_domains)


def source_type(domain: str) -> str:
    if domain.endswith("espn.com"):
        return "espn"
    if domain.endswith("theathletic.com"):
        return "the_athletic"
    if domain.endswith(".edu"):
        return "press_release"
    return "local_media"


def enrich_coach(coach: dict, allowed_domains: list[str], allow_edu: bool, max_results: int) -> dict | None:
    name = coach.get("coach")
    school = coach.get("school")
    if not name:
        return None

    queries = [f"{name} contract", f"{name} salary"]
    for query in queries:
        results = duckduckgo_search(query, max_results=max_results)
        for result in results:
            if not domain_allowed(result.domain, allowed_domains, allow_edu):
                continue
            combined = f"{result.title} {result.snippet}"
            salary, salary_text = extract_salary(combined)
            if salary:
                return {
                    "coach": name,
                    "school": school,
                    "position": coach.get("position"),
                    "conference": coach.get("conference"),
                    "salary": salary,
                    "salaryText": salary_text,
                    "source": result.url,
                    "sourceDomain": result.domain,
                    "sourceType": source_type(result.domain),
                    "sourceTitle": result.title,
                    "sourceSnippet": result.snippet,
                    "query": query,
                    "lastUpdated": datetime.now().strftime("%Y-%m-%d"),
                }
    return None


def load_existing(path: Path) -> dict[tuple[str, str | None], dict]:
    if not path.exists():
        return {}
    with path.open() as f:
        data = json.load(f)
    existing = {}
    for item in data.get("reports", []):
        key = (item.get("coach"), item.get("school"))
        existing[key] = item
    return existing


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich coach salary data from media reports")
    parser.add_argument("--staff", default="data/staff_test.json", help="Staff data JSON")
    parser.add_argument("--output", default="data/media_reports.json", help="Output JSON")
    parser.add_argument("--max-coaches", type=int, default=200, help="Maximum coaches to search")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between searches")
    parser.add_argument("--max-results", type=int, default=8, help="Max search results per query")
    parser.add_argument(
        "--allowed-domain",
        action="append",
        default=list(DEFAULT_ALLOWED_DOMAINS),
        help="Allowed domains (repeatable)",
    )
    parser.add_argument("--allow-edu", action="store_true", help="Allow .edu press releases")
    parser.add_argument("--include-non-coordinators", action="store_true", help="Include all positions")
    parser.add_argument("--resume", action="store_true", help="Skip coaches already in output")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.parent
    staff_path = script_dir / args.staff
    output_path = script_dir / args.output

    coaches = load_staff(staff_path)

    if not args.include_non_coordinators:
        coaches = [c for c in coaches if is_coordinator(c.get("position"))]

    # Deterministic order by school, then coach name.
    coaches.sort(key=lambda c: (c.get("school") or "", c.get("coach") or ""))

    existing = load_existing(output_path) if args.resume else {}

    reports = [] if not args.resume else list(existing.values())
    searched = 0
    for coach in coaches:
        if searched >= args.max_coaches:
            break
        key = (coach.get("coach"), coach.get("school"))
        if args.resume and key in existing:
            continue

        report = enrich_coach(
            coach,
            allowed_domains=args.allowed_domain,
            allow_edu=args.allow_edu,
            max_results=args.max_results,
        )
        searched += 1
        if report:
            reports.append(report)
            print(f"Matched {report['coach']} ({report.get('school')}) - ${report['salary']:,}")
        else:
            print(f"No match for {coach.get('coach')} ({coach.get('school')})")

        time.sleep(args.delay)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(
            {
                "metadata": {
                    "source": "Media reports",
                    "lastUpdated": datetime.now().strftime("%Y-%m-%d"),
                    "totalReports": len(reports),
                    "staffSource": str(args.staff),
                    "allowedDomains": args.allowed_domain,
                    "allowEdu": args.allow_edu,
                },
                "reports": reports,
            },
            f,
            indent=2,
        )

    print(f"Saved {len(reports)} reports to {output_path}")


if __name__ == "__main__":
    main()
