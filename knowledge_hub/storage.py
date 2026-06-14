import os
import json
import sqlite3
from pathlib import Path

from knowledge_hub.paths import resolve_configured_path, resolve_local_db_path


def resolve_hub_db_path(config: dict, hub_dir: Path) -> Path:
    """Resolve the Hub TinyDB path and keep the historical default."""
    configured = resolve_configured_path(config.get("hub_db_path"), hub_dir)
    return configured or (hub_dir / "hub_tinydb" / "knowledge-index.json")


def open_tinydb(db_path: Path):
    """Open a TinyDB database, creating its parent directory first."""
    from tinydb import TinyDB

    os.makedirs(db_path.parent, exist_ok=True)
    return TinyDB(str(db_path))


class TinyDBKnowledgeStore:
    """TinyDB-backed knowledge store preserving the original runtime behavior."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db = open_tinydb(db_path)
        self.table = self.db.table("knowledge")

    def all(self) -> list:
        return self.table.all()

    def insert_if_missing(self, item: dict) -> bool:
        from tinydb import Query

        existing = self.table.search(Query().id == item.get("id"))
        if existing:
            return False
        self.table.insert(item)
        return True

    def update_item(self, item_id: str, patch: dict) -> tuple[dict | None, str | None]:
        from tinydb import Query

        matches = self.table.search(Query().id == item_id)
        if not matches:
            return None, "not_found"
        updated = _merge_item_patch(matches[0], patch)
        self.table.update(updated, Query().id == item_id)
        return updated, None

    def delete_item(self, item_id: str) -> int:
        from tinydb import Query

        removed = self.table.remove(Query().id == item_id)
        return len(removed)

    def increment_usage_counts(self, items: list, count_field: str, date_field: str, date_value: str) -> int:
        updated = 0
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            for original in self.table.all():
                if original.get("id") == item_id:
                    self.table.update(
                        {
                            count_field: (original.get(count_field) or 0) + 1,
                            date_field: date_value,
                        },
                        lambda doc, iid=item_id: doc.get("id") == iid,
                    )
                    updated += 1
                    break
        return updated

    def maintenance(self, vacuum: bool = False) -> dict:
        return {
            "backend": "tinydb",
            "knowledge_count": len(self.table.all()),
            "integrity_check": "ok",
            "vacuumed": False,
            "path": str(self.db_path),
        }

    def close(self):
        self.db.close()


class SQLiteKnowledgeStore:
    """SQLite-backed knowledge store with JSON document compatibility."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        os.makedirs(db_path.parent, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                title TEXT,
                summary TEXT,
                category TEXT,
                source_node TEXT,
                created_at TEXT,
                content_hash TEXT,
                document TEXT NOT NULL
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge(category)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_source_node ON knowledge(source_node)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_created_at ON knowledge(created_at)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_content_hash ON knowledge(content_hash)")
        self.conn.commit()

    def all(self) -> list:
        rows = self.conn.execute("SELECT document FROM knowledge ORDER BY created_at DESC, id ASC").fetchall()
        return [json.loads(row["document"]) for row in rows]

    def insert_if_missing(self, item: dict) -> bool:
        item_id = item.get("id")
        if not item_id:
            raise ValueError("knowledge item id is required")
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO knowledge
                (id, title, summary, category, source_node, created_at, content_hash, document)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _sqlite_record_values(item),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def update_item(self, item_id: str, patch: dict) -> tuple[dict | None, str | None]:
        row = self.conn.execute("SELECT document FROM knowledge WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None, "not_found"
        updated = _merge_item_patch(json.loads(row["document"]), patch)
        self.conn.execute(
            """
            UPDATE knowledge
               SET title = ?, summary = ?, category = ?, source_node = ?,
                   created_at = ?, content_hash = ?, document = ?
             WHERE id = ?
            """,
            (
                updated.get("title"),
                updated.get("summary"),
                updated.get("category"),
                updated.get("source_node"),
                updated.get("created_at"),
                _item_content_hash(updated),
                json.dumps(updated, ensure_ascii=False),
                item_id,
            ),
        )
        self.conn.commit()
        return updated, None

    def delete_item(self, item_id: str) -> int:
        cursor = self.conn.execute("DELETE FROM knowledge WHERE id = ?", (item_id,))
        self.conn.commit()
        return cursor.rowcount

    def increment_usage_counts(self, items: list, count_field: str, date_field: str, date_value: str) -> int:
        updated = 0
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            row = self.conn.execute("SELECT document FROM knowledge WHERE id = ?", (item_id,)).fetchone()
            if not row:
                continue
            document = json.loads(row["document"])
            document[count_field] = (document.get(count_field) or 0) + 1
            document[date_field] = date_value
            self.conn.execute(
                "UPDATE knowledge SET document = ? WHERE id = ?",
                (json.dumps(document, ensure_ascii=False), item_id),
            )
            updated += 1
        self.conn.commit()
        return updated

    def maintenance(self, vacuum: bool = False) -> dict:
        integrity = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        count = self.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        if vacuum:
            self.conn.execute("VACUUM")
        return {
            "backend": "sqlite",
            "knowledge_count": count,
            "integrity_check": integrity,
            "vacuumed": bool(vacuum),
            "path": str(self.db_path),
        }

    def close(self):
        self.conn.close()


def _item_content_hash(item: dict) -> str:
    provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
    return item.get("content_hash") or provenance.get("content_hash") or ""


def _sqlite_record_values(item: dict) -> tuple:
    return (
        item.get("id"),
        item.get("title"),
        item.get("summary"),
        item.get("category"),
        item.get("source_node"),
        item.get("created_at"),
        _item_content_hash(item),
        json.dumps(item, ensure_ascii=False),
    )


def _merge_item_patch(original: dict, patch: dict) -> dict:
    protected_fields = {"id", "source_node", "created_at", "schema_version"}
    updated = dict(original)
    for key, value in patch.items():
        if key in protected_fields:
            continue
        updated[key] = value
    return updated


def open_knowledge_store(config: dict, hub_dir: Path):
    """Open the configured knowledge store backend."""
    backend = str(config.get("storage_backend", "tinydb") or "tinydb").lower()
    db_path = resolve_hub_db_path(config, hub_dir)
    if backend == "sqlite":
        return SQLiteKnowledgeStore(db_path)
    return TinyDBKnowledgeStore(db_path)


def migrate_tinydb_to_sqlite(tinydb_path: Path, sqlite_path: Path) -> dict:
    """Copy TinyDB knowledge records into SQLite without duplicating existing ids."""
    source = TinyDBKnowledgeStore(tinydb_path)
    target = SQLiteKnowledgeStore(sqlite_path)
    inserted = 0
    skipped = 0
    try:
        for item in source.all():
            if target.insert_if_missing(item):
                inserted += 1
            else:
                skipped += 1
    finally:
        source.close()
        target.close()
    return {"inserted": inserted, "skipped": skipped}


def open_hub_db(config: dict, hub_dir: Path):
    """Open the configured Hub TinyDB database."""
    return open_tinydb(resolve_hub_db_path(config, hub_dir))


def read_knowledge_items(config: dict, hub_dir: Path) -> list:
    """Read all Hub knowledge records from the configured backend."""
    store = open_knowledge_store(config, hub_dir)
    try:
        return store.all()
    finally:
        store.close()


def insert_knowledge_item(config: dict, hub_dir: Path, item: dict) -> bool:
    """Insert a Hub knowledge record through the configured backend."""
    store = open_knowledge_store(config, hub_dir)
    try:
        return store.insert_if_missing(item)
    finally:
        store.close()


def update_knowledge_store_item(config: dict, hub_dir: Path, item_id: str, patch: dict):
    """Patch a Hub knowledge record through the configured backend."""
    store = open_knowledge_store(config, hub_dir)
    try:
        return store.update_item(item_id, patch)
    finally:
        store.close()


def delete_knowledge_store_item(config: dict, hub_dir: Path, item_id: str) -> int:
    """Delete a Hub knowledge record through the configured backend."""
    store = open_knowledge_store(config, hub_dir)
    try:
        return store.delete_item(item_id)
    finally:
        store.close()


def maintain_knowledge_store(config: dict, hub_dir: Path, vacuum: bool = False) -> dict:
    """Run backend maintenance checks and optional compaction."""
    store = open_knowledge_store(config, hub_dir)
    try:
        return store.maintenance(vacuum=vacuum)
    finally:
        store.close()


def increment_store_usage_counts(
    config: dict,
    hub_dir: Path,
    items: list,
    count_field: str,
    date_field: str,
    date_value: str,
) -> int:
    """Increment usage counters through the configured backend."""
    store = open_knowledge_store(config, hub_dir)
    try:
        return store.increment_usage_counts(items, count_field, date_field, date_value)
    finally:
        store.close()


def open_local_db(config: dict, hub_dir: Path, config_path: Path):
    """Open the optional local TinyDB database when it exists."""
    db_path = resolve_local_db_path(config, hub_dir, config_path)
    if db_path.exists():
        return open_tinydb(db_path)
    return None


def read_table(db_path: Path, table_name: str) -> list:
    """Read all records from a TinyDB table."""
    if not db_path.exists():
        return []
    db = open_tinydb(db_path)
    try:
        return db.table(table_name).all()
    finally:
        db.close()


def increment_usage_counts(
    db_path: Path,
    items: list,
    count_field: str,
    date_field: str,
    date_value: str,
) -> int:
    """Increment usage counters for matching item ids in a TinyDB knowledge table."""
    if not db_path.exists():
        return 0

    db = open_tinydb(db_path)
    updated = 0
    try:
        table = db.table("knowledge")
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            for original in table.all():
                if original.get("id") == item_id:
                    table.update(
                        {
                            count_field: (original.get(count_field) or 0) + 1,
                            date_field: date_value,
                        },
                        lambda doc, iid=item_id: doc.get("id") == iid,
                    )
                    updated += 1
                    break
    finally:
        db.close()
    return updated


def insert_knowledge_if_missing(db_path: Path, item: dict) -> bool:
    """Insert a knowledge item into TinyDB when the id does not already exist."""
    from tinydb import Query

    db = open_tinydb(db_path)
    try:
        table = db.table("knowledge")
        existing = table.search(Query().id == item.get("id"))
        if existing:
            return False
        table.insert(item)
        return True
    finally:
        db.close()
