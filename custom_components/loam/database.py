"""SQLite database layer for Loam."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# A garden is a single to-scale grid (1 cell = 1 ft) that plants are placed into.
# The earlier garden→bed split was collapsed into this one element.
GARDENS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS gardens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'raised_bed',
        width_ft INTEGER,
        height_ft INTEGER,
        created_at TEXT NOT NULL
    );
"""

PLANTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS plants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        scientific_name TEXT,
        openfarm_slug TEXT,
        description TEXT,
        sun_requirements TEXT,
        sowing_method TEXT,
        row_spacing_cm REAL,
        spread_cm REAL,
        days_to_maturity_min INTEGER,
        days_to_maturity_max INTEGER,
        is_custom INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
"""

PLANTINGS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS plantings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        garden_id INTEGER NOT NULL,
        plant_id INTEGER NOT NULL,
        planted_date TEXT NOT NULL,
        quantity INTEGER,
        notes TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        removed_date TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(garden_id) REFERENCES gardens(id) ON DELETE CASCADE,
        FOREIGN KEY(plant_id) REFERENCES plants(id)
    );
"""

# A placement is one plant assigned to one 1-ft cell of a garden (square-foot
# layout). At most one plant per cell, enforced by the UNIQUE constraint.
# planting_id links the cell to its dated plantings-log entry so the grid and
# the Plantings tab stay in sync.
PLACEMENTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS placements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        garden_id INTEGER NOT NULL,
        grid_col INTEGER NOT NULL,
        grid_row INTEGER NOT NULL,
        plant_id INTEGER NOT NULL,
        planting_id INTEGER,
        note TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(garden_id, grid_col, grid_row),
        FOREIGN KEY(garden_id) REFERENCES gardens(id) ON DELETE CASCADE,
        FOREIGN KEY(plant_id) REFERENCES plants(id) ON DELETE CASCADE
    );
"""

# Cached companion-planting relationships between two plants, resolved once via
# Claude and reused. Stored with plant_a_id < plant_b_id so each unordered pair
# has a single row. relationship is 'good', 'bad', or 'neutral'.
COMPANIONS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS companions (
        plant_a_id INTEGER NOT NULL,
        plant_b_id INTEGER NOT NULL,
        relationship TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (plant_a_id, plant_b_id),
        FOREIGN KEY(plant_a_id) REFERENCES plants(id) ON DELETE CASCADE,
        FOREIGN KEY(plant_b_id) REFERENCES plants(id) ON DELETE CASCADE
    );
"""

# Cached growing-calendar data per plant, estimated once via Ollama.
# All week offsets are relative to the user's last spring frost date.
# Negative = weeks before frost (e.g. -8 = 8 weeks before for seed starting).
PHENOLOGY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS plant_phenology (
        plant_id INTEGER PRIMARY KEY,
        plant_type TEXT,
        start_indoors_week INTEGER,
        direct_sow_week INTEGER,
        transplant_week INTEGER,
        harvest_start_week INTEGER,
        harvest_end_week INTEGER,
        bloom_start_week INTEGER,
        bloom_end_week INTEGER,
        bloom_color TEXT,
        pollinators TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(plant_id) REFERENCES plants(id) ON DELETE CASCADE
    );
"""

# Simple key/value store for user-configurable settings (e.g. frost_date).
SETTINGS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS loam_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
"""


class LoamDatabase:
    """Manages all Loam data in a local SQLite database."""

    def __init__(self, db_path: str) -> None:
        self._path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                GARDENS_SCHEMA + PLANTS_SCHEMA + PLANTINGS_SCHEMA
                + PLACEMENTS_SCHEMA + COMPANIONS_SCHEMA
                + PHENOLOGY_SCHEMA + SETTINGS_SCHEMA
            )
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Bring older databases up to the combined-garden schema without losing the plant library."""
        # Columns added when gardens absorbed the old bed fields.
        self._add_column(conn, "gardens", "type", "TEXT NOT NULL DEFAULT 'raised_bed'")
        self._add_column(conn, "gardens", "width_ft", "INTEGER")
        self._add_column(conn, "gardens", "height_ft", "INTEGER")

        # The bed layer is gone; plantings now reference gardens directly.
        # Older plantings referenced beds (no real data) — rebuild against gardens.
        planting_cols = {r["name"] for r in conn.execute("PRAGMA table_info(plantings)").fetchall()}
        if "bed_id" in planting_cols:
            conn.execute("DROP TABLE plantings")
            conn.executescript(PLANTINGS_SCHEMA)
        conn.execute("DROP TABLE IF EXISTS beds")

        # Link placements to their plantings-log entry (added with grid↔log sync).
        self._add_column(conn, "placements", "planting_id", "INTEGER")

        # Scientific (Latin) name shown on plant cards; was previously merged
        # into description.
        self._add_column(conn, "plants", "scientific_name", "TEXT")

        # Wishlist flag — plants starred for future planning; appear in the
        # Calendar tab even when not yet planted.
        self._add_column(conn, "plants", "wishlist", "INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # ------------------------------------------------------------------
    # Gardens
    # ------------------------------------------------------------------

    def _attach_planting_count(self, conn: sqlite3.Connection, garden: dict) -> dict:
        garden["planting_count"] = conn.execute(
            "SELECT COUNT(*) FROM plantings WHERE garden_id = ? AND status = 'active'",
            (garden["id"],),
        ).fetchone()[0]
        return garden

    def get_gardens(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM gardens ORDER BY id").fetchall()
            return [self._attach_planting_count(conn, dict(r)) for r in rows]

    def get_garden(self, garden_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM gardens WHERE id = ?", (garden_id,)).fetchone()
            return self._attach_planting_count(conn, dict(row)) if row else None

    def create_garden(self, name: str, garden_type: str, width_ft: int, height_ft: int) -> dict:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO gardens (name, type, width_ft, height_ft, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, garden_type, width_ft, height_ft, _utcnow()),
            )
            row = conn.execute("SELECT * FROM gardens WHERE id = ?", (cur.lastrowid,)).fetchone()
            garden = dict(row)
            garden["planting_count"] = 0
            return garden

    def update_garden(self, garden_id: int, name: str | None, garden_type: str | None,
                      width_ft: int | None, height_ft: int | None) -> dict | None:
        with self._connect() as conn:
            updates, params = [], []
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if garden_type is not None:
                updates.append("type = ?")
                params.append(garden_type)
            if width_ft is not None:
                updates.append("width_ft = ?")
                params.append(width_ft)
            if height_ft is not None:
                updates.append("height_ft = ?")
                params.append(height_ft)
            if not updates:
                return self.get_garden(garden_id)
            params.append(garden_id)
            conn.execute(f"UPDATE gardens SET {', '.join(updates)} WHERE id = ?", params)
        return self.get_garden(garden_id)

    def delete_garden(self, garden_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM gardens WHERE id = ?", (garden_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Placements (a plant assigned to one garden cell)
    # ------------------------------------------------------------------

    def get_placements(self, garden_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT pc.*, p.name AS plant_name
                   FROM placements pc
                   JOIN plants p ON p.id = pc.plant_id
                   WHERE pc.garden_id = ?
                   ORDER BY pc.grid_row, pc.grid_col""",
                (garden_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def apply_placements(self, garden_id: int, cells: list[dict]) -> list[dict]:
        """Set or clear cells in one pass. A cell with plant_id None is cleared.

        Keeps the plantings log in sync: setting a cell creates an active
        planting; clearing or replacing one marks the old planting removed.
        """
        today = _utcnow()[:10]
        with self._connect() as conn:
            for cell in cells:
                col = int(cell["grid_col"])
                row = int(cell["grid_row"])
                plant_id = cell.get("plant_id")
                existing = conn.execute(
                    "SELECT id, plant_id, planting_id FROM placements "
                    "WHERE garden_id = ? AND grid_col = ? AND grid_row = ?",
                    (garden_id, col, row),
                ).fetchone()

                if plant_id is None:
                    if existing:
                        self._retire_planting(conn, existing["planting_id"], today)
                        conn.execute("DELETE FROM placements WHERE id = ?", (existing["id"],))
                    continue

                plant_id = int(plant_id)
                if existing and existing["plant_id"] == plant_id:
                    continue  # no change — keep its planting

                if existing:
                    self._retire_planting(conn, existing["planting_id"], today)
                planting_id = self._insert_planting(conn, garden_id, plant_id, today)
                conn.execute(
                    """INSERT INTO placements
                       (garden_id, grid_col, grid_row, plant_id, planting_id, note, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(garden_id, grid_col, grid_row)
                       DO UPDATE SET plant_id = excluded.plant_id,
                                     planting_id = excluded.planting_id,
                                     note = excluded.note""",
                    (garden_id, col, row, plant_id, planting_id, cell.get("note"), _utcnow()),
                )
        return self.get_placements(garden_id)

    @staticmethod
    def _insert_planting(conn: sqlite3.Connection, garden_id: int, plant_id: int, today: str) -> int:
        cur = conn.execute(
            """INSERT INTO plantings (garden_id, plant_id, planted_date, status, created_at)
               VALUES (?, ?, ?, 'active', ?)""",
            (garden_id, plant_id, today, _utcnow()),
        )
        return cur.lastrowid

    @staticmethod
    def _retire_planting(conn: sqlite3.Connection, planting_id: int | None, today: str) -> None:
        if planting_id is None:
            return
        conn.execute(
            "UPDATE plantings SET status = 'removed', removed_date = ? "
            "WHERE id = ? AND status = 'active'",
            (today, planting_id),
        )

    # ------------------------------------------------------------------
    # Companions (cached good/bad/neutral relationships between two plants)
    # ------------------------------------------------------------------

    @staticmethod
    def _pair(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    def get_companions(self, plant_ids: list[int]) -> dict[str, str]:
        """Return cached relationships for all pairs among plant_ids, keyed 'a,b' (a<b)."""
        ids = sorted(set(plant_ids))
        if len(ids) < 2:
            return {}
        placeholders = ",".join("?" * len(ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT plant_a_id, plant_b_id, relationship FROM companions
                    WHERE plant_a_id IN ({placeholders}) AND plant_b_id IN ({placeholders})""",
                ids + ids,
            ).fetchall()
        return {f"{r['plant_a_id']},{r['plant_b_id']}": r["relationship"] for r in rows}

    def save_companions(self, pairs: list[dict]) -> None:
        """Persist resolved relationships. Each pair: {a, b, relationship}."""
        with self._connect() as conn:
            for p in pairs:
                a, b = self._pair(int(p["a"]), int(p["b"]))
                conn.execute(
                    """INSERT INTO companions (plant_a_id, plant_b_id, relationship, created_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(plant_a_id, plant_b_id)
                       DO UPDATE SET relationship = excluded.relationship""",
                    (a, b, p["relationship"], _utcnow()),
                )

    # ------------------------------------------------------------------
    # Plants
    # ------------------------------------------------------------------

    def get_plants(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM plants ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    def get_plant(self, plant_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plants WHERE id = ?", (plant_id,)).fetchone()
            return dict(row) if row else None

    def create_plant(self, data: dict) -> dict:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO plants
                   (name, scientific_name, openfarm_slug, description, sun_requirements,
                    sowing_method, row_spacing_cm, spread_cm, days_to_maturity_min,
                    days_to_maturity_max, is_custom, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["name"],
                    data.get("scientific_name"),
                    data.get("openfarm_slug"),
                    data.get("description"),
                    data.get("sun_requirements"),
                    data.get("sowing_method"),
                    data.get("row_spacing_cm"),
                    data.get("spread_cm"),
                    data.get("days_to_maturity_min"),
                    data.get("days_to_maturity_max"),
                    1 if data.get("is_custom") else 0,
                    _utcnow(),
                ),
            )
            row = conn.execute("SELECT * FROM plants WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row)

    def update_plant(self, plant_id: int, days_to_maturity_min: int | None = None,
                     wishlist: bool | None = None, name: str | None = None,
                     scientific_name: str | None = None) -> dict | None:
        with self._connect() as conn:
            updates, params = [], []
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if scientific_name is not None:
                updates.append("scientific_name = ?")
                params.append(scientific_name)
            if days_to_maturity_min is not None:
                updates.append("days_to_maturity_min = ?")
                params.append(days_to_maturity_min)
            if wishlist is not None:
                updates.append("wishlist = ?")
                params.append(1 if wishlist else 0)
            if not updates:
                return self.get_plant(plant_id)
            params.append(plant_id)
            conn.execute(f"UPDATE plants SET {', '.join(updates)} WHERE id = ?", params)
        return self.get_plant(plant_id)

    def plant_exists_by_slug(self, slug: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM plants WHERE openfarm_slug = ?", (slug,)
            ).fetchone()
            return row is not None

    def delete_plant(self, plant_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM plants WHERE id = ?", (plant_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Plantings
    # ------------------------------------------------------------------

    def get_plantings(self, garden_id: int | None = None, status: str | None = None) -> list[dict]:
        with self._connect() as conn:
            query = """
                SELECT pl.*, p.name AS plant_name, p.days_to_maturity_min, g.name AS garden_name
                FROM plantings pl
                JOIN plants p ON p.id = pl.plant_id
                JOIN gardens g ON g.id = pl.garden_id
            """
            conditions, params = [], []
            if garden_id is not None:
                conditions.append("pl.garden_id = ?")
                params.append(garden_id)
            if status is not None:
                conditions.append("pl.status = ?")
                params.append(status)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY pl.planted_date DESC, pl.id DESC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_planting(self, planting_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT pl.*, p.name AS plant_name, p.days_to_maturity_min, g.name AS garden_name
                   FROM plantings pl
                   JOIN plants p ON p.id = pl.plant_id
                   JOIN gardens g ON g.id = pl.garden_id
                   WHERE pl.id = ?""",
                (planting_id,),
            ).fetchone()
            return dict(row) if row else None

    def create_planting(self, garden_id: int, plant_id: int, planted_date: str,
                        quantity: int | None, notes: str | None) -> dict:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO plantings (garden_id, plant_id, planted_date, quantity, notes, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?)""",
                (garden_id, plant_id, planted_date, quantity, notes, _utcnow()),
            )
        return self.get_planting(cur.lastrowid)

    def update_planting(self, planting_id: int, status: str | None,
                        notes: str | None, removed_date: str | None,
                        planted_date: str | None = None) -> dict | None:
        with self._connect() as conn:
            updates, params = [], []
            if status is not None:
                updates.append("status = ?")
                params.append(status)
            if notes is not None:
                updates.append("notes = ?")
                params.append(notes)
            if removed_date is not None:
                updates.append("removed_date = ?")
                params.append(removed_date)
            if planted_date is not None:
                updates.append("planted_date = ?")
                params.append(planted_date)
            if not updates:
                return self.get_planting(planting_id)
            params.append(planting_id)
            conn.execute(f"UPDATE plantings SET {', '.join(updates)} WHERE id = ?", params)
            # Harvesting/removing in the log clears the matching grid cell.
            if status in ("harvested", "removed"):
                conn.execute("DELETE FROM placements WHERE planting_id = ?", (planting_id,))
        return self.get_planting(planting_id)

    def delete_planting(self, planting_id: int) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM placements WHERE planting_id = ?", (planting_id,))
            cur = conn.execute("DELETE FROM plantings WHERE id = ?", (planting_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Phenology (cached growing-calendar data per plant)
    # ------------------------------------------------------------------

    def get_phenology(self, plant_ids: list[int]) -> dict[int, dict]:
        """Return cached phenology keyed by plant_id for the given IDs."""
        if not plant_ids:
            return {}
        placeholders = ",".join("?" * len(plant_ids))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM plant_phenology WHERE plant_id IN ({placeholders})",
                plant_ids,
            ).fetchall()
        result = {}
        for r in rows:
            d = dict(r)
            import json as _json
            raw = d.get("pollinators")
            d["pollinators"] = _json.loads(raw) if raw else []
            result[d["plant_id"]] = d
        return result

    def save_phenology(self, plant_id: int, data: dict) -> None:
        """Persist phenology data for one plant (upsert)."""
        import json as _json
        pollinators = _json.dumps(data.get("pollinators") or [])
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO plant_phenology
                   (plant_id, plant_type, start_indoors_week, direct_sow_week,
                    transplant_week, harvest_start_week, harvest_end_week,
                    bloom_start_week, bloom_end_week, bloom_color, pollinators, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(plant_id) DO UPDATE SET
                     plant_type = excluded.plant_type,
                     start_indoors_week = excluded.start_indoors_week,
                     direct_sow_week = excluded.direct_sow_week,
                     transplant_week = excluded.transplant_week,
                     harvest_start_week = excluded.harvest_start_week,
                     harvest_end_week = excluded.harvest_end_week,
                     bloom_start_week = excluded.bloom_start_week,
                     bloom_end_week = excluded.bloom_end_week,
                     bloom_color = excluded.bloom_color,
                     pollinators = excluded.pollinators""",
                (
                    plant_id,
                    data.get("plant_type"),
                    data.get("start_indoors_week"),
                    data.get("direct_sow_week"),
                    data.get("transplant_week"),
                    data.get("harvest_start_week"),
                    data.get("harvest_end_week"),
                    data.get("bloom_start_week"),
                    data.get("bloom_end_week"),
                    data.get("bloom_color"),
                    pollinators,
                    _utcnow(),
                ),
            )

    # ------------------------------------------------------------------
    # Settings (simple key/value for user-configurable values)
    # ------------------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM loam_settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO loam_settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------------
    # Calendar grouping
    # ------------------------------------------------------------------

    def get_calendar_plants(self) -> dict:
        """Return all plants split into three groups for the calendar view.

        - garden:  plants with at least one active planting
        - wishlist: plants with wishlist=1 that are NOT currently in the garden
        - library:  remaining saved plants (no active planting, not wishlisted)

        Each plant appears in exactly one group.
        """
        with self._connect() as conn:
            garden_rows = conn.execute(
                """SELECT DISTINCT p.* FROM plants p
                   JOIN plantings pl ON pl.plant_id = p.id AND pl.status = 'active'
                   ORDER BY p.name"""
            ).fetchall()

            non_garden = conn.execute(
                """SELECT * FROM plants
                   WHERE id NOT IN (
                       SELECT DISTINCT plant_id FROM plantings WHERE status = 'active'
                   )
                   ORDER BY name"""
            ).fetchall()

        wishlist_rows = [r for r in non_garden if r["wishlist"]]
        library_rows  = [r for r in non_garden if not r["wishlist"]]

        return {
            "garden":   [dict(r) for r in garden_rows],
            "wishlist": [dict(r) for r in wishlist_rows],
            "library":  [dict(r) for r in library_rows],
        }
