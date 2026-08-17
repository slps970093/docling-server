"""SQLite-backed task store for async embedding jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_db_path: Path | None = None


def _get_conn() -> sqlite3.Connection:
    assert _db_path is not None
    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    with _get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "task_id TEXT PRIMARY KEY, "
            "status TEXT NOT NULL DEFAULT 'processing', "
            "filename TEXT NOT NULL, "
            "result TEXT, "
            "error TEXT, "
            "webhook_url TEXT, "
            "webhook_secret TEXT, "
            "retry_count INTEGER NOT NULL DEFAULT 0, "
            "created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL)"
        )
        conn.commit()


def create_task(
    *,
    task_id: str,
    filename: str,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
) -> dict[str, Any]:
    now = time.time()
    with _lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO tasks (task_id, status, filename, webhook_url, webhook_secret, "
            "retry_count, created_at, updated_at) VALUES (?, 'processing', ?, ?, ?, 0, ?, ?)",
            (task_id, filename, webhook_url, webhook_secret, now, now),
        )
        conn.commit()
    return get_task(task_id)


def get_task(task_id: str) -> dict[str, Any] | None:
    with _lock, _get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if row is None:
        return None
    return dict(row)


def complete_task(task_id: str, result: dict[str, Any]) -> None:
    now = time.time()
    with _lock, _get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET status = 'completed', result = ?, updated_at = ? WHERE task_id = ?",
            (json.dumps(result, ensure_ascii=False), now, task_id),
        )
        conn.commit()


def fail_task(task_id: str, error: str) -> None:
    now = time.time()
    with _lock, _get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET status = 'failed', error = ?, updated_at = ? WHERE task_id = ?",
            (error, now, task_id),
        )
        conn.commit()


def increment_retry(task_id: str) -> int:
    now = time.time()
    with _lock, _get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET retry_count = retry_count + 1, updated_at = ? WHERE task_id = ?",
            (now, task_id),
        )
        conn.commit()
        row = conn.execute("SELECT retry_count FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    return row["retry_count"] if row else 0


def pending_webhook_tasks() -> list[dict[str, Any]]:
    """Tasks that completed but webhook has not been delivered yet."""
    with _lock, _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = 'completed' AND webhook_url IS NOT NULL "
            "AND retry_count < 3 ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]
