# Coach Database Scripts

This directory contains automation scripts for the Coach Database project.

## Staff Update Monitor

### Overview

`staff_update_monitor.py` automatically monitors college football news sources for coaching staff changes and posts them to the Coach Database webhook.

### Quick Start

1. **Install dependencies:**
   ```bash
   pip install feedparser requests
   ```

2. **Set environment variables:**
   ```bash
   export OPENAI_API_KEY="your-openai-api-key"
   export WEBHOOK_API_KEY="f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d"
   export BRAVE_API_KEY="your-brave-api-key"  # Optional
   ```

3. **Run the script:**
   ```bash
   python staff_update_monitor.py
   ```

4. **Test with dry-run:**
   ```bash
   python staff_update_monitor.py --dry-run --verbose
   ```

### Configuration

Edit the `CONFIG` dictionary in `staff_update_monitor.py`:

```python
CONFIG = {
    'webhook_url': 'https://coach-database-api.fly.dev/api/webhooks/staff-update',
    'webhook_api_key': 'your-api-key',
    'openai_api_key': 'your-openai-key',
    'openai_model': 'gpt-3.5-turbo',  # or 'gpt-4' for better accuracy
    'rss_feeds': [
        'https://www.footballscoop.com/feed/',
        # Add more feeds...
    ],
    'state_retention_days': 90,
}
```

### Usage

```bash
# Normal run
python staff_update_monitor.py

# Dry run (don't post to webhook)
python staff_update_monitor.py --dry-run

# Verbose logging
python staff_update_monitor.py --verbose

# Clean up old state entries
python staff_update_monitor.py --cleanup

# Combine options
python staff_update_monitor.py --dry-run --verbose
```

### Cron Job Setup

To run automatically every hour:

1. **Create a wrapper script** (`~/clawd/coach-database/scripts/run_staff_monitor.sh`):
   ```bash
   #!/bin/bash
   cd /path/to/coach-database
   source venv/bin/activate  # If using virtual environment
   export OPENAI_API_KEY="your-key"
   export WEBHOOK_API_KEY="f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d"
   python scripts/staff_update_monitor.py >> logs/staff_monitor_cron.log 2>&1
   ```

2. **Make it executable:**
   ```bash
   chmod +x ~/clawd/coach-database/scripts/run_staff_monitor.sh
   ```

3. **Add to crontab:**
   ```bash
   crontab -e
   ```
   
   Add this line to run every hour:
   ```
   0 * * * * /path/to/coach-database/scripts/run_staff_monitor.sh
   ```
   
   Or every 4 hours:
   ```
   0 */4 * * * /path/to/coach-database/scripts/run_staff_monitor.sh
   ```

### State Management

The script maintains state in `data/staff_monitor_state.json`:

```json
{
  "processed_hashes": {
    "abc123...": "2026-02-12T10:30:00",
    "def456...": "2026-02-12T11:45:00"
  },
  "last_run": "2026-02-12T12:00:00"
}
```

- **Deduplication**: Each article is hashed and tracked to avoid reprocessing
- **Cleanup**: Old entries (>90 days) are automatically removed
- **Manual cleanup**: Run with `--cleanup` flag

### Logs

Logs are written to:
- `stdout` (console)
- `logs/staff_monitor.log` (file)

Log rotation is recommended if running frequently:

```bash
# Add to logrotate config
cat > /etc/logrotate.d/coach-db-monitor << EOF
/path/to/coach-database/logs/staff_monitor*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
EOF
```

### Monitoring

Check if the script is running properly:

```bash
# View recent logs
tail -f ~/clawd/coach-database/logs/staff_monitor.log

# Check last run time
cat ~/clawd/coach-database/data/staff_monitor_state.json | grep last_run

# View state file
cat ~/clawd/coach-database/data/staff_monitor_state.json | jq .
```

### Troubleshooting

#### No changes detected

- Check if RSS feeds are accessible
- Verify keyword matching is working
- Run with `--verbose` to see filtering decisions

#### OpenAI extraction failures

- Check API key is valid
- Review API quotas and rate limits
- Try switching from GPT-3.5 to GPT-4
- Check logs for parsing errors

#### Webhook POST failures

- Verify API key matches Coach DB `.env`
- Check endpoint URL is correct
- Test with curl:
  ```bash
  curl -X POST https://coach-database-api.fly.dev/api/webhooks/staff-update \
    -H "Content-Type: application/json" \
    -H "X-API-Key: f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d" \
    -d '{
      "school": "Test University",
      "name": "Test Coach",
      "role": "Head Coach",
      "source_url": "https://example.com/test"
    }'
  ```

#### State file issues

- Delete state file to start fresh: `rm data/staff_monitor_state.json`
- Run cleanup: `python staff_update_monitor.py --cleanup`

### Cost Estimates

Running every hour (24 times/day):

**With GPT-3.5-turbo:**
- ~500 tokens per article
- ~10 coaching articles/day
- ~5,000 tokens/day
- Cost: ~$0.005/day = ~$0.15/month

**With GPT-4:**
- ~500 tokens per article
- ~10 coaching articles/day
- ~5,000 tokens/day
- Cost: ~$0.25/day = ~$7.50/month

**Brave Search (optional):**
- Free tier: 2,000 queries/month
- Running 4 queries per hour = ~2,880/month
- Requires paid plan ($10/month for 15,000 queries)

**Recommendation**: Start with GPT-3.5 + RSS only (no Brave Search) = ~$0.15/month

### Adding More RSS Feeds

Edit the `rss_feeds` list in `CONFIG`:

```python
'rss_feeds': [
    'https://www.footballscoop.com/feed/',
    'https://www.cbssports.com/rss/headlines/college-football/',
    'https://www.on3.com/feed/',
    'https://saturdayblitz.com/feed/',
    'https://247sports.com/rss/',
    # Add university-specific feeds:
    'https://texassports.com/rss.aspx',
    'https://rolltide.com/rss.aspx',
    # Add more...
],
```

### Performance Tuning

**Reduce API calls:**
- Increase cron interval (every 4-6 hours)
- Reduce number of RSS feeds
- Disable Brave Search

**Improve accuracy:**
- Use GPT-4 instead of GPT-3.5
- Refine keyword matching
- Add custom extraction logic for specific sources

**Handle high volume:**
- Implement rate limiting
- Add backoff/retry logic
- Use async requests

## Other Scripts

### scrape_collegepressbox.py

Scrapes coaching staff data from CollegePressbox.com.

**Usage:**
```bash
python scripts/scrape_collegepressbox.py
```

### fix_duplicates.py

Cleans duplicate schools and coaches from the database.

**Usage:**
```bash
python scripts/fix_duplicates.py
```

## Contributing

When adding new scripts:
1. Add docstring with usage examples
2. Update this README
3. Include error handling and logging
4. Add configuration options
5. Create tests if applicable
