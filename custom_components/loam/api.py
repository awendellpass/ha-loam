"""Permapeople plant database client + Ollama companion classifier for Loam."""
from __future__ import annotations

import json
import logging

import requests

from .const import OLLAMA_MODEL, PERMAPEOPLE_API_URL

_LOGGER = logging.getLogger(__name__)


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

        sowing = (_data_value(fields, "Propagation - Direct sowing")
                  or _data_value(fields, "Propagation - Transplanting"))

        results.append({
            # Reuse the library's external-id column for dedup across sources.
            "openfarm_slug": f"permapeople:{item.get('id', '')}",
            "name": name,
            "scientific_name": scientific,
            "description": description,
            "sun_requirements": _data_value(fields, "Light requirement"),
            "sowing_method": sowing,
            "row_spacing_cm": None,
            "spread_cm": None,
            "days_to_maturity_min": None,
            "days_to_maturity_max": None,
            "image_url": "",
        })
    return results


def estimate_plant_metadata(name: str, scientific_name: str | None, ollama_host: str) -> dict:
    """Estimate growing-calendar data + days to maturity for a plant via Ollama.

    Returns a dict with 'days_to_maturity' plus phenology fields (all week offsets
    are relative to the last spring frost date). Raises on network errors so callers
    can degrade gracefully. Returns {} when inputs are missing.

    Replaces the old estimate_days_to_maturity — one call gives everything.
    """
    if not name or not ollama_host:
        return {}

    latin = f" ({scientific_name})" if scientific_name else ""
    prompt = (
        f"Give growing-calendar data for: {name}{latin}\n\n"
        "Assume a northern US / upper Midwest climate (last spring frost ~May 7, "
        "first fall frost ~Oct 1). All week offsets are relative to the last "
        "spring frost date (negative = before frost, e.g. -8 = 8 weeks before).\n\n"
        "Return JSON with exactly these fields:\n"
        "  common_name        — the familiar common name in English (e.g. 'Tomato', not 'Solanum lycopersicum');\n"
        "                       if the input name is already a common name, repeat it here\n"
        "  scientific_name    — the full Latin binomial (e.g. 'Solanum lycopersicum'); null if unknown\n"
        "  days_to_maturity   — integer for annuals/vegs (from transplant or direct sow); null for perennials/trees\n"
        "  plant_type         — one of: vegetable, herb, native_plant, annual_flower, perennial_flower, tree_shrub\n"
        "  start_indoors_week — weeks before frost to start seeds indoors (e.g. -8); null if not started indoors\n"
        "  direct_sow_week    — weeks relative to frost for outdoor direct sowing; null if not direct-sown\n"
        "  transplant_week    — weeks relative to frost to transplant outside; null if direct-sown\n"
        "  harvest_start_week — weeks after frost when harvest begins; null for ornamentals\n"
        "  harvest_end_week   — weeks after frost when harvest ends (or frost kills it); null for ornamentals\n"
        "  bloom_start_week   — weeks after frost when blooming begins (ornamentals); null for veg/herbs\n"
        "  bloom_end_week     — weeks after frost when blooming ends; null for veg/herbs\n"
        "  bloom_color        — hex color of dominant bloom (e.g. \"#ff6600\"); null for veg/herbs\n"
        "  pollinators        — array from [\"bee\",\"butterfly\",\"hummingbird\",\"bird\"]; [] for veg/herbs\n"
    )

    resp = requests.post(
        f"{ollama_host}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a horticulture expert for northern US gardens. "
                        "Always respond with valid JSON only, no explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
        },
        timeout=90,
    )
    resp.raise_for_status()

    text = resp.json()["message"]["content"]
    _LOGGER.debug("Loam: metadata raw response for %r: %r", name, text)
    parsed = json.loads(text)

    def _week(val):
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    plant_type = parsed.get("plant_type", "vegetable")
    if plant_type not in ("vegetable", "herb", "native_plant",
                          "annual_flower", "perennial_flower", "tree_shrub"):
        plant_type = "vegetable"

    pollinators = parsed.get("pollinators") or []
    if not isinstance(pollinators, list):
        pollinators = []
    pollinators = [p for p in pollinators if p in {"bee", "butterfly", "hummingbird", "bird"}]

    bloom_color = parsed.get("bloom_color")
    if bloom_color and not str(bloom_color).startswith("#"):
        bloom_color = None

    dtm = _week(parsed.get("days_to_maturity"))
    if dtm is not None and dtm <= 0:
        dtm = None

    common_name = (parsed.get("common_name") or "").strip() or None
    sci_name    = (parsed.get("scientific_name") or "").strip() or None

    return {
        "common_name":     common_name,
        "scientific_name": sci_name,
        "days_to_maturity": dtm,
        "plant_type": plant_type,
        "start_indoors_week": _week(parsed.get("start_indoors_week")),
        "direct_sow_week":    _week(parsed.get("direct_sow_week")),
        "transplant_week":    _week(parsed.get("transplant_week")),
        "harvest_start_week": _week(parsed.get("harvest_start_week")),
        "harvest_end_week":   _week(parsed.get("harvest_end_week")),
        "bloom_start_week":   _week(parsed.get("bloom_start_week")),
        "bloom_end_week":     _week(parsed.get("bloom_end_week")),
        "bloom_color":        bloom_color,
        "pollinators":        pollinators,
    }


def classify_companions(pairs: list[dict], ollama_host: str) -> list[dict]:
    """Classify plant pairs as good/bad/neutral companions via Ollama.

    `pairs`: list of {"a", "b", "a_name", "b_name"}. Returns
    [{"a", "b", "relationship"}]. Raises on network errors so the caller
    can degrade gracefully (show no companion lines rather than crashing).
    """
    if not pairs or not ollama_host:
        return []

    lines = "\n".join(
        f"{i}: {p['a_name']} & {p['b_name']}" for i, p in enumerate(pairs)
    )
    prompt = (
        "Classify each pair of plants for companion planting:\n"
        "- 'good': they benefit each other when grown adjacent\n"
        "- 'bad': they harm each other and should not be adjacent\n"
        "- 'neutral': no significant beneficial or harmful interaction\n\n"
        f"Pairs:\n{lines}\n\n"
        "Respond with JSON in this exact format: "
        '{"results": [{"index": 0, "relationship": "good"}, {"index": 1, "relationship": "bad"}]}'
    )

    resp = requests.post(
        f"{ollama_host}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert in vegetable and herb companion planting. "
                        "Always respond with valid JSON only, no explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
        },
        timeout=120,
    )
    resp.raise_for_status()

    text = resp.json()["message"]["content"]
    parsed = json.loads(text)

    results = []
    for item in parsed.get("results", []):
        idx = item.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(pairs):
            continue
        relationship = item.get("relationship", "neutral")
        if relationship not in ("good", "bad", "neutral"):
            relationship = "neutral"
        results.append({
            "a": pairs[idx]["a"],
            "b": pairs[idx]["b"],
            "relationship": relationship,
        })
    return results
