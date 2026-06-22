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


def estimate_days_to_maturity(name: str, ollama_host: str) -> int | None:
    """Estimate a plant's typical days to maturity via Ollama.

    Permapeople's feed doesn't carry maturity timing, so we ask the local model
    for a typical figure (from transplant for transplanted crops, from sowing for
    direct-sown ones). Returns None for perennials/trees/shrubs where the concept
    doesn't apply, or when the model can't give a sensible number. Raises on
    network errors so the caller can degrade (save the plant without an estimate;
    it stays editable).
    """
    if not name or not ollama_host:
        return None

    prompt = (
        f"What is the typical days to maturity for: {name}?\n\n"
        "For annual vegetables and herbs, return the integer number of days "
        "(from transplant for transplanted crops, from direct sowing otherwise). "
        "For perennials, trees, shrubs, or anything where days-to-maturity does "
        "not apply, return null.\n\n"
        'Respond with JSON in this exact format: {"days_to_maturity": 75} '
        'or {"days_to_maturity": null}'
    )

    resp = requests.post(
        f"{ollama_host}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a horticulture expert. "
                        "Always respond with valid JSON only, no explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()

    text = resp.json()["message"]["content"]
    _LOGGER.debug("Loam: maturity raw response for %r: %r", name, text)
    parsed = json.loads(text)
    val = parsed.get("days_to_maturity")
    return val if isinstance(val, int) and val > 0 else None


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
