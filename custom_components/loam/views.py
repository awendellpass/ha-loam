"""HTTP API views for Loam."""
from __future__ import annotations

import json
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN, BED_TYPES, PLANTING_STATUSES


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


def async_setup_views(hass: HomeAssistant) -> None:
    hass.http.register_view(LoamGardenView)
    hass.http.register_view(LoamGardenDetailView)
    hass.http.register_view(LoamBedsView)
    hass.http.register_view(LoamBedDetailView)
    hass.http.register_view(LoamPlantsView)
    hass.http.register_view(LoamPlantSearchView)
    hass.http.register_view(LoamPlantDetailView)
    hass.http.register_view(LoamPlantingsView)
    hass.http.register_view(LoamPlantingDetailView)


# ---------------------------------------------------------------------------
# GET /api/loam/garden        — list all gardens
# POST /api/loam/garden       — create a garden
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

        db = _db(request)
        garden = await request.app["hass"].async_add_executor_job(
            db.create_garden,
            name,
            body.get("lat"),
            body.get("lon"),
            body.get("address"),
        )
        return _json(garden, 201)


# ---------------------------------------------------------------------------
# PUT /api/loam/garden/{garden_id}   — update garden (name, lat, lon, address)
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

        db = _db(request)
        garden = await request.app["hass"].async_add_executor_job(
            db.update_garden,
            gid,
            body.get("name"),
            body.get("lat"),
            body.get("lon"),
            body.get("address"),
        )
        if garden is None:
            return _error("Garden not found", 404)
        return _json(garden)


# ---------------------------------------------------------------------------
# GET  /api/loam/beds          — list beds (optional ?garden_id=)
# POST /api/loam/beds          — create a bed
# ---------------------------------------------------------------------------

class LoamBedsView(HomeAssistantView):
    url = "/api/loam/beds"
    name = "api:loam:beds"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        db = _db(request)
        garden_id = request.rel_url.query.get("garden_id")
        gid = int(garden_id) if garden_id and garden_id.isdigit() else None
        beds = await request.app["hass"].async_add_executor_job(db.get_beds, gid)
        return _json(beds)

    async def post(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        garden_id = body.get("garden_id")
        name = (body.get("name") or "").strip()
        bed_type = body.get("type", "raised_bed")

        if not garden_id:
            return _error("garden_id is required")
        if not name:
            return _error("name is required")
        if bed_type not in BED_TYPES:
            return _error(f"type must be one of: {', '.join(BED_TYPES)}")

        db = _db(request)
        bed = await request.app["hass"].async_add_executor_job(
            db.create_bed,
            int(garden_id),
            name,
            bed_type,
            body.get("shape_geojson"),
            body.get("area_sqft"),
            body.get("notes"),
        )
        return _json(bed, 201)


# ---------------------------------------------------------------------------
# PUT    /api/loam/beds/{bed_id}
# DELETE /api/loam/beds/{bed_id}
# ---------------------------------------------------------------------------

class LoamBedDetailView(HomeAssistantView):
    url = "/api/loam/beds/{bed_id}"
    name = "api:loam:bed_detail"
    requires_auth = True

    async def put(self, request: web.Request, bed_id: str) -> web.Response:
        try:
            bid = int(bed_id)
        except ValueError:
            return _error("Invalid bed_id")

        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        bed_type = body.get("type")
        if bed_type is not None and bed_type not in BED_TYPES:
            return _error(f"type must be one of: {', '.join(BED_TYPES)}")

        db = _db(request)
        bed = await request.app["hass"].async_add_executor_job(
            db.update_bed,
            bid,
            body.get("name"),
            bed_type,
            body.get("shape_geojson"),
            body.get("area_sqft"),
            body.get("notes"),
        )
        if bed is None:
            return _error("Bed not found", 404)
        return _json(bed)

    async def delete(self, request: web.Request, bed_id: str) -> web.Response:
        try:
            bid = int(bed_id)
        except ValueError:
            return _error("Invalid bed_id")

        db = _db(request)
        success = await request.app["hass"].async_add_executor_job(db.delete_bed, bid)
        if not success:
            return _error("Bed not found", 404)
        return _json({"ok": True})


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

        # Prevent duplicate OpenFarm saves
        slug = body.get("openfarm_slug", "").strip()
        if slug:
            db = _db(request)
            exists = await request.app["hass"].async_add_executor_job(
                db.plant_exists_by_slug, slug
            )
            if exists:
                return _error("Plant already in library", 409)

        db = _db(request)
        plant = await request.app["hass"].async_add_executor_job(db.create_plant, body)
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

        from .api import search_openfarm
        results = await request.app["hass"].async_add_executor_job(search_openfarm, query)
        return _json(results)


# ---------------------------------------------------------------------------
# DELETE /api/loam/plants/{plant_id}
# ---------------------------------------------------------------------------

class LoamPlantDetailView(HomeAssistantView):
    url = "/api/loam/plants/{plant_id}"
    name = "api:loam:plant_detail"
    requires_auth = True

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
# GET  /api/loam/plantings     — list plantings (optional ?bed_id= &status=)
# POST /api/loam/plantings     — log a planting
# ---------------------------------------------------------------------------

class LoamPlantingsView(HomeAssistantView):
    url = "/api/loam/plantings"
    name = "api:loam:plantings"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        db = _db(request)
        bed_id = request.rel_url.query.get("bed_id")
        status = request.rel_url.query.get("status")
        bid = int(bed_id) if bed_id and bed_id.isdigit() else None
        plantings = await request.app["hass"].async_add_executor_job(db.get_plantings, bid, status)
        return _json(plantings)

    async def post(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON")

        bed_id = body.get("bed_id")
        plant_id = body.get("plant_id")
        planted_date = (body.get("planted_date") or "").strip()

        if not bed_id:
            return _error("bed_id is required")
        if not plant_id:
            return _error("plant_id is required")
        if not planted_date:
            return _error("planted_date is required")

        db = _db(request)
        planting = await request.app["hass"].async_add_executor_job(
            db.create_planting,
            int(bed_id),
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

        db = _db(request)
        planting = await request.app["hass"].async_add_executor_job(
            db.update_planting,
            pid,
            status,
            body.get("notes"),
            body.get("removed_date"),
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
