# Loam — Claude Project Conventions

Loam is a Home Assistant custom integration for outdoor garden management. It provides a satellite map-based interface for drawing garden beds, building a plant library, and logging plantings.

## Stack

- **Backend:** Python, SQLite (via `database.py`), `aiohttp` for HA REST endpoints
- **Frontend:** Vanilla JS, no frameworks. Leaflet.js + Leaflet.draw via CDN. ESRI World Imagery satellite tiles (free, no API key). Nominatim for geocoding.
- **Plant data:** OpenFarm API (free, no key required) — live search, saved to local SQLite
- **Weather:** Tomorrow.io (reuse Aura's key) — stubbed in Phase 1, active in Phase 2
- **HA integration pattern:** Python backend + SQLite + vanilla JS frontend served as HA iframe panel

## File Structure

```
custom_components/loam/
  __init__.py       — setup, view + panel registration
  manifest.json     — requirements: requests
  const.py          — TOMORROW_API_KEY, DOMAIN, OPENFARM_API_URL
  database.py       — all SQLite CRUD
  api.py            — OpenFarm search
  views.py          — REST endpoints
  panel.py          — iframe panel
  frontend/
    loam-panel.html
    loam-panel.js
```

## Database Schema

- **gardens** — `id, name, lat, lon, address, created_at` (multiple gardens supported)
- **beds** — `id, garden_id, name, type (raised_bed/in_ground/container/grow_bag), shape_geojson, area_sqft, notes, created_at`
- **plants** — `id, name, openfarm_slug, description, sun_requirements, sowing_method, row_spacing_cm, spread_cm, days_to_maturity_min, days_to_maturity_max, is_custom, created_at`
- **plantings** — `id, bed_id, plant_id, planted_date, quantity, notes, status (active/harvested/removed), removed_date, created_at`

## API Endpoints

```
GET/POST  /api/loam/garden
GET/POST  /api/loam/beds
PUT/DELETE /api/loam/beds/{id}
GET/POST  /api/loam/plants
GET       /api/loam/plants/search?q=
DELETE    /api/loam/plants/{id}
GET/POST  /api/loam/plantings
PUT/DELETE /api/loam/plantings/{id}
```

## UI — 3 Tabs

- **Garden:** Satellite map, draw beds with Leaflet.draw, set garden location, list beds with type badge and planting counts
- **Library:** Live OpenFarm search, save to local library, add custom plants, browse saved plants
- **Plantings:** Log new planting (bed + plant + date + quantity + notes), view active plantings by bed, mark harvested/removed

## Hard Constraints

- **Multiple gardens supported from the start** — never assume single-garden
- **Beds have a type field:** `raised_bed`, `in_ground`, `container`, `grow_bag`
- **Dark theme** — consistent with Aura and Ember
- **No debug logging** in finished code
- **No inline CSS** — all styles in the `<style>` block in the HTML file
- **No external JS frameworks** — vanilla JS only; Leaflet.js and Leaflet.draw loaded via CDN only
- **Tomorrow.io is stubbed in Phase 1** — do not implement weather logic yet
- **Leaflet.js loaded via CDN** — do not bundle locally
- **ESRI World Imagery tiles** — `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`

## Deployment Workflow

Files live in this GitHub repo (`awendellpass/ha-loam`). GitHub Actions auto-deploys to the Raspberry Pi on every push to `main`. Do NOT revert to copy-paste into the HA file editor.

## Code Quality Hooks (Automated)

- **PostToolUse:** ruff runs automatically on every `.py` file Claude writes or edits. Fix any reported errors before moving on.
- **Stop gate:** pytest runs when Claude finishes a task. If tests fail, Claude is blocked from completing until they pass.

## What Claude Is Responsible For

- Writing all application code
- Following the constraints above without being reminded
- Explaining every significant design decision when asked
- Keeping code changes targeted — prefer editing specific functions over rewriting whole files
- Never adding features beyond what the current phase specifies
