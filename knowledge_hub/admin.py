import copy
from pathlib import Path


def build_node_config(token: str, role: str, description: str) -> dict:
    """Build the persisted config shape for one node."""
    return {"token": token, "role": role, "description": description}


def create_node_state(node_tokens: dict, token_map: dict, name: str, role: str, description: str, token: str):
    """Return updated node/token maps for a new node."""
    node_name = (name or "").strip()
    if not node_name or node_name in node_tokens:
        return None, None, {"reason": "node name empty or exists"}

    updated_nodes = copy.deepcopy(node_tokens)
    updated_map = copy.deepcopy(token_map)
    updated_nodes[node_name] = build_node_config(token, role, description)
    updated_map[token] = node_name
    return updated_nodes, updated_map, None


def reset_node_token_state(node_tokens: dict, token_map: dict, node_name: str, new_token: str):
    """Return updated node/token maps after resetting a node token."""
    if node_name not in node_tokens:
        return None, None, {"reason": "not_found"}

    updated_nodes = copy.deepcopy(node_tokens)
    updated_map = copy.deepcopy(token_map)
    old_token = updated_nodes[node_name]["token"]
    if old_token in updated_map:
        del updated_map[old_token]
    updated_nodes[node_name]["token"] = new_token
    updated_map[new_token] = node_name
    return updated_nodes, updated_map, None


def upsert_config_node(config: dict, name: str, token: str, role: str, description: str) -> dict:
    """Return a copied config with the node entry upserted."""
    updated = copy.deepcopy(config)
    if "nodes" not in updated:
        updated["nodes"] = {}
    updated["nodes"][name] = build_node_config(token, role, description)
    return updated


def build_token_listing(node_tokens: dict) -> dict:
    """Build the admin token listing response shape."""
    return {
        name: {
            "role": info["role"],
            "token": info["token"],
            "description": info["description"],
        }
        for name, info in node_tokens.items()
    }


def update_knowledge_item(db_path: Path, item_id: str, patch: dict) -> tuple[dict | None, str | None]:
    """Patch one knowledge item by id and return the updated item."""
    from tinydb import Query, TinyDB

    db = TinyDB(str(db_path))
    try:
        table = db.table("knowledge")
        matches = table.search(Query().id == item_id)
        if not matches:
            return None, "not_found"
        updated = copy.deepcopy(matches[0])
        for key, value in patch.items():
            if key in {"id", "source_node", "created_at", "schema_version"}:
                continue
            updated[key] = value
        table.update(updated, Query().id == item_id)
        return updated, None
    finally:
        db.close()


def delete_knowledge_item(db_path: Path, item_id: str) -> int:
    """Delete one knowledge item by id."""
    from tinydb import Query, TinyDB

    db = TinyDB(str(db_path))
    try:
        table = db.table("knowledge")
        removed = table.remove(Query().id == item_id)
        return len(removed)
    finally:
        db.close()


def paginate_audit_log(raw_text: str, page: int = 1, size: int = 50) -> dict:
    """Filter audit log lines, newest first, and return a page."""
    lines = [line for line in raw_text.split("\n") if line.strip() and "AUDIT" in line]
    total = len(lines)
    lines.reverse()
    start = (page - 1) * size
    end = start + size
    return {
        "total": total,
        "lines": lines[start:end],
        "page": page,
        "size": size,
    }
