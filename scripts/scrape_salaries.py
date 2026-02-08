#!/usr/bin/env python3
"""
Scrape public assistant coach / staff salary data from multiple sources.

Phase 1 sources:
  - Ohio State HR (osu_hr)
  - UNC System salary DB (unc_system)
  - Transparent California (transparent_ca) for UC schools

This script pulls `salary_sources` rows from SQLite, scrapes each active source,
then inserts/updates `salaries` for matched coaches.

Usage:
  python scripts/scrape_salaries.py seed
  python scripts/scrape_salaries.py run --school ohio-state
  python scripts/scrape_salaries.py run --active-only
  python scripts/scrape_salaries.py run --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import time
from dataclasses import dataclass, replace as dc_replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup


DB_PATH_DEFAULT = Path(__file__).parent.parent / "db" / "coaches.db"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_money(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.\\-]", "", str(value))
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z\\s]", " ", name)
    tokens = [
        t
        for t in cleaned.lower().split()
        if t not in {"jr", "sr", "ii", "iii", "iv"}
    ]
    return " ".join(tokens)


def name_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def last_first_to_first_last(name: str) -> str:
    if "," not in name:
        return name
    last, first = [p.strip() for p in name.split(",", 1)]
    if not first:
        return name
    return f"{first} {last}".strip()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS salary_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            base_url TEXT NOT NULL,
            query_params TEXT,
            parser_name TEXT NOT NULL,
            last_scraped TEXT,
            active BOOLEAN DEFAULT 1,
            FOREIGN KEY (school_id) REFERENCES schools(id)
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_salary_sources_school ON salary_sources(school_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_salary_sources_active ON salary_sources(active);"
    )
    conn.commit()


def get_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def latest_coach_year(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(year) FROM coaches").fetchone()
    if row and row[0]:
        return int(row[0])
    return int(dt.date.today().year)


@dataclass(frozen=True)
class SalaryRow:
    person_name: str
    title: str | None
    department: str | None
    year: int | None
    school_pay: int | None
    total_pay: int | None
    source: str
    source_date: str


def iter_active_sources(conn: sqlite3.Connection, school_slug: str | None) -> Iterable[sqlite3.Row]:
    if school_slug:
        return conn.execute(
            """
            SELECT ss.*, s.slug as school_slug, s.name as school_name
            FROM salary_sources ss
            JOIN schools s ON ss.school_id = s.id
            WHERE s.slug = ? AND ss.active = 1
            ORDER BY ss.id
            """,
            (school_slug,),
        )
    return conn.execute(
        """
        SELECT ss.*, s.slug as school_slug, s.name as school_name
        FROM salary_sources ss
        JOIN schools s ON ss.school_id = s.id
        WHERE ss.active = 1
        ORDER BY ss.id
        """
    )


def load_params(row: sqlite3.Row) -> dict[str, Any]:
    raw = row["query_params"] or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


class OSUHRParser:
    name = "osu_hr"

    def scrape(self, source_row: sqlite3.Row) -> list[SalaryRow]:
        params = load_params(source_row)
        cost_center = params.get("costCenter") or params.get("cost_center")
        if not cost_center:
            raise ValueError("osu_hr requires query_params.costCenter")

        title_contains = [s.lower() for s in (params.get("title_contains") or ["coach"])]
        default_year = int(params.get("year") or 2025)

        resp = requests.get(
            source_row["base_url"],
            params={"costCenter": cost_center},
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        rows: list[SalaryRow] = []
        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if not tds:
                continue
            values = [td.get_text(" ", strip=True) for td in tds]
            row_map = dict(zip(headers, values))

            name = (row_map.get("preferred name") or "").strip()
            title = (row_map.get("title") or "").strip() or None
            salary_text = row_map.get("salary / hourly\u00a0rate") or row_map.get("salary / hourly rate")
            salary = parse_money(salary_text)

            if not name or not title or salary is None:
                continue
            if not any(tok in title.lower() for tok in title_contains):
                continue

            rows.append(
                SalaryRow(
                    person_name=last_first_to_first_last(name),
                    title=title,
                    department=row_map.get("cch6 / funding unit"),
                    year=default_year,
                    school_pay=salary,
                    total_pay=salary,
                    source=self.name,
                    source_date=utc_now_iso(),
                )
            )

        return rows


class UNCSystemParser:
    name = "unc_system"

    def _agree(self, session: requests.Session, base_url: str) -> None:
        # The search UI requires accepting terms to set a PHP session.
        index_url = base_url.rstrip("/") + "/index.php"
        resp = session.post(index_url, data={"action": "agree"}, timeout=30, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()

    def _post_page(self, session: requests.Session, base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
        ajax_url = base_url.rstrip("/") + "/ajax.php"
        resp = session.post(
            ajax_url,
            data=payload,
            timeout=30,
            headers={"User-Agent": USER_AGENT, "Referer": base_url.rstrip("/") + "/"},
        )
        resp.raise_for_status()
        return resp.json()

    def scrape(self, source_row: sqlite3.Row) -> list[SalaryRow]:
        params = load_params(source_row)
        campus = params.get("campus")
        if not campus:
            raise ValueError("unc_system requires query_params.campus (e.g. 'UNC-CH', 'NCSU')")

        dept_contains = [s.lower() for s in (params.get("department_contains") or ["football"])]
        pos_contains = [s.lower() for s in (params.get("position_contains") or ["coach"])]
        default_year = int(params.get("year") or 2025)

        session = requests.Session()
        self._agree(session, source_row["base_url"])

        page_size = int(params.get("page_size") or 200)
        # The site uses 0-based page indexing.
        page = 0
        total_records: int | None = None
        rows: list[SalaryRow] = []

        while total_records is None or page * page_size < total_records:
            payload: dict[str, Any] = {
                "type": "json",
                "campus": campus,
                "page": page,
                "pageSize": page_size,
            }

            # Keep query broad enough that the local filters can find football staff.
            # Most campuses expose football via department fields containing "Football".
            if params.get("position"):
                payload["position"] = params["position"]
            else:
                payload["position"] = "Coach"

            data = self._post_page(session, source_row["base_url"], payload)
            total_records = int(data.get("totalRecords") or 0)

            names = data.get("names") or []
            for raw_row in data.get("data") or []:
                record = dict(zip(names, raw_row))
                department = (record.get("department") or "").strip()
                position = (record.get("position") or "").strip()

                if dept_contains and not any(tok in department.lower() for tok in dept_contains):
                    continue
                if pos_contains and not any(tok in position.lower() for tok in pos_contains):
                    continue

                first = (record.get("first") or "").strip()
                last = (record.get("last") or "").strip()
                name = f"{first} {last}".strip()
                salary = parse_money(record.get("salary"))
                if not name or salary is None:
                    continue

                rows.append(
                    SalaryRow(
                        person_name=name,
                        title=position or None,
                        department=department or None,
                        year=default_year,
                        school_pay=salary,
                        total_pay=salary,
                        source=self.name,
                        source_date=utc_now_iso(),
                    )
                )

            page += 1
            time.sleep(0.2)

            if not total_records:
                break

        return rows


class TransparentCAParser:
    name = "transparent_ca"

    def _search(self, session: requests.Session, base_url: str, agency: str, query: str) -> str:
        resp = session.get(
            base_url,
            params={"a": agency, "q": query},
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.text

    def _iter_results(self, html: str) -> Iterable[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return
        rows = table.find_all("tr")
        for tr in rows[1:]:
            tds = tr.find_all("td")
            if not tds:
                continue
            href = tr.find("a", href=True)
            year = None
            if href and href["href"]:
                m = re.search(r"/salaries/(\d{4})/", href["href"])
                if m:
                    year = int(m.group(1))
            yield {
                "name": tds[0].get_text(" ", strip=True),
                "job_title": tds[1].get_text(" ", strip=True),
                "regular_pay": tds[2].get_text(" ", strip=True),
                "total_pay": tds[5].get_text(" ", strip=True),
                "year": year,
            }

    def scrape_for_school(self, conn: sqlite3.Connection, source_row: sqlite3.Row, roster_year: int) -> list[SalaryRow]:
        params = load_params(source_row)
        agency = params.get("agency") or "university-of-california"
        year_min = int(params.get("year_min") or 2022)
        default_year = int(params.get("year") or roster_year)

        # TransparentCA does not provide a stable campus filter for UC schools.
        # Strategy: search per-coach name from our roster and pull the most recent
        # coaching-related row.
        coaches = conn.execute(
            """
            SELECT id, name
            FROM coaches
            WHERE school_id = ? AND year = ?
            ORDER BY is_head_coach DESC, name ASC
            """,
            (source_row["school_id"], roster_year),
        ).fetchall()

        session = requests.Session()
        out: list[SalaryRow] = []
        for coach in coaches:
            coach_name = coach["name"]
            html = self._search(session, source_row["base_url"], agency, coach_name)
            best: dict[str, Any] | None = None
            for row in self._iter_results(html):
                if not row.get("year") or row["year"] < year_min:
                    continue
                if normalize_name(row["name"]) != normalize_name(coach_name):
                    continue
                # Keep coach roles (job titles are sometimes abbreviated: "Coach Ast 3", etc.)
                if "coach" not in (row.get("job_title") or "").lower():
                    continue
                if best is None or row["year"] > (best.get("year") or 0):
                    best = row

            if best:
                school_pay = parse_money(best.get("regular_pay"))
                total_pay = parse_money(best.get("total_pay"))
                out.append(
                    SalaryRow(
                        person_name=coach_name,
                        title=best.get("job_title"),
                        department=None,
                        year=int(best.get("year") or default_year),
                        school_pay=school_pay,
                        total_pay=total_pay,
                        source=self.name,
                        source_date=utc_now_iso(),
                    )
                )

            time.sleep(0.25)

        return out


PARSERS: dict[str, Any] = {
    OSUHRParser.name: OSUHRParser(),
    UNCSystemParser.name: UNCSystemParser(),
    TransparentCAParser.name: TransparentCAParser(),
}


def best_coach_match(
    conn: sqlite3.Connection, school_id: int, person_name: str, roster_year: int, min_score: float = 0.86
) -> sqlite3.Row | None:
    target = normalize_name(person_name)
    if not target:
        return None

    candidates = conn.execute(
        "SELECT id, name, position, is_head_coach FROM coaches WHERE school_id = ? AND year = ?",
        (school_id, roster_year),
    ).fetchall()
    if not candidates:
        return None

    exact = [c for c in candidates if normalize_name(c["name"]) == target]
    if exact:
        # Prefer head coach if duplicates exist.
        exact.sort(key=lambda r: (r["is_head_coach"], r["name"]), reverse=True)
        return exact[0]

    best: tuple[float, sqlite3.Row] | None = None
    for cand in candidates:
        score = name_score(target, normalize_name(cand["name"]))
        if best is None or score > best[0]:
            best = (score, cand)

    if best and best[0] >= min_score:
        return best[1]
    return None


def upsert_salary(
    conn: sqlite3.Connection,
    coach_id: int,
    salary: SalaryRow,
    dry_run: bool,
) -> None:
    existing = conn.execute(
        "SELECT id FROM salaries WHERE coach_id = ? AND year = ? AND source = ? LIMIT 1",
        (coach_id, salary.year, salary.source),
    ).fetchone()

    if dry_run:
        return

    if existing:
        conn.execute(
            """
            UPDATE salaries
            SET total_pay = ?, school_pay = ?, source_date = ?
            WHERE id = ?
            """,
            (salary.total_pay, salary.school_pay, salary.source_date, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO salaries (coach_id, year, total_pay, school_pay, source, source_date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                coach_id,
                salary.year,
                salary.total_pay,
                salary.school_pay,
                salary.source,
                salary.source_date,
            ),
        )


def seed_sources(conn: sqlite3.Connection) -> None:
    ensure_schema(conn)
    schools = {
        row["name"]: row["id"]
        for row in conn.execute(
            """
            SELECT id, name
            FROM schools
            WHERE name IN ('Ohio State', 'UCLA', 'California', 'North Carolina', 'North Carolina State')
            """
        ).fetchall()
    }

    def upsert(name: str, source_type: str, base_url: str, params: dict[str, Any], parser_name: str) -> None:
        school_id = schools.get(name)
        if not school_id:
            print(f"Seed skipped (missing school): {name}")
            return
        existing = conn.execute(
            "SELECT id FROM salary_sources WHERE school_id = ? AND source_type = ? LIMIT 1",
            (school_id, source_type),
        ).fetchone()
        payload = (base_url, json.dumps(params, sort_keys=True), parser_name)
        if existing:
            conn.execute(
                """
                UPDATE salary_sources
                SET base_url = ?, query_params = ?, parser_name = ?, active = 1
                WHERE id = ?
                """,
                (*payload, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO salary_sources (school_id, source_type, base_url, query_params, parser_name, active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (school_id, source_type, base_url, payload[1], parser_name),
            )

    upsert(
        "Ohio State",
        "osu_hr",
        "https://apps.hr.osu.edu/salaries/Home/Salaries",
        {"costCenter": "CC12637 Athletics | Football", "title_contains": ["Coach"], "year": 2025},
        "osu_hr",
    )
    upsert(
        "North Carolina",
        "unc_system",
        "https://uncdm.northcarolina.edu/salaries/",
        {"campus": "UNC-CH", "department_contains": ["Football"], "position_contains": ["Coach", "Coordinator"], "year": 2025},
        "unc_system",
    )
    upsert(
        "North Carolina State",
        "unc_system",
        "https://uncdm.northcarolina.edu/salaries/",
        {"campus": "NCSU", "department_contains": ["Football"], "position_contains": ["Coach", "Coordinator"], "year": 2025},
        "unc_system",
    )
    upsert(
        "UCLA",
        "transparent_ca",
        "https://transparentcalifornia.com/salaries/search/",
        {"agency": "university-of-california", "year_min": 2022, "year": 2025},
        "transparent_ca",
    )
    upsert(
        "California",
        "transparent_ca",
        "https://transparentcalifornia.com/salaries/search/",
        {"agency": "university-of-california", "year_min": 2022, "year": 2025},
        "transparent_ca",
    )

    conn.commit()


def run_scrape(db_path: Path, school_slug: str | None, roster_year: int | None, active_only: bool, dry_run: bool) -> None:
    conn = get_db(db_path)
    ensure_schema(conn)
    effective_year = int(roster_year or latest_coach_year(conn))

    total_scraped = 0
    total_matched = 0
    total_upserted = 0

    sources = list(iter_active_sources(conn, school_slug))
    if not sources:
        print("No active salary_sources found for filter.")
        return

    for src in sources:
        parser_name = src["parser_name"]
        parser = PARSERS.get(parser_name)
        if not parser:
            print(f"Skipping source {src['id']} ({src['school_name']}): unknown parser {parser_name!r}")
            continue

        print(f"\n==> {src['school_name']} ({src['school_slug']}) [{parser_name}] (year={effective_year})")

        try:
            if parser_name == "transparent_ca":
                salary_rows = parser.scrape_for_school(conn, src, roster_year=effective_year)
            else:
                salary_rows = parser.scrape(src)
        except Exception as e:
            print(f"  ERROR scraping: {e}")
            continue

        total_scraped += len(salary_rows)
        print(f"  Scraped rows: {len(salary_rows)}")

        matched = 0
        upserted = 0
        for salary in salary_rows:
            salary_for_write = dc_replace(salary, year=effective_year)
            coach = best_coach_match(conn, src["school_id"], salary_for_write.person_name, roster_year=effective_year)
            if not coach:
                continue
            matched += 1
            total_matched += 1
            upsert_salary(conn, coach["id"], salary_for_write, dry_run=dry_run)
            upserted += 1
            total_upserted += 1

        if not dry_run:
            conn.execute(
                "UPDATE salary_sources SET last_scraped = ? WHERE id = ?",
                (utc_now_iso(), src["id"]),
            )
            conn.commit()

        print(f"  Matched coaches: {matched}")
        print(f"  Upserted salaries: {upserted}{' (dry-run)' if dry_run else ''}")

        time.sleep(0.2)

    print("\nDone.")
    print(f"Scraped rows: {total_scraped}")
    print(f"Matched coaches: {total_matched}")
    print(f"Upserted salaries: {total_upserted}{' (dry-run)' if dry_run else ''}")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape assistant coach salary data from multiple sources")
    parser.add_argument("--db", type=Path, default=DB_PATH_DEFAULT, help="Path to SQLite database")

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub_seed = sub.add_parser("seed", help="Create salary_sources and seed initial sources")
    sub_seed.set_defaults(cmd="seed")

    sub_run = sub.add_parser("run", help="Run scraping for active salary_sources")
    sub_run.add_argument("--school", help="School slug to scrape (e.g. ohio-state)")
    sub_run.add_argument("--year", type=int, default=None, help="Season year to match/write (default: latest year in coaches table)")
    sub_run.add_argument("--active-only", action="store_true", help="(kept for future compatibility; sources are already filtered to active=1)")
    sub_run.add_argument("--dry-run", action="store_true", help="Scrape + match but do not write to DB")
    sub_run.set_defaults(cmd="run")

    args = parser.parse_args()

    if args.cmd == "seed":
        conn = get_db(args.db)
        seed_sources(conn)
        print("Seeded salary_sources.")
        conn.close()
        return

    if args.cmd == "run":
        run_scrape(args.db, args.school, roster_year=args.year, active_only=args.active_only, dry_run=args.dry_run)
        return


if __name__ == "__main__":
    main()
