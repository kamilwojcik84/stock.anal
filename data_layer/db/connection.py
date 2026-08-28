"""DuckDB connection + schema bootstrap.

DuckDB zamiast Postgresa w warstwie badawczej: kolumnowa, zero ops,
pojedynczy plik, skan 1500 spolek x 25 lat w sekundach. Postgres
dolozymy dopiero pod aplikacje (Faza 5), gdy pojawi sie stan uzytkownika.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

DEFAULT_DB_PATH = Path(
    os.getenv("DB_PATH", Path(__file__).resolve().parents[2] / "data" / "warehouse.duckdb")
)


def connect(db_path: str | Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Otwiera polaczenie i zapewnia, ze schemat istnieje."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        apply_schema(con)
    return con


def apply_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))
