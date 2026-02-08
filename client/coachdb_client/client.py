from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests


@dataclass(frozen=True)
class CoachDBClient:
    base_url: str = "https://coach-database-api.fly.dev"
    api_key: Optional[str] = None
    timeout_s: float = 10.0

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        resp = requests.get(url, params=params or {}, headers=self._headers(), timeout=self.timeout_s)
        resp.raise_for_status()
        ct = (resp.headers.get("content-type") or "").lower()
        if "application/json" in ct:
            return resp.json()
        return resp.text

    def stats(self) -> dict[str, Any]:
        return self._get("/stats")

    def coaches(
        self,
        *,
        school: Optional[str] = None,
        position: Optional[str] = None,
        head_only: bool = False,
        year: Optional[int] = None,
        limit: int = 2500,
    ) -> list[dict[str, Any]]:
        return self._get(
            "/coaches",
            params={
                "school": school,
                "position": position,
                "head_only": head_only,
                "year": year,
                "limit": limit,
            },
        )

    def coach(self, coach_id: int) -> dict[str, Any]:
        return self._get(f"/coaches/{coach_id}")

    def coach_career(self, coach_id: int) -> list[dict[str, Any]]:
        return self._get(f"/coaches/{coach_id}/career")

    def schools(self, *, conference: Optional[str] = None, q: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._get("/schools", params={"conference": conference, "q": q, "limit": limit})

    def school(self, slug: str) -> dict[str, Any]:
        return self._get(f"/schools/{slug}")

    def salaries(
        self,
        *,
        min_pay: Optional[int] = None,
        conference: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._get(
            "/salaries",
            params={"min_pay": min_pay, "conference": conference, "year": year, "limit": limit},
        )

    def search(self, q: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self._get("/search", params={"q": q, "limit": limit})

    def yr_coaches(
        self,
        school_slug: str,
        *,
        position: Optional[str] = None,
        year: Optional[int] = None,
        text: bool = False,
    ) -> Any:
        return self._get(
            f"/yr/{school_slug}/coaches",
            params={"position": position, "year": year, "format": "text" if text else None},
        )

