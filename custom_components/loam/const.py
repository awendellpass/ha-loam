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
# Optional: override the frost dates set via the UI (MM-DD, e.g. "05-07").
# frost_date = last spring frost, first_frost_date = first fall frost.
CONF_FROST_DATE = "frost_date"
CONF_FIRST_FROST_DATE = "first_frost_date"

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

# Triclopyr timing for creeping charlie (Glechoma hederacea). Two seasonal
# windows per standard extension guidance: fall is primary (the plant is
# translocating sugars to its roots for winter, pulling the systemic
# herbicide down with them); spring is secondary and must land before bloom,
# after which uptake drops off. Static MM-DD ranges, not computed from
# historical data like the Lawn windows — creeping charlie's fall trigger is
# root translocation, not a soil-temperature crossing.
HERBICIDE_FALL_WINDOW = ("09-01", "10-15")
HERBICIDE_SPRING_WINDOW = ("04-15", "05-31")

# Ideal air-temperature band (°F) for triclopyr application. Below this,
# plant growth/uptake is too slow for good translocation; above it, product
# labels generally caution against spraying due to volatilization/drift risk.
HERBICIDE_TEMP_MIN_F = 45
HERBICIDE_TEMP_MAX_F = 85

# Minimum forecast rain-free window (inches, next 48h) treated as "dry
# enough to spray" — triclopyr needs to stay on the leaf surface to absorb
# before rain can wash it off.
HERBICIDE_DRY_THRESHOLD_IN = 0.1
