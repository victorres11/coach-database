#!/usr/bin/env python3
"""
Aggregate assistant coach salary info from media reports.

Usage:
  python scripts/media_enrichment.py \
    --staff data/staff_test.json \
    --output data/media_salaries.json
"""

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

DEFAULT_ALLOWED_DOMAINS = [
    "espn.com",
    "theathletic.com",
    "cbssports.com",
    "si.com",
    "247sports.com",
    "usatoday.com",
    "on3.com",
]

# Match salary-style dollar amounts like "$1.2 million" or "$750,000".
MONEY_PATTERN = re.compile(
    r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(million|m|thousand|k)?",
    re.IGNORECASE,
)

SALARY_CONTEXT = re.compile(
    r"salary|contract|deal|extension|per year|annually|annual|annual rate|base",
    re.IGNORECASE,
)

NEGATIVE_SALARY_CONTEXT = re.compile(
    r"signing bonus|cap hit|rookie contract",
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

def normalize_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def name_in_text(name: str, text: str) -> bool:
    """Avoid cross-sport false positives for common last names."""
    name_norm = normalize_for_match(name)
    text_norm = normalize_for_match(text)
    if not name_norm or not text_norm:
        return False
    tokens = [t for t in name_norm.split() if t]
    if len(tokens) >= 2:
        return tokens[0] in text_norm and tokens[-1] in text_norm
    return name_norm in text_norm


def school_in_text(school: str | None, text: str) -> bool:
    if not school:
        return True
    school_norm = normalize_for_match(school)
    text_norm = normalize_for_match(text)
    if not school_norm:
        return True
    if school_norm in text_norm:
        return True
    # Fall back to token overlap for abbreviations (e.g. "App State").
    return any(tok in text_norm for tok in school_norm.split() if len(tok) > 3)


def brave_search(session: requests.Session, query: str, max_results: int = 10) -> list[SearchResult]:
    """
    Uses the Brave Search API to find relevant URLs.
    Looks for API key in multiple locations for sandbox compatibility.
    """
    api_key = os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY")
    key_paths = [
        Path.home() / ".clawdbot/credentials/brave_api_key",
        Path.home() / ".config/brave/api_key",
    ]
    for key_path in key_paths:
        if api_key:
            break
        try:
            api_key = key_path.read_text().strip()
            break
        except Exception:
            continue
    if not api_key:
        raise RuntimeError(
            "Missing Brave API key. Set BRAVE_API_KEY (or BRAVE_SEARCH_API_KEY) "
            f"or add a key file at one of: {key_paths}"
        )

    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    params = {
        "q": query,
        "count": max_results
    }
    resp = session.get(url, headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("web", {}).get("results", []):
        title = item.get("title") or ""
        url_val = item.get("url") or ""
        parsed = urlparse(url_val)
        domain = parsed.netloc.lower()
        snippet = item.get("description") or ""
        results.append(SearchResult(
            title=title,
            url=url_val,
            snippet=snippet,
            domain=domain,
        ))
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


def extract_salary(text: str, min_salary: int, max_salary: int) -> tuple[int | None, str | None]:
    if not SALARY_CONTEXT.search(text):
        return None, None
    if NEGATIVE_SALARY_CONTEXT.search(text):
        return None, None

    candidates: list[tuple[int, str, int]] = []
    for match in MONEY_PATTERN.finditer(text):
        amount = normalize_money(match.group(1), match.group(2))
        if not amount:
            continue
        if amount < min_salary or amount > max_salary:
            continue

        start = max(match.start() - 50, 0)
        end = min(match.end() + 50, len(text))
        context = text[start:end].lower()
        score = 0
        if "per year" in context or "annually" in context or "annual" in context:
            score += 3
        if "salary" in context or "annual rate" in context or "base" in context:
            score += 2
        if "buyout" in context or "bonus" in context or "signing" in context:
            score -= 4

        candidates.append((amount, match.group(0).strip(), score))

    if not candidates:
        return None, None

    # Prefer salary-ish mentions, then larger amounts.
    candidates.sort(key=lambda x: (x[2], x[0]), reverse=True)
    amount, raw_text, _score = candidates[0]
    return amount, raw_text


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

def brave_search_with_retries(
    session: requests.Session,
    query: str,
    max_results: int,
    delay_s: float,
    max_retries: int,
) -> list[SearchResult]:
    for attempt in range(max_retries + 1):
        try:
            results = brave_search(session, query, max_results=max_results)
            if delay_s:
                time.sleep(delay_s)
            return results
        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
            if status not in {429, 500, 502, 503, 504} or attempt >= max_retries:
                raise
            backoff = min(60.0, (2**attempt) * max(1.0, delay_s))
            print(f"Brave search error {status} for query={query!r}. Retrying in {backoff:.1f}s...")
            time.sleep(backoff)
        except requests.RequestException:
            if attempt >= max_retries:
                raise
            backoff = min(60.0, (2**attempt) * max(1.0, delay_s))
            print(f"Brave search request error for query={query!r}. Retrying in {backoff:.1f}s...")
            time.sleep(backoff)
    return []


def is_result_relevant(coach_name: str, school: str | None, position: str | None, result: SearchResult) -> bool:
    combined = f"{result.title} {result.snippet}"
    if not name_in_text(coach_name, combined):
        return False
    # Require the school to appear to avoid "Crosby"/"Rodriguez"-style cross-sport matches.
    if school and not school_in_text(school, combined):
        return False
    if position and "coordinator" in (position or "").lower():
        lowered = combined.lower()
        if not any(tok in lowered for tok in ["coordinator", "football", "ncaa", "assistant", "college"]):
            return False
    return True


def enrich_coach(
    session: requests.Session,
    coach: dict,
    allowed_domains: list[str],
    allow_edu: bool,
    max_results: int,
    delay_s: float,
    max_retries: int,
    min_salary: int,
    max_salary: int,
) -> dict | None:
    name = coach.get("coach")
    school = coach.get("school")
    if not name:
        return None

    position = coach.get("position") or ""
    base_query = f"\"{name}\" \"{school}\" {position} salary"
    queries = [
        base_query,
        f"\"{name}\" \"{school}\" coordinator contract salary",
    ]

    for query in queries:
        results = brave_search_with_retries(
            session,
            query,
            max_results=max_results,
            delay_s=delay_s,
            max_retries=max_retries,
        )
        for result in results:
            if not domain_allowed(result.domain, allowed_domains, allow_edu):
                continue
            if not is_result_relevant(name, school, position, result):
                continue
            combined = f"{result.title} {result.snippet}"
            salary, salary_text = extract_salary(combined, min_salary=min_salary, max_salary=max_salary)
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
    parser.add_argument("--output", default="data/media_salaries.json", help="Output JSON")
    parser.add_argument("--max-coaches", type=int, default=200, help="Maximum coaches to search")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between searches")
    parser.add_argument("--max-results", type=int, default=8, help="Max search results per query")
    parser.add_argument("--min-salary", type=int, default=50_000, help="Minimum annual salary (filter)")
    parser.add_argument("--max-salary", type=int, default=5_000_000, help="Maximum annual salary (filter)")
    parser.add_argument("--max-retries", type=int, default=5, help="Max retries on 429/5xx")
    parser.add_argument(
        "--allowed-domain",
        action="append",
        default=None,
        help="Allowed domains (repeatable)",
    )
    parser.add_argument("--allow-edu", action="store_true", help="Allow .edu press releases")
    parser.add_argument("--include-non-coordinators", action="store_true", help="Include all positions")
    parser.add_argument("--resume", action="store_true", help="Skip coaches already in output")
    parser.add_argument("--checkpoint-every", type=int, default=1, help="Write output every N searched coaches")
    args = parser.parse_args()

    allowed_domains = args.allowed_domain or list(DEFAULT_ALLOWED_DOMAINS)
    seen_domains: set[str] = set()
    allowed_domains = [d for d in allowed_domains if not (d in seen_domains or seen_domains.add(d))]

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
    session = requests.Session()
    searched = 0
    for coach in coaches:
        if searched >= args.max_coaches:
            break
        key = (coach.get("coach"), coach.get("school"))
        if args.resume and key in existing:
            continue

        report = enrich_coach(
            session,
            coach,
            allowed_domains=allowed_domains,
            allow_edu=args.allow_edu,
            max_results=args.max_results,
            delay_s=args.delay,
            max_retries=args.max_retries,
            min_salary=args.min_salary,
            max_salary=args.max_salary,
        )
        searched += 1
        if report:
            reports.append(report)
            print(f"Matched {report['coach']} ({report.get('school')}) - ${report['salary']:,}")
        else:
            print(f"No match for {coach.get('coach')} ({coach.get('school')})")

        if args.checkpoint_every and searched % args.checkpoint_every == 0:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w") as f:
                json.dump(
                    {
                        "metadata": {
                            "source": "Media reports",
                            "lastUpdated": datetime.now().strftime("%Y-%m-%d"),
                            "totalReports": len(reports),
                            "staffSource": str(args.staff),
                            "allowedDomains": allowed_domains,
                            "allowEdu": args.allow_edu,
                        },
                        "reports": reports,
                    },
                    f,
                    indent=2,
                )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(
            {
                "metadata": {
                    "source": "Media reports",
                    "lastUpdated": datetime.now().strftime("%Y-%m-%d"),
                    "totalReports": len(reports),
                    "staffSource": str(args.staff),
                    "allowedDomains": allowed_domains,
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
