import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from .models import utc_now


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    error TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def create(self, job_id: str, request: dict[str, Any], idempotency_key: str | None) -> bool:
        now = utc_now()
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO jobs
                    (job_id, idempotency_key, request_json, status, progress, created_at, updated_at)
                    VALUES (?, ?, ?, 'queued', 0, ?, ?)
                    """,
                    (job_id, idempotency_key, json.dumps(request), now, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_by_idempotency_key(self, key: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?", (key,)
            ).fetchone()

    def get(self, job_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()

    def list(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[sqlite3.Row]:
        with self._connect() as connection:
            if status:
                return connection.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                ).fetchall()
            return connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM jobs GROUP BY status"
            ).fetchall()
        result = {"queued": 0, "processing": 0, "completed": 0, "failed": 0}
        result.update({str(row["status"]): int(row["total"]) for row in rows})
        return result

    def update(self, job_id: str, *, status: str | None = None, progress: int | None = None,
               error: str | None = None, result: dict[str, str] | None = None) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if progress is not None:
            fields.append("progress = ?")
            values.append(progress)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if result is not None:
            fields.append("result_json = ?")
            values.append(json.dumps(result))
        values.append(job_id)
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?", values)

    @staticmethod
    def as_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "progress": row["progress"],
            "error": row["error"],
            "result": result,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
