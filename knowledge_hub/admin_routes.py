import secrets
from pathlib import Path

from fastapi import HTTPException, Request

from knowledge_hub.admin import (
    create_node_state,
    paginate_audit_log,
    reset_node_token_state,
)
from knowledge_hub.schema import quality_score


def filter_admin_items(
    items: list,
    q: str = "",
    category: str = "",
    node: str = "",
    min_quality: int = 0,
    page: int = 1,
    size: int = 20,
) -> dict:
    """Filter, sort, and paginate knowledge items for the admin list endpoint."""
    q = (q or "").strip().lower()
    page = max(1, int(page or 1))
    size = min(200, max(1, int(size or 20)))
    min_quality = int(min_quality or 0)

    filtered = []
    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        if q and q not in text:
            continue
        if category and item.get("category", "其他") != category:
            continue
        if node and item.get("source_node") != node:
            continue
        if min_quality and quality_score(item) < min_quality:
            continue
        filtered.append(item)

    filtered.sort(key=lambda item: (item.get("created_at") or "", item.get("id") or ""), reverse=True)
    total = len(filtered)
    start = (page - 1) * size
    end = start + size
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": filtered[start:end],
    }


def build_admin_session_resolver(
    authenticate_admin,
    resolve_admin_bearer,
    node_token_map: dict,
    node_tokens: dict,
):
    """Build an admin resolver that accepts session cookies or admin bearer tokens."""

    def require_admin(request: Request) -> dict:
        session = authenticate_admin(request)
        if session:
            return session
        admin = resolve_admin_bearer(
            request.headers.get("authorization", ""),
            node_token_map,
            node_tokens,
        )
        if admin:
            return admin
        raise HTTPException(401, "Admin session required")

    return require_admin


def register_admin_api_routes(
    app,
    *,
    node_state,
    authenticate_admin,
    resolve_admin_bearer,
    save_config_node,
    audit_log,
    update_item,
    delete_item,
    list_items,
    maintain_store,
    log_path: Path,
):
    """Register admin JSON APIs outside the main server factory."""

    def _require_admin(request: Request) -> dict:
        return build_admin_session_resolver(
            authenticate_admin,
            resolve_admin_bearer,
            node_state["tokens"],
            node_state["nodes"],
        )(request)

    @app.post("/admin/node")
    def admin_create_node(req: dict, request: Request):
        admin_session = _require_admin(request)
        username = admin_session["username"]

        name = req.get("name", "").strip()
        role = req.get("role", "reader")
        desc = req.get("description", "")
        token = secrets.token_urlsafe(24)
        updated_nodes, updated_map, error = create_node_state(
            node_state["nodes"],
            node_state["tokens"],
            name,
            role,
            desc,
            token,
        )
        if error:
            raise HTTPException(400, "node name empty or exists")
        node_state["nodes"] = updated_nodes
        node_state["tokens"] = updated_map
        save_config_node(name, token, role, desc)
        audit_log("create_node", username, f"node={name} role={role}")
        return {"status": "ok", "name": name, "token": token}

    @app.put("/admin/item/{item_id}")
    def admin_update_item(item_id: str, req: dict, request: Request):
        admin_session = _require_admin(request)
        updated, error = update_item(item_id, req)
        if error:
            raise HTTPException(404, "Knowledge item not found")
        audit_log("update_item", admin_session["username"], f"item={item_id}")
        return {"status": "ok", "item": updated}

    @app.delete("/admin/item/{item_id}")
    def admin_delete_item(item_id: str, request: Request):
        admin_session = _require_admin(request)
        deleted = delete_item(item_id)
        if deleted == 0:
            raise HTTPException(404, "Knowledge item not found")
        audit_log("delete_item", admin_session["username"], f"item={item_id}")
        return {"status": "ok", "deleted": deleted}

    @app.get("/admin/items")
    def admin_list_items(
        request: Request,
        q: str = "",
        category: str = "",
        node: str = "",
        min_quality: int = 0,
        page: int = 1,
        size: int = 20,
    ):
        _require_admin(request)
        return filter_admin_items(
            list_items(),
            q=q,
            category=category,
            node=node,
            min_quality=min_quality,
            page=page,
            size=size,
        )

    @app.post("/admin/node/{node_name}/reset-token")
    def admin_reset_token(node_name: str, request: Request):
        admin_session = _require_admin(request)
        new_token = secrets.token_urlsafe(24)
        updated_nodes, updated_map, error = reset_node_token_state(
            node_state["nodes"],
            node_state["tokens"],
            node_name,
            new_token,
        )
        if error:
            raise HTTPException(404, "not_found")
        node_state["nodes"] = updated_nodes
        node_state["tokens"] = updated_map
        save_config_node(
            node_name,
            new_token,
            node_state["nodes"][node_name]["role"],
            node_state["nodes"][node_name]["description"],
        )
        audit_log("reset_token", admin_session["username"], f"node={node_name}")
        return {"status": "ok", "name": node_name, "token": new_token}

    @app.get("/admin/log")
    def admin_get_log(request: Request, page: int = 1, size: int = 50):
        _require_admin(request)
        try:
            return paginate_audit_log(log_path.read_text(encoding="utf-8"), page=page, size=size)
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.post("/admin/storage/maintenance")
    def admin_storage_maintenance(request: Request, req: dict | None = None):
        admin_session = _require_admin(request)
        vacuum = bool((req or {}).get("vacuum", False))
        report = maintain_store(vacuum)
        audit_log("storage_maintenance", admin_session["username"], f"vacuum={vacuum}")
        return report
