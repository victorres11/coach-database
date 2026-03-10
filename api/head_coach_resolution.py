"""Utilities for resolving a canonical head coach from noisy staff titles."""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional

_HEAD_COACH_RE = re.compile(r"\bhead(?:\s+football)?\s+coach\b", re.IGNORECASE)
_EXCLUDE_RE = re.compile(r"\b(assistant|associate|asst\.?|interim|co-?head)\b", re.IGNORECASE)


def is_canonical_head_coach_title(title: Optional[str]) -> bool:
    """Return True when title indicates a primary head coach role."""
    if not title:
        return False
    normalized = " ".join(title.split())
    if _EXCLUDE_RE.search(normalized):
        return False
    return bool(_HEAD_COACH_RE.search(normalized))


def _score_title(title: Optional[str]) -> int:
    """Higher score means more likely to be the canonical head coach title."""
    if not title:
        return -1
    normalized = " ".join(title.lower().split())
    if normalized == "head football coach":
        return 200
    if normalized == "head coach":
        return 190
    if "head football coach" in normalized:
        return 180
    if "head coach" in normalized:
        return 170
    return -1


def resolve_head_coach(staff_rows: Iterable[Mapping]) -> Optional[Mapping]:
    """
    Pick a canonical head coach row from staff records.

    Preference order:
    1) Canonical head-coach title (not assistant/associate/interim)
    2) Higher title confidence score
    3) Newer year
    4) Higher id (latest write)
    """
    candidates = []
    for row in staff_rows:
        position = row.get("position")
        if not is_canonical_head_coach_title(position):
            continue
        score = _score_title(position)
        year = int(row.get("year") or 0)
        row_id = int(row.get("id") or 0)
        candidates.append((score, year, row_id, row))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return candidates[0][3]
