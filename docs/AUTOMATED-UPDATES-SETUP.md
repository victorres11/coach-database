# Automated Staff Updates Setup Guide

This guide walks through setting up automated coaching staff change monitoring for the Coach Database.

## Overview

Two approaches are available:

1. **Pipedream Workflow** (Recommended) - Serverless, managed, easy to set up
2. **Python Script + Cron** (Alternative) - Self-hosted, full control

Both approaches:
- Monitor RSS feeds for coaching news
- Extract structured data using AI
- POST to Coach Database webhook
- Include deduplication logic

## Prerequisites

### Required
- OpenAI API key (for data extraction)
- Webhook API key (generated below)

### Optional
- Brave Search API key (for additional discovery)
- Pipedream account (for managed approach)

## Step 1: Configure Webhook API Key

A secure webhook API key has been generated:
```
f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d
```

### Set in Coach Database API

**Option A: Fly.io Deployment**
```bash
fly secrets set WEBHOOK_API_KEY=f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d -a coach-database-api
```

**Option B: Local Development**
```bash
cd ~/clawd/coach-database
cp .env.example .env
# Edit .env and set WEBHOOK_API_KEY
```

**Option C: Vercel/Other Platforms**
Add environment variable through your platform's dashboard:
- Variable name: `WEBHOOK_API_KEY`
- Value: `f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d`

### Verify Webhook Endpoint

Test the webhook is working:
```bash
curl -X POST https://coach-database-api.fly.dev/api/webhooks/staff-update \
  -H "Content-Type: application/json" \
  -H "X-API-Key: f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d" \
  -d '{
    "school": "Test University",
    "conference": "Test Conference",
    "role": "Test Coach",
    "name": "John Doe",
    "source_url": "https://example.com/test",
    "effective_date": "2026-02-12"
  }'
```

Expected response: `200 OK` with success message

## Step 2: Choose Your Approach

### Approach A: Pipedream Workflow (Recommended)

**Pros:**
- ✅ No server needed
- ✅ Built-in monitoring and logs
- ✅ Easy to set up and maintain
- ✅ Handles RSS polling automatically
- ✅ Visual workflow builder

**Cons:**
- ❌ Requires Pipedream account
- ❌ Free tier may not be sufficient (~$19/month recommended)
- ❌ Less control over execution

**Setup Instructions:** See `PIPEDREAM-SETUP.md`

**Quick Start:**
1. Create Pipedream account: https://pipedream.com
2. Import workflow from `pipedream-workflow-sample.json`
3. Connect OpenAI account
4. Configure RSS feed trigger
5. Deploy and enable

**Cost:** ~$19/month (Pipedream) + ~$1-7/month (OpenAI)

---

### Approach B: Python Script + Cron

**Pros:**
- ✅ Full control over execution
- ✅ No external dependencies
- ✅ Can customize any aspect
- ✅ Lower cost (only OpenAI API)

**Cons:**
- ❌ Requires server/machine
- ❌ Need to manage cron scheduling
- ❌ Manual monitoring required
- ❌ More maintenance overhead

**Setup Instructions:**

#### 1. Install Dependencies

```bash
cd ~/clawd/coach-database
python3 -m venv venv
source venv/bin/activate
pip install feedparser requests
```

#### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and set:
# - OPENAI_API_KEY
# - WEBHOOK_API_KEY (already set)
# - BRAVE_API_KEY (optional)
```

#### 3. Test the Script

```bash
# Dry run (won't post to webhook)
python scripts/staff_update_monitor.py --dry-run --verbose

# Real run
python scripts/staff_update_monitor.py
```

#### 4. Set Up Cron Job

```bash
# Edit the wrapper script with your paths
nano scripts/run_staff_monitor.sh

# Make it executable (already done)
chmod +x scripts/run_staff_monitor.sh

# Add to crontab
crontab -e
```

Add this line to run every 4 hours:
```
0 */4 * * * /Users/vicmacmini/clawd/coach-database/scripts/run_staff_monitor.sh
```

Or every hour during peak times (9am-6pm):
```
0 9-18 * * * /Users/vicmacmini/clawd/coach-database/scripts/run_staff_monitor.sh
```

#### 5. Monitor Execution

```bash
# Check logs
tail -f ~/clawd/coach-database/logs/staff_monitor.log

# Check cron logs
tail -f ~/clawd/coach-database/logs/staff_monitor_cron.log

# View state
cat ~/clawd/coach-database/data/staff_monitor_state.json | jq .
```

**Cost:** ~$0.15-7.50/month (OpenAI only, depending on GPT-3.5 vs GPT-4)

## Step 3: Configure RSS Feeds

Both approaches monitor these RSS feeds by default:

1. **FootballScoop** - `https://www.footballscoop.com/feed/`
   - Best source for coaching changes
   - Updates multiple times daily

2. **CBS Sports** - `https://www.cbssports.com/rss/headlines/college-football/`
   - Major coaching announcements

3. **On3** - `https://www.on3.com/feed/`
   - Recruiting and coaching news

4. **Saturday Blitz** - `https://saturdayblitz.com/feed/`
   - College football news and analysis

### Adding More Feeds

**Pipedream:** Duplicate the workflow and change the RSS feed URL

**Python Script:** Edit `CONFIG['rss_feeds']` in `staff_update_monitor.py`

### Recommended Additional Feeds

- **247Sports**: Check individual team/conference pages for RSS links
- **Athletic Department Sites**: Each school publishes press releases
  - Example: `https://texassports.com/rss.aspx`
  - Example: `https://rolltide.com/rss.aspx`

## Step 4: Monitor and Maintain

### Daily Checks

- [ ] Review workflow execution count / cron logs
- [ ] Check for extraction failures
- [ ] Verify data quality in Coach Database
- [ ] Monitor API rate limits (OpenAI)

### Weekly Checks

- [ ] Review false positives/negatives
- [ ] Check deduplication state file size
- [ ] Update keyword filters if needed
- [ ] Add new RSS feeds as discovered

### Monthly Checks

- [ ] Clean up old state data (automated for Python script)
- [ ] Review OpenAI token usage and costs
- [ ] Optimize extraction prompts
- [ ] Update school/conference mappings

## Troubleshooting

### No changes detected

**Symptoms:**
- Script runs but finds 0 coaching-related articles
- Workflow executes but filters out all items

**Solutions:**
- Check RSS feeds are accessible (test in browser)
- Review keyword matching (run with `--verbose`)
- Verify feeds have recent content
- Try different RSS feeds

### Data extraction failures

**Symptoms:**
- Articles detected but extraction fails
- OpenAI returns invalid JSON
- Changes have missing required fields

**Solutions:**
- Check OpenAI API key is valid
- Review rate limits (429 errors)
- Try GPT-4 for better accuracy
- Refine extraction prompt
- Check article content quality

### Webhook POST failures

**Symptoms:**
- HTTP 401/403 errors
- HTTP 400 errors
- No changes appearing in database

**Solutions:**
- Verify API key matches Coach DB environment
- Check endpoint URL is correct
- Test with curl command (see Step 1)
- Review Coach DB API logs
- Ensure required fields (school, name) are present

### State file corruption

**Symptoms:**
- Script crashes on startup
- Duplicates being re-reported
- State cleanup fails

**Solutions:**
```bash
# Delete and restart
rm ~/clawd/coach-database/data/staff_monitor_state.json

# Or just clean up
python scripts/staff_update_monitor.py --cleanup
```

## Performance Tuning

### Reduce Costs

**Use GPT-3.5 instead of GPT-4:**
- Edit script: `'openai_model': 'gpt-3.5-turbo'`
- 60x cheaper (~$0.15/month vs $7.50/month)
- Slightly lower accuracy

**Reduce Execution Frequency:**
- Run every 6-12 hours instead of hourly
- Fewer OpenAI API calls
- Still catches most changes within a day

**Disable Brave Search:**
- Set `BRAVE_API_KEY=""` or comment out search queries
- Saves $10/month (or avoids rate limits on free tier)
- RSS feeds are usually sufficient

### Improve Accuracy

**Use GPT-4:**
- Better at extracting structured data
- Fewer parsing errors
- More expensive (~$7.50/month)

**Refine Keywords:**
- Add sport-specific terms
- Filter out false positives
- Test with `--dry-run` to see what gets filtered

**Add Custom Extraction Logic:**
- For specific sources (e.g., 247Sports format)
- Parse HTML if RSS description is truncated
- Use regex for known patterns

### Handle High Volume

**Use Async/Concurrent Requests:**
- Process multiple articles simultaneously
- Reduce total execution time

**Implement Rate Limiting:**
- Respect OpenAI API rate limits
- Add backoff/retry logic
- Queue articles if rate limited

**Optimize Deduplication:**
- Use database instead of JSON file
- Add bloom filter for fast lookups
- Index on content hash

## Security Considerations

### API Key Management

- ✅ Webhook API key stored in environment variables (not code)
- ✅ `.env` file gitignored
- ✅ Fly.io secrets encrypted at rest
- ⚠️ Rotate webhook key if compromised:
  ```bash
  # Generate new key
  openssl rand -hex 32
  
  # Update Coach DB environment
  fly secrets set WEBHOOK_API_KEY=<new-key> -a coach-database-api
  
  # Update Pipedream/script config
  ```

### Access Control

- Webhook endpoint requires valid API key
- No public access to state files
- Logs don't contain sensitive data

## Cost Summary

### Option A: Pipedream + GPT-3.5
- Pipedream: $19/month (or free tier with limitations)
- OpenAI: ~$0.15/month
- **Total: ~$19/month**

### Option B: Pipedream + GPT-4
- Pipedream: $19/month
- OpenAI: ~$7.50/month
- **Total: ~$27/month**

### Option C: Python Cron + GPT-3.5 (Cheapest)
- Server: $0 (if already have)
- OpenAI: ~$0.15/month
- **Total: ~$0.15/month**

### Option D: Python Cron + GPT-4 (Best Quality)
- Server: $0 (if already have)
- OpenAI: ~$7.50/month
- **Total: ~$7.50/month**

**Recommendation:** Start with Option C (Python + GPT-3.5) to test, upgrade to GPT-4 if accuracy isn't good enough.

## Next Steps

1. ✅ Set `WEBHOOK_API_KEY` in Coach Database API
2. ⬜ Choose approach (Pipedream or Python script)
3. ⬜ Set up monitoring (Pipedream workflow or cron job)
4. ⬜ Test with dry-run
5. ⬜ Enable and monitor for 1 week
6. ⬜ Refine keywords and prompts based on results
7. ⬜ Add more RSS feeds as needed
8. ⬜ Set up alerting for failures

## Support

- **Pipedream Setup:** See `PIPEDREAM-SETUP.md`
- **Python Script Details:** See `scripts/README.md`
- **Webhook API:** See Coach Database API docs
- **Issues:** Create a GitHub issue with logs

## Resources

- [Pipedream Documentation](https://pipedream.com/docs/)
- [OpenAI API Documentation](https://platform.openai.com/docs)
- [Coach Database API](https://coach-database-api.fly.dev)
- [FootballScoop RSS](https://www.footballscoop.com/feed/)
