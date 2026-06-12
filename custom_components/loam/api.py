"""Perenual plant database client for Loam."""
from __future__ import annotations

import requests

from .const import PERENUAL_API_URL


def search_perenual(query: str, api_key: str) -> list[dict]:
    """Search Perenual for plant species matching the query string.

    Returns a list of plant dicts shaped for Loam's plant library. Returns an
    empty list on any error or when no API key is configured.
    """
    if not api_key:
        return []

    try:
        resp = requests.get(
            PERENUAL_API_URL,
            params={"key": api_key, "q": query},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results = []
    for item in data.get("data", []):
        scientific = item.get("scientific_name") or []
        sunlight = item.get("sunlight") or []
        image = ""
        default_image = item.get("default_image")
        if isinstance(default_image, dict):
            image = default_image.get("thumbnail") or default_image.get("small_url") or ""

        name = item.get("common_name") or (scientific[0] if scientific else "")
        if not name:
            continue

        description_parts = []
        if scientific:
            description_parts.append(", ".join(scientific))
        if item.get("cycle"):
            description_parts.append(item["cycle"])

        results.append({
            # Reuse the library's external-id column for dedup across sources.
            "openfarm_slug": f"perenual:{item.get('id', '')}",
            "name": name,
            "description": " · ".join(description_parts),
            "sun_requirements": ", ".join(sunlight) if isinstance(sunlight, list) else str(sunlight or ""),
            "sowing_method": "",
            "row_spacing_cm": None,
            "spread_cm": None,
            "days_to_maturity_min": None,
            "days_to_maturity_max": None,
            "image_url": image,
        })
    return results
