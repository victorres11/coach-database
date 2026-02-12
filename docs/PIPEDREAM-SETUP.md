# Pipedream Workflow Setup for Coach Database Staff Updates

This guide covers setting up automated coaching staff change monitoring using Pipedream workflows and/or a standalone Python script.

## Overview

The system monitors multiple news sources for college football coaching staff changes and automatically posts them to the Coach Database webhook endpoint.

**Webhook Endpoint:** `https://coach-database-api.fly.dev/api/webhooks/staff-update`  
**Authentication:** `X-API-Key` header  
**API Key:** `f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d`

## Setup Requirements

### 1. Configure API Key in Coach Database

Add the webhook API key to your Coach Database API's `.env` file:

```bash
# On the deployment machine or Fly.io secrets
fly secrets set WEBHOOK_API_KEY=f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d -a coach-database-api
```

Or locally in `.env`:
```
WEBHOOK_API_KEY=f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d
```

## Approach 1: Pipedream Workflow (Recommended)

### What is Pipedream?

Pipedream is a serverless integration platform that allows you to:
- Monitor RSS feeds continuously
- Trigger workflows on new items
- Call APIs and process data with Node.js or Python
- Run on a schedule (cron)
- Free tier: 333 credits/day (~10,000 invocations/month)

### Step 1: Create Pipedream Account

1. Go to https://pipedream.com
2. Sign up with GitHub or email
3. Verify your account

### Step 2: Create a New Workflow

1. Click **"New Workflow"**
2. Choose a trigger:
   - **RSS Feed** (monitors a feed for new items)
   - **HTTP / Webhook** (for manual testing)
   - **Cron Scheduler** (run on a schedule)

### Step 3: RSS Feed Sources

Based on research, these are the best sources for coaching staff changes:

#### Primary Sources (Recommended)

1. **FootballScoop**
   - Main site: https://www.footballscoop.com
   - RSS: `https://www.footballscoop.com/feed/`
   - Best for: Breaking coaching news, staff changes
   - Update frequency: Multiple times daily

2. **247Sports**
   - Main site: https://247sports.com
   - RSS: Check individual team pages or `https://247sports.com/rss/`
   - Good for: Team-specific updates

3. **CBS Sports - College Football**
   - RSS: `https://www.cbssports.com/rss/headlines/college-football/`
   - Good for: Major coaching changes

4. **On3**
   - Main site: https://www.on3.com
   - RSS: `https://www.on3.com/feed/`
   - Good for: Recruiting and coaching news

5. **Athletic Department Press Releases**
   - Each school publishes their own
   - Example: `https://texassports.com/rss.aspx`
   - Requires monitoring multiple feeds (130+ FBS schools)

#### Secondary Sources

- **Saturday Blitz**: `https://saturdayblitz.com/feed/`
- **Sporting News**: `https://www.sportingnews.com/us/rss`
- **TigerDroppings Coaching Changes Forum**: (no RSS, would need scraping)

### Step 4: Workflow Structure

```
[RSS Feed Trigger]
    ↓
[Filter New Items]
    ↓
[Parse Article with OpenAI]
    ↓
[Extract Structured Data]
    ↓
[POST to Webhook]
    ↓
[Log Results]
```

### Step 5: Pipedream Workflow Code

Here's a sample workflow configuration:

#### Trigger: RSS Feed

```javascript
// Step 1: RSS Feed Trigger
// Configure in Pipedream UI:
// - Feed URL: https://www.footballscoop.com/feed/
// - Polling interval: Every 15 minutes
```

#### Step 2: Filter Coaching News

```javascript
export default defineComponent({
  async run({ steps, $ }) {
    const item = steps.trigger.event;
    const title = item.title.toLowerCase();
    const description = (item.description || '').toLowerCase();
    
    // Keywords that indicate coaching staff changes
    const keywords = [
      'coaching', 'coach', 'hire', 'fired', 'resign', 'promotion',
      'coordinator', 'assistant', 'offensive', 'defensive', 'special teams',
      'staff', 'appointment', 'named', 'joins', 'leaving', 'departure'
    ];
    
    const isCoachingNews = keywords.some(keyword => 
      title.includes(keyword) || description.includes(keyword)
    );
    
    if (!isCoachingNews) {
      $.flow.exit('Not coaching-related news');
    }
    
    return item;
  }
});
```

#### Step 3: Extract Data with OpenAI

```javascript
import { Configuration, OpenAIApi } from 'openai';

export default defineComponent({
  props: {
    openai: {
      type: "app",
      app: "openai",
    }
  },
  async run({ steps, $ }) {
    const configuration = new Configuration({
      apiKey: this.openai.$auth.api_key,
    });
    const openai = new OpenAIApi(configuration);
    
    const article = {
      title: steps.trigger.event.title,
      content: steps.trigger.event.description || steps.trigger.event.content,
      url: steps.trigger.event.link,
      pubDate: steps.trigger.event.pubDate
    };
    
    const prompt = `Extract college football coaching staff change information from this article.

Article Title: ${article.title}
Article Content: ${article.content}
Article URL: ${article.url}

Extract the following information in JSON format:
- school: Full school name (e.g., "Texas Longhorns", "Alabama Crimson Tide")
- conference: Conference name (e.g., "SEC", "Big Ten", "Big 12")
- role: Specific coaching role (e.g., "Offensive Coordinator", "Defensive Line Coach", "Head Coach")
- name: Full name of the coach
- action: Type of change ("hired", "fired", "resigned", "promoted")
- effective_date: Date when the change is effective (YYYY-MM-DD format, or null if not specified)

If multiple coaches are mentioned, extract all of them as an array.
If you cannot extract all required fields, return null for that change.

Return ONLY valid JSON, no other text.`;

    const completion = await openai.createChatCompletion({
      model: "gpt-4",
      messages: [
        { role: "system", content: "You are a data extraction assistant. Extract structured information from college football coaching news articles. Return only valid JSON." },
        { role: "user", content: prompt }
      ],
      temperature: 0.3,
      max_tokens: 1000
    });
    
    const response = completion.data.choices[0].message.content;
    
    try {
      const extracted = JSON.parse(response);
      return {
        source_url: article.url,
        pub_date: article.pubDate,
        changes: Array.isArray(extracted) ? extracted : [extracted]
      };
    } catch (error) {
      console.error('Failed to parse OpenAI response:', response);
      $.flow.exit('Failed to extract structured data');
    }
  }
});
```

#### Step 4: Post to Webhook

```javascript
import { axios } from "@pipedream/platform";

export default defineComponent({
  async run({ steps, $ }) {
    const changes = steps.extract_data.changes;
    const apiKey = 'f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d';
    
    const results = [];
    
    for (const change of changes) {
      if (!change || !change.school || !change.name) {
        console.log('Skipping incomplete change:', change);
        continue;
      }
      
      const payload = {
        school: change.school,
        conference: change.conference || null,
        role: change.role || null,
        name: change.name,
        source_url: steps.extract_data.source_url,
        effective_date: change.effective_date || null
      };
      
      try {
        const response = await axios($, {
          method: 'POST',
          url: 'https://coach-database-api.fly.dev/api/webhooks/staff-update',
          headers: {
            'Content-Type': 'application/json',
            'X-API-Key': apiKey
          },
          data: payload
        });
        
        results.push({
          success: true,
          coach: change.name,
          response: response
        });
        
        console.log(`✅ Posted update for ${change.name} at ${change.school}`);
      } catch (error) {
        results.push({
          success: false,
          coach: change.name,
          error: error.message
        });
        
        console.error(`❌ Failed to post update for ${change.name}:`, error.message);
      }
    }
    
    return results;
  }
});
```

### Step 6: Testing the Workflow

1. **Test with manual trigger**: Use the "Test" button in Pipedream
2. **Monitor logs**: Check the workflow execution logs
3. **Verify webhook**: Check Coach Database logs for incoming requests
4. **Test API key**: Ensure authentication works

### Step 7: Deploy and Monitor

1. **Enable workflow**: Toggle the workflow to "On"
2. **Set alert notifications**: Configure email/Slack alerts for failures
3. **Monitor daily**: Check workflow executions in Pipedream dashboard
4. **Review data quality**: Periodically review the extracted data for accuracy

## Approach 2: Standalone Python Script (Alternative)

If Pipedream doesn't work out or you prefer a self-hosted solution, use the Python script provided in `scripts/staff_update_monitor.py`.

### Advantages of Python Script

- ✅ Full control over execution
- ✅ Can run as cron job
- ✅ No external service dependencies
- ✅ Can customize data extraction logic
- ✅ Local state management

### Disadvantages

- ❌ Requires server/machine to run
- ❌ Need to manage cron scheduling
- ❌ Need to handle failures manually

See `scripts/staff_update_monitor.py` for implementation.

## Deduplication Strategy

Both approaches include deduplication to avoid reporting the same change multiple times:

1. **Content-based hashing**: Generate a hash from (school + name + role + date)
2. **State tracking**: Store processed hashes in a JSON file or database
3. **Expiry**: Remove old hashes after 90 days to keep state file small

## Expected Data Format

The webhook expects this JSON structure:

```json
{
  "school": "Texas Longhorns",
  "conference": "SEC",
  "role": "Offensive Coordinator",
  "name": "John Smith",
  "source_url": "https://www.footballscoop.com/article/...",
  "effective_date": "2026-02-15"
}
```

**Required fields**: `school`, `name`  
**Optional fields**: `conference`, `role`, `source_url`, `effective_date`

## Monitoring and Maintenance

### Daily Checks

- [ ] Review workflow execution count
- [ ] Check for failed executions
- [ ] Verify data quality in Coach Database
- [ ] Monitor API rate limits

### Weekly Checks

- [ ] Review deduplication state file size
- [ ] Check for new RSS feeds to add
- [ ] Update keyword filters if needed
- [ ] Review false positives/negatives

### Monthly Checks

- [ ] Clean up old state data (>90 days)
- [ ] Review OpenAI token usage
- [ ] Optimize extraction prompts
- [ ] Update school/conference mappings

## Troubleshooting

### Workflow not triggering

- Check RSS feed URL is valid
- Verify polling interval is set
- Check Pipedream credit balance

### Data extraction failures

- Review OpenAI prompt clarity
- Check API key validity
- Increase temperature for more flexible parsing

### Webhook POST failures

- Verify API key matches Coach DB `.env`
- Check endpoint URL is correct
- Review Coach DB logs for error messages
- Test with curl:

```bash
curl -X POST https://coach-database-api.fly.dev/api/webhooks/staff-update \
  -H "Content-Type: application/json" \
  -H "X-API-Key: f0db180c08995ba77850b8aa4caccb72a02d9751f38ce7b570a5d95bc7c41c5d" \
  -d '{
    "school": "Test University",
    "conference": "Test Conference",
    "role": "Head Coach",
    "name": "Test Coach",
    "source_url": "https://example.com/test",
    "effective_date": "2026-02-12"
  }'
```

## Cost Estimates

### Pipedream

- Free tier: 333 credits/day
- Typical workflow: ~1-2 credits per execution
- With 4 RSS feeds polling every 15 minutes: ~384 executions/day = ~768 credits/day
- **Recommendation**: Paid plan ($19/month for 10,000 credits/day)

### OpenAI API

- GPT-4 input: ~$0.03 per 1K tokens
- GPT-4 output: ~$0.06 per 1K tokens
- Estimated: ~500 tokens per article
- 50 articles/day = ~25,000 tokens = ~$1.50/day = ~$45/month

**Total estimated cost**: ~$64/month for fully automated system

## Alternative: Cheaper GPT-3.5 Option

Replace GPT-4 with GPT-3.5-turbo in the extraction step:
- Cost: ~$0.001 per 1K tokens (60x cheaper)
- 50 articles/day = ~$0.025/day = ~$0.75/month
- **Trade-off**: Slightly lower extraction accuracy

## Next Steps

1. ✅ Set `WEBHOOK_API_KEY` in Coach Database API environment
2. ⬜ Create Pipedream account
3. ⬜ Set up first workflow with FootballScoop RSS feed
4. ⬜ Test with sample articles
5. ⬜ Add additional RSS feeds
6. ⬜ Monitor for 1 week and refine
7. ⬜ Set up alerting for failures

## Resources

- [Pipedream Documentation](https://pipedream.com/docs/)
- [Pipedream RSS Component](https://pipedream.com/apps/rss)
- [OpenAI API Docs](https://platform.openai.com/docs)
- [FootballScoop RSS Feed](https://www.footballscoop.com/feed/)
