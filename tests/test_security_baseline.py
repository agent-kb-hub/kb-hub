import importlib
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_client(tmp_path, config_overrides=None):
    import hub_server

    hub_server = importlib.reload(hub_server)
    config = {
        "port": 10128,
        "host": "127.0.0.1",
        "hub_db_path": "hub_tinydb/knowledge-index.json",
        "local_db_path": str(tmp_path / "local" / "knowledge-index.json"),
        "rate_limit_per_node": 100,
        "rate_limit_window_seconds": 60,
        "quality_threshold": 60,
        "max_item_size_bytes": 10240,
        "nodes": {
            "admin-node": {
                "token": "admin-token",
                "role": "admin",
                "description": "admin",
            },
            "writer-node": {
                "token": "writer-token",
                "role": "writer",
                "description": "writer",
            },
            "reader-node": {
                "token": "reader-token",
                "role": "reader",
                "description": "reader",
            },
        },
    }
    if config_overrides:
        config.update(config_overrides)

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "logs").mkdir()

    hub_server.HUB_DIR = tmp_path
    hub_server.CONFIG_PATH = config_path
    hub_server.LOG_PATH = tmp_path / "logs" / "audit.log"
    hub_server.STATS_PERSIST_PATH = tmp_path / "logs" / "query_stats.json"
    hub_server.NODE_TOKENS = {}
    hub_server.NODE_TOKEN_MAP = {}
    hub_server.NODE_CONFIG = {}
    hub_server.CONTENT_HASH_INDEX = {}
    hub_server.RATE_LIMITS.clear()
    hub_server.NODE_QUERY_STATS.clear()

    app = hub_server.create_app()
    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def admin_password_hash():
    from knowledge_hub.security import hash_password

    return hash_password("Admin@123456")


def test_health_is_public(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_tokens_endpoint_rejects_anonymous_requests(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/tokens")

    assert response.status_code == 401


def test_tokens_endpoint_allows_admin_bearer_token(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/tokens", headers=auth("admin-token"))

    assert response.status_code == 200
    assert response.json()["writer-node"]["role"] == "writer"


def test_tokens_endpoint_rejects_non_admin_token(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/tokens", headers=auth("writer-token"))

    assert response.status_code == 403


def test_sync_rejects_low_quality_items(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/sync",
        headers=auth("writer-token"),
        json={"items": [{"title": "bad", "summary": "short"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["new"] == 0
    assert body["updated"] == 0
    assert body["skipped"][0]["reason"] == "quality_too_low"


def test_rate_limit_uses_configured_limit(tmp_path):
    client = build_client(
        tmp_path,
        {
            "rate_limit_per_node": 1,
            "rate_limit_window_seconds": 60,
        },
    )

    first = client.post("/query", headers=auth("reader-token"), json={"query": "anything"})
    second = client.post("/query", headers=auth("reader-token"), json={"query": "anything"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_prefixed_health_route_is_supported(tmp_path):
    client = build_client(
        tmp_path,
        {"public_base_path": "/avatar-expose/12345678/kb-hub"},
    )

    response = client.get("/avatar-expose/12345678/kb-hub/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_prefixed_admin_login_form_uses_prefixed_action(tmp_path):
    client = build_client(
        tmp_path,
        {"public_base_path": "/avatar-expose/12345678/kb-hub"},
    )

    response = client.get("/avatar-expose/12345678/kb-hub/admin")

    assert response.status_code == 401
    assert 'action="/avatar-expose/12345678/kb-hub/admin/login"' in response.text
    assert 'value="/avatar-expose/12345678/kb-hub/admin"' in response.text


def test_prefixed_admin_panel_uses_prefixed_language_links(tmp_path):
    client = build_client(
        tmp_path,
        {
            "public_base_path": "/avatar-expose/12345678/kb-hub",
            "admin_users": {"admin": admin_password_hash()},
        },
    )

    login = client.post(
        "/avatar-expose/12345678/kb-hub/admin/login",
        data={
            "username": "admin",
            "password": "Admin@123456",
            "redirect": "/avatar-expose/12345678/kb-hub/admin",
        },
        follow_redirects=False,
    )
    assert login.status_code == 302

    response = client.get(
        "/avatar-expose/12345678/kb-hub/admin",
        cookies=login.cookies,
    )

    assert response.status_code == 200
    assert 'href="/avatar-expose/12345678/kb-hub/lang?lang=zh&redirect=/admin"' in response.text
    assert 'href="/avatar-expose/12345678/kb-hub/lang?lang=en&redirect=/admin"' in response.text
    assert 'href="/lang?lang=en&redirect=/admin"' not in response.text


def test_ingest_stores_v2_knowledge_schema(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/ingest",
        headers=auth("writer-token"),
        json={
            "items": [
                {
                    "title": "High quality policy knowledge",
                    "summary": "This is a substantial summary with enough detail for reuse by agents and human operators.",
                    "content": "Full policy content with implementation details and reusable context.",
                    "url": "https://example.com/policy",
                    "source": "Gov",
                    "topics": ["policy"],
                    "assets": [{"url": "https://example.com/policy.pdf"}],
                    "relations": [{"type": "cites", "target_id": "kb-source"}],
                    "metadata": {"region": "CN"},
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["ingested"] == 1

    query = client.post("/query", headers=auth("reader-token"), json={"query": "implementation", "limit": 1})

    assert query.status_code == 200
    item = query.json()["items"][0]
    assert item["schema_version"] == "2.0"
    assert item["content_type"] == "article"
    assert item["source"]["name"] == "Gov"
    assert item["source"]["url"] == "https://example.com/policy"
    assert item["provenance"]["source_node"] == "writer-node"
    assert item["provenance"]["content_hash"]
    assert item["quality_detail"]["review_status"] == "auto"
    assert item["access"]["visibility"] == "team"
    assert item["lifecycle"]["status"] == "active"
    assert item["assets"][0]["kind"] == "file"
    assert item["relations"][0] == {"type": "cites", "target_id": "kb-source"}
    assert item["metadata"] == {"region": "CN"}
    assert "content" not in item

    full = client.post(
        "/query",
        headers=auth("reader-token"),
        json={"query": "implementation", "limit": 1, "include_content": True, "include_chunks": True},
    )

    assert full.status_code == 200
    full_item = full.json()["items"][0]
    assert full_item["content"] == "Full policy content with implementation details and reusable context."
    assert full_item["chunks"][0]["text"] == "Full policy content with implementation details and reusable context."


def test_ingest_parses_local_attachment_and_semantic_query_finds_it(tmp_path):
    attachment = tmp_path / "coal-note.md"
    attachment.write_text("coal inventory pressure and port supply analysis", encoding="utf-8")
    client = build_client(tmp_path, {"asset_allowed_dirs": [str(tmp_path)]})

    response = client.post(
        "/ingest",
        headers=auth("writer-token"),
        json={
            "items": [
                {
                    "title": "High quality supply knowledge",
                    "summary": "This is a substantial summary with enough detail for reuse by agents and human operators.",
                    "assets": [{"path": str(attachment), "kind": "file"}],
                    "topics": ["coal"],
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["ingested"] == 1

    query = client.post(
        "/query",
        headers=auth("reader-token"),
        json={"query": "port inventory", "search_mode": "semantic", "include_content": True, "include_chunks": True},
    )

    assert query.status_code == 200
    item = query.json()["items"][0]
    assert item["title"] == "High quality supply knowledge"
    assert "coal inventory pressure" in item["content"]
    assert item["assets"][0]["parse_status"] == "parsed"
    assert item["semantic_score"] > 0


def test_ingest_rejects_attachment_outside_allowed_directory(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    attachment = outside / "secret.md"
    attachment.write_text("secret text", encoding="utf-8")
    client = build_client(tmp_path, {"asset_allowed_dirs": [str(allowed)]})

    response = client.post(
        "/ingest",
        headers=auth("writer-token"),
        json={
            "items": [
                {
                    "title": "High quality attachment knowledge",
                    "summary": "This is a substantial summary with enough detail for reuse by agents and human operators.",
                    "assets": [{"path": str(attachment), "kind": "file"}],
                }
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ingested"] == 0
    assert body["details"][0]["reason"] == "asset_invalid"


def test_admin_can_update_and_delete_knowledge_items(tmp_path):
    client = build_client(tmp_path)
    ingest = client.post(
        "/ingest",
        headers=auth("writer-token"),
        json={
            "items": [
                {
                    "title": "High quality editable knowledge",
                    "summary": "This is a substantial summary with enough detail for reuse by agents and human operators.",
                    "topics": ["old"],
                }
            ]
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["ingested"] == 1

    query = client.post("/query", headers=auth("reader-token"), json={"query": "editable", "limit": 1})
    item_id = query.json()["items"][0]["id"]

    update = client.put(
        f"/admin/item/{item_id}",
        headers=auth("admin-token"),
        json={"title": "Updated knowledge title", "topics": ["new"]},
    )

    assert update.status_code == 200
    assert update.json()["item"]["title"] == "Updated knowledge title"
    assert update.json()["item"]["topics"] == ["new"]

    delete = client.delete(f"/admin/item/{item_id}", headers=auth("admin-token"))

    assert delete.status_code == 200
    assert delete.json()["deleted"] == 1
    after = client.post("/query", headers=auth("reader-token"), json={"query": "Updated", "limit": 1})
    assert after.json()["count"] == 0


def test_ingest_auto_classifies_topics_tags_and_entities(tmp_path):
    client = build_client(
        tmp_path,
        {
            "topic_map": {
                "煤炭市场": ["动力煤", "煤炭", "BSPI"],
                "价格监测": ["价格", "指数", "行情"],
            }
        },
    )

    response = client.post(
        "/ingest",
        headers=auth("writer-token"),
        json={
            "items": [
                {
                    "title": "动力煤价格指数行情",
                    "summary": "环渤海5500K价格和BSPI指数用于煤炭市场监测分析，帮助判断供需变化、港口库存压力、产地供应变化和下游采购节奏。",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["ingested"] == 1

    query = client.post("/query", headers=auth("reader-token"), json={"query": "BSPI", "limit": 1})

    assert query.status_code == 200
    item = query.json()["items"][0]
    assert item["category"] == "数据资产"
    assert item["topics"] == ["煤炭市场", "价格监测"]
    assert item["tags"]
    assert "BSPI" in item["entities"]
