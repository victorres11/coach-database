#!/usr/bin/env python3
"""
Automated College Football Coaching Staff Change Monitor

This script:
1. Monitors RSS feeds for coaching staff changes
2. Uses Brave Search API to find recent coaching changes
3. Extracts structured data using OpenAI API
4. Posts changes to Coach Database webhook
5. Maintains deduplication state to avoid duplicates

Usage:
    python staff_update_monitor.py [--dry-run] [--verbose]

Configuration:
    Set environment variables or edit CONFIG section below:
    - WEBHOOK_API_KEY: API key for Coach Database webhook
    - OPENAI_API_KEY: OpenAI API key for data extraction
    - BRAVE_API_KEY: Brave Search API key (optional)
"""

import os
import sys
import json
import hashlib
import logging
import argparse
import feedparser
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    # Webhook endpoint
    'webhook_url': 'https://coach-database-api.fly.dev/api/webhooks/staff-update',
    'webhook_api_key': os.getenv('WEBHOOK_API_KEY', 'f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d'),
    
    # OpenAI API
    'openai_api_key': os.getenv('OPENAI_API_KEY', ''),
    'openai_model': 'gpt-3.5-turbo',  # Use gpt-4 for better accuracy (more expensive)
    
    # Brave Search API (optional - for additional discovery)
    'brave_api_key': os.getenv('BRAVE_API_KEY', ''),
    
    # State file for deduplication
    'state_file': Path(__file__).parent.parent / 'data' / 'staff_monitor_state.json',
    
    # RSS Feeds to monitor
    'rss_feeds': [
        'https://www.footballscoop.com/feed/',
        'https://www.cbssports.com/rss/headlines/college-football/',
        'https://www.on3.com/feed/',
        'https://saturdayblitz.com/feed/',
        # Add more feeds as needed
    ],
    
    # Search queries for Brave Search
    'search_queries': [
        'college football coaching changes',
        'CFB coordinator hire',
        'college football staff changes',
        'FBS coaching news',
    ],
    
    # Keywords that indicate coaching staff changes
    'coaching_keywords': [
        'coaching', 'coach', 'hire', 'hired', 'fired', 'resign', 'resigned',
        'promotion', 'promoted', 'coordinator', 'assistant', 'offensive',
        'defensive', 'special teams', 'staff', 'appointment', 'appointed',
        'named', 'joins', 'joining', 'leaving', 'departure', 'departs'
    ],
    
    # Days to keep state entries before cleanup
    'state_retention_days': 90,
}

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent.parent / 'logs' / 'staff_monitor.log')
    ]
)
logger = logging.getLogger('staff_monitor')

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

class StateManager:
    """Manages deduplication state using a JSON file"""
    
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load state from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load state file: {e}")
                return {'processed_hashes': {}, 'last_run': None}
        return {'processed_hashes': {}, 'last_run': None}
    
    def _save_state(self):
        """Save state to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state file: {e}")
    
    def is_processed(self, content_hash: str) -> bool:
        """Check if content hash has been processed"""
        return content_hash in self.state['processed_hashes']
    
    def mark_processed(self, content_hash: str):
        """Mark content hash as processed"""
        self.state['processed_hashes'][content_hash] = datetime.now().isoformat()
        self._save_state()
    
    def cleanup_old_entries(self, days: int = 90):
        """Remove entries older than specified days"""
        cutoff = datetime.now() - timedelta(days=days)
        old_hashes = []
        
        for hash_key, timestamp in self.state['processed_hashes'].items():
            try:
                entry_date = datetime.fromisoformat(timestamp)
                if entry_date < cutoff:
                    old_hashes.append(hash_key)
            except:
                old_hashes.append(hash_key)
        
        for hash_key in old_hashes:
            del self.state['processed_hashes'][hash_key]
        
        if old_hashes:
            logger.info(f"Cleaned up {len(old_hashes)} old state entries")
            self._save_state()
    
    def update_last_run(self):
        """Update last run timestamp"""
        self.state['last_run'] = datetime.now().isoformat()
        self._save_state()

# ============================================================================
# RSS FEED MONITORING
# ============================================================================

def fetch_rss_feeds(feeds: List[str]) -> List[Dict]:
    """Fetch and parse RSS feeds"""
    articles = []
    
    for feed_url in feeds:
        try:
            logger.info(f"Fetching RSS feed: {feed_url}")
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries[:20]:  # Limit to 20 most recent
                article = {
                    'title': entry.get('title', ''),
                    'link': entry.get('link', ''),
                    'description': entry.get('description', entry.get('summary', '')),
                    'published': entry.get('published', ''),
                    'source': feed_url
                }
                articles.append(article)
            
            logger.info(f"Found {len(feed.entries[:20])} articles from {feed_url}")
        except Exception as e:
            logger.error(f"Failed to fetch RSS feed {feed_url}: {e}")
    
    return articles

# ============================================================================
# BRAVE SEARCH INTEGRATION
# ============================================================================

def search_brave(query: str, api_key: str, days: int = 7) -> List[Dict]:
    """Search Brave for recent articles"""
    if not api_key:
        logger.warning("Brave API key not configured, skipping search")
        return []
    
    articles = []
    freshness = 'pw' if days <= 7 else 'pm'  # past week or past month
    
    try:
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key
        }
        params = {
            "q": query,
            "freshness": freshness,
            "count": 10
        }
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        results = response.json()
        
        for result in results.get('web', {}).get('results', []):
            article = {
                'title': result.get('title', ''),
                'link': result.get('url', ''),
                'description': result.get('description', ''),
                'published': result.get('age', ''),
                'source': 'brave_search'
            }
            articles.append(article)
        
        logger.info(f"Found {len(articles)} articles from Brave search: {query}")
    except Exception as e:
        logger.error(f"Failed to search Brave: {e}")
    
    return articles

# ============================================================================
# CONTENT FILTERING
# ============================================================================

def is_coaching_related(article: Dict, keywords: List[str]) -> bool:
    """Check if article is related to coaching changes"""
    text = f"{article['title']} {article['description']}".lower()
    return any(keyword in text for keyword in keywords)

def generate_content_hash(article: Dict) -> str:
    """Generate unique hash for article content"""
    # Use URL as primary identifier, fallback to title+description
    content = article.get('link', '') or f"{article['title']}{article['description']}"
    return hashlib.md5(content.encode()).hexdigest()

# ============================================================================
# DATA EXTRACTION WITH OPENAI
# ============================================================================

def extract_coaching_changes(article: Dict, api_key: str, model: str) -> Optional[List[Dict]]:
    """Extract structured coaching change data using OpenAI"""
    if not api_key:
        logger.error("OpenAI API key not configured")
        return None
    
    prompt = f"""Extract college football coaching staff change information from this article.

Article Title: {article['title']}
Article Content: {article['description']}
Article URL: {article['link']}

Extract the following information in JSON format for EACH coaching change mentioned:
- school: Full school name (e.g., "Texas Longhorns", "Alabama Crimson Tide")
- conference: Conference name (e.g., "SEC", "Big Ten", "Big 12", "ACC", etc.)
- role: Specific coaching role (e.g., "Offensive Coordinator", "Defensive Line Coach", "Head Coach")
- name: Full name of the coach
- action: Type of change ("hired", "fired", "resigned", "promoted")
- effective_date: Date when effective (YYYY-MM-DD format, or null if not specified)

Return an array of changes. If multiple coaches are mentioned, extract all of them.
If you cannot extract all required fields, skip that change.
Return ONLY valid JSON array, no other text or markdown.

Example format:
[
  {{
    "school": "Texas Longhorns",
    "conference": "SEC",
    "role": "Offensive Coordinator",
    "name": "John Smith",
    "action": "hired",
    "effective_date": "2026-02-15"
  }}
]"""

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a data extraction assistant. Extract structured information from college football coaching news articles. Return only valid JSON arrays, no markdown or other text."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,
            "max_tokens": 1000
        }
        
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data
        )
        response.raise_for_status()
        
        result = response.json()
        content = result['choices'][0]['message']['content'].strip()
        
        # Remove markdown code blocks if present
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
            content = content.strip()
        
        changes = json.loads(content)
        
        # Ensure it's a list
        if isinstance(changes, dict):
            changes = [changes]
        
        # Add source URL to each change
        for change in changes:
            change['source_url'] = article['link']
        
        logger.info(f"Extracted {len(changes)} coaching changes from article: {article['title']}")
        return changes
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse OpenAI response as JSON: {e}")
        logger.debug(f"Response content: {content}")
        return None
    except Exception as e:
        logger.error(f"Failed to extract data with OpenAI: {e}")
        return None

# ============================================================================
# WEBHOOK POSTING
# ============================================================================

def post_to_webhook(change: Dict, webhook_url: str, api_key: str, dry_run: bool = False) -> bool:
    """Post coaching change to webhook endpoint"""
    
    # Validate required fields
    if not change.get('school') or not change.get('name'):
        logger.warning(f"Skipping incomplete change: {change}")
        return False
    
    payload = {
        'school': change['school'],
        'conference': change.get('conference'),
        'role': change.get('role'),
        'name': change['name'],
        'source_url': change.get('source_url'),
        'effective_date': change.get('effective_date')
    }
    
    if dry_run:
        logger.info(f"[DRY RUN] Would post: {json.dumps(payload, indent=2)}")
        return True
    
    try:
        headers = {
            'Content-Type': 'application/json',
            'X-API-Key': api_key
        }
        
        response = requests.post(webhook_url, headers=headers, json=payload)
        response.raise_for_status()
        
        logger.info(f"✅ Posted update for {change['name']} at {change['school']}")
        return True
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ HTTP error posting update for {change['name']}: {e}")
        logger.debug(f"Response: {e.response.text if e.response else 'No response'}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to post update for {change['name']}: {e}")
        return False

# ============================================================================
# MAIN PROCESSING LOOP
# ============================================================================

def process_articles(articles: List[Dict], state: StateManager, config: Dict, dry_run: bool = False) -> Dict:
    """Process articles and extract coaching changes"""
    stats = {
        'total_articles': len(articles),
        'coaching_related': 0,
        'already_processed': 0,
        'extraction_attempts': 0,
        'extraction_successes': 0,
        'changes_found': 0,
        'changes_posted': 0,
        'errors': 0
    }
    
    for article in articles:
        # Filter for coaching-related content
        if not is_coaching_related(article, config['coaching_keywords']):
            continue
        
        stats['coaching_related'] += 1
        
        # Check if already processed
        content_hash = generate_content_hash(article)
        if state.is_processed(content_hash):
            logger.debug(f"Already processed: {article['title']}")
            stats['already_processed'] += 1
            continue
        
        # Extract coaching changes
        stats['extraction_attempts'] += 1
        changes = extract_coaching_changes(
            article,
            config['openai_api_key'],
            config['openai_model']
        )
        
        if not changes:
            stats['errors'] += 1
            continue
        
        stats['extraction_successes'] += 1
        stats['changes_found'] += len(changes)
        
        # Post each change to webhook
        for change in changes:
            if post_to_webhook(change, config['webhook_url'], config['webhook_api_key'], dry_run):
                stats['changes_posted'] += 1
        
        # Mark as processed
        state.mark_processed(content_hash)
    
    return stats

# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Monitor coaching staff changes and post to webhook')
    parser.add_argument('--dry-run', action='store_true', help='Run without posting to webhook')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--cleanup', action='store_true', help='Clean up old state entries and exit')
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Ensure logs directory exists
    logs_dir = Path(__file__).parent.parent / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # Ensure data directory exists
    data_dir = Path(__file__).parent.parent / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize state manager
    state = StateManager(CONFIG['state_file'])
    
    # Cleanup old entries if requested
    if args.cleanup:
        state.cleanup_old_entries(CONFIG['state_retention_days'])
        logger.info("State cleanup complete")
        return
    
    logger.info("="*60)
    logger.info("Starting coaching staff change monitor")
    logger.info(f"Dry run mode: {args.dry_run}")
    logger.info("="*60)
    
    # Collect articles from all sources
    all_articles = []
    
    # Fetch RSS feeds
    logger.info("Fetching RSS feeds...")
    rss_articles = fetch_rss_feeds(CONFIG['rss_feeds'])
    all_articles.extend(rss_articles)
    
    # Search with Brave (if API key configured)
    if CONFIG['brave_api_key']:
        logger.info("Searching with Brave API...")
        for query in CONFIG['search_queries']:
            brave_articles = search_brave(query, CONFIG['brave_api_key'])
            all_articles.extend(brave_articles)
    
    logger.info(f"Collected {len(all_articles)} total articles")
    
    # Process articles
    stats = process_articles(all_articles, state, CONFIG, dry_run=args.dry_run)
    
    # Update last run time
    state.update_last_run()
    
    # Periodic cleanup
    state.cleanup_old_entries(CONFIG['state_retention_days'])
    
    # Print summary
    logger.info("="*60)
    logger.info("Processing Summary:")
    logger.info(f"  Total articles: {stats['total_articles']}")
    logger.info(f"  Coaching-related: {stats['coaching_related']}")
    logger.info(f"  Already processed: {stats['already_processed']}")
    logger.info(f"  Extraction attempts: {stats['extraction_attempts']}")
    logger.info(f"  Extraction successes: {stats['extraction_successes']}")
    logger.info(f"  Changes found: {stats['changes_found']}")
    logger.info(f"  Changes posted: {stats['changes_posted']}")
    logger.info(f"  Errors: {stats['errors']}")
    logger.info("="*60)
    
    return stats

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)
