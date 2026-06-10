"""Constants for the Loam integration."""

DOMAIN = "loam"
DB_FILENAME = "loam.db"
FRONTEND_PATH = "/loam_frontend"

OPENFARM_API_URL = "https://openfarm.cc/api/v1/crops"

# Secrets load from an untracked secrets.py (gitignored — see secrets.py.example).
# Real API keys never enter version control. Falls back to "" if the file is
# absent, e.g. before Phase 2 weather is configured or on a fresh checkout.
try:
    from .secrets import TOMORROW_API_KEY
except ImportError:
    TOMORROW_API_KEY = ""

BED_TYPES = ["raised_bed", "in_ground", "container", "grow_bag"]

PLANTING_STATUSES = ["active", "harvested", "removed"]
