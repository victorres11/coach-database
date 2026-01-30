#!/usr/bin/env python3
"""
Find game notes PDF URLs for all FBS football programs.
Tries common URL patterns on each school's athletic site.
"""

import json
import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from datetime import datetime, date, timezone

# FBS Schools with their athletic site domains
# Format: (school_name, domain, conference)
FBS_SCHOOLS = [
    # SEC
    ("Alabama", "rolltide.com", "SEC"),
    ("Arkansas", "arkansasrazorbacks.com", "SEC"),
    ("Auburn", "auburntigers.com", "SEC"),
    ("Florida", "floridagators.com", "SEC"),
    ("Georgia", "georgiadogs.com", "SEC"),
    ("Kentucky", "ukathletics.com", "SEC"),
    ("LSU", "lsusports.net", "SEC"),
    ("Mississippi State", "hailstate.com", "SEC"),
    ("Missouri", "mutigers.com", "SEC"),
    ("Oklahoma", "soonersports.com", "SEC"),
    ("Ole Miss", "olemisssports.com", "SEC"),
    ("South Carolina", "gamecocksonline.com", "SEC"),
    ("Tennessee", "utsports.com", "SEC"),
    ("Texas", "texassports.com", "SEC"),
    ("Texas A&M", "12thman.com", "SEC"),
    ("Vanderbilt", "vucommodores.com", "SEC"),
    
    # Big Ten
    ("Illinois", "fightingillini.com", "Big Ten"),
    ("Indiana", "iuhoosiers.com", "Big Ten"),
    ("Iowa", "hawkeyesports.com", "Big Ten"),
    ("Maryland", "umterps.com", "Big Ten"),
    ("Michigan", "mgoblue.com", "Big Ten"),
    ("Michigan State", "msuspartans.com", "Big Ten"),
    ("Minnesota", "gophersports.com", "Big Ten"),
    ("Nebraska", "huskers.com", "Big Ten"),
    ("Northwestern", "nusports.com", "Big Ten"),
    ("Ohio State", "ohiostatebuckeyes.com", "Big Ten"),
    ("Oregon", "goducks.com", "Big Ten"),
    ("Penn State", "gopsusports.com", "Big Ten"),
    ("Purdue", "purduesports.com", "Big Ten"),
    ("Rutgers", "scarletknights.com", "Big Ten"),
    ("UCLA", "uclabruins.com", "Big Ten"),
    ("USC", "usctrojans.com", "Big Ten"),
    ("Washington", "gohuskies.com", "Big Ten"),
    ("Wisconsin", "uwbadgers.com", "Big Ten"),
    
    # Big 12
    ("Arizona", "arizonawildcats.com", "Big 12"),
    ("Arizona State", "thesundevils.com", "Big 12"),
    ("Baylor", "baylorbears.com", "Big 12"),
    ("BYU", "byucougars.com", "Big 12"),
    ("Cincinnati", "gobearcats.com", "Big 12"),
    ("Colorado", "cubuffs.com", "Big 12"),
    ("Houston", "uhcougars.com", "Big 12"),
    ("Iowa State", "cyclones.com", "Big 12"),
    ("Kansas", "kuathletics.com", "Big 12"),
    ("Kansas State", "kstatesports.com", "Big 12"),
    ("Oklahoma State", "okstate.com", "Big 12"),
    ("TCU", "gofrogs.com", "Big 12"),
    ("Texas Tech", "texastech.com", "Big 12"),
    ("UCF", "ucfknights.com", "Big 12"),
    ("Utah", "utahutes.com", "Big 12"),
    ("West Virginia", "wvusports.com", "Big 12"),
    
    # ACC
    ("Boston College", "bceagles.com", "ACC"),
    ("California", "calbears.com", "ACC"),
    ("Clemson", "clemsontigers.com", "ACC"),
    ("Duke", "goduke.com", "ACC"),
    ("Florida State", "seminoles.com", "ACC"),
    ("Georgia Tech", "ramblinwreck.com", "ACC"),
    ("Louisville", "gocards.com", "ACC"),
    ("Miami", "miamihurricanes.com", "ACC"),
    ("NC State", "gopack.com", "ACC"),
    ("North Carolina", "goheels.com", "ACC"),
    ("Pittsburgh", "pittsburghpanthers.com", "ACC"),
    ("SMU", "smumustangs.com", "ACC"),
    ("Stanford", "gostanford.com", "ACC"),
    ("Syracuse", "cuse.com", "ACC"),
    ("Virginia", "virginiasports.com", "ACC"),
    ("Virginia Tech", "hokiesports.com", "ACC"),
    ("Wake Forest", "godeacs.com", "ACC"),
    
    # American
    ("Army", "goarmywestpoint.com", "American"),
    ("Charlotte", "charlotte49ers.com", "American"),
    ("East Carolina", "ecupirates.com", "American"),
    ("FAU", "fausports.com", "American"),
    ("Memphis", "gotigersgo.com", "American"),
    ("Navy", "navysports.com", "American"),
    ("North Texas", "meangreensports.com", "American"),
    ("Rice", "riceowls.com", "American"),
    ("South Florida", "gousfbulls.com", "American"),
    ("Temple", "owlsports.com", "American"),
    ("Tulane", "tulanegreenwave.com", "American"),
    ("Tulsa", "tulsahurricane.com", "American"),
    ("UAB", "uabsports.com", "American"),
    ("UTSA", "goutsa.com", "American"),
    
    # Mountain West
    ("Air Force", "goairforcefalcons.com", "Mountain West"),
    ("Boise State", "broncosports.com", "Mountain West"),
    ("Colorado State", "csurams.com", "Mountain West"),
    ("Fresno State", "gobulldogs.com", "Mountain West"),
    ("Hawaii", "hawaiiathletics.com", "Mountain West"),
    ("Nevada", "nevadawolfpack.com", "Mountain West"),
    ("New Mexico", "golobos.com", "Mountain West"),
    ("San Diego State", "goaztecs.com", "Mountain West"),
    ("San Jose State", "sjsuspartans.com", "Mountain West"),
    ("UNLV", "unlvrebels.com", "Mountain West"),
    ("Utah State", "utahstateaggies.com", "Mountain West"),
    ("Wyoming", "gowyo.com", "Mountain West"),
    
    # Conference USA
    ("FIU", "fiusports.com", "Conference USA"),
    ("Jacksonville State", "jsugamecocksports.com", "Conference USA"),
    ("Kennesaw State", "ksuowls.com", "Conference USA"),
    ("Liberty", "libertyflames.com", "Conference USA"),
    ("Louisiana Tech", "latechsports.com", "Conference USA"),
    ("Middle Tennessee", "goblueraiders.com", "Conference USA"),
    ("New Mexico State", "nmstatesports.com", "Conference USA"),
    ("Sam Houston", "gobearkats.com", "Conference USA"),
    ("UTEP", "utepathletics.com", "Conference USA"),
    ("Western Kentucky", "wkusports.com", "Conference USA"),
    
    # MAC
    ("Akron", "gozips.com", "MAC"),
    ("Ball State", "ballstatesports.com", "MAC"),
    ("Bowling Green", "bgsufalcons.com", "MAC"),
    ("Buffalo", "ubbulls.com", "MAC"),
    ("Central Michigan", "cmuchippewas.com", "MAC"),
    ("Eastern Michigan", "emueagles.com", "MAC"),
    ("Kent State", "kentstatesports.com", "MAC"),
    ("Miami (OH)", "miamiredhawks.com", "MAC"),
    ("Northern Illinois", "niuhuskies.com", "MAC"),
    ("Ohio", "ohiobobcats.com", "MAC"),
    ("Toledo", "utrockets.com", "MAC"),
    ("Western Michigan", "wmubroncos.com", "MAC"),
    
    # Sun Belt
    ("Appalachian State", "appstatesports.com", "Sun Belt"),
    ("Arkansas State", "astateredwolves.com", "Sun Belt"),
    ("Coastal Carolina", "goccusports.com", "Sun Belt"),
    ("Georgia Southern", "gseagles.com", "Sun Belt"),
    ("Georgia State", "georgiastatesports.com", "Sun Belt"),
    ("James Madison", "jmusports.com", "Sun Belt"),
    ("Louisiana", "ragincajuns.com", "Sun Belt"),
    ("Louisiana Monroe", "ulmwarhawks.com", "Sun Belt"),
    ("Marshall", "herdzone.com", "Sun Belt"),
    ("Old Dominion", "odusports.com", "Sun Belt"),
    ("South Alabama", "usajaguars.com", "Sun Belt"),
    ("Southern Miss", "southernmiss.com", "Sun Belt"),
    ("Texas State", "txstatebobcats.com", "Sun Belt"),
    ("Troy", "troytrojans.com", "Sun Belt"),
    
    # Independents
    ("Notre Dame", "und.com", "Independent"),
    ("UConn", "uconnhuskies.com", "Independent"),
    ("UMass", "umassathletics.com", "Independent"),
    ("Oregon State", "osubeavers.com", "Independent"),
    ("Washington State", "wsucougars.com", "Independent"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}
REQUEST_TIMEOUT = 12
MAX_CANDIDATES_PER_SCHOOL = 20
DDG_RESULT_LIMIT = 6


def build_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def is_pdf_response(resp, url):
    content_type = resp.headers.get('content-type', '')
    return 'pdf' in content_type.lower() or url.lower().endswith('.pdf')


def check_url_exists(session, url):
    """Check if a URL exists and is a PDF."""
    try:
        resp = session.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code == 200 and is_pdf_response(resp, url):
            return True
        if resp.status_code in {403, 405}:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
            if resp.status_code == 200 and is_pdf_response(resp, url):
                return True
        return False
    except requests.RequestException:
        return False


def fetch_url(session, url):
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.text
    except requests.RequestException:
        return None
    return None


def fetch_with_jina(session, url):
    jina_url = f"https://r.jina.ai/http://{url.lstrip('https://').lstrip('http://')}"
    return fetch_url(session, jina_url)


def extract_pdf_links(html, base_url):
    if not html:
        return []
    soup = BeautifulSoup(html, 'html.parser')
    links = set()

    for link in soup.find_all('a', href=True):
        href = link['href']
        if '.pdf' in href.lower():
            links.add(urljoin(base_url, href))

    # Also scan raw HTML for PDF links (some are embedded in scripts)
    for match in re.findall(r'https?://[^"\\s>]+\\.pdf', html, re.I):
        links.add(match)

    return list(links)


def score_url(url):
    url_lower = url.lower()
    score = 0
    keywords = {
        'game notes': 8,
        'gamenotes': 7,
        'game-notes': 7,
        'game_notes': 7,
        'football': 5,
        '/fb/': 3,
        'fb_': 3,
        'fb-': 3,
        'postgame': 2,
        'pregame': 2,
        'notes': 2,
    }
    for key, weight in keywords.items():
        if key in url_lower:
            score += weight
    return score


def extract_date_from_url(url):
    patterns = [
        r'(?P<y>20\\d{2})[/-](?P<m>\\d{1,2})[/-](?P<d>\\d{1,2})',
        r'(?P<y>20\\d{2})(?P<m>\\d{2})(?P<d>\\d{2})',
        r'(?P<m>\\d{1,2})[/-](?P<d>\\d{1,2})[/-](?P<y>20\\d{2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            try:
                return date(int(match.group('y')), int(match.group('m')), int(match.group('d')))
            except ValueError:
                continue
    return None


def select_latest_url(urls):
    if not urls:
        return None
    scored = []
    for url in urls:
        date_value = extract_date_from_url(url)
        scored.append((date_value or date.min, score_url(url), url))
    scored.sort(reverse=True)
    return scored[0][2]


def search_for_game_notes(session, domain):
    """
    Search a school's athletic site for game notes links.
    Returns list of potential game notes URLs.
    """
    potential_urls = []
    base_url = f"https://{domain}"
    
    # Common pages where game notes might be linked
    search_pages = [
        f"{base_url}/sports/football",
        f"{base_url}/sports/football/schedule",
        f"{base_url}/sports/football/news",
        f"{base_url}/sports/football/media-center",
        f"{base_url}/sports/football/media",
        f"{base_url}/sports/football/game-notes",
        f"{base_url}/sports/football/additional-links",
        f"{base_url}/sports/football/archives",
    ]
    
    for page_url in search_pages:
        try:
            html = fetch_url(session, page_url)
            if not html:
                html = fetch_with_jina(session, page_url)
            if not html:
                continue

            soup = BeautifulSoup(html, 'html.parser')
            
            # Find all links that might be game notes
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                text = link.get_text().lower()
                
                # Look for game notes indicators in URL
                note_patterns = ['game_notes', 'gamenotes', 'game-notes', 'notes.pdf', 
                                'fb_notes', 'football_notes', 'postgame', 'pregame']
                if any(x in href for x in note_patterns):
                    full_url = urljoin(base_url, link['href'])
                    if full_url not in potential_urls and '.pdf' in full_url.lower():
                        potential_urls.append(full_url)
                        
                # Look for game notes indicators in link text
                text_patterns = ['game notes', 'gamenotes', 'postgame notes', 'pregame notes']
                if any(x in text for x in text_patterns):
                    full_url = urljoin(base_url, link['href'])
                    if full_url not in potential_urls:
                        potential_urls.append(full_url)
                        
            # Also look in document download paths
            for link in soup.find_all('a', href=re.compile(r'documents.*\d{4}.*\.pdf', re.I)):
                href = link['href']
                # Check if it might be football related
                if any(x in href.lower() for x in ['football', 'fb_', 'fb-', '/fb/', 'notes']):
                    full_url = urljoin(base_url, href)
                    if full_url not in potential_urls:
                        potential_urls.append(full_url)
                    
        except Exception as e:
            print(f"    Error searching {page_url}: {e}")
            continue
    
    return potential_urls


def try_common_patterns(domain, school_name):
    """
    Try common URL patterns that schools use for game notes.
    """
    base_url = f"https://{domain}"
    patterns = []
    
    # Common date patterns (try recent dates)
    dates = ["2024/12", "2024/11", "2024/10", "2024/9"]
    
    # Pattern variations
    for date in dates:
        patterns.extend([
            f"{base_url}/documents/download/{date}/football_game_notes.pdf",
            f"{base_url}/documents/download/{date}/FB_GameNotes.pdf",
            f"{base_url}/documents/download/{date}/game_notes.pdf",
        ])
    
    # Try documents list page
    patterns.append(f"{base_url}/sports/football/game-notes")
    patterns.append(f"{base_url}/sports/football/schedule?view=2")  # Some have notes in schedule
    
    return patterns


def parse_sitemap_locs(xml_text):
    if not xml_text:
        return []
    return re.findall(r'<loc>([^<]+)</loc>', xml_text)


def fetch_sitemap_urls(session, domain):
    base_url = f"https://{domain}"
    candidates = []

    robots_text = fetch_url(session, f"{base_url}/robots.txt")
    sitemap_urls = []
    if robots_text:
        for line in robots_text.splitlines():
            if line.lower().startswith("sitemap:"):
                sitemap_urls.append(line.split(":", 1)[1].strip())

    if not sitemap_urls:
        sitemap_urls = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/sitemap-index.xml",
        ]

    seen_sitemaps = set()
    for sitemap_url in sitemap_urls:
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        xml_text = fetch_url(session, sitemap_url)
        if not xml_text:
            continue

        locs = parse_sitemap_locs(xml_text)
        nested = [loc for loc in locs if loc.endswith(".xml")]
        url_locs = [loc for loc in locs if not loc.endswith(".xml")]

        for loc in url_locs:
            if '.pdf' in loc.lower() and any(x in loc.lower() for x in ['football', 'game', 'notes', 'fb']):
                candidates.append(loc)

        for nested_url in nested[:6]:
            nested_xml = fetch_url(session, nested_url)
            for loc in parse_sitemap_locs(nested_xml):
                if '.pdf' in loc.lower() and any(x in loc.lower() for x in ['football', 'game', 'notes', 'fb']):
                    candidates.append(loc)

    return list(dict.fromkeys(candidates))


def search_duckduckgo(session, domain):
    queries = [
        f"site:{domain} football \"game notes\" pdf",
        f"site:{domain} \"game notes\" football pdf",
        f"site:{domain} \"game notes\" filetype:pdf",
    ]
    results = []
    for query in queries:
        url = "https://duckduckgo.com/html/?q=" + requests.utils.quote(query)
        html = fetch_url(session, url)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for link in soup.select("a.result__a")[:DDG_RESULT_LIMIT]:
            href = link.get("href", "")
            if "uddg=" in href:
                parsed = urlparse(href)
                query_params = parse_qs(parsed.query)
                if "uddg" in query_params:
                    href = unquote(query_params["uddg"][0])
            if href:
                results.append(href)
    return list(dict.fromkeys(results))


def find_game_notes_for_school(session, school_name, domain, conference):
    """Find game notes URL for a single school."""
    print(f"Searching {school_name} ({domain})...")

    found_urls = []

    # First try searching the site pages
    found_urls.extend(search_for_game_notes(session, domain))

    # Try sitemap discovery
    found_urls.extend(fetch_sitemap_urls(session, domain))

    # Try DuckDuckGo search
    for result_url in search_duckduckgo(session, domain):
        if '.pdf' in result_url.lower():
            found_urls.append(result_url)
            continue
        html = fetch_url(session, result_url)
        found_urls.extend(extract_pdf_links(html, result_url))
    
    # Validate found URLs (check if they're actually PDFs)
    valid_urls = []
    for url in found_urls[:MAX_CANDIDATES_PER_SCHOOL]:
        if check_url_exists(session, url):
            valid_urls.append(url)
            print(f"  ✓ Found: {url[:80]}...")
    
    if valid_urls:
        latest_url = select_latest_url(valid_urls)
        return {
            "school": school_name,
            "domain": domain,
            "conference": conference,
            "game_notes_urls": valid_urls[:10],  # Keep top 10
            "latest_game_notes_url": latest_url,
            "status": "found"
        }
    
    # If nothing found, try common patterns
    patterns = try_common_patterns(domain, school_name)
    for url in patterns[:5]:  # Limit pattern checks
        if check_url_exists(session, url):
            print(f"  ✓ Found via pattern: {url[:80]}...")
            return {
                "school": school_name,
                "domain": domain,
                "conference": conference,
                "game_notes_urls": [url],
                "latest_game_notes_url": url,
                "status": "found"
            }
    
    print(f"  ✗ Not found")
    return {
        "school": school_name,
        "domain": domain,
        "conference": conference,
        "game_notes_urls": [],
        "latest_game_notes_url": None,
        "status": "not_found"
    }


def main():
    """Main scraper function."""
    output_path = Path(__file__).parent.parent / "data" / "game_notes_urls.json"
    mapping_path = Path(__file__).parent.parent / "data" / "schools_game_notes.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing results if any
    results = []
    if output_path.exists():
        with open(output_path) as f:
            existing = json.load(f)
            results = existing.get("schools", [])
            print(f"Loaded {len(results)} existing results")

    for entry in results:
        if entry.get("game_notes_urls") and not entry.get("latest_game_notes_url"):
            entry["latest_game_notes_url"] = select_latest_url(entry["game_notes_urls"])
    
    # Get list of already processed schools
    processed = {r["school"] for r in results}
    
    # Process schools
    found_count = 0
    session = build_session()
    for school_name, domain, conference in FBS_SCHOOLS:
        if school_name in processed:
            print(f"Skipping {school_name} (already processed)")
            continue
            
        result = find_game_notes_for_school(session, school_name, domain, conference)
        results.append(result)
        
        if result["status"] == "found":
            found_count += 1
        
        # Save progress after each school
        with open(output_path, 'w') as f:
            json.dump({
                "metadata": {
                    "total_schools": len(FBS_SCHOOLS),
                    "processed": len(results),
                    "found": sum(1 for r in results if r["status"] == "found"),
                },
                "schools": results
            }, f, indent=2)

        with open(mapping_path, 'w') as f:
            mapping = {
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "schools": {
                    r["school"]: r.get("latest_game_notes_url")
                    for r in results
                    if r.get("latest_game_notes_url")
                }
            }
            json.dump(mapping, f, indent=2)
        
        time.sleep(0.5)  # Be nice to servers
    
    print(f"\n{'='*50}")
    print(f"Total: {len(results)} schools processed")
    print(f"Found: {sum(1 for r in results if r['status'] == 'found')}")
    print(f"Not found: {sum(1 for r in results if r['status'] == 'not_found')}")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
