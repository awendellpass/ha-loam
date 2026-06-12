"""SQLite database layer for Loam."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS gardens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    width_ft INTEGER,
                    height_ft INTEGER,
                    lat REAL,
                    lon REAL,
                    address TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS beds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    garden_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'raised_bed',
                    grid_x INTEGER,
                    grid_y INTEGER,
                    grid_w INTEGER,
                    grid_h INTEGER,
                    shape_geojson TEXT,
                    area_sqft REAL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(garden_id) REFERENCES gardens(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS plants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
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

                CREATE TABLE IF NOT EXISTS plantings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bed_id INTEGER NOT NULL,
                    plant_id INTEGER NOT NULL,
                    planted_date TEXT NOT NULL,
                    quantity INTEGER,
                    notes TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    removed_date TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(bed_id) REFERENCES beds(id) ON DELETE CASCADE,
                    FOREIGN KEY(plant_id) REFERENCES plants(id)
                );
            """)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add columns to pre-existing databases without dropping data."""
        self._add_column(conn, "gardens", "width_ft", "INTEGER")
        self._add_column(conn, "gardens", "height_ft", "INTEGER")
        self._add_column(conn, "beds", "grid_x", "INTEGER")
        self._add_column(conn, "beds", "grid_y", "INTEGER")
        self._add_column(conn, "beds", "grid_w", "INTEGER")
        self._add_column(conn, "beds", "grid_h", "INTEGER")

    @staticmethod
    def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # ------------------------------------------------------------------
    # Gardens
    # ------------------------------------------------------------------

    def get_gardens(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM gardens ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def get_garden(self, garden_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM gardens WHERE id = ?", (garden_id,)).fetchone()
            return dict(row) if row else None

    def create_garden(self, name: str, width_ft: int, height_ft: int) -> dict:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO gardens (name, width_ft, height_ft, created_at) VALUES (?, ?, ?, ?)",
                (name, width_ft, height_ft, _utcnow()),
            )
            row = conn.execute("SELECT * FROM gardens WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row)

    def update_garden(self, garden_id: int, name: str | None,
                      width_ft: int | None, height_ft: int | None) -> dict | None:
        with self._connect() as conn:
            updates, params = [], []
            if name is not None:
                updates.append("name = ?")
                params.append(name)
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
            row = conn.execute("SELECT * FROM gardens WHERE id = ?", (garden_id,)).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Beds
    # ------------------------------------------------------------------

    def get_beds(self, garden_id: int | None = None) -> list[dict]:
        with self._connect() as conn:
            if garden_id is not None:
                rows = conn.execute(
                    "SELECT * FROM beds WHERE garden_id = ? ORDER BY id", (garden_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM beds ORDER BY id").fetchall()
            beds = [dict(r) for r in rows]
            for bed in beds:
                bed["planting_count"] = conn.execute(
                    "SELECT COUNT(*) FROM plantings WHERE bed_id = ? AND status = 'active'",
                    (bed["id"],),
                ).fetchone()[0]
            return beds

    def get_bed(self, bed_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM beds WHERE id = ?", (bed_id,)).fetchone()
            if not row:
                return None
            bed = dict(row)
            bed["planting_count"] = conn.execute(
                "SELECT COUNT(*) FROM plantings WHERE bed_id = ? AND status = 'active'",
                (bed_id,),
            ).fetchone()[0]
            return bed

    def create_bed(self, garden_id: int, name: str, bed_type: str,
                   grid_x: int, grid_y: int, grid_w: int, grid_h: int,
                   notes: str | None) -> dict:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO beds (garden_id, name, type, grid_x, grid_y, grid_w, grid_h, "
                "area_sqft, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (garden_id, name, bed_type, grid_x, grid_y, grid_w, grid_h,
                 grid_w * grid_h, notes, _utcnow()),
            )
            row = conn.execute("SELECT * FROM beds WHERE id = ?", (cur.lastrowid,)).fetchone()
            bed = dict(row)
            bed["planting_count"] = 0
            return bed

    def update_bed(self, bed_id: int, name: str | None, bed_type: str | None,
                   grid_x: int | None, grid_y: int | None,
                   grid_w: int | None, grid_h: int | None, notes: str | None) -> dict | None:
        with self._connect() as conn:
            updates, params = [], []
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if bed_type is not None:
                updates.append("type = ?")
                params.append(bed_type)
            if grid_x is not None:
                updates.append("grid_x = ?")
                params.append(grid_x)
            if grid_y is not None:
                updates.append("grid_y = ?")
                params.append(grid_y)
            if grid_w is not None:
                updates.append("grid_w = ?")
                params.append(grid_w)
            if grid_h is not None:
                updates.append("grid_h = ?")
                params.append(grid_h)
            if grid_w is not None and grid_h is not None:
                updates.append("area_sqft = ?")
                params.append(grid_w * grid_h)
            if notes is not None:
                updates.append("notes = ?")
                params.append(notes)
            if not updates:
                return self.get_bed(bed_id)
            params.append(bed_id)
            conn.execute(f"UPDATE beds SET {', '.join(updates)} WHERE id = ?", params)
        return self.get_bed(bed_id)

    def delete_bed(self, bed_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM beds WHERE id = ?", (bed_id,))
            return cur.rowcount > 0

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
                   (name, openfarm_slug, description, sun_requirements, sowing_method,
                    row_spacing_cm, spread_cm, days_to_maturity_min, days_to_maturity_max,
                    is_custom, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["name"],
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

    def get_plantings(self, bed_id: int | None = None, status: str | None = None) -> list[dict]:
        with self._connect() as conn:
            query = """
                SELECT pl.*, p.name AS plant_name, b.name AS bed_name, b.garden_id
                FROM plantings pl
                JOIN plants p ON p.id = pl.plant_id
                JOIN beds b ON b.id = pl.bed_id
            """
            conditions, params = [], []
            if bed_id is not None:
                conditions.append("pl.bed_id = ?")
                params.append(bed_id)
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
                """SELECT pl.*, p.name AS plant_name, b.name AS bed_name, b.garden_id
                   FROM plantings pl
                   JOIN plants p ON p.id = pl.plant_id
                   JOIN beds b ON b.id = pl.bed_id
                   WHERE pl.id = ?""",
                (planting_id,),
            ).fetchone()
            return dict(row) if row else None

    def create_planting(self, bed_id: int, plant_id: int, planted_date: str,
                        quantity: int | None, notes: str | None) -> dict:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO plantings (bed_id, plant_id, planted_date, quantity, notes, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?)""",
                (bed_id, plant_id, planted_date, quantity, notes, _utcnow()),
            )
        return self.get_planting(cur.lastrowid)

    def update_planting(self, planting_id: int, status: str | None,
                        notes: str | None, removed_date: str | None) -> dict | None:
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
            if not updates:
                return self.get_planting(planting_id)
            params.append(planting_id)
            conn.execute(f"UPDATE plantings SET {', '.join(updates)} WHERE id = ?", params)
        return self.get_planting(planting_id)

    def delete_planting(self, planting_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM plantings WHERE id = ?", (planting_id,))
            return cur.rowcount > 0
