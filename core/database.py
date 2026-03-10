"""
core/database.py — SQLite database layer.

Tables:
  devices    — tracked APC NMC devices (name, IP, type, notes, location)
  audit_log  — structured action log
  settings   — key/value store (also used by credentials module)
"""

import sqlite3
import os
import sys
from typing import List, Dict, Optional, Any


def _get_db_path() -> str:
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "apc_devices.db")


DB_PATH = _get_db_path()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_db() -> None:
    conn = get_connection()
    # Enable WAL mode once; it persists in the DB file — no need to set it on every open.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL UNIQUE,
            ip            TEXT    NOT NULL,
            card_type     TEXT    NOT NULL DEFAULT 'NMC2',
            notes         TEXT    NOT NULL DEFAULT '',
            location      TEXT    NOT NULL DEFAULT '',
            last_connected DATETIME,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
            device_name TEXT,
            ip          TEXT,
            username    TEXT,
            action      TEXT NOT NULL,
            details     TEXT NOT NULL DEFAULT '',
            result      TEXT NOT NULL DEFAULT 'success'
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );

        -- TOFU host key store: fingerprints accepted by the operator.
        -- If a device's fingerprint changes and no override is given, the
        -- connection is blocked to prevent MITM attacks.
        CREATE TABLE IF NOT EXISTS host_keys (
            ip          TEXT PRIMARY KEY,
            key_type    TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            accepted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            accepted_by TEXT NOT NULL DEFAULT ''
        );
    """)
    conn.commit()
    conn.close()


# ──────────────────────────── Devices ──────────────────────────────── #

def get_all_devices() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM devices ORDER BY name ASC"
    ).fetchall()]
    conn.close()
    return rows


def get_device_by_name(name: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM devices WHERE UPPER(TRIM(name)) = UPPER(TRIM(?))", (name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_device_by_id(device_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM devices WHERE id = ?", (device_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_device(name: str, ip: str, card_type: str = 'NMC2',
               notes: str = '', location: str = '') -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO devices (name, ip, card_type, notes, location) VALUES (?,?,?,?,?)",
        (name.strip().upper(), ip.strip(), card_type, notes.strip(), location.strip())
    )
    device_id = cur.lastrowid
    conn.commit()
    conn.close()
    return device_id


def update_device(device_id: int, name: str, ip: str, card_type: str,
                  notes: str = '', location: str = '') -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE devices
           SET name=?, ip=?, card_type=?, notes=?, location=?
           WHERE id=?""",
        (name.strip().upper(), ip.strip(), card_type,
         notes.strip(), location.strip(), device_id)
    )
    conn.commit()
    conn.close()


def delete_device(device_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    conn.commit()
    conn.close()


def get_device_count() -> int:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    conn.close()
    return count


def update_last_connected(device_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE devices SET last_connected = CURRENT_TIMESTAMP WHERE id = ?",
        (device_id,)
    )
    conn.commit()
    conn.close()


def update_card_type(device_id: int, card_type: str) -> None:
    """Persist an auto-detected card type for a device."""
    conn = get_connection()
    conn.execute(
        "UPDATE devices SET card_type = ? WHERE id = ?",
        (card_type, device_id)
    )
    conn.commit()
    conn.close()


# ──────────────────────────── Audit Log ────────────────────────────── #

def log_audit(device_name: str, ip: str, username: str,
              action: str, details: str = '', result: str = 'success') -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO audit_log (device_name, ip, username, action, details, result)
           VALUES (?,?,?,?,?,?)""",
        (device_name, ip, username, action, details, result)
    )
    conn.commit()
    conn.close()


def get_audit_log(limit: int = 1000, device_name: Optional[str] = None,
                  search: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    query = "SELECT * FROM audit_log WHERE 1=1"
    params: List[Any] = []

    if device_name:
        query += " AND device_name = ?"
        params.append(device_name)

    if search:
        query += " AND (action LIKE ? OR details LIKE ? OR device_name LIKE ? OR ip LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s, s])

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return rows


def get_audit_count() -> int:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    conn.close()
    return count


def clear_audit_log() -> None:
    conn = get_connection()
    conn.execute("DELETE FROM audit_log")
    conn.commit()
    conn.close()


def export_audit_csv(filepath: str) -> int:
    """Export audit log to CSV. Returns number of rows written."""
    import csv
    rows = get_audit_log(limit=100000)
    if not rows:
        return 0
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# ──────────────────────────── Settings ────────────────────────────── #

def get_setting(key: str, default: str = '') -> str:
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value)
    )
    conn.commit()
    conn.close()


def delete_setting(key: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    conn.commit()
    conn.close()


def delete_settings_prefix(prefix: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM settings WHERE key LIKE ?", (f"{prefix}%",))
    conn.commit()
    conn.close()


# ──────────────────────────── Host Keys (TOFU) ─────────────────────── #

def get_host_key(ip: str) -> Optional[Dict[str, Any]]:
    """Return the stored host key record for an IP, or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM host_keys WHERE ip = ?", (ip,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_host_key(ip: str, key_type: str, fingerprint: str,
                  accepted_by: str = "") -> None:
    """Insert or replace the trusted host key for an IP."""
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO host_keys (ip, key_type, fingerprint, accepted_by)
           VALUES (?,?,?,?)""",
        (ip, key_type, fingerprint, accepted_by)
    )
    conn.commit()
    conn.close()


def delete_host_key(ip: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM host_keys WHERE ip = ?", (ip,))
    conn.commit()
    conn.close()
