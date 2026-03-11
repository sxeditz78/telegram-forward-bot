# database.py

import json
import os
import sqlite3

from config import DB_PATH


def get_conn() -> sqlite3.Connection:
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS source_channels (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            identifier TEXT UNIQUE NOT NULL,
            label      TEXT DEFAULT ''
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS destination_channels (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            identifier TEXT UNIQUE NOT NULL,
            label      TEXT DEFAULT ''
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            id              INTEGER PRIMARY KEY CHECK (id = 1),
            posts_checked   INTEGER DEFAULT 0,
            posts_forwarded INTEGER DEFAULT 0,
            posts_ignored   INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id             INTEGER PRIMARY KEY CHECK (id = 1),
            session_string TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS api_creds (
            id       INTEGER PRIMARY KEY CHECK (id = 1),
            api_id   INTEGER NOT NULL,
            api_hash TEXT NOT NULL,
            phone    TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id   INTEGER PRIMARY KEY CHECK (id = 1),
            data TEXT NOT NULL DEFAULT '{}'
        )
    """)

    c.execute("INSERT OR IGNORE INTO stats    (id)       VALUES (1)")
    c.execute("INSERT OR IGNORE INTO settings (id, data) VALUES (1, '{}')")
    conn.commit()
    conn.close()


# ── Sources ──────────────────────────────────────────────────────
def add_source(identifier: str) -> bool:
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO source_channels (identifier) VALUES (?)",
            (identifier.strip(),)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_source(identifier: str) -> bool:
    conn = get_conn()
    cur  = conn.execute(
        "DELETE FROM source_channels WHERE identifier = ?",
        (identifier.strip(),)
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def get_all_sources() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM source_channels").fetchall()
    conn.close()
    return rows


# ── Destinations ─────────────────────────────────────────────────
def add_destination(identifier: str) -> bool:
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO destination_channels (identifier) VALUES (?)",
            (identifier.strip(),)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_destination(identifier: str) -> bool:
    conn = get_conn()
    cur  = conn.execute(
        "DELETE FROM destination_channels WHERE identifier = ?",
        (identifier.strip(),)
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def get_all_destinations() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM destination_channels").fetchall()
    conn.close()
    return rows


# ── Stats ─────────────────────────────────────────────────────────
_VALID_STATS = {"posts_checked", "posts_forwarded", "posts_ignored"}


def increment_stat(field: str):
    if field not in _VALID_STATS:
        return
    conn = get_conn()
    conn.execute(f"UPDATE stats SET {field} = {field} + 1 WHERE id = 1")
    conn.commit()
    conn.close()


def get_stats() -> dict:
    conn = get_conn()
    row  = conn.execute("SELECT * FROM stats WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else {}


# ── Session ───────────────────────────────────────────────────────
def save_session(session_string: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO sessions (id, session_string) VALUES (1, ?)",
        (session_string,)
    )
    conn.commit()
    conn.close()


def get_session():
    try:
        conn = get_conn()
        row  = conn.execute(
            "SELECT session_string FROM sessions WHERE id = 1"
        ).fetchone()
        conn.close()
        return row["session_string"] if row else None
    except Exception:
        return None


def delete_session():
    conn = get_conn()
    conn.execute("DELETE FROM sessions")
    conn.execute("DELETE FROM api_creds")
    conn.commit()
    conn.close()


# ── API Credentials ───────────────────────────────────────────────
def save_api_creds(api_id: int, api_hash: str, phone: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO api_creds (id, api_id, api_hash, phone) "
        "VALUES (1, ?, ?, ?)",
        (api_id, api_hash, phone)
    )
    conn.commit()
    conn.close()


def get_api_creds():
    try:
        conn = get_conn()
        row  = conn.execute("SELECT * FROM api_creds WHERE id = 1").fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


# ── Settings ──────────────────────────────────────────────────────
def get_settings() -> dict:
    try:
        conn = get_conn()
        row  = conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
        conn.close()
        return json.loads(row["data"]) if row else {}
    except Exception:
        return {}


def save_settings(data: dict):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)",
        (json.dumps(data),)
    )
    conn.commit()
    conn.close()
