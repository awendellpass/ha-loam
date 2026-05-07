# Loam — Home Assistant Garden Manager

A Home Assistant custom integration for managing outdoor gardens. Satellite map-based interface for drawing garden beds, building a plant library, and logging plantings.

## Features

- **Satellite map** — Draw garden beds directly on ESRI World Imagery tiles using Leaflet.js
- **Multiple gardens** — Manage separate garden spaces from one panel
- **Bed types** — Raised bed, in-ground, container, grow bag
- **Plant library** — Live search via OpenFarm API (free, no key required); save plants locally or add custom entries
- **Planting log** — Record what was planted, when, and where; mark harvested or removed

## Installation

1. Copy `custom_components/loam/` into your HA config's `custom_components/` folder
2. Add to `configuration.yaml`:
   ```yaml
   loam:
   ```
3. Restart Home Assistant
4. Loam appears in the sidebar under the sprout icon

## Stack

- Python backend with SQLite (aiohttp REST API)
- Vanilla JS frontend served as HA iframe panel
- Leaflet.js + Leaflet.draw via CDN
- ESRI World Imagery satellite tiles (free, no API key)
- OpenFarm API for plant data (free, no API key)
