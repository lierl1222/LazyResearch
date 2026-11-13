import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Storage:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "runs.sqlite"
        self.lock_dir = root / "locks"
        self.lock_dir.mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    run_id TEXT, name TEXT, body TEXT, PRIMARY KEY (run_id, name)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, run_id TEXT, body TEXT
                );
                CREATE INDEX IF NOT EXISTS events_run ON events (run_id, id);
            """)

    @contextmanager
    def claim(self, run_id: str):
        # Keep the lock file in place so every process locks the same inode.
        with (self.lock_dir / run_id).open("a+b") as lock:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError("任务正在执行") from error
            yield

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, run_id: str, name: str):
        with self.connect() as db:
            row = db.execute("SELECT body FROM records WHERE run_id=? AND name=?",
                             (run_id, name)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, run_id: str, name: str, value) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO records VALUES (?, ?, ?)",
                       (run_id, name, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def emit(self, run_id: str, stage: str, **details) -> None:
        event = {"stage": stage, **details}
        with self.connect() as db:
            db.execute("INSERT INTO events (run_id, body) VALUES (?, ?)",
                       (run_id, json.dumps(event, ensure_ascii=False, allow_nan=False)))

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, body FROM events WHERE run_id=? AND id>? ORDER BY id",
                (run_id, after),
            ).fetchall()
        return [{"id": key, **json.loads(body)} for key, body in rows]

    def pending(self) -> list[str]:
        with self.connect() as db:
            rows = db.execute("""
                SELECT run_id FROM records WHERE name='task'
                  AND run_id NOT IN (SELECT run_id FROM records WHERE name='final')
            """).fetchall()
        return [row[0] for row in rows]

    def finish(self, run_id: str, state: dict) -> None:
        terminal = {key: state[key] for key in
                    ("status", "stop_reason", "elapsed", "cloud_requests", "tokens", "tokens_pending")}
        terminal.update(stage="finished", round=state.get("round", 0), tools=state.get("tools", 0))
        with self.connect() as db:
            db.execute("INSERT INTO records VALUES (?, 'final', ?)",
                       (run_id, json.dumps(state, ensure_ascii=False)))
            db.execute("INSERT INTO events (run_id, body) VALUES (?, ?)",
                       (run_id, json.dumps(terminal, ensure_ascii=False)))
