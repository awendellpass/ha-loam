"""OpenFarm API client for Loam."""
from __future__ import annotations

import requests

from .const import OPENFARM_API_URL


def search_openfarm(query: str) -> list[dict]:
    """Search OpenFarm for crops matching the query string."""
    try:
        resp = requests.get(
            OPENFARM_API_URL,
            params={"filter": query, "include": "main_image_path"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results = []
    for item in data.get("data", []):
        attrs = item.get("attributes", {})
        results.append({
            "openfarm_slug": item.get("id", ""),
            "name": attrs.get("name", ""),
            "description": attrs.get("description", ""),
            "sun_requirements": attrs.get("sun_requirements", ""),
            "sowing_method": attrs.get("sowing_method", ""),
            "row_spacing_cm": attrs.get("row_spacing_cm"),
            "spread_cm": attrs.get("spread_cm"),
            "days_to_maturity_min": attrs.get("growing_degree_days"),
            "days_to_maturity_max": None,
            "image_url": attrs.get("main_image_path", ""),
        })
    return results
