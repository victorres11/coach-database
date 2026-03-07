import argparse
import os
import sys
import requests
from bs4 import BeautifulSoup
import re
from api.position_map import POSITION_MAP, match_position_code

try:
    import libsql_experimental
except ImportError:
    libsql_experimental = None

# AI API helpers
def ai_parse_text(text, api_key, api_url='https://api.anthropic.com/v1/messages'):
    if not api_key:
        raise RuntimeError("No ANTHROPIC_API_KEY set — can't run --ai-parse.")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": "claude-3-haiku-20240307",
        "max_tokens": 512,
        "messages": [
            {"role": "user", "content": f"Extract football coach staff as Name, Position pairs, one per line, from this text: {text}"}
        ],
    }
    resp = requests.post(api_url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()
    result = resp.json()["content"][0]["text"]
    return result

def parse_url(url):
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        sys.exit(1)
    if resp.status_code == 403 and 'cloudflare' in resp.text.lower():
        print("Blocked by Cloudflare (HTTP 403). Try a VPN, or copy-paste the staff section text and use --text instead.")
        sys.exit(2)
    soup = BeautifulSoup(resp.text, 'html.parser')
    # Very naive: just scrap all text (better to tune selector for real staffing tables if needed)
    text = soup.get_text(separator=' ', strip=True)
    return text

def parse_text(text, ai_parse=False):
    """
    Parse text block into [(name, position)] pairs.
    Regex logic first, then Claude fallback if --ai-parse.
    """
    pairs = []
    # Try to find "Name, Position" lines (tolerant to whitespace)
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z .'-]+),\s*([^\\n,]+)$", line.strip())
        if m:
            pairs.append((m.group(1).strip(), m.group(2).strip()))
    # If not good and ai_parse is set, use Claude
    if ai_parse and len(pairs) < 2:
        print("Parsing with Claude API...", file=sys.stderr)
        api_key = os.getenv('ANTHROPIC_API_KEY')
        ai_out = ai_parse_text(text, api_key)
        # Try to re-parse the Claude output as same "name, position" lines
        return parse_text(ai_out, ai_parse=False)
    return pairs

def normalize_staff(pairs):
    normed = []
    for name, pos in pairs:
        code = match_position_code(pos)
        normed.append({"name": name, "position": pos, "code": code})
    return normed

def get_conn():
    # Use Turso in prod per env; fallback to local SQLite
    db_url = os.getenv("TURSO_DATABASE_URL")
    if db_url:
        auth = os.getenv("TURSO_AUTH_TOKEN")
        return libsql_experimental.connect_async(db_url, auth_token=auth)
    # Fallback for development if needed
    import sqlite3
    return sqlite3.connect("coach.db")

def update_db(school_slug, staff, year=2025, dry_run=False):
    conn = get_conn()
    if isinstance(conn, type(get_conn.__globals__.get('sqlite3', None))):
        c = conn.cursor()
    else:
        c = conn
    for entry in staff:
        query = '''
        INSERT INTO coaches (school_id, name, position, position_code, year)
        SELECT s.id, ?, ?, ?, ? FROM schools s WHERE s.slug = ?
        ON CONFLICT(school_id, name, year) DO UPDATE SET
          position = excluded.position, position_code = excluded.position_code
        '''
        print(f"UPSERT: {entry['name']} ({entry['position']}) [code={entry['code']}] @ {school_slug}, {year}")
        if not dry_run:
            c.execute(query, (entry['name'], entry['position'], entry['code'], year, school_slug))
    conn.commit()
    conn.close()

def verify(school_slug):
    url = f"https://coach-database-api.fly.dev/yr/{school_slug}/coaches"
    resp = requests.get(url, timeout=10)
    try:
        dat = resp.json()
    except Exception:
        print(f"Failed to parse response: {resp.text}", file=sys.stderr)
        sys.exit(3)
    for k, v in dat.items():
        print(f"{k}: {v}")

def main():
    parser = argparse.ArgumentParser(description="Update staff coaches from URL or text.")
    parser.add_argument('--school', required=True, help='School slug for db update.')
    parser.add_argument('--url', help='URL for requests+scrape (paste staff page).')
    parser.add_argument('--text', help='Text file path for staff block.')
    parser.add_argument('--dry-run', action='store_true', help='Print ops, no db write.')
    parser.add_argument('--verify', action='store_true', help='Fetch from live API after update.')
    parser.add_argument('--year', type=int, default=2025, help='Year for staff.')
    parser.add_argument('--ai-parse', action='store_true', help='Send to Claude for extraction if parsing fails.')
    args = parser.parse_args()

    # Get input text
    if args.url:
        text = parse_url(args.url)
    elif args.text:
        with open(args.text) as f:
            text = f.read()
    else:
        print('Must provide --url or --text.', file=sys.stderr)
        sys.exit(2)

    pairs = parse_text(text, ai_parse=args.ai_parse)
    staff = normalize_staff(pairs)
    update_db(args.school, staff, year=args.year, dry_run=args.dry_run)
    if args.verify:
        verify(args.school)

if __name__ == '__main__':
    main()
