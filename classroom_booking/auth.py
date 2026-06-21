from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3

from .db import log_action

HASH_NAME = "sha256"
ITERATIONS = 260_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password is required.")
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_{HASH_NAME}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if scheme != f"pbkdf2_{HASH_NAME}":
            return False
        digest = hashlib.pbkdf2_hmac(
            HASH_NAME,
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def user_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
    return int(row["count"])


def create_user(
    conn: sqlite3.Connection,
    username: str,
    password: str,
    is_admin: bool = False,
    actor_id: int | None = None,
) -> int:
    username = username.strip()
    if not username:
        raise ValueError("Username is required.")
    cur = conn.execute(
        """
        INSERT INTO users (username, password_hash, is_admin)
        VALUES (?, ?, ?)
        """,
        (username, hash_password(password), int(is_admin)),
    )
    conn.commit()
    user_id = int(cur.lastrowid)
    log_action(conn, actor_id, "create_user", "user", user_id, f"username={username}")
    return user_id


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? AND is_active = 1",
        (username.strip(),),
    ).fetchone()
    if row and verify_password(password, row["password_hash"]):
        return public_user(row)
    return None


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "is_active": bool(row["is_active"]),
    }


def get_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return public_user(row) if row else None


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT id, username, is_admin, is_active, created_at FROM users ORDER BY username"))


def set_user_admin(conn: sqlite3.Connection, user_id: int, is_admin: bool, actor_id: int) -> None:
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id))
    conn.commit()
    log_action(conn, actor_id, "set_user_admin", "user", user_id, f"is_admin={is_admin}")


def set_user_active(conn: sqlite3.Connection, user_id: int, is_active: bool, actor_id: int) -> None:
    conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id))
    conn.commit()
    log_action(conn, actor_id, "set_user_active", "user", user_id, f"is_active={is_active}")


def reset_password(conn: sqlite3.Connection, user_id: int, password: str, actor_id: int) -> None:
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
    conn.commit()
    log_action(conn, actor_id, "reset_password", "user", user_id)
