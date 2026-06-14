# Backend Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract framework-independent backend logic from `hub_server.py` into testable modules.

**Architecture:** Add a `knowledge_hub` package for pure helpers and keep FastAPI routes in `hub_server.py` for this stage.

**Tech Stack:** Python 3.11+, standard-library `unittest`, existing FastAPI/TinyDB runtime.

---

### Task 1: Core Modules

**Files:**
- Create: `knowledge_hub/security.py`
- Create: `knowledge_hub/quality.py`
- Create: `knowledge_hub/search.py`
- Create: `knowledge_hub/paths.py`

- [x] Move password hash helpers into `security.py`.
- [x] Move quality scoring into `quality.py`.
- [x] Move content hashing and in-memory search into `search.py`.
- [x] Move configured path resolution into `paths.py`.

### Task 2: Unit Tests

**Files:**
- Create: `tests/test_core_modules.py`

- [x] Add `unittest` coverage for password verification.
- [x] Add `unittest` coverage for quality scoring.
- [x] Add `unittest` coverage for content hash and search filters.
- [x] Add `unittest` coverage for configured path resolution.

### Task 3: Server Wiring

**Files:**
- Modify: `hub_server.py`

- [x] Import extracted helpers from `knowledge_hub`.
- [x] Remove duplicate pure helper implementations.
- [x] Keep route signatures and response shapes unchanged.

### Task 4: Verification

**Files:**
- No new files.

- [ ] Run `python3 -m unittest tests.test_core_modules -v`.
- [ ] Run `python3 -m py_compile hub_server.py hub_sync.py scripts/reclassify_v6.py i18n/__init__.py knowledge_hub/*.py`.
- [ ] Run `git diff --check`.

### Task 5: Auth Core Extraction

**Files:**
- Create: `knowledge_hub/auth.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract bearer token parsing into `knowledge_hub.auth.extract_bearer_token`.
- [x] Extract node token resolution into `knowledge_hub.auth.resolve_node_from_token`.
- [x] Extract admin bearer fallback into `knowledge_hub.auth.resolve_admin_bearer`.
- [x] Extract session expiry check into `knowledge_hub.auth.is_session_valid`.
- [x] Add standard-library tests for token parsing, role checks, and session expiry.

### Task 6: Storage Core Extraction

**Files:**
- Create: `knowledge_hub/storage.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract Hub TinyDB path resolution into `knowledge_hub.storage.resolve_hub_db_path`.
- [x] Extract TinyDB open helpers into `knowledge_hub.storage.open_hub_db` and `open_local_db`.
- [x] Extract table reads into `knowledge_hub.storage.read_table`.
- [x] Add standard-library tests for Hub DB path resolution.
- [x] Extract usage counter updates into `knowledge_hub.storage.increment_usage_counts`.
- [x] Extract local insert-if-missing into `knowledge_hub.storage.insert_knowledge_if_missing`.
- [x] Wire `_record_usage` and `_sync_to_local` through storage helpers.

### Task 7: Query Service Extraction

**Files:**
- Create: `knowledge_hub/query.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract public query result formatting into `knowledge_hub.query.format_query_item`.
- [x] Extract Hub/local merge, dedupe, and limit behavior into `knowledge_hub.query.build_query_results`.
- [x] Wire `/query` route to `build_query_results` while keeping DB reads, usage tracking, and stats in the route.
- [x] Add standard-library tests for summary truncation, source-node defaulting, hub-first dedupe, and limit behavior.

### Task 8: Ingest Service Extraction

**Files:**
- Modify: `knowledge_hub/ingest.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract source node, id, and created-at preparation into `knowledge_hub.ingest.prepare_ingest_item`.
- [x] Extract duplicate hash decision into `prepare_ingest_item`.
- [x] Wire `/ingest` route to `prepare_ingest_item` while keeping DB insert and local sync in the route.
- [x] Add standard-library tests for metadata defaults, preserving existing fields, and duplicate rejection.

### Task 9: Sync Service Extraction

**Files:**
- Modify: `knowledge_hub/ingest.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract sync action decision into `knowledge_hub.ingest.prepare_sync_item`.
- [x] Preserve existing behavior: insert new content, update only when quality is higher, skip otherwise.
- [x] Wire `/sync` route to `prepare_sync_item` while keeping TinyDB update/insert in the route.
- [x] Add standard-library tests for insert, update, and skip decisions.

### Task 10: Stats Service Extraction

**Files:**
- Create: `knowledge_hub/stats.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract Hub total/source-node/topic aggregation into `knowledge_hub.stats.build_hub_stats`.
- [x] Extract node query stats sorting and totals into `knowledge_hub.stats.build_node_query_stats`.
- [x] Extract local/Hub usage merge and sorting into `knowledge_hub.stats.build_usage_stats`.
- [x] Wire `/stats`, `/node-stats`, and `/usage-stats` to the stats helpers.
- [x] Add standard-library tests for hub stats, node query stats, and usage stats.

### Task 11: Dashboard Model Extraction

**Files:**
- Modify: `knowledge_hub/stats.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract dashboard aggregate model into `knowledge_hub.stats.build_dashboard_model`.
- [x] Keep dashboard HTML/JS unchanged and only replace the data aggregation block.
- [x] Add standard-library tests for node counters, category/topic counters, quality ranges, recent items, and seven-day activity.

### Task 12: Admin Core Extraction

**Files:**
- Create: `knowledge_hub/admin.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract node config shape into `knowledge_hub.admin.build_node_config`.
- [x] Extract create-node state transition into `knowledge_hub.admin.create_node_state`.
- [x] Extract reset-token state transition into `knowledge_hub.admin.reset_node_token_state`.
- [x] Extract config node upsert into `knowledge_hub.admin.upsert_config_node`.
- [x] Wire admin create/reset/config-save paths to admin helpers.
- [x] Add standard-library tests for create, duplicate rejection, token reset, missing node, and config upsert behavior.

### Task 13: Admin Utility Extraction

**Files:**
- Modify: `knowledge_hub/admin.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract token listing response construction into `knowledge_hub.admin.build_token_listing`.
- [x] Extract audit-log filtering, newest-first ordering, and pagination into `knowledge_hub.admin.paginate_audit_log`.
- [x] Wire `/tokens` and `/admin/log` routes to admin utility helpers.
- [x] Add standard-library tests for token listing shape and audit log pagination.

### Task 14: Config Initialization Extraction

**Files:**
- Create: `knowledge_hub/config.py`
- Modify: `hub_server.py`
- Modify: `tests/test_core_modules.py`

- [x] Extract node token materialization into `knowledge_hub.config.materialize_node_config`.
- [x] Preserve existing token handling and replace `AUTO_GENERATED` tokens through a caller-provided token factory.
- [x] Keep config file I/O in `hub_server.py` and move only pure config transformation.
- [x] Add standard-library tests for existing tokens, generated tokens/defaults, and input immutability.
