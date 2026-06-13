"""HTTP API views for Loam."""
from __future__ import annotations

import itertools
import json
import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN, GARDEN_TYPES, PLANTING_STATUSES, MAX_GARDEN_FT

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

        api_key = hass.data[DOMAIN].get("anthropic_api_key", "")
        if missing and api_key:
            from .api import classify_companions
            try:
                resolved = await hass.async_add_executor_job(
                    classify_companions, missing, api_key
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

        # Auto-estimate days to maturity via Claude when the caller didn't supply
        # one (Permapeople's feed has no maturity data). Stays editable afterward.
        if not body.get("days_to_maturity_min"):
            api_key = hass.data[DOMAIN].get("anthropic_api_key", "")
            if not api_key:
                _LOGGER.warning(
                    "Loam: no anthropic_api_key configured — skipping days-to-maturity estimate"
                )
            else:
                from .api import estimate_days_to_maturity
                try:
                    dtm = await hass.async_add_executor_job(
                        estimate_days_to_maturity, name, api_key
                    )
                    if dtm:
                        body["days_to_maturity_min"] = dtm
                    else:
                        _LOGGER.info("Loam: Claude returned no maturity estimate for %r", name)
                except Exception:
                    # degrade: save without an estimate, user can fill it in
                    _LOGGER.exception("Loam: days-to-maturity estimate failed for %r", name)

        db = _db(request)
        plant = await hass.async_add_executor_job(db.create_plant, body)
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

        db = _db(request)
        plant = await request.app["hass"].async_add_executor_job(db.update_plant, pid, dtm)
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
