# coachdb-client

Tiny Python client for the Coach DB API.

## Install (from this repo)

```bash
pip install -e ./client
```

## Usage

```python
from coachdb_client import CoachDBClient

client = CoachDBClient(base_url="https://coach-database-api.fly.dev", api_key=None)
coaches = client.coaches(head_only=True, limit=25)
kirby = client.search("Kirby Smart")
uga_staff = client.school("georgia")  # slug
```

