#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrate Hub knowledge records from TinyDB JSON to SQLite."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from knowledge_hub.storage import migrate_tinydb_to_sqlite  # noqa: E402

CONFIG_PATH = PROJECT_DIR / "config.json"


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def load_default_paths(config_path: Path) -> tuple[Path, Path]:
    if not config_path.exists():
        return (
            PROJECT_DIR / "hub_tinydb" / "knowledge-index.json",
            PROJECT_DIR / "hub_sqlite" / "knowledge.sqlite3",
        )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    tinydb_path = _resolve_path(
        config.get("tinydb_source_path") or "hub_tinydb/knowledge-index.json",
        config_path.parent,
    )
    sqlite_path = _resolve_path(
        config.get("sqlite_db_path") or "hub_sqlite/knowledge.sqlite3",
        config_path.parent,
    )
    return tinydb_path, sqlite_path


def main() -> int:
    default_tinydb_path, default_sqlite_path = load_default_paths(CONFIG_PATH)
    parser = argparse.ArgumentParser(description="Migrate Knowledge Hub TinyDB data to SQLite.")
    parser.add_argument("--tinydb", default=str(default_tinydb_path), help="Source TinyDB JSON path.")
    parser.add_argument("--sqlite", default=str(default_sqlite_path), help="Target SQLite database path.")
    args = parser.parse_args()

    tinydb_path = Path(args.tinydb).expanduser()
    sqlite_path = Path(args.sqlite).expanduser()
    if not tinydb_path.exists():
        raise SystemExit(f"TinyDB source does not exist: {tinydb_path}")

    result = migrate_tinydb_to_sqlite(tinydb_path, sqlite_path)
    print(json.dumps({
        "status": "ok",
        "source": str(tinydb_path),
        "target": str(sqlite_path),
        **result,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
