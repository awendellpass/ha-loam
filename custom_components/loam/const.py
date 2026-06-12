"""Constants for the Loam integration."""

DOMAIN = "loam"
DB_FILENAME = "loam.db"
FRONTEND_PATH = "/loam_frontend"

# Perenual plant database (replaced OpenFarm, which shut down). The API key is
# NOT stored here — it comes from /config/secrets.yaml via configuration.yaml so
# it stays out of version control and survives HACS updates. See CONF_* below.
PERENUAL_API_URL = "https://perenual.com/api/v2/species-list"

# configuration.yaml keys read by CONFIG_SCHEMA in __init__.py.
CONF_PERENUAL_API_KEY = "perenual_api_key"

# Secrets load from an untracked secrets.py (gitignored — see secrets.py.example).
# Real API keys never enter version control. Falls back to "" if the file is
# absent, e.g. before Phase 2 weather is configured or on a fresh checkout.
try:
    from .secrets import TOMORROW_API_KEY
except ImportError:
    TOMORROW_API_KEY = ""

# Garden types (a garden is the single grid element plants are placed into).
GARDEN_TYPES = ["raised_bed", "in_ground", "container", "grow_bag"]

PLANTING_STATUSES = ["active", "harvested", "removed"]

# Largest garden dimension (feet) allowed in either direction. Bounds the grid
# canvas and validates bed footprints server-side.
MAX_GARDEN_FT = 200
