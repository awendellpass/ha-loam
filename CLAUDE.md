# Loam — Claude Project Conventions

Loam is a Home Assistant custom integration for outdoor garden management. It provides a grid-based layout interface for drawing garden beds to scale (1 square = 1 foot), building a plant library, and logging plantings.

> **Layout model (current):** The satellite-map approach was shelved for a later iteration — it didn't give the granularity needed at bed scale. The Garden tab is now a per-garden grid canvas: each garden has a width/height in feet, and beds are rectangles snapped to whole-foot cells. The 1-ft cells are the foundation for placing individual plants per cell (square-foot gardening) in a future iteration.

## Stack

- **Backend:** Python, SQLite (via `database.py`), `aiohttp` for HA REST endpoints
- **Frontend:** Vanilla JS, no frameworks. Garden layout is a DOM/CSS grid (no map libraries, no CDN dependencies).
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
    loam-panel.html   — grid markup + all CSS
    loam-panel.js     — HA web component (iframe + postMessage auth)
    loam-app.js       — app logic (grid render, bed drawing, library, plantings)
```

## Database Schema

- **gardens** — `id, name, width_ft, height_ft, created_at` (multiple gardens supported; `lat/lon/address` columns remain from the map era but are unused)
- **beds** — `id, garden_id, name, type (raised_bed/in_ground/container/grow_bag), grid_x, grid_y, grid_w, grid_h, area_sqft, notes, created_at` (`shape_geojson` column remains but is unused; `area_sqft` = `grid_w * grid_h`)
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

- **Garden:** Per-garden grid canvas (1 square = 1 ft), draw beds by dragging a snapped rectangle, list beds with type badge, footprint (W×H ft), and planting counts
- **Library:** Live OpenFarm search, save to local library, add custom plants, browse saved plants
- **Plantings:** Log new planting (bed + plant + date + quantity + notes), view active plantings by bed, mark harvested/removed

## Hard Constraints

- **Multiple gardens supported from the start** — never assume single-garden
- **Each garden has a size in feet** (`width_ft` × `height_ft`); the grid renders to those bounds, capped by `MAX_GARDEN_FT` in `const.py`
- **Beds are whole-foot rectangles** — `grid_x/grid_y` origin (0-based), `grid_w/grid_h` size (≥1); snapped to 1-ft cells; beds must not overlap
- **Beds have a type field:** `raised_bed`, `in_ground`, `container`, `grow_bag`
- **Dark theme** — consistent with Aura and Ember
- **No debug logging** in finished code
- **No inline CSS** — all styles in the `<style>` block in the HTML file (the grid cell size lives in the `--cell` CSS var and the `CELL` JS constant — keep them in sync)
- **No external JS frameworks or CDN dependencies** — vanilla JS only; the grid is plain DOM/CSS
- **Tomorrow.io is stubbed in Phase 1** — do not implement weather logic yet

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
