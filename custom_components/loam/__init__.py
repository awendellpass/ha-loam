"""Loam — garden management integration for Home Assistant."""
from __future__ import annotations

import os

from homeassistant.core import HomeAssistant

from .const import DOMAIN, FRONTEND_PATH
from .database import LoamDatabase


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Loam integration."""

    db_path = hass.config.path("loam.db")
    db = LoamDatabase(db_path)
    await hass.async_add_executor_job(db.initialize)

    hass.data[DOMAIN] = {"db": db}

    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    try:
        from homeassistant.components.http import StaticPathConfig
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_PATH, frontend_dir, cache_headers=False)]
        )
    except (ImportError, AttributeError):
        hass.http.register_static_path(FRONTEND_PATH, frontend_dir, False)

    from .views import async_setup_views
    async_setup_views(hass)

    await _register_panel(hass)

    return True


async def _register_panel(hass: HomeAssistant) -> None:
    """Register the Loam panel in the HA sidebar."""
    from homeassistant.components.panel_custom import async_register_panel

    await async_register_panel(
        hass,
        webcomponent_name="loam-panel",
        frontend_url_path="loam",
        sidebar_title="Loam",
        sidebar_icon="mdi:sprout",
        module_url=f"{FRONTEND_PATH}/loam-panel.js",
        trust_external=False,
        require_admin=False,
    )
