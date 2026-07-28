"""HTTP API views for Loam."""
from __future__ import annotations

import itertools
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    GARDEN_TYPES,
    LAWN_CACHE_MAX_AGE_DAYS,
    LAWN_SOIL_TEMP_MAX_F,
    LAWN_SOIL_TEMP_MIN_F,
    MAX_GARDEN_FT,
    PLANTING_STATUSES,
)

_LOGGER = logging.getLogger(__name__)


def _db(request: web.Request):
    return request.app["hass"].data[DOMAIN]["db"]


def _json(data: Any, status: int = 200) -> web.Response:
    return web.Response(
        body=json.dumps(data),
        content_type="application/json",
        status=status,
    )


def _error(message: str, status: int = 400) -> web.Response:
    return _json({"error": message}, status)


def _as_dim(value: Any, label: str) -> tuple[int | None, str | None]:
    """Coerce a value to a positive integer within garden bounds."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None, f"{label} must be a whole number"
    if n < 1 or n > MAX_GARDEN_FT:
        return None, f"{label} must be between 1 and {MAX_GARDEN_FT}"
    return n, None


def async_setup_views(hass: HomeAssistant) -> None:
    hass.http.register_view(LoamGardenView)
    hass.http.register_view(LoamGardenDetailView)
    hass.http.register_view(LoamPlacementsView)
    hass.http.register_view(LoamCompanionsView)
    hass.http.register_view(LoamPlantsView)
    hass.http.register_view(LoamPlantSearchView)
    hass.http.register_view(LoamPlantDetailView)
    hass.http.register_view(LoamPlantingsView)
    hass.http.register_view(LoamPlantingDetailView)
    hass.http.register_view(LoamCalendarView)
    hass.http.register_view(LoamPhenologyView)
    hass.http.register_view(LoamSettingsView)
    hass.http.register_view(LoamLawnView)


# ---------------------------------------------------------------------------
# GET /api/loam/garden        — list all gardens
# POST /api/loam/garden       — create a garden (name, type, width_ft, height_ft)
# ---------------------------------------------------------------------------

class LoamGardenView(HomeAssistantView):
    url = "/api/loam/garden"
    name = "api:loam:garden"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        db = _db(request)
        gardens = await request.app["hass"].async_add_executor_job(db.get_gardens)
        return _json(gardens)

    async def post(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        name = (body.get("name") or "").strip()
        if not name:
            return _error("name is required")

        garden_type = body.get("type", "raised_bed")
        if garden_type not in GARDEN_TYPES:
            return _error(f"type must be one of: {', '.join(GARDEN_TYPES)}")

        width_ft, err = _as_dim(body.get("width_ft"), "width_ft")
        if err:
            return _error(err)
        height_ft, err = _as_dim(body.get("height_ft"), "height_ft")
        if err:
            return _error(err)

        db = _db(request)
        garden = await request.app["hass"].async_add_executor_job(
            db.create_garden,
            name,
            garden_type,
            width_ft,
            height_ft,
        )
        return _json(garden, 201)


# ---------------------------------------------------------------------------
# PUT    /api/loam/garden/{garden_id}   — update (name, type, width_ft, height_ft)
# DELETE /api/loam/garden/{garden_id}
# ---------------------------------------------------------------------------

class LoamGardenDetailView(HomeAssistantView):
    url = "/api/loam/garden/{garden_id}"
    name = "api:loam:garden_detail"
    requires_auth = True

    async def put(self, request: web.Request, garden_id: str) -> web.Response:
        try:
            gid = int(garden_id)
        except ValueError:
            return _error("Invalid garden_id")

        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        garden_type = body.get("type")
        if garden_type is not None and garden_type not in GARDEN_TYPES:
            return _error(f"type must be one of: {', '.join(GARDEN_TYPES)}")

        width_ft = height_ft = None
        if body.get("width_ft") is not None:
            width_ft, err = _as_dim(body.get("width_ft"), "width_ft")
            if err:
                return _error(err)
        if body.get("height_ft") is not None:
            height_ft, err = _as_dim(body.get("height_ft"), "height_ft")
            if err:
                return _error(err)

        db = _db(request)
        garden = await request.app["hass"].async_add_executor_job(
            db.update_garden,
            gid,
            body.get("name"),
            garden_type,
            width_ft,
            height_ft,
        )
        if garden is None:
            return _error("Garden not found", 404)
        return _json(garden)

    async def delete(self, request: web.Request, garden_id: str) -> web.Response:
        try:
            gid = int(garden_id)
        except ValueError:
            return _error("Invalid garden_id")

        db = _db(request)
        success = await request.app["hass"].async_add_executor_job(db.delete_garden, gid)
        if not success:
            return _error("Garden not found", 404)
        return _json({"ok": True})


# ---------------------------------------------------------------------------
# GET  /api/loam/placements?garden_id=   — list cell placements for a garden
# POST /api/loam/placements              — set/clear cells (plant_id null clears)
# ---------------------------------------------------------------------------

class LoamPlacementsView(HomeAssistantView):
    url = "/api/loam/placements"
    name = "api:loam:placements"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        garden_id = request.rel_url.query.get("garden_id")
        if not garden_id or not garden_id.isdigit():
            return _error("garden_id is required")
        db = _db(request)
        placements = await request.app["hass"].async_add_executor_job(
            db.get_placements, int(garden_id)
        )
        return _json(placements)

    async def post(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        garden_id = body.get("garden_id")
        cells = body.get("cells")
        if not garden_id:
            return _error("garden_id is required")
        if not isinstance(cells, list) or not cells:
            return _error("cells must be a non-empty list")

        clean: list[dict] = []
        for cell in cells:
            try:
                col = int(cell["grid_col"])
                row = int(cell["grid_row"])
            except (KeyError, TypeError, ValueError):
                return _error("each cell needs grid_col and grid_row")
            if col < 0 or row < 0 or col >= MAX_GARDEN_FT or row >= MAX_GARDEN_FT:
                return _error("cell is outside the garden bounds")
            plant_id = cell.get("plant_id")
            if plant_id is not None:
                try:
                    plant_id = int(plant_id)
                except (TypeError, ValueError):
                    return _error("plant_id must be a number or null")
            clean.append({"grid_col": col, "grid_row": row, "plant_id": plant_id,
                          "note": cell.get("note")})

        db = _db(request)
        placements = await request.app["hass"].async_add_executor_job(
            db.apply_placements, int(garden_id), clean
        )
        return _json(placements)


# ---------------------------------------------------------------------------
# GET /api/loam/companions?garden_id=  — good/bad/neutral for the garden's plant
#   pairs. Cached relationships are returned immediately; uncached pairs are
#   resolved via Claude, cached, then included. Returns {"relationships": {...}}
#   keyed "a,b" (a < b). Degrades to cached-only if Claude isn't configured/fails.
# ---------------------------------------------------------------------------

class LoamCompanionsView(HomeAssistantView):
    url = "/api/loam/companions"
    name = "api:loam:companions"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        garden_id = request.rel_url.query.get("garden_id")
        if not garden_id or not garden_id.isdigit():
            return _error("garden_id is required")
        gid = int(garden_id)

        hass = request.app["hass"]
        db = _db(request)

        placements = await hass.async_add_executor_job(db.get_placements, gid)
        names = {p["plant_id"]: p["plant_name"] for p in placements}
        plant_ids = sorted(names)
        if len(plant_ids) < 2:
            return _json({"relationships": {}})

        cached = await hass.async_add_executor_job(db.get_companions, plant_ids)

        missing = [
            {"a": a, "b": b, "a_name": names[a], "b_name": names[b]}
            for a, b in itertools.combinations(plant_ids, 2)
            if f"{a},{b}" not in cached
        ]

        ollama_host = hass.data[DOMAIN].get("ollama_host", "")
        if missing and ollama_host:
            from .api import classify_companions
            try:
                resolved = await hass.async_add_executor_job(
                    classify_companions, missing, ollama_host
                )
            except Exception:
                resolved = []  # degrade: show only cached relationships
                _LOGGER.exception("Loam: companion classification failed")
            if resolved:
                await hass.async_add_executor_job(db.save_companions, resolved)
                for r in resolved:
                    a, b = (r["a"], r["b"]) if r["a"] < r["b"] else (r["b"], r["a"])
                    cached[f"{a},{b}"] = r["relationship"]

        return _json({"relationships": cached})


# ---------------------------------------------------------------------------
# GET  /api/loam/plants        — list saved plants
# POST /api/loam/plants        — save a plant to library
# ---------------------------------------------------------------------------

class LoamPlantsView(HomeAssistantView):
    url = "/api/loam/plants"
    name = "api:loam:plants"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        db = _db(request)
        plants = await request.app["hass"].async_add_executor_job(db.get_plants)
        return _json(plants)

    async def post(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        name = (body.get("name") or "").strip()
        if not name:
            return _error("name is required")

        hass = request.app["hass"]

        # Prevent duplicate saves of the same external plant (e.g. "permapeople:182")
        slug = body.get("openfarm_slug", "").strip()
        if slug:
            db = _db(request)
            exists = await hass.async_add_executor_job(db.plant_exists_by_slug, slug)
            if exists:
                return _error("Plant already in library", 409)

        # Ask Ollama for days-to-maturity + full growing-calendar phenology in
        # one call (Permapeople carries neither). Both are cached; phenology
        # powers the Calendar tab; maturity powers harvest-date estimates.
        ollama_host = hass.data[DOMAIN].get("ollama_host", "")
        metadata = {}
        if ollama_host:
            from .api import estimate_plant_metadata
            try:
                metadata = await hass.async_add_executor_job(
                    estimate_plant_metadata,
                    name,
                    body.get("scientific_name"),
                    ollama_host,
                )
            except Exception:
                _LOGGER.exception("Loam: metadata estimate failed for %r", name)
        else:
            _LOGGER.warning(
                "Loam: no ollama_host configured — skipping maturity/phenology estimate"
            )

        # Normalize common vs. scientific name. Permapeople sometimes indexes
        # plants by their Latin binomial as the primary name. Ollama corrects
        # this: common_name is always the English name, scientific_name the Latin.
        if metadata.get("common_name"):
            body["name"] = metadata["common_name"]
        if metadata.get("scientific_name") and not body.get("scientific_name"):
            body["scientific_name"] = metadata["scientific_name"]

        if not body.get("days_to_maturity_min") and metadata.get("days_to_maturity"):
            body["days_to_maturity_min"] = metadata["days_to_maturity"]

        db = _db(request)
        plant = await hass.async_add_executor_job(db.create_plant, body)

        # Persist phenology so the Calendar tab has data immediately.
        if metadata:
            phenology_data = {k: metadata[k] for k in (
                "plant_type", "start_indoors_week", "direct_sow_week",
                "transplant_week", "harvest_start_week", "harvest_end_week",
                "bloom_start_week", "bloom_end_week", "bloom_color", "pollinators",
            ) if k in metadata}
            await hass.async_add_executor_job(
                db.save_phenology, plant["id"], phenology_data
            )

        return _json(plant, 201)


# ---------------------------------------------------------------------------
# GET /api/loam/plants/search?q=
# ---------------------------------------------------------------------------

class LoamPlantSearchView(HomeAssistantView):
    url = "/api/loam/plants/search"
    name = "api:loam:plants_search"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        query = request.rel_url.query.get("q", "").strip()
        if not query:
            return _json([])

        data = request.app["hass"].data[DOMAIN]
        key_id = data.get("permapeople_key_id", "")
        key_secret = data.get("permapeople_key_secret", "")
        if not key_id or not key_secret:
            return _error(
                "Plant search isn't configured. Add Permapeople key id/secret to configuration.yaml.",
                503,
            )

        from .api import search_permapeople
        try:
            results = await request.app["hass"].async_add_executor_job(
                search_permapeople, query, key_id, key_secret
            )
        except Exception as err:  # surface the real reason instead of empty results
            return _error(f"Plant search failed: {err}", 502)
        return _json(results)


# ---------------------------------------------------------------------------
# PUT    /api/loam/plants/{plant_id}   — update days_to_maturity_min
# DELETE /api/loam/plants/{plant_id}
# ---------------------------------------------------------------------------

class LoamPlantDetailView(HomeAssistantView):
    url = "/api/loam/plants/{plant_id}"
    name = "api:loam:plant_detail"
    requires_auth = True

    async def put(self, request: web.Request, plant_id: str) -> web.Response:
        try:
            pid = int(plant_id)
        except ValueError:
            return _error("Invalid plant_id")

        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        dtm = body.get("days_to_maturity_min")
        if dtm is not None:
            try:
                dtm = int(dtm)
            except (TypeError, ValueError):
                return _error("days_to_maturity_min must be a whole number")
            if dtm < 0:
                return _error("days_to_maturity_min must be 0 or greater")

        wishlist = body.get("wishlist")
        if wishlist is not None:
            wishlist = bool(wishlist)

        db = _db(request)
        plant = await request.app["hass"].async_add_executor_job(
            db.update_plant, pid, dtm, wishlist
        )
        if plant is None:
            return _error("Plant not found", 404)
        return _json(plant)

    async def delete(self, request: web.Request, plant_id: str) -> web.Response:
        try:
            pid = int(plant_id)
        except ValueError:
            return _error("Invalid plant_id")

        db = _db(request)
        success = await request.app["hass"].async_add_executor_job(db.delete_plant, pid)
        if not success:
            return _error("Plant not found", 404)
        return _json({"ok": True})


# ---------------------------------------------------------------------------
# GET  /api/loam/plantings     — list plantings (optional ?garden_id= &status=)
# POST /api/loam/plantings     — log a planting
# ---------------------------------------------------------------------------

class LoamPlantingsView(HomeAssistantView):
    url = "/api/loam/plantings"
    name = "api:loam:plantings"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        db = _db(request)
        garden_id = request.rel_url.query.get("garden_id")
        status = request.rel_url.query.get("status")
        gid = int(garden_id) if garden_id and garden_id.isdigit() else None
        plantings = await request.app["hass"].async_add_executor_job(db.get_plantings, gid, status)
        return _json(plantings)

    async def post(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        garden_id = body.get("garden_id")
        plant_id = body.get("plant_id")
        planted_date = (body.get("planted_date") or "").strip()

        if not garden_id:
            return _error("garden_id is required")
        if not plant_id:
            return _error("plant_id is required")
        if not planted_date:
            return _error("planted_date is required")

        db = _db(request)
        planting = await request.app["hass"].async_add_executor_job(
            db.create_planting,
            int(garden_id),
            int(plant_id),
            planted_date,
            body.get("quantity"),
            body.get("notes"),
        )
        return _json(planting, 201)


# ---------------------------------------------------------------------------
# PUT    /api/loam/plantings/{planting_id}
# DELETE /api/loam/plantings/{planting_id}
# ---------------------------------------------------------------------------

class LoamPlantingDetailView(HomeAssistantView):
    url = "/api/loam/plantings/{planting_id}"
    name = "api:loam:planting_detail"
    requires_auth = True

    async def put(self, request: web.Request, planting_id: str) -> web.Response:
        try:
            pid = int(planting_id)
        except ValueError:
            return _error("Invalid planting_id")

        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        status = body.get("status")
        if status is not None and status not in PLANTING_STATUSES:
            return _error(f"status must be one of: {', '.join(PLANTING_STATUSES)}")

        planted_date = body.get("planted_date")
        if planted_date is not None and not str(planted_date).strip():
            return _error("planted_date cannot be blank")

        db = _db(request)
        planting = await request.app["hass"].async_add_executor_job(
            db.update_planting,
            pid,
            status,
            body.get("notes"),
            body.get("removed_date"),
            planted_date,
        )
        if planting is None:
            return _error("Planting not found", 404)
        return _json(planting)

    async def delete(self, request: web.Request, planting_id: str) -> web.Response:
        try:
            pid = int(planting_id)
        except ValueError:
            return _error("Invalid planting_id")

        db = _db(request)
        success = await request.app["hass"].async_add_executor_job(db.delete_planting, pid)
        if not success:
            return _error("Planting not found", 404)
        return _json({"ok": True})


# ---------------------------------------------------------------------------
# GET /api/loam/calendar
#   Returns all plants grouped (garden / wishlist / library) with cached
#   phenology attached. Does NOT trigger Ollama — use POST /api/loam/phenology
#   to fill in uncached plants.
# ---------------------------------------------------------------------------

class LoamCalendarView(HomeAssistantView):
    url = "/api/loam/calendar"
    name = "api:loam:calendar"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        db = _db(request)

        # Frost date: config.yaml override wins; fall back to DB setting.
        frost_override = hass.data[DOMAIN].get("frost_date_override", "")
        if frost_override:
            frost_date = frost_override
        else:
            frost_date = await hass.async_add_executor_job(db.get_setting, "frost_date") or ""

        groups = await hass.async_add_executor_job(db.get_calendar_plants)
        all_plants = groups["garden"] + groups["wishlist"] + groups["library"]
        all_ids = [p["id"] for p in all_plants]

        phenology_map = await hass.async_add_executor_job(db.get_phenology, all_ids)

        def attach_phenology(plant_list):
            for p in plant_list:
                p["phenology"] = phenology_map.get(p["id"])
            return plant_list

        return _json({
            "frost_date": frost_date,
            "frost_from_config": bool(frost_override),
            "sections": [
                {"label": "In My Garden", "key": "garden",
                 "plants": attach_phenology(groups["garden"])},
                {"label": "Wishlist",     "key": "wishlist",
                 "plants": attach_phenology(groups["wishlist"])},
                {"label": "My Library",   "key": "library",
                 "plants": attach_phenology(groups["library"])},
            ],
        })


# ---------------------------------------------------------------------------
# POST /api/loam/phenology
#   Body: { "plant_id": N }
#   Estimates phenology for one plant via Ollama and caches it.
#   The Calendar tab calls this one-at-a-time for uncached plants so the
#   user sees rows fill in progressively.
# ---------------------------------------------------------------------------

class LoamPhenologyView(HomeAssistantView):
    url = "/api/loam/phenology"
    name = "api:loam:phenology"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        plant_id = body.get("plant_id")
        if not plant_id:
            return _error("plant_id is required")
        try:
            pid = int(plant_id)
        except (TypeError, ValueError):
            return _error("plant_id must be a number")

        hass = request.app["hass"]
        db = _db(request)

        plant = await hass.async_add_executor_job(db.get_plant, pid)
        if plant is None:
            return _error("Plant not found", 404)

        ollama_host = hass.data[DOMAIN].get("ollama_host", "")
        if not ollama_host:
            return _error("Ollama not configured", 503)

        from .api import estimate_plant_metadata
        try:
            metadata = await hass.async_add_executor_job(
                estimate_plant_metadata,
                plant["name"],
                plant.get("scientific_name"),
                ollama_host,
            )
        except Exception as err:
            return _error(f"Ollama estimation failed: {err}", 502)

        phenology_data = {k: metadata[k] for k in (
            "plant_type", "start_indoors_week", "direct_sow_week",
            "transplant_week", "harvest_start_week", "harvest_end_week",
            "bloom_start_week", "bloom_end_week", "bloom_color", "pollinators",
        ) if k in metadata}

        await hass.async_add_executor_job(db.save_phenology, pid, phenology_data)

        # If Ollama returned a proper common name that differs from what's stored
        # (Permapeople sometimes uses Latin as the primary name), fix it in place.
        common = metadata.get("common_name", "")
        if common and common.lower() != plant["name"].lower():
            sci = metadata.get("scientific_name") if not plant.get("scientific_name") else None
            await hass.async_add_executor_job(
                db.update_plant, pid, None, None, common, sci
            )
            phenology_data["_name_updated"] = common

        return _json({"plant_id": pid, "phenology": phenology_data})


# ---------------------------------------------------------------------------
# GET  /api/loam/settings        — returns all user-configurable settings
# PUT  /api/loam/settings        — update settings (currently frost_date)
# ---------------------------------------------------------------------------

class LoamSettingsView(HomeAssistantView):
    url = "/api/loam/settings"
    name = "api:loam:settings"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        db = _db(request)
        frost_override = hass.data[DOMAIN].get("frost_date_override", "")
        frost_date = frost_override or await hass.async_add_executor_job(
            db.get_setting, "frost_date"
        ) or ""
        return _json({"frost_date": frost_date, "frost_from_config": bool(frost_override)})

    async def put(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        frost_date = (body.get("frost_date") or "").strip()
        if frost_date:
            # Validate MM-DD format
            parts = frost_date.split("-")
            valid = (
                len(parts) == 2
                and all(p.isdigit() for p in parts)
                and 1 <= int(parts[0]) <= 12
                and 1 <= int(parts[1]) <= 31
            )
            if not valid:
                return _error("frost_date must be MM-DD (e.g. 05-07)")

        hass = request.app["hass"]
        db = _db(request)
        if frost_date:
            await hass.async_add_executor_job(db.set_setting, "frost_date", frost_date)
        return _json({"frost_date": frost_date, "frost_from_config": False})


# ---------------------------------------------------------------------------
# GET /api/loam/lawn
#   Grass-seed timing: historical spring/fall soil-temp windows for the home
#   location (cached, recomputed when stale) combined with a live verdict
#   from current/forecast conditions. Degrades to {"available": false} if
#   Open-Meteo can't be reached — never breaks the Calendar tab.
# ---------------------------------------------------------------------------

def _window_status(today: date, start_md: str, end_md: str) -> dict:
    """Compare today against a recurring MM-DD..MM-DD window (same year)."""
    start_m, start_d = (int(p) for p in start_md.split("-"))
    end_m, end_d = (int(p) for p in end_md.split("-"))
    start_date = date(today.year, start_m, start_d)
    end_date = date(today.year, end_m, end_d)

    if start_date <= today <= end_date:
        return {"status": "in_window", "days_until": 0}
    if today < start_date:
        return {"status": "upcoming", "days_until": (start_date - today).days}
    next_start = date(today.year + 1, start_m, start_d)
    return {"status": "passed", "days_until": (next_start - today).days}


def _lawn_verdict(windows: dict, live: dict | None) -> dict:
    today = date.today()
    spring = {"season": "spring", **_window_status(today, windows["spring_start"], windows["spring_end"])}
    fall = {"season": "fall", **_window_status(today, windows["fall_start"], windows["fall_end"])}

    active = next((w for w in (spring, fall) if w["status"] == "in_window"), None)
    if active is None:
        active = min((spring, fall), key=lambda w: w["days_until"])

    result = {
        "available": True,
        "spring_start": windows["spring_start"], "spring_end": windows["spring_end"],
        "fall_start": windows["fall_start"], "fall_end": windows["fall_end"],
        "active_season": active["season"],
        "status": active["status"],
        "days_until": active["days_until"],
    }

    window_start = windows["spring_start"] if active["season"] == "spring" else windows["fall_start"]

    if live is None:
        result["message"] = (
            "Good time to plant now."
            if active["status"] == "in_window"
            else f"{active['days_until']} days until the {active['season']} window opens (~{window_start})."
        )
        return result

    soil_f = live["soil_temp_f"]
    result["soil_temp_f"] = round(soil_f, 1)
    result["precip_next_7d_in"] = round(live["precip_next_7d_in"], 2)
    in_band = LAWN_SOIL_TEMP_MIN_F <= soil_f <= LAWN_SOIL_TEMP_MAX_F

    if active["status"] == "in_window":
        if in_band:
            msg = f"Good time to plant now — soil temp {soil_f:.0f}°F, in the ideal {LAWN_SOIL_TEMP_MIN_F}–{LAWN_SOIL_TEMP_MAX_F}°F range."
        elif soil_f > LAWN_SOIL_TEMP_MAX_F:
            msg = f"Historically a good window, but soil is running warm right now ({soil_f:.0f}°F, above the {LAWN_SOIL_TEMP_MAX_F}°F ideal max)."
        else:
            msg = f"Historically a good window, but soil is running cool right now ({soil_f:.0f}°F, below the {LAWN_SOIL_TEMP_MIN_F}°F ideal min)."
        if live["precip_next_7d_in"] < 0.25:
            msg += " Forecast is dry over the next week — plan to water if you seed now."
    else:
        msg = f"{active['days_until']} days until the {active['season']} window opens (~{window_start})."
        if in_band:
            msg += f" Soil is already {soil_f:.0f}°F, within range — conditions may be running ahead of the historical average this year."

    result["message"] = msg
    return result


class LoamLawnView(HomeAssistantView):
    url = "/api/loam/lawn"
    name = "api:loam:lawn"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        db = _db(request)
        lat, lon = hass.config.latitude, hass.config.longitude

        from .api import fetch_live_soil_conditions, fetch_soil_temp_normals

        windows = await hass.async_add_executor_job(db.get_lawn_windows)
        stale = (
            windows is None
            or datetime.now(timezone.utc) - datetime.fromisoformat(windows["computed_at"])
            > timedelta(days=LAWN_CACHE_MAX_AGE_DAYS)
        )
        if stale:
            try:
                windows = await hass.async_add_executor_job(fetch_soil_temp_normals, lat, lon)
            except Exception as err:
                if windows is None:
                    _LOGGER.warning("Loam: lawn historical fetch failed: %s", err)
                    return _json({"available": False})
                # Keep serving the stale cache rather than fail outright.
            else:
                await hass.async_add_executor_job(db.save_lawn_windows, windows)

        try:
            live = await hass.async_add_executor_job(fetch_live_soil_conditions, lat, lon)
        except Exception as err:
            _LOGGER.warning("Loam: lawn live-conditions fetch failed: %s", err)
            live = None

        return _json(_lawn_verdict(windows, live))
