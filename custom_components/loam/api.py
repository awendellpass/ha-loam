"""Permapeople plant database client + Claude companion classifier for Loam."""
from __future__ import annotations

import json

import requests

from .const import CLAUDE_MODEL, COMPANION_MODEL, PERMAPEOPLE_API_URL

_MATURITY_SCHEMA = {
    "type": "object",
    "properties": {
        "days_to_maturity": {"type": ["integer", "null"]},
    },
    "required": ["days_to_maturity"],
    "additionalProperties": False,
}

_COMPANION_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "relationship": {"type": "string", "enum": ["good", "bad", "neutral"]},
                },
                "required": ["index", "relationship"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


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


def estimate_days_to_maturity(name: str, api_key: str) -> int | None:
    """Estimate a plant's typical days to maturity via Claude.

    Permapeople's feed doesn't carry maturity timing, so we ask Claude for a
    typical figure (from transplant for transplanted crops, from sowing for
    direct-sown ones). Returns None for perennials/trees/shrubs where the
    concept doesn't apply, or when Claude can't give a sensible number. Raises
    on API/network errors so the caller can degrade (save the plant without an
    estimate; it stays editable).
    """
    if not name or not api_key:
        return None

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=200,
        system=(
            "You are a horticulture expert. Given a plant or variety name, return its "
            "typical days to maturity as a single integer — measured from transplant for "
            "crops normally transplanted, or from direct sowing otherwise. Return null for "
            "perennials, trees, shrubs, or anything where days-to-maturity doesn't apply."
        ),
        messages=[{"role": "user", "content": f"Plant: {name}"}],
        # Passed via extra_body so it reaches the API regardless of SDK version.
        extra_body={"output_config": {"format": {"type": "json_schema", "schema": _MATURITY_SCHEMA}}},
    )

    text = next((b.text for b in resp.content if b.type == "text"), "")
    parsed = json.loads(text)
    val = parsed.get("days_to_maturity")
    return val if isinstance(val, int) and val > 0 else None


def classify_companions(pairs: list[dict], api_key: str) -> list[dict]:
    """Classify plant pairs as good/bad/neutral companions via Claude.

    `pairs`: list of {"a", "b", "a_name", "b_name"}. Returns
    [{"a", "b", "relationship"}]. Raises on API/network errors so the caller
    can degrade gracefully (show no companion lines rather than crashing).
    """
    if not pairs or not api_key:
        return []

    import anthropic

    lines = "\n".join(
        f"{i}: {p['a_name']} & {p['b_name']}" for i, p in enumerate(pairs)
    )
    prompt = (
        "Classify each pair of plants for companion planting as:\n"
        "- \"good\": they benefit each other when grown adjacent\n"
        "- \"bad\": they harm each other and should not be adjacent\n"
        "- \"neutral\": no significant beneficial or harmful interaction\n\n"
        f"Pairs:\n{lines}\n\n"
        "Return one result per pair, by index."
    )

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=COMPANION_MODEL,
        max_tokens=4000,
        system="You are an expert in vegetable and herb companion planting.",
        messages=[{"role": "user", "content": prompt}],
        # Passed via extra_body so it reaches the API regardless of SDK version.
        extra_body={"output_config": {"format": {"type": "json_schema", "schema": _COMPANION_SCHEMA}}},
    )

    text = next((b.text for b in resp.content if b.type == "text"), "")
    parsed = json.loads(text)

    results = []
    for item in parsed.get("results", []):
        idx = item.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(pairs):
            continue
        results.append({
            "a": pairs[idx]["a"],
            "b": pairs[idx]["b"],
            "relationship": item.get("relationship", "neutral"),
        })
    return results
