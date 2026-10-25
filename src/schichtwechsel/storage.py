from __future__ import annotations

import gzip
import json
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from schichtwechsel.config import RAW_DIR, WAREHOUSE


def write_raw(items: list[dict[str, Any]], *, day: date, name: str, root: Path = RAW_DIR) -> Path:
    """Keep the untouched API payload so we can re-parse later without re-fetching."""
    folder = root / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    return path


class Warehouse:
    def __init__(self, path: Path = WAREHOUSE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        schema = resources.files("schichtwechsel.sql").joinpath("schema.sql").read_text("utf-8")
        self.con.execute(schema)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def replace_snapshot(self, day: date, competitor: str, rows: list[dict[str, Any]]) -> int:
        """Write one competitor's snapshot for a day. Re-running the same day replaces it."""
        incoming = pd.DataFrame(rows)
        if not incoming.empty:
            incoming = incoming.drop_duplicates(subset="refnr").dropna(subset=["refnr"])
            incoming.insert(0, "snapshot_date", day)

        self.con.execute("BEGIN")
        try:
            self.con.execute(
                "DELETE FROM postings_snapshot WHERE snapshot_date = ? AND competitor = ?",
                [day, competitor],
            )
            if not incoming.empty:
                self.con.register("incoming", incoming)
                self.con.execute("INSERT INTO postings_snapshot BY NAME SELECT * FROM incoming")
                self.con.unregister("incoming")
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        return len(incoming)

    def upsert(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Insert rows by column name, replacing existing rows with the same key."""
        return self._insert(table, rows, "INSERT OR REPLACE")

    def append(self, table: str, rows: list[dict[str, Any]]) -> int:
        return self._insert(table, rows, "INSERT")

    def _insert(self, table: str, rows: list[dict[str, Any]], verb: str) -> int:
        if not rows:
            return 0
        self.con.register("incoming", pd.DataFrame(rows))
        try:
            self.con.execute(f"{verb} INTO {table} BY NAME SELECT * FROM incoming")
        finally:
            self.con.unregister("incoming")
        return len(rows)

    def query(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or []).df()

    def scalar(self, sql: str, params: list[Any] | None = None) -> Any:
        row = self.con.execute(sql, params or []).fetchone()
        return row[0] if row else None
