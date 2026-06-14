import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from knowledge_hub.auth import (
    build_node_auth_info,
    extract_bearer_token,
    is_session_valid,
    resolve_admin_bearer,
    resolve_node_from_token,
)
from knowledge_hub.attachments import (
    AssetPolicy,
    extract_asset_text,
    extract_text_from_file,
    validate_asset_path,
)
from knowledge_hub.classification import auto_annotate_item, classify_category, extract_entities, extract_tags, infer_topics
from knowledge_hub.embedding import embed_text, semantic_search
from knowledge_hub.admin import (
    build_token_listing,
    create_node_state,
    paginate_audit_log,
    reset_node_token_state,
    upsert_config_node,
)
from knowledge_hub.admin_routes import build_admin_session_resolver, filter_admin_items
from knowledge_hub.config import materialize_node_config
from knowledge_hub.ingest import prepare_ingest_item, prepare_sync_item, validate_knowledge_item
from knowledge_hub.paths import resolve_configured_path, resolve_local_db_path
from knowledge_hub.quality import auto_evaluate_quality, evaluate_quality_detail
from knowledge_hub.query import build_query_results, format_query_item
from knowledge_hub.search import content_hash, simple_search
from knowledge_hub.security import hash_password, verify_password
from knowledge_hub.schema import build_content_chunks, normalize_knowledge_item, quality_score
from knowledge_hub.stats import build_dashboard_model, build_hub_stats, build_node_query_stats, build_usage_stats
from knowledge_hub.storage import (
    increment_usage_counts,
    insert_knowledge_if_missing,
    open_tinydb,
    read_table,
    resolve_hub_db_path,
    migrate_tinydb_to_sqlite,
    open_knowledge_store,
)


class SecurityTests(unittest.TestCase):
    def test_hash_password_round_trips_valid_password(self):
        stored = hash_password("correct horse battery staple")

        self.assertTrue(verify_password("correct horse battery staple", stored))
        self.assertFalse(verify_password("wrong", stored))

    def test_verify_password_rejects_malformed_hash(self):
        self.assertFalse(verify_password("secret", "not-a-supported-hash"))
        self.assertFalse(verify_password("secret", "sha256:missing-parts"))


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.node_tokens = {
            "admin-node": {"token": "admin-token", "role": "admin", "description": "admin"},
            "writer-node": {"token": "writer-token", "role": "writer", "description": "writer"},
        }
        self.token_map = {
            "admin-token": "admin-node",
            "writer-token": "writer-node",
        }

    def test_extract_bearer_token_requires_bearer_prefix(self):
        self.assertEqual(extract_bearer_token("Bearer abc"), "abc")
        self.assertIsNone(extract_bearer_token("Basic abc"))
        self.assertIsNone(extract_bearer_token(None))

    def test_resolve_node_from_token_returns_node_info(self):
        node = resolve_node_from_token("writer-token", self.token_map, self.node_tokens)

        self.assertEqual(node["name"], "writer-node")
        self.assertEqual(node["role"], "writer")

    def test_resolve_node_from_token_rejects_unknown_token(self):
        self.assertIsNone(resolve_node_from_token("missing", self.token_map, self.node_tokens))

    def test_build_node_auth_info_preserves_route_shape(self):
        info = build_node_auth_info(
            "writer-node",
            self.node_tokens["writer-node"],
            "zh",
        )

        self.assertEqual(info["name"], "writer-node")
        self.assertEqual(info["lang"], "zh")
        self.assertEqual(info["role"], "writer")
        self.assertFalse(info["is_admin"])

    def test_is_session_valid_checks_expiry(self):
        self.assertTrue(is_session_valid({"created_at": 100.0}, now=200.0, ttl_seconds=200))
        self.assertFalse(is_session_valid({"created_at": 100.0}, now=400.0, ttl_seconds=200))
        self.assertFalse(is_session_valid(None, now=100.0))

    def test_resolve_admin_bearer_accepts_only_admin_tokens(self):
        admin = resolve_admin_bearer("Bearer admin-token", self.token_map, self.node_tokens)
        writer = resolve_admin_bearer("Bearer writer-token", self.token_map, self.node_tokens)

        self.assertEqual(admin, {"username": "token:admin-node"})
        self.assertIsNone(writer)


class AdminTests(unittest.TestCase):
    def test_create_node_state_adds_node_and_token_mapping(self):
        nodes, token_map, error = create_node_state(
            {},
            {},
            " writer ",
            "writer",
            "desc",
            "new-token",
        )

        self.assertIsNone(error)
        self.assertEqual(nodes["writer"], {"token": "new-token", "role": "writer", "description": "desc"})
        self.assertEqual(token_map["new-token"], "writer")

    def test_create_node_state_rejects_empty_or_existing_name(self):
        _, _, empty_error = create_node_state({}, {}, " ", "reader", "", "token")
        _, _, existing_error = create_node_state({"node": {"token": "old"}}, {}, "node", "reader", "", "token")

        self.assertEqual(empty_error["reason"], "node name empty or exists")
        self.assertEqual(existing_error["reason"], "node name empty or exists")

    def test_reset_node_token_state_replaces_old_mapping(self):
        nodes, token_map, error = reset_node_token_state(
            {"node": {"token": "old", "role": "reader", "description": "desc"}},
            {"old": "node"},
            "node",
            "new",
        )

        self.assertIsNone(error)
        self.assertEqual(nodes["node"]["token"], "new")
        self.assertNotIn("old", token_map)
        self.assertEqual(token_map["new"], "node")

    def test_reset_node_token_state_reports_missing_node(self):
        _, _, error = reset_node_token_state({}, {}, "missing", "new")

        self.assertEqual(error["reason"], "not_found")

    def test_upsert_config_node_preserves_other_config(self):
        config = {"port": 10128}

        updated = upsert_config_node(config, "node", "token", "writer", "desc")

        self.assertEqual(updated["port"], 10128)
        self.assertEqual(updated["nodes"]["node"], {"token": "token", "role": "writer", "description": "desc"})
        self.assertNotIn("nodes", config)

    def test_build_token_listing_preserves_admin_response_shape(self):
        listing = build_token_listing({
            "node": {"token": "token", "role": "writer", "description": "desc"},
        })

        self.assertEqual(listing, {
            "node": {"token": "token", "role": "writer", "description": "desc"},
        })

    def test_paginate_audit_log_filters_reverses_and_pages(self):
        page = paginate_audit_log(
            "\n".join([
                "not audit",
                "2026 [INFO] AUDIT | node=a | action=query",
                "2026 [INFO] AUDIT | node=b | action=ingest",
                "",
                "2026 [INFO] AUDIT | node=c | action=sync",
            ]),
            page=2,
            size=2,
        )

        self.assertEqual(page["total"], 3)
        self.assertEqual(page["lines"], ["2026 [INFO] AUDIT | node=a | action=query"])
        self.assertEqual(page["page"], 2)
        self.assertEqual(page["size"], 2)

    def test_build_admin_session_resolver_accepts_session_before_bearer(self):
        class Request:
            headers = {"authorization": "Bearer ignored"}

        session = {"username": "cookie-admin"}
        resolver = build_admin_session_resolver(
            authenticate_admin=lambda request: session,
            resolve_admin_bearer=lambda authorization, token_map, node_tokens: {"username": "bearer-admin"},
            node_token_map={},
            node_tokens={},
        )

        self.assertEqual(resolver(Request()), session)

    def test_build_admin_session_resolver_accepts_admin_bearer_fallback(self):
        class Request:
            headers = {"authorization": "Bearer admin"}

        resolver = build_admin_session_resolver(
            authenticate_admin=lambda request: None,
            resolve_admin_bearer=lambda authorization, token_map, node_tokens: {"username": "bearer-admin"},
            node_token_map={"admin": "admin-node"},
            node_tokens={"admin-node": {"role": "admin"}},
        )

        self.assertEqual(resolver(Request()), {"username": "bearer-admin"})


class ConfigTests(unittest.TestCase):
    def test_materialize_node_config_preserves_existing_tokens(self):
        node_tokens, token_map, updated_config, needs_save = materialize_node_config(
            {"nodes": {"node": {"token": "token", "role": "writer", "description": "desc"}}},
            lambda: "new-token",
        )

        self.assertFalse(needs_save)
        self.assertEqual(node_tokens["node"], {"token": "token", "role": "writer", "description": "desc"})
        self.assertEqual(token_map["token"], "node")
        self.assertEqual(updated_config["nodes"]["node"]["token"], "token")

    def test_materialize_node_config_generates_missing_tokens_and_defaults(self):
        node_tokens, token_map, updated_config, needs_save = materialize_node_config(
            {"nodes": {"node": {"token": "AUTO_GENERATED"}}},
            lambda: "generated",
        )

        self.assertTrue(needs_save)
        self.assertEqual(node_tokens["node"], {"token": "generated", "role": "reader", "description": ""})
        self.assertEqual(token_map["generated"], "node")
        self.assertEqual(updated_config["nodes"]["node"], {"token": "generated", "role": "reader", "description": ""})

    def test_materialize_node_config_does_not_mutate_input(self):
        config = {"nodes": {"node": {"token": "AUTO_GENERATED"}}}

        materialize_node_config(config, lambda: "generated")

        self.assertEqual(config["nodes"]["node"]["token"], "AUTO_GENERATED")


class QualityTests(unittest.TestCase):
    def test_quality_rewards_substantial_items_with_url(self):
        score = auto_evaluate_quality({
            "title": "High quality policy knowledge",
            "summary": "This is a substantial summary with enough detail for reuse by agents and human operators.",
            "url": "https://example.com/policy",
        })

        self.assertGreaterEqual(score, 70)

    def test_quality_penalizes_short_placeholder_items(self):
        score = auto_evaluate_quality({"title": "测试", "summary": "暂无"})

        self.assertLess(score, 60)

    def test_evaluate_quality_detail_explains_score_and_review_status(self):
        detail = evaluate_quality_detail({"title": "测试", "summary": "暂无"})

        self.assertLess(detail["score"], 60)
        self.assertEqual(detail["review_status"], "rejected")
        self.assertTrue(any(reason["code"] == "title_too_short" for reason in detail["reasons"]))
        self.assertTrue(any(reason["code"] == "low_quality_signal" for reason in detail["reasons"]))

    def test_validate_knowledge_item_returns_quality_reasons_on_rejection(self):
        prepared, skipped = validate_knowledge_item({"title": "测试", "summary": "暂无"}, {"quality_threshold": 60})

        self.assertIsNone(prepared)
        self.assertEqual(skipped["reason"], "quality_too_low")
        self.assertTrue(skipped["quality_detail"]["reasons"])


class SearchTests(unittest.TestCase):
    def test_content_hash_is_case_and_whitespace_insensitive(self):
        self.assertEqual(
            content_hash("  Policy A ", "Summary Text"),
            content_hash("policy a", "summary text"),
        )

    def test_simple_search_filters_by_query_topic_and_quality(self):
        items = [
            {"title": "Power market policy", "summary": "Long enough", "topics": ["energy"], "quality": 80},
            {"title": "Other topic", "summary": "Power mention", "topics": ["other"], "quality": 90},
            {"title": "Power draft", "summary": "Draft", "topics": ["energy"], "quality": 20},
        ]

        results = simple_search(items, query="power", topics=["energy"], min_quality=60)

        self.assertEqual([item["title"] for item in results], ["Power market policy"])


class EmbeddingTests(unittest.TestCase):
    def test_embed_text_is_deterministic_and_normalized(self):
        first = embed_text("power market policy")
        second = embed_text("power market policy")

        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(value * value for value in first) ** 0.5, 1.0, places=6)

    def test_semantic_search_ranks_relevant_content_first(self):
        items = [
            {"id": "coal", "title": "Coal supply", "content": "coal mine production railway port inventory"},
            {"id": "weather", "title": "Weather", "content": "temperature rain wind forecast"},
        ]

        results = semantic_search(items, "coal inventory", limit=2)

        self.assertEqual(results[0]["id"], "coal")
        self.assertGreater(results[0]["semantic_score"], results[1]["semantic_score"])


class AttachmentTests(unittest.TestCase):
    def test_extract_text_from_text_markdown_html_json_and_csv(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            txt = root / "a.txt"
            md = root / "a.md"
            html = root / "a.html"
            js = root / "a.json"
            csv = root / "a.csv"
            txt.write_text("plain text", encoding="utf-8")
            md.write_text("# Title\nmarkdown body", encoding="utf-8")
            html.write_text("<html><body><h1>Heading</h1><p>HTML body</p></body></html>", encoding="utf-8")
            js.write_text('{"title":"JSON title","body":"JSON body"}', encoding="utf-8")
            csv.write_text("name,value\ncoal,100\n", encoding="utf-8")

            self.assertIn("plain text", extract_text_from_file(txt))
            self.assertIn("markdown body", extract_text_from_file(md))
            self.assertIn("HTML body", extract_text_from_file(html))
            self.assertIn("JSON body", extract_text_from_file(js))
            self.assertIn("coal", extract_text_from_file(csv))

    def test_extract_asset_text_updates_asset_status(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.txt"
            path.write_text("asset body", encoding="utf-8")
            policy = AssetPolicy([Path(tmp)])

            text, asset = extract_asset_text({"path": str(path), "kind": "file"}, policy=policy)

            self.assertEqual(text, "asset body")
            self.assertEqual(asset["parse_status"], "parsed")
            self.assertEqual(asset["text_length"], len("asset body"))

    def test_validate_asset_path_enforces_allowed_directory_suffix_and_size(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed = root / "uploads"
            allowed.mkdir()
            valid = allowed / "note.md"
            valid.write_text("safe", encoding="utf-8")
            outside = root / "outside.md"
            outside.write_text("unsafe", encoding="utf-8")
            bad_suffix = allowed / "note.exe"
            bad_suffix.write_text("bad", encoding="utf-8")
            too_large = allowed / "large.md"
            too_large.write_text("123456", encoding="utf-8")
            policy = AssetPolicy([allowed], max_bytes=5, allowed_suffixes={".md"})

            self.assertEqual(validate_asset_path(valid, policy), valid.resolve())
            with self.assertRaises(ValueError):
                validate_asset_path(outside, policy)
            with self.assertRaises(ValueError):
                validate_asset_path(bad_suffix, policy)
            with self.assertRaises(ValueError):
                validate_asset_path(too_large, policy)


class ClassificationTests(unittest.TestCase):
    def test_classify_category_uses_rules_and_preserves_manual_category(self):
        self.assertEqual(
            classify_category({"title": "动力煤价格指数行情", "summary": "环渤海5500K价格监测"}),
            "数据资产",
        )
        self.assertEqual(
            classify_category({"category": "产品方案", "title": "政策通知"}),
            "产品方案",
        )

    def test_infer_topics_uses_topic_map_and_merges_existing_topics(self):
        item = {
            "title": "电力市场现货交易政策",
            "summary": "售电和现货市场规则更新",
            "topics": ["已有主题"],
        }
        topics = infer_topics(item, {"电力市场": ["现货市场", "售电"], "数据政策": ["政策"]})

        self.assertEqual(topics, ["已有主题", "电力市场", "数据政策"])

    def test_extract_tags_and_entities_are_deterministic(self):
        item = {
            "title": "朗新科技发布煤价指数行情平台",
            "summary": "BSPI 指数和 5500K 价格用于能源数据监测。",
            "url": "https://example.com/report",
        }

        tags = extract_tags(item)
        entities = extract_entities(item)

        self.assertIn("朗新科技", entities)
        self.assertIn("BSPI", entities)
        self.assertIn("5500K", entities)
        self.assertIn("example.com", entities)
        self.assertTrue(tags)

    def test_auto_annotate_item_adds_category_topics_tags_and_entities(self):
        item = auto_annotate_item(
            {
                "title": "动力煤价格指数行情",
                "summary": "环渤海5500K价格和BSPI指数用于煤炭市场监测分析。",
            },
            {
                "topic_map": {
                    "煤炭市场": ["动力煤", "煤炭", "BSPI"],
                    "价格监测": ["价格", "指数", "行情"],
                }
            },
        )

        self.assertEqual(item["category"], "数据资产")
        self.assertEqual(item["topics"], ["煤炭市场", "价格监测"])
        self.assertIn("BSPI", item["entities"])
        self.assertTrue(item["tags"])


class QueryServiceTests(unittest.TestCase):
    def test_format_query_item_truncates_summary_and_defaults_source_node(self):
        item = format_query_item({
            "id": "1",
            "title": "Policy",
            "summary": "x" * 250,
            "topics": ["energy"],
            "quality": 80,
        })

        self.assertEqual(len(item["summary"]), 200)
        self.assertEqual(item["source_node"], "unknown")
        self.assertEqual(item["topics"], ["energy"])

    def test_build_query_results_merges_hub_first_and_deduplicates_by_content(self):
        hub_items = [
            {"id": "hub-1", "title": "Power market policy", "summary": "Detailed summary " * 5, "quality": 80},
        ]
        local_items = [
            {"id": "local-1", "title": " power market policy ", "summary": "Detailed summary " * 5, "quality": 90},
            {"id": "local-2", "title": "Power market case", "summary": "Another detailed summary " * 5, "quality": 85},
        ]

        results = build_query_results(hub_items, local_items, query_text="power", limit=10)

        self.assertEqual([item["id"] for item in results], ["hub-1", "local-2"])

    def test_build_query_results_applies_limit(self):
        items = [
            {"id": str(index), "title": f"Power item {index}", "summary": "Detailed summary " * 5, "quality": 80}
            for index in range(3)
        ]

        results = build_query_results(items, [], query_text="power", limit=2)

        self.assertEqual([item["id"] for item in results], ["0", "1"])

    def test_query_response_exposes_v2_metadata_without_full_content(self):
        item = format_query_item(
            {
                "id": "1",
                "title": "Policy",
                "summary": "Short summary",
                "content": "Full content should not be returned by compact query results",
                "chunks": [{"id": "chunk-1", "text": "chunk text"}],
                "assets": [{"id": "asset-1", "kind": "web", "url": "https://example.com"}],
                "content_type": "policy",
                "quality": 82,
                "quality_detail": {"score": 82, "confidence": 0.8},
                "source": {"name": "Gov", "url": "https://example.com"},
                "provenance": {"content_hash": "abc", "source_node": "writer-node"},
                "lifecycle": {"status": "active", "version": 2},
                "access": {"visibility": "team"},
                "metadata": {"region": "CN"},
            }
        )

        self.assertEqual(item["content_type"], "policy")
        self.assertEqual(item["source"]["name"], "Gov")
        self.assertEqual(item["quality_detail"]["confidence"], 0.8)
        self.assertEqual(item["lifecycle"]["version"], 2)
        self.assertEqual(item["metadata"], {"region": "CN"})
        self.assertEqual(item["assets"][0]["id"], "asset-1")
        self.assertNotIn("content", item)
        self.assertNotIn("chunks", item)

    def test_query_response_can_include_full_content_and_chunks(self):
        item = format_query_item(
            {
                "id": "1",
                "title": "Policy",
                "summary": "Short summary",
                "content": "Full content",
                "chunks": [{"id": "chunk-1", "text": "Full content"}],
                "quality": 80,
            },
            include_content=True,
            include_chunks=True,
        )

        self.assertEqual(item["content"], "Full content")
        self.assertEqual(item["chunks"][0]["id"], "chunk-1")


class StorageBackendTests(unittest.TestCase):
    def test_sqlite_store_inserts_reads_updates_and_deletes_knowledge_items(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "knowledge.sqlite3"
            store = open_knowledge_store({"storage_backend": "sqlite", "hub_db_path": str(db_path)}, Path(tmp))

            inserted = store.insert_if_missing({
                "id": "item-1",
                "title": "Power market policy",
                "summary": "Detailed summary",
                "category": "行业政策",
                "topics": ["电力市场"],
                "source_node": "writer",
                "created_at": "2026-06-14 10:00:00",
            })
            duplicate = store.insert_if_missing({"id": "item-1", "title": "Duplicate", "summary": "Ignored"})
            items = store.all()
            updated, error = store.update_item("item-1", {"title": "Updated", "source_node": "blocked"})
            usage_updates = store.increment_usage_counts(
                [{"id": "item-1"}],
                "hub_usage_count",
                "hub_last_used",
                "2026-06-14",
            )
            after_usage = store.all()[0]
            deleted = store.delete_item("item-1")
            store.close()

            self.assertTrue(inserted)
            self.assertFalse(duplicate)
            self.assertEqual(len(items), 1)
            self.assertEqual(updated["title"], "Updated")
            self.assertEqual(updated["source_node"], "writer")
            self.assertIsNone(error)
            self.assertEqual(usage_updates, 1)
            self.assertEqual(after_usage["hub_usage_count"], 1)
            self.assertEqual(after_usage["hub_last_used"], "2026-06-14")
            self.assertEqual(deleted, 1)

    def test_migrate_tinydb_to_sqlite_copies_items_once(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            tiny_path = root / "knowledge.json"
            sqlite_path = root / "knowledge.sqlite3"
            tiny = open_tinydb(tiny_path)
            tiny.table("knowledge").insert({"id": "item-1", "title": "Policy", "summary": "Detailed summary"})
            tiny.table("knowledge").insert({"id": "item-2", "title": "Data", "summary": "Detailed summary"})
            tiny.close()

            first = migrate_tinydb_to_sqlite(tiny_path, sqlite_path)
            second = migrate_tinydb_to_sqlite(tiny_path, sqlite_path)
            store = open_knowledge_store({"storage_backend": "sqlite", "hub_db_path": str(sqlite_path)}, root)
            ids = sorted(item["id"] for item in store.all())
            store.close()

            self.assertEqual(first["inserted"], 2)
            self.assertEqual(first["skipped"], 0)
            self.assertEqual(second["inserted"], 0)
            self.assertEqual(second["skipped"], 2)
            self.assertEqual(ids, ["item-1", "item-2"])

    def test_sqlite_store_maintenance_reports_integrity_and_vacuum(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "knowledge.sqlite3"
            store = open_knowledge_store({"storage_backend": "sqlite", "hub_db_path": str(db_path)}, Path(tmp))
            store.insert_if_missing({"id": "item-1", "title": "Policy", "summary": "Detailed summary"})

            report = store.maintenance(vacuum=True)
            store.close()

            self.assertEqual(report["backend"], "sqlite")
            self.assertEqual(report["integrity_check"], "ok")
            self.assertEqual(report["knowledge_count"], 1)
            self.assertTrue(report["vacuumed"])


class AdminListTests(unittest.TestCase):
    def test_filter_admin_items_filters_sorts_and_paginates(self):
        items = [
            {"id": "1", "title": "Coal policy", "summary": "A", "category": "行业政策", "source_node": "node-a", "quality": 80, "created_at": "2026-06-14 10:00:00"},
            {"id": "2", "title": "Coal data", "summary": "B", "category": "数据资产", "source_node": "node-b", "quality": 90, "created_at": "2026-06-15 10:00:00"},
            {"id": "3", "title": "Weather data", "summary": "C", "category": "数据资产", "source_node": "node-b", "quality": 50, "created_at": "2026-06-13 10:00:00"},
        ]

        page = filter_admin_items(items, q="coal", category="数据资产", node="node-b", min_quality=70, page=1, size=10)

        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["id"], "2")
        self.assertEqual(page["page"], 1)
        self.assertEqual(page["size"], 10)


class SchemaTests(unittest.TestCase):
    def test_quality_score_supports_legacy_and_v2_quality(self):
        self.assertEqual(quality_score({"quality": 75}), 75)
        self.assertEqual(quality_score({"quality": {"score": 88}}), 88)
        self.assertEqual(quality_score({}), 0)

    def test_normalize_knowledge_item_adds_v2_storage_fields(self):
        item = normalize_knowledge_item(
            {
                "title": "Policy",
                "summary": "Detailed summary",
                "content": "Detailed summary with more reusable implementation content.",
                "url": "https://example.com/policy",
                "source": "Gov",
                "source_date": "2026-06-01",
                "quality": 80,
                "topics": "energy",
                "assets": [{"url": "https://example.com/policy.pdf", "mime_type": "application/pdf"}],
                "relations": [{"type": "cites", "target_id": "kb-other"}],
                "metadata": {"region": "CN"},
            },
            source_node="writer-node",
            now="2026-06-13 10:00:00",
            content_hash_value="hash123",
        )

        self.assertEqual(item["schema_version"], "2.0")
        self.assertEqual(item["content"], "Detailed summary with more reusable implementation content.")
        self.assertEqual(item["content_type"], "article")
        self.assertEqual(item["chunks"][0]["knowledge_id"], "hash123")
        self.assertEqual(item["chunks"][0]["chunk_index"], 0)
        self.assertEqual(item["assets"][0]["kind"], "file")
        self.assertEqual(item["assets"][0]["url"], "https://example.com/policy.pdf")
        self.assertEqual(item["relations"], [{"type": "cites", "target_id": "kb-other"}])
        self.assertEqual(item["topics"], ["energy"])
        self.assertEqual(item["source"], {
            "name": "Gov",
            "url": "https://example.com/policy",
            "published_at": "2026-06-01",
            "collected_at": "2026-06-13 10:00:00",
            "type": "web",
        })
        self.assertEqual(item["source_name"], "Gov")
        self.assertEqual(item["provenance"]["source_node"], "writer-node")
        self.assertEqual(item["provenance"]["content_hash"], "hash123")
        self.assertEqual(item["quality"], 80)
        self.assertEqual(item["quality_detail"]["score"], 80)
        self.assertEqual(item["quality_detail"]["review_status"], "auto")
        self.assertEqual(item["access"]["visibility"], "team")
        self.assertEqual(item["lifecycle"]["status"], "active")
        self.assertEqual(item["lifecycle"]["version"], 1)
        self.assertEqual(item["created_at"], "2026-06-13 10:00:00")
        self.assertEqual(item["updated_at"], "2026-06-13 10:00:00")

    def test_build_content_chunks_splits_long_content_with_overlap(self):
        chunks = build_content_chunks("abcdef" * 200, "kid", chunk_size=300, overlap=30)

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["id"], "kid-chunk-0000")
        self.assertEqual(chunks[1]["chunk_index"], 1)
        self.assertTrue(chunks[1]["text"].startswith(chunks[0]["text"][-30:]))


class PathTests(unittest.TestCase):
    def test_resolve_configured_path_handles_relative_paths(self):
        self.assertEqual(
            resolve_configured_path("data/db.json", Path("/srv/kb")),
            Path("/srv/kb/data/db.json"),
        )

    def test_resolve_local_db_path_uses_configured_path(self):
        path = resolve_local_db_path(
            {"local_db_path": "local/db.json"},
            Path("/srv/kb"),
            Path("/srv/kb/config.json"),
        )

        self.assertEqual(path, Path("/srv/kb/local/db.json"))


class StorageTests(unittest.TestCase):
    def test_resolve_hub_db_path_uses_configured_relative_path(self):
        self.assertEqual(
            resolve_hub_db_path({"hub_db_path": "data/hub.json"}, Path("/srv/kb")),
            Path("/srv/kb/data/hub.json"),
        )

    def test_resolve_hub_db_path_uses_default_when_missing(self):
        self.assertEqual(
            resolve_hub_db_path({}, Path("/srv/kb")),
            Path("/srv/kb/hub_tinydb/knowledge-index.json"),
        )

    def test_increment_usage_counts_updates_matching_items(self):
        try:
            import tinydb  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("tinydb is not installed")

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "knowledge.json"
            db = open_tinydb(db_path)
            db.table("knowledge").insert({"id": "a", "usage_count": 2})
            db.table("knowledge").insert({"id": "b", "usage_count": 0})
            db.close()

            updated = increment_usage_counts(
                db_path,
                [{"id": "a"}, {"id": "missing"}, {}],
                "usage_count",
                "last_used",
                "2026-06-13",
            )

            rows = {row["id"]: row for row in read_table(db_path, "knowledge")}
            self.assertEqual(updated, 1)
            self.assertEqual(rows["a"]["usage_count"], 3)
            self.assertEqual(rows["a"]["last_used"], "2026-06-13")
            self.assertEqual(rows["b"]["usage_count"], 0)

    def test_insert_knowledge_if_missing_inserts_once(self):
        try:
            import tinydb  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("tinydb is not installed")

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "knowledge.json"

            first = insert_knowledge_if_missing(db_path, {"id": "a", "title": "A"})
            second = insert_knowledge_if_missing(db_path, {"id": "a", "title": "A duplicate"})

            rows = read_table(db_path, "knowledge")
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "A")


class StatsTests(unittest.TestCase):
    def test_build_hub_stats_counts_nodes_and_top_topics(self):
        stats = build_hub_stats([
            {"source_node": "a", "topics": ["energy", "policy"]},
            {"source_node": "a", "topics": ["energy"]},
            {"topics": ["other"]},
        ])

        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["source_nodes"], {"a": 2, "unknown": 1})
        self.assertEqual(stats["top_topics"]["energy"], 2)

    def test_build_node_query_stats_sorts_by_query_count(self):
        stats = build_node_query_stats(
            {
                "b": {"query_count": 1, "last_query": "later", "total_results": 3},
                "a": {"query_count": 5, "last_query": "now", "total_results": 8},
            },
            {"a": {"role": "writer"}},
        )

        self.assertEqual(stats["total_nodes_queried"], 2)
        self.assertEqual(stats["total_queries"], 6)
        self.assertEqual([item["node"] for item in stats["nodes"]], ["a", "b"])
        self.assertEqual(stats["nodes"][1]["role"], "unknown")

    def test_build_usage_stats_merges_and_sorts_usage(self):
        stats = build_usage_stats(
            [
                {"id": "a", "title": "A", "usage_count": 2, "last_used": "local"},
                {"id": "unused", "title": "Unused", "usage_count": 0},
            ],
            [
                {"id": "a", "title": "A", "hub_usage_count": 4, "hub_last_used": "hub"},
                {"id": "b", "title": "B", "hub_usage_count": 3, "hub_last_used": "hub-b"},
            ],
        )

        self.assertEqual(stats["total_used"], 2)
        self.assertEqual([item["id"] for item in stats["top_used"]], ["a", "b"])
        self.assertEqual(stats["top_used"][0]["local_usage"], 2)
        self.assertEqual(stats["top_used"][0]["hub_usage"], 4)

    def test_build_dashboard_model_counts_dashboard_aggregates(self):
        model = build_dashboard_model(
            [
                {
                    "title": "A",
                    "source_node": "node-a",
                    "quality": 65,
                    "category": "行业政策",
                    "topics": ["energy"],
                    "created_at": "2026-06-12 10:00:00",
                },
                {
                    "title": "B",
                    "source_node": "node-a",
                    "quality": 90,
                    "category": "技术资料",
                    "topics": ["energy", "ai"],
                    "created_at": "2026-06-10 10:00:00",
                },
            ],
            {"node-a": {}, "node-b": {}},
            datetime(2026, 6, 13),
        )

        self.assertEqual(model["total"], 2)
        self.assertEqual(model["avg_quality"], 77.5)
        self.assertEqual(model["active_nodes"], 1)
        self.assertEqual(model["total_topics"], 2)
        self.assertEqual(model["nodes_counter"]["node-a"], 2)
        self.assertEqual(model["quality_ranges"], {"60-70": 1, "70-85": 0, "85-100": 1})
        self.assertEqual(model["node_activity"]["node-a"], 2)
        self.assertEqual(model["node_activity"]["node-b"], 0)
        self.assertEqual([item["title"] for item in model["recent_items"]], ["A", "B"])


class IngestValidationTests(unittest.TestCase):
    def test_validate_knowledge_item_rejects_oversized_items(self):
        item, skipped = validate_knowledge_item(
            {"title": "Large item", "summary": "x" * 200},
            {"max_item_size_bytes": 20, "quality_threshold": 60},
        )

        self.assertIsNone(item)
        self.assertEqual(skipped["reason"], "too_large")

    def test_validate_knowledge_item_rejects_low_quality_items(self):
        item, skipped = validate_knowledge_item(
            {"title": "bad", "summary": "short", "quality": 100},
            {"max_item_size_bytes": 10240, "quality_threshold": 60},
        )

        self.assertIsNone(item)
        self.assertEqual(skipped["reason"], "quality_too_low")
        self.assertEqual(skipped["submitted_score"], 100)

    def test_validate_knowledge_item_overwrites_submitted_quality_on_copy(self):
        original = {
            "title": "High quality policy knowledge",
            "summary": "This is a substantial summary with enough detail for reuse by agents and human operators.",
            "url": "https://example.com/policy",
            "quality": 1,
        }

        item, skipped = validate_knowledge_item(
            original,
            {"max_item_size_bytes": 10240, "quality_threshold": 60},
        )

        self.assertIsNone(skipped)
        self.assertGreater(item["quality"], original["quality"])
        self.assertEqual(original["quality"], 1)

    def test_prepare_ingest_item_adds_source_id_and_created_at(self):
        item, skipped, item_hash = prepare_ingest_item(
            {"title": "Policy", "summary": "Detailed summary"},
            "writer-node",
            set(),
            "2026-06-13 10:00:00",
        )

        self.assertIsNone(skipped)
        self.assertEqual(item["source_node"], "writer-node")
        self.assertEqual(item["id"], f"hub-{item_hash}")
        self.assertEqual(item["created_at"], "2026-06-13 10:00:00")

    def test_prepare_ingest_item_preserves_existing_id_and_created_at(self):
        item, skipped, _ = prepare_ingest_item(
            {"id": "custom", "title": "Policy", "summary": "Detailed summary", "created_at": "old"},
            "writer-node",
            set(),
            "2026-06-13 10:00:00",
        )

        self.assertIsNone(skipped)
        self.assertEqual(item["id"], "custom")
        self.assertEqual(item["created_at"], "old")

    def test_prepare_ingest_item_rejects_duplicate_hash(self):
        existing_hash = content_hash("Policy", "Detailed summary")

        item, skipped, item_hash = prepare_ingest_item(
            {"title": "Policy", "summary": "Detailed summary"},
            "writer-node",
            {existing_hash},
            "2026-06-13 10:00:00",
        )

        self.assertIsNone(item)
        self.assertEqual(item_hash, existing_hash)
        self.assertEqual(skipped, {"title": "Policy", "reason": "duplicate"})

    def test_prepare_sync_item_inserts_new_item(self):
        action, item, item_hash = prepare_sync_item(
            {"title": "Policy", "summary": "Detailed summary", "quality": 70},
            "writer-node",
            {},
        )

        self.assertEqual(action, "insert")
        self.assertEqual(item["id"], f"hub-sync-{item_hash}")
        self.assertEqual(item["source_node"], "writer-node")

    def test_prepare_sync_item_updates_when_quality_is_higher(self):
        item_hash = content_hash("Policy", "Detailed summary")
        existing = {"id": "existing", "title": "Policy", "summary": "Detailed summary", "quality": 60, "source": "old"}

        action, item, _ = prepare_sync_item(
            {"title": "Policy", "summary": "Detailed summary", "quality": 80, "source": "new"},
            "writer-node",
            {item_hash: existing},
        )

        self.assertEqual(action, "update")
        self.assertEqual(item["id"], "existing")
        self.assertEqual(item["quality"], 80)
        self.assertEqual(item["source"], {"name": "new", "type": "agent"})
        self.assertEqual(item["source_name"], "new")
        self.assertEqual(item["lifecycle"]["version"], 2)
        self.assertEqual(existing["quality"], 60)

    def test_prepare_sync_item_skips_when_quality_is_not_higher(self):
        item_hash = content_hash("Policy", "Detailed summary")
        existing = {"id": "existing", "title": "Policy", "summary": "Detailed summary", "quality": 80}

        action, item, _ = prepare_sync_item(
            {"title": "Policy", "summary": "Detailed summary", "quality": 70},
            "writer-node",
            {item_hash: existing},
        )

        self.assertEqual(action, "skip")
        self.assertIsNone(item)


if __name__ == "__main__":
    unittest.main()
