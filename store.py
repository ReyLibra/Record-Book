"""SQLite storage for Record Book: logged characters, DPS runs, notes and UI settings."""

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from app_info import APP_DIR

HERE = APP_DIR
DB_PATH = HERE / "record_book.db"
OLD_JOURNAL_PATH = HERE / "journal.db"

CHARACTER_FIELDS = (
    "char_id",
    "name",
    "element",
    "weapon_id",
    "refinement",
    "artifact1",
    "artifact2",
    "talent1",
    "talent2",
    "talent3",
    "notes",
    "constellation",
)


# the gear and talents part of a character record, shared with teammates
BUILD_FIELDS = ("weapon_id", "refinement", "artifact1", "artifact2", "talent1", "talent2", "talent3")


class Store:
    def __init__(self, path=DB_PATH):
        if path == DB_PATH and not DB_PATH.exists() and OLD_JOURNAL_PATH.exists():
            # Carry the old journal entries over; journal.db itself is left untouched.
            shutil.copyfile(OLD_JOURNAL_PATH, DB_PATH)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS characters (
                char_id    TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                element    TEXT NOT NULL,
                weapon_id  INTEGER,
                refinement INTEGER NOT NULL DEFAULT 1,
                artifact1  INTEGER,
                artifact2  INTEGER,
                talent1    INTEGER NOT NULL DEFAULT 1,
                talent2    INTEGER NOT NULL DEFAULT 1,
                talent3    INTEGER NOT NULL DEFAULT 1,
                notes      TEXT NOT NULL DEFAULT '',
                added_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dps_runs (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                char_id  TEXT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
                dps      REAL NOT NULL,
                run_date TEXT NOT NULL,
                note     TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            -- a logged run on the character log: the whole team as it was (JSON list of builds, the
            -- logged character first), the notes, the damage and the DPS it works out to
            CREATE TABLE IF NOT EXISTS runs (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                char_id  TEXT NOT NULL REFERENCES characters(char_id) ON DELETE CASCADE,
                run_date TEXT NOT NULL,
                mode     TEXT NOT NULL DEFAULT 'abyss',
                damage   REAL,
                dps      REAL NOT NULL DEFAULT 0,
                is_best  INTEGER NOT NULL DEFAULT 0,
                notes    TEXT NOT NULL DEFAULT '',
                team     TEXT NOT NULL DEFAULT '[]'
            );
            -- "My Build" on the Characters page for a character not in the Record Book (a logged one's is
            -- their record): the build they get when picked as a teammate on the log
            CREATE TABLE IF NOT EXISTS my_builds (
                char_id       TEXT PRIMARY KEY,
                weapon_id     INTEGER,
                refinement    INTEGER NOT NULL DEFAULT 1,
                artifact1     INTEGER,
                artifact2     INTEGER,
                talent1       INTEGER NOT NULL DEFAULT 1,
                talent2       INTEGER NOT NULL DEFAULT 1,
                talent3       INTEGER NOT NULL DEFAULT 1,
                constellation INTEGER NOT NULL DEFAULT 0
            );
            -- the last build entered for each teammate, used to fill them in on other teams
            CREATE TABLE IF NOT EXISTS support_builds (
                char_id    TEXT PRIMARY KEY,
                weapon_id  INTEGER,
                refinement INTEGER NOT NULL DEFAULT 1,
                artifact1  INTEGER,
                artifact2  INTEGER,
                talent1    INTEGER NOT NULL DEFAULT 1,
                talent2    INTEGER NOT NULL DEFAULT 1,
                talent3    INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        # DPS runs gained the damage entered, the mode it was divided by, and a "highest" mark
        columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(dps_runs)")}
        for column, kind in (("damage", "REAL"), ("mode", "TEXT"), ("is_best", "INTEGER NOT NULL DEFAULT 0")):
            if column not in columns:
                self.conn.execute(f"ALTER TABLE dps_runs ADD COLUMN {column} {kind}")
        if "constellation" not in {r["name"] for r in self.conn.execute("PRAGMA table_info(characters)")}:
            self.conn.execute("ALTER TABLE characters ADD COLUMN constellation INTEGER NOT NULL DEFAULT 0")
        if "team_name" not in {r["name"] for r in self.conn.execute("PRAGMA table_info(runs)")}:
            self.conn.execute("ALTER TABLE runs ADD COLUMN team_name TEXT NOT NULL DEFAULT ''")
        self.conn.commit()
        # DPS logged the old way becomes runs (without a team), once
        if not self.get_setting("runs_migrated"):
            self.conn.execute(
                "INSERT INTO runs (char_id, run_date, mode, damage, dps, is_best, notes) "
                "SELECT char_id, run_date, COALESCE(mode, 'abyss'), damage, dps, is_best, note FROM dps_runs WHERE dps > 0"
            )
            self.set_setting("runs_migrated", True)

    # ---------- characters ----------
    def characters(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM characters ORDER BY name")]

    def character(self, char_id):
        row = self.conn.execute("SELECT * FROM characters WHERE char_id = ?", (char_id,)).fetchone()
        return dict(row) if row else None

    def save_character(self, data):
        """Insert or update a logged character from a dict with CHARACTER_FIELDS keys."""
        values = {f: data.get(f) for f in CHARACTER_FIELDS}
        values["notes"] = values["notes"] or ""
        values["constellation"] = values["constellation"] or 0
        existing = self.character(values["char_id"])
        if existing:
            sets = ", ".join(f"{f} = :{f}" for f in CHARACTER_FIELDS[1:])
            self.conn.execute(f"UPDATE characters SET {sets} WHERE char_id = :char_id", values)
        else:
            values["added_at"] = datetime.now().isoformat(timespec="seconds")
            cols = ", ".join(values)
            self.conn.execute(f"INSERT INTO characters ({cols}) VALUES ({', '.join(':' + c for c in values)})", values)
        self.conn.commit()

    def update_character(self, char_id, **fields):
        bad = set(fields) - set(CHARACTER_FIELDS[1:])
        if bad:
            raise ValueError(f"Unknown fields: {bad}")
        sets = ", ".join(f"{f} = ?" for f in fields)
        self.conn.execute(f"UPDATE characters SET {sets} WHERE char_id = ?", (*fields.values(), char_id))
        self.conn.commit()

    def delete_character(self, char_id):
        self.conn.execute("DELETE FROM characters WHERE char_id = ?", (char_id,))
        self.conn.commit()

    # ---------- runs (character log) ----------
    def runs(self, char_id):
        """A character's runs, newest first; `team` decoded to a list of build dicts."""
        rows = self.conn.execute(
            "SELECT * FROM runs WHERE char_id = ? ORDER BY substr(run_date, 1, 10) DESC, id DESC", (char_id,)
        ).fetchall()
        return [dict(r, team=json.loads(r["team"] or "[]")) for r in rows]

    def run(self, run_id):
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row, team=json.loads(row["team"] or "[]")) if row else None

    def save_run(self, char_id, data, run_id=None):
        """Insert (run_id None) or update a run from {run_date, mode, damage, dps, notes, team, is_best}.
        Teammates' builds are remembered for filling them in on other characters' runs."""
        values = {
            "run_date": data.get("run_date") or datetime.now().date().isoformat(),
            "mode": data.get("mode") or "abyss",
            "damage": data.get("damage"),
            "dps": data.get("dps") or 0,
            "notes": data.get("notes") or "",
            "team": json.dumps(data.get("team") or []),
            "team_name": (data.get("team_name") or "").strip(),
        }
        if run_id is None:
            values["char_id"] = char_id
            cols = ", ".join(values)
            run_id = self.conn.execute(
                f"INSERT INTO runs ({cols}) VALUES ({', '.join(':' + c for c in values)})", values
            ).lastrowid
        else:
            sets = ", ".join(f"{c} = :{c}" for c in values)
            self.conn.execute(f"UPDATE runs SET {sets} WHERE id = :id", {**values, "id": run_id})
        if "is_best" in data:
            if data["is_best"]:
                self.conn.execute("UPDATE runs SET is_best = (id = ?) WHERE char_id = ?", (run_id, char_id))
            else:
                self.conn.execute("UPDATE runs SET is_best = 0 WHERE id = ?", (run_id,))
        for member in (data.get("team") or [])[1:]:
            # a teammate with no My Build yet: the build given them here becomes it (from then on, they're
            # always filled in from My Build)
            mine = self.my_build(str(member["char_id"])) or {}
            if not (mine.get("weapon_id") and mine.get("artifact1")) and member.get("weapon_id") and member.get("artifact1"):
                self.set_my_build(str(member["char_id"]), member)
            elif mine:
                # they have one: the talent levels and constellation entered here update it (the weapon and
                # artifacts stay as My Build has them)
                levels = {f: member.get(f) for f in ("talent1", "talent2", "talent3", "constellation") if member.get(f) is not None}
                if any(mine.get(f) != v for f, v in levels.items()):
                    self.set_my_build(str(member["char_id"]), {**mine, **levels})
            saved = {"char_id": str(member["char_id"]), **{f: member.get(f) for f in BUILD_FIELDS}}
            self.conn.execute(
                f"INSERT OR REPLACE INTO support_builds ({', '.join(saved)}) VALUES ({', '.join(':' + c for c in saved)})",
                saved,
            )
        self.conn.commit()
        return run_id

    def team_names(self):
        """Every team name used on any run, for suggestions."""
        rows = self.conn.execute("SELECT DISTINCT team_name FROM runs WHERE team_name != '' ORDER BY team_name")
        return [r[0] for r in rows]

    def delete_run(self, run_id):
        self.conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        self.conn.commit()

    def my_build(self, char_id):
        """A character's "My Build" (Characters page): their logged build if they're in the Record Book,
        else the one filled in for them, else None."""
        record = self.character(char_id)
        if record:
            return {f: record[f] for f in ("char_id",) + BUILD_FIELDS + ("constellation",)}
        row = self.conn.execute("SELECT * FROM my_builds WHERE char_id = ?", (str(char_id),)).fetchone()
        return dict(row) if row else None

    def set_my_build(self, char_id, values):
        fields = {f: values.get(f) for f in BUILD_FIELDS + ("constellation",)}
        if self.character(char_id):
            self.update_character(char_id, **fields)
            return
        fields["char_id"] = str(char_id)
        cols = ", ".join(fields)
        self.conn.execute(f"INSERT OR REPLACE INTO my_builds ({cols}) VALUES ({', '.join(':' + c for c in fields)})", fields)
        self.conn.commit()

    def saved_build(self, char_id):
        """The build a character gets when picked as a teammate: their My Build, else the build they last
        had on a team, else None."""
        mine = self.my_build(char_id)
        if mine and (mine.get("weapon_id") or mine.get("artifact1")):
            return mine
        row = self.conn.execute("SELECT * FROM support_builds WHERE char_id = ?", (char_id,)).fetchone()
        return dict(row) if row else mine

    # ---------- DPS ----------
    def dps_runs(self, char_id):
        """Runs in the order they were added."""
        return [dict(r) for r in self.conn.execute("SELECT * FROM dps_runs WHERE char_id = ? ORDER BY id", (char_id,))]

    def best_run_id(self, char_id, mode=None):
        """The run with the highest DPS (the newest one on a tie), overall or for one mode, or None."""
        sql = "SELECT id FROM runs WHERE char_id = ? AND dps > 0"
        args = [char_id]
        if mode:
            sql += " AND mode = ?"
            args.append(mode)
        row = self.conn.execute(sql + " ORDER BY dps DESC, id DESC LIMIT 1", args).fetchone()
        return row[0] if row else None

    def best_dps(self, char_id, mode=None):
        """The highest DPS on the character log, overall or for one mode ('abyss', 'fearless', 'dire')."""
        if mode:
            row = self.conn.execute(
                "SELECT MAX(dps) FROM runs WHERE char_id = ? AND mode = ?", (char_id, mode)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT MAX(dps) FROM runs WHERE char_id = ?", (char_id,)).fetchone()
        return row[0] or 0

    def add_dps(self, char_id, dps, run_date, note="", damage=None, mode=None):
        cur = self.conn.execute(
            "INSERT INTO dps_runs (char_id, dps, run_date, note, damage, mode) VALUES (?, ?, ?, ?, ?, ?)",
            (char_id, dps, run_date, note, damage, mode),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_dps(self, run_id, **fields):
        bad = set(fields) - {"dps", "damage", "mode", "note"}
        if bad:
            raise ValueError(f"Unknown fields: {bad}")
        sets = ", ".join(f"{f} = ?" for f in fields)
        self.conn.execute(f"UPDATE dps_runs SET {sets} WHERE id = ?", (*fields.values(), run_id))
        self.conn.commit()

    def mark_best_dps(self, char_id, run_id):
        """Make run_id the character's highest DPS (None clears the mark)."""
        self.conn.execute("UPDATE dps_runs SET is_best = (id = ?) WHERE char_id = ?", (run_id or -1, char_id))
        self.conn.commit()

    def delete_dps(self, run_id):
        self.conn.execute("DELETE FROM dps_runs WHERE id = ?", (run_id,))
        self.conn.commit()

    # ---------- favourites (the ★ on a log page) ----------
    def favourites(self):
        return [str(c) for c in self.get_setting("favourites", []) or []]

    def set_favourite(self, char_id, on):
        favs = [c for c in self.favourites() if c != str(char_id)]
        if on:
            favs.append(str(char_id))
        self.set_setting("favourites", favs)

    # ---------- settings (JSON values) ----------
    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
        self.conn.commit()
