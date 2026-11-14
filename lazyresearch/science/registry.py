import json
import sqlite3
import os
from contextlib import contextmanager
from pathlib import Path


class Registry:
    """SQLite is authoritative; JSON/JSONL files are reproducible exports."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "registry.sqlite"
        with self.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, payload TEXT, PRIMARY KEY(kind,id))")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    @staticmethod
    def get_from(db, kind, id):
        row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def put_into(db, kind, id, value):
        db.execute("INSERT OR REPLACE INTO records VALUES(?,?,?)",
                   (kind, id, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def get(self, kind, id="current"):
        with self.transaction() as db:
            return self.get_from(db, kind, id)

    def put(self, kind, value, id="current"):
        with self.transaction() as db:
            self.put_into(db, kind, id, value)

    def list(self, kind):
        with self.transaction() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM records WHERE kind=? ORDER BY rowid", (kind,))]

    def export(self, kind, filename):
        values = self.list(kind)
        path = self.root / filename
        temporary = path.with_suffix(path.suffix + ".tmp")
        if filename.endswith(".jsonl"):
            content = "".join(json.dumps(v, ensure_ascii=False, allow_nan=False) + "\n" for v in values)
        else:
            content = json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False)
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @contextmanager
    def claim(self):
        with (self.root / "run.lock").open("a+b") as lock:
            lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError("Research run is already active") from error
            yield
