# Webhook Bridge for Coach DB Updates

## Goal
Add a webhook endpoint to the Coach Database API that allows external services (Pipedream, Zapier, etc.) to push coaching staff updates in real-time.

## Task
Add `POST /api/webhooks/staff-update` endpoint to `api/main.py` with authentication, validation, and deduplication.

## Requirements

### 1. Webhook Endpoint
Add to `api/main.py`:

```python
@app.post("/api/webhooks/staff-update")
async def webhook_staff_update(
    update: StaffUpdate,
    api_key: str = Header(..., alias="X-API-Key")
):
    """
    Webhook endpoint for external services to push coaching staff updates.
    
    Requires authentication via X-API-Key header.
    Validates payload, deduplicates, and updates database.
    """
```

### 2. Pydantic Models
Add to models section:

```python
class StaffUpdate(BaseModel):
    """Payload for staff update webhook"""
    school: str  # School name (will normalize to slug)
    coach_name: str
    position: Optional[str]
    hire_date: Optional[str] = None  # YYYY-MM-DD format
    departure_date: Optional[str] = None  # YYYY-MM-DD format
    source_url: Optional[str] = None  # Citation URL
    notes: Optional[str] = None  # Additional context
    
    class Config:
        json_schema_extra = {
            "example": {
                "school": "Michigan State",
                "coach_name": "John Smith",
                "position": "Offensive Coordinator",
                "hire_date": "2026-01-15",
                "source_url": "https://example.com/news/hiring"
            }
        }
```

### 3. Authentication
- Check `X-API-Key` header against environment variable `WEBHOOK_API_KEY`
- Raise `HTTPException(401, "Invalid API key")` if mismatch
- Add env var to README.md deployment section

### 4. Processing Logic

**Validation:**
- School must exist in `schools` table (normalize name to slug first)
- Coach name must not be empty
- Position should be standardized if possible (use existing `standardize_position()` if it exists)
- If hire_date/departure_date provided, validate YYYY-MM-DD format

**Deduplication:**
- Check if coach + school + position combo already exists in `coaches` table
- If exists and data matches: return `{"status": "no_change", "message": "Coach already in database"}`
- If exists but data differs: update record, return `{"status": "updated", ...}`
- If new: insert record, return `{"status": "created", ...}`

**Database Update:**
- Insert/update `coaches` table with normalized data
- Set `year` to current year if not provided
- Set `is_head_coach` based on position title (HC, Head Coach, etc.)
- Log update with timestamp

### 5. Response Format
```python
{
    "status": "created" | "updated" | "no_change" | "error",
    "message": "Human-readable result",
    "coach_id": 123,  # Only if created/updated
    "details": {...}  # Optional additional info
}
```

### 6. Error Handling
- 401: Invalid API key
- 400: Invalid payload (missing fields, bad format)
- 404: School not found
- 500: Database error

### 7. Environment Variable
Add to README.md and example env file:
```
WEBHOOK_API_KEY=your-secret-key-here
```

Generate a secure default for local dev (e.g., `openssl rand -hex 32`).

### 8. Testing
Add basic tests (can use pytest or just manual curl tests):
```bash
# Valid update
curl -X POST http://localhost:8000/api/webhooks/staff-update \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{"school": "Michigan State", "coach_name": "Test Coach", "position": "OC"}'

# Invalid key
curl -X POST http://localhost:8000/api/webhooks/staff-update \
  -H "Content-Type: application/json" \
  -H "X-API-Key: wrong" \
  -d '{"school": "Michigan State", "coach_name": "Test Coach", "position": "OC"}'

# Missing school
curl -X POST http://localhost:8000/api/webhooks/staff-update \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{"coach_name": "Test Coach", "position": "OC"}'
```

## Notes
- Keep it simple - don't overcomplicate deduplication logic
- Log all webhook calls (success and failure) for debugging
- Consider rate limiting in future (not required for v1)
- Pipedream integration will be set up separately once endpoint is ready

## Acceptance Criteria
- [ ] Endpoint added to api/main.py
- [ ] Authentication via X-API-Key works
- [ ] Validation catches missing/bad data
- [ ] Deduplication prevents duplicate entries
- [ ] Updates existing records when appropriate
- [ ] Returns proper status codes and messages
- [ ] README.md updated with WEBHOOK_API_KEY env var
- [ ] Tested with curl (at least 3 scenarios: valid, invalid key, bad payload)
