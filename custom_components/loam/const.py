"""Constants for the Loam integration."""

DOMAIN = "loam"
DB_FILENAME = "loam.db"
FRONTEND_PATH = "/loam_frontend"

# Permapeople plant database (replaced OpenFarm, which shut down). Credentials
# are NOT stored here — they come from /config/secrets.yaml via configuration.yaml
# so they stay out of version control and survive HACS updates. See CONF_* below.
# Auth is a key-id + key-secret pair sent as request headers.
PERMAPEOPLE_API_URL = "https://permapeople.org/api/search"

# configuration.yaml keys read by CONFIG_SCHEMA in __init__.py.
CONF_PERMAPEOPLE_KEY_ID = "permapeople_key_id"
CONF_PERMAPEOPLE_KEY_SECRET = "permapeople_key_secret"
CONF_OLLAMA_HOST = "ollama_host"
# Optional: override the frost date set via the UI (MM-DD, e.g. "05-07").
CONF_FROST_DATE = "frost_date"

# Ollama model used for companion-planting classification and days-to-maturity
# estimates (Permapeople's feed carries neither). Ollama runs locally on forge.
OLLAMA_MODEL = "llama3.1:8b"

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

# Open-Meteo (no API key required). Archive is ERA5-Land reanalysis for
# historical soil-temp normals; Forecast is the live/short-term outlook. The
# two use different soil-depth conventions (layer-mean vs. point depth), so
# they carry different variable names in api.py.
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Cool-season lawn grass (bluegrass/fescue/rye) germinates best when soil
# temperature at shallow depth is in this band (°F).
LAWN_SOIL_TEMP_MIN_F = 50
LAWN_SOIL_TEMP_MAX_F = 65

# Years of historical hourly soil-temp data to average when computing the
# spring/fall seeding windows for the home location.
LAWN_HISTORICAL_YEARS = 10

# Recompute the cached historical windows after this many days.
LAWN_CACHE_MAX_AGE_DAYS = 180

# Bump whenever the window-detection algorithm changes so cached windows from
# an older version are treated as stale and recomputed automatically.
LAWN_ALGO_VERSION = 3
