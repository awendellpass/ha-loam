"""Permapeople plant database client for Loam."""
from __future__ import annotations

import requests

from .const import PERMAPEOPLE_API_URL


def _data_value(data: list, key: str) -> str:
    """Pull a value out of Permapeople's key/value `data` array."""
    for item in data or []:
        if item.get("key") == key:
            return item.get("value") or ""
    return ""


def search_permapeople(query: str, key_id: str, key_secret: str) -> list[dict]:
    """Search Permapeople for plants matching the query string.

    Returns a list of plant dicts shaped for Loam's plant library. Raises on
    HTTP/network errors so the caller can surface a useful message; returns an
    empty list only when credentials are missing or the API genuinely matches
    nothing.
    """
    if not key_id or not key_secret:
        return []

    resp = requests.post(
        PERMAPEOPLE_API_URL,
        headers={
            "x-permapeople-key-id": key_id,
            "x-permapeople-key-secret": key_secret,
            "Content-Type": "application/json",
            "User-Agent": "Loam-HomeAssistant/1.0",
        },
        json={"q": query},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("plants", []):
        name = item.get("name") or ""
        if not name:
            continue

        fields = item.get("data") or []
        scientific = item.get("scientific_name") or ""
        description = item.get("description") or ""
        full_description = " — ".join(p for p in (scientific, description) if p)

        sowing = (_data_value(fields, "Propagation - Direct sowing")
                  or _data_value(fields, "Propagation - Transplanting"))

        results.append({
            # Reuse the library's external-id column for dedup across sources.
            "openfarm_slug": f"permapeople:{item.get('id', '')}",
            "name": name,
            "description": full_description,
            "sun_requirements": _data_value(fields, "Light requirement"),
            "sowing_method": sowing,
            "row_spacing_cm": None,
            "spread_cm": None,
            "days_to_maturity_min": None,
            "days_to_maturity_max": None,
            "image_url": "",
        })
    return results
