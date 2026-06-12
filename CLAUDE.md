# Loam — Claude Project Conventions

Loam is a Home Assistant custom integration for outdoor garden management. It provides a grid-based layout interface where each garden is drawn to scale (1 square = 1 foot), plus a plant library and a planting log.

> **Layout model (current):** Two deliberate simplifications were made.
> 1. The satellite-map approach was shelved for a later iteration — it didn't give the granularity needed at bed scale.
> 2. The garden→bed split was then **collapsed into a single element: the garden.** A garden is itself a to-scale grid (its own `width_ft` × `height_ft`) with a `type`; plants are placed directly into its 1-ft cells. There is no separate "bed" layer. "Multiple garden plots" = multiple gardens. If a whole-yard map with beds positioned relative to each other is ever needed, reintroduce a parent layer above gardens — restructure later only if the need arises.
> The 1-ft cells are the foundation for placing individual plants per cell (square-foot gardening) in a future iteration.

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
  const.py          — DOMAIN, OPENFARM_API_URL, GARDEN_TYPES, MAX_GARDEN_FT, TOMORROW_API_KEY
  database.py       — all SQLite CRUD
  api.py            — OpenFarm search
  views.py          — REST endpoints
  panel.py          — iframe panel
  frontend/
    loam-panel.html   — grid markup + all CSS
    loam-panel.js     — HA web component (iframe + postMessage auth)
    loam-app.js       — app logic (grid render, garden CRUD, library, plantings)
```

## Database Schema

- **gardens** — `id, name, type (raised_bed/in_ground/container/grow_bag), width_ft, height_ft, created_at` (multiple gardens supported; each garden is the grid)
- **plants** — `id, name, openfarm_slug, description, sun_requirements, sowing_method, row_spacing_cm, spread_cm, days_to_maturity_min, days_to_maturity_max, is_custom, created_at`
- **plantings** — `id, garden_id, plant_id, planted_date, quantity, notes, status (active/harvested/removed), removed_date, created_at` (the dated Plantings-tab log)
- **placements** — `id, garden_id, grid_col, grid_row, plant_id, note, created_at` — one plant assigned to one 1-ft cell (square-foot layout); `UNIQUE(garden_id, grid_col, grid_row)`, one plant per cell. This is the lightweight grid layer, separate from `plantings`.

> There is **no `beds` table** — it was collapsed into `gardens`. `database.py` migrates older DBs: it adds `type/width_ft/height_ft` to `gardens`, rebuilds `plantings` to reference `garden_id`, and drops `beds`. The plant library is preserved.

## API Endpoints

```
GET/POST   /api/loam/garden
PUT/DELETE /api/loam/garden/{id}
GET/POST   /api/loam/placements         (GET ?garden_id= ; POST {garden_id, cells:[{grid_col,grid_row,plant_id|null,note}]})
GET/POST   /api/loam/plants
GET        /api/loam/plants/search?q=
DELETE     /api/loam/plants/{id}
GET/POST   /api/loam/plantings        (filter: ?garden_id= &status=)
PUT/DELETE /api/loam/plantings/{id}
```

## UI — 3 Tabs

- **Garden:** Sidebar lists gardens (name, type badge, W×H ft, planting count) with **+ New** and per-card **Delete**. Selecting a garden renders its to-scale grid (1 square = 1 ft). A toolbar holds a **brush** (pick a plant, or "Erase") plus **Copy from square** (click a planted cell to load its plant as the brush). Click or drag squares to plant/clear; changes batch-save on mouse-up via `/placements`. Creating a garden is a form: name, type, width, height.
- **Library:** Live plant search via the **Permapeople** API (`POST /api/search`, auth = `x-permapeople-key-id` + `x-permapeople-key-secret` headers), save to local library, add custom plants, browse saved. Credentials come from `configuration.yaml` → `secrets.yaml` (`permapeople_key_id`, `permapeople_key_secret`), read by `CONFIG_SCHEMA` in `__init__.py`. (Replaced OpenFarm, which shut down. Perenual was tried first but the account was actually a Permapeople one.)
- **Plantings:** Log new planting (garden + plant + date + quantity + notes), view active plantings grouped by garden, mark harvested/removed. (Separate from the grid `placements` layer.)

## Hard Constraints

- **Multiple gardens supported from the start** — never assume single-garden
- **A garden IS the grid** — there is no bed layer; do not reintroduce one without an explicit decision
- **Each garden has a size in feet** (`width_ft` × `height_ft`); the grid renders to those bounds, capped by `MAX_GARDEN_FT` in `const.py`
- **Gardens have a type field:** `raised_bed`, `in_ground`, `container`, `grow_bag` (constant `GARDEN_TYPES`)
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
