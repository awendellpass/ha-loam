"""Loam — garden management integration for Home Assistant."""
from __future__ import annotations

import os

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_PERMAPEOPLE_KEY_ID,
    CONF_PERMAPEOPLE_KEY_SECRET,
    DOMAIN,
    FRONTEND_PATH,
)
from .database import LoamDatabase

# Optional YAML config: the Permapeople key-id/key-secret come from
# /config/secrets.yaml, referenced under `loam:` in configuration.yaml. Keeps
# credentials out of the repo and the integration folder (HACS overwrites that).
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_PERMAPEOPLE_KEY_ID): cv.string,
                vol.Optional(CONF_PERMAPEOPLE_KEY_SECRET): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Loam integration."""

    # `config.get(DOMAIN)` is None when the YAML has a bare `loam:` line.
    conf = config.get(DOMAIN) or {}

    db_path = hass.config.path("loam.db")
    db = LoamDatabase(db_path)
    await hass.async_add_executor_job(db.initialize)

    hass.data[DOMAIN] = {
        "db": db,
        "permapeople_key_id": conf.get(CONF_PERMAPEOPLE_KEY_ID, ""),
        "permapeople_key_secret": conf.get(CONF_PERMAPEOPLE_KEY_SECRET, ""),
    }

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
