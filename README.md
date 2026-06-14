# Knowledge Hub

> Multi-Agent Knowledge Base Hub — Distributed knowledge aggregation, query, and synchronization for AI agents

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)

A lightweight, self-hosted knowledge aggregation server designed for **multi-agent environments**. Unified query, ingestion, synchronization, visual dashboard, and admin panel for distributed knowledge bases.

**🤖 Built for Agents**: Install, configure, and operate entirely via AI agents — zero human interaction required.

🌐 **Bilingual UI**: Full Chinese (默认) and English interface with one-click switching.

[中文文档](README.zh.md)

---

## ✨ Features

| | |
|---|---|
| 🔍 **Unified Query** | Search across all connected nodes with keyword + quality filtering |
| 📥 **Knowledge Ingestion** | Submit knowledge items with automatic quality evaluation (≥60 accepted) |
| 🔄 **Bi-directional Sync** | Push/pull between Hub and local knowledge bases with usage tracking |
| 📊 **Visual Dashboard** | Real-time stats, charts, knowledge growth tracking, and per-node analytics |
| 🛡️ **Admin Panel** | Knowledge CRUD, node management, audit log with tab navigation |
| 🌐 **i18n Support** | Chinese + English bilingual UI, cookie-persistent, URL-overridable |
| 🔐 **Token-based Auth** | Node-level access control with role-based permissions (admin/writer/reader) |
| 📋 **Audit Log** | Complete operation history for compliance and debugging |
| 🎨 **Modern UI** | Dark-themed dashboard with Chart.js visualizations |
| 🚀 **Lightweight** | Single-service deployment with TinyDB lightweight mode and SQLite production baseline |

---

## 🚀 Quick Start

### One-Click Install (Agent-Friendly)

```bash
git clone https://github.com/agent-kb-hub/kb-hub.git
cd kb-hub
bash install.sh
```

The `install.sh` script automatically:
1. ✅ Checks Python 3.11+
2. ✅ Creates virtual environment
3. ✅ Installs dependencies from `requirements.txt`
4. ✅ Generates secure tokens for all node roles
5. ✅ Generates an admin login password and stores only its salted hash
6. ✅ Initializes empty database
7. ✅ Configures systemd service (Linux) or creates startup script (macOS)
8. ✅ Starts the service
9. ✅ Runs health check

### Manual Install

```bash
git clone https://github.com/agent-kb-hub/kb-hub.git
cd kb-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
mkdir -p hub_tinydb logs
```

Edit `config.json`:

- Replace `admin_users.admin` with a real admin password hash.
- Replace `nodes.*.token` with random tokens.
- Adjust `port`, `host`, `hub_db_path`, and `local_db_path` as needed.

Generate an admin password hash:

```bash
python3 - <<'PY'
from knowledge_hub.security import hash_password
print(hash_password("replace-with-strong-password"))
PY
```

Generate a node token:

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
```

Start the service:

```bash
python3 hub_server.py
```

Start in the background:

```bash
setsid .venv/bin/python hub_server.py > logs/server.out 2>&1 < /dev/null &
echo $! > logs/server.pid
```

Stop the background service:

```bash
kill "$(cat logs/server.pid)"
```

### Docker Deploy

Requires Docker with the Compose v2 plugin (`docker compose`).

Prepare a production config before starting the container:

```bash
cp .env.example .env
cp config.docker.example.json config.json
mkdir -p hub_tinydb logs
```

Edit `config.json` and replace all placeholder tokens and admin password hash. You can generate a password hash with:

```bash
python3 - <<'PY'
from knowledge_hub.security import hash_password
print(hash_password("replace-with-strong-password"))
PY
```

Start the service:

```bash
docker compose up -d --build
```

Verify:

```bash
curl http://127.0.0.1:10128/health
```

Runtime data is persisted in `hub_tinydb/` and `logs/`. Keep `config.json` and `.env` out of version control because they contain deployment secrets.

### Path Prefix Deployments

If the service is mounted under a subpath, for example through an ingress, gateway, or reverse proxy:

```text
/avatar-expose/12345678/kb-hub
```

configure `config.json` with:

```json
{
  "public_base_path": "/avatar-expose/12345678/kb-hub"
}
```

After this, HTML pages, static assets, login redirects, and frontend API calls will use the same prefix. Verify with the prefixed health URL:

```bash
curl http://127.0.0.1:10128/avatar-expose/12345678/kb-hub/health
```

You can also override it with an environment variable:

```bash
KNOWLEDGE_HUB_PUBLIC_BASE_PATH=/avatar-expose/12345678/kb-hub python3 hub_server.py
```

### Verify and Test

```bash
curl http://127.0.0.1:10128/health
# → {"status": "ok", "nodes": ["admin-node"], ...}
```

Verify an admin token:

```bash
curl -H "Authorization: Bearer <admin-token>" \
  http://127.0.0.1:10128/tokens
```

Verify the query API:

```bash
curl -X POST http://127.0.0.1:10128/query \
  -H "Authorization: Bearer <reader-or-admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"query":"","limit":5}'
```

Run tests:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests -q
python -m py_compile hub_server.py hub_sync.py scripts/reclassify_v6.py i18n/__init__.py knowledge_hub/*.py
```

---

## ⚙️ Configuration

The main configuration file is `config.json`:

| Field | Default | Description |
|-------|---------|-------------|
| `host` | `0.0.0.0` | Bind host |
| `port` | `10128` | Bind port |
| `public_base_path` | empty | Deployment subpath, for example `/avatar-expose/12345678/kb-hub` |
| `storage_backend` | `tinydb` | Hub storage backend, either `tinydb` or `sqlite` |
| `hub_db_path` | `hub_tinydb/knowledge-index.json` | Hub database path; use `hub_sqlite/knowledge.sqlite3` for SQLite mode |
| `sqlite_db_path` | `hub_sqlite/knowledge.sqlite3` | Default SQLite target for the migration script |
| `tinydb_source_path` | `hub_tinydb/knowledge-index.json` | Default TinyDB source for the migration script |
| `local_db_path` | empty | Optional local knowledge DB path for merged query and usage writeback |
| `log_path` | `logs/audit.log` | Audit log path |
| `rate_limit_per_node` | `100` | Per-node rate limit |
| `rate_limit_window_seconds` | `60` | Rate limit window in seconds |
| `dashboard_session_ttl_seconds` | `3600` | Short-lived dashboard session TTL; legacy token links exchange for a cookie and redirect to a token-free URL |
| `quality_threshold` | `60` | Minimum accepted knowledge quality score |
| `max_item_size_bytes` | `10240` | Maximum JSON size per knowledge item |
| `asset_allowed_dirs` | `[]` | Directories allowed for local attachment reads; empty disables `assets[].path` |
| `asset_max_bytes` | `5242880` | Maximum size for one local attachment |
| `asset_allowed_suffixes` | text/PDF/Docx, etc. | Allowed local attachment suffixes |
| `max_auto_tags` | `12` | Maximum number of generated tags |
| `max_auto_entities` | `20` | Maximum number of extracted entities |
| `admin_users` | `{}` | Admin users, values are `sha256:<salt>:<hash>` |
| `nodes` | `{}` | Node tokens, roles, and descriptions |
| `topic_map` | `{}` | Topic keyword mapping |
| `category_rules` | built in | Keyword rules for top-level categories |

Production recommendations:

- Do not use example tokens, example passwords, or fixed test credentials.
- Do not commit `config.json`, `.env`, `hub_tinydb/`, or `logs/`.
- Prefer HTTPS for public deployments.
- `/tokens` returns node credentials and should remain admin-only.

### SQLite Storage And Migration

The default `tinydb` backend is good for local demos and small single-node deployments. For a growing knowledge base, switch to `sqlite`. The SQLite backend keeps the full JSON document and adds indexes for `id`, `category`, `source_node`, `created_at`, and `content_hash`. Ingestion, sync, query, stats, admin update/delete, and usage writeback use the same storage interface.

Migrate existing TinyDB data:

```bash
source .venv/bin/activate
python scripts/migrate_to_sqlite.py \
  --tinydb hub_tinydb/knowledge-index.json \
  --sqlite hub_sqlite/knowledge.sqlite3
```

The migration is idempotent: existing `id` values are skipped. After migration, update `config.json`:

```json
{
  "storage_backend": "sqlite",
  "hub_db_path": "hub_sqlite/knowledge.sqlite3"
}
```

Restart the service and verify `/health`, `/stats`, and one `/query` request.

SQLite maintenance check:

```bash
curl -X POST http://127.0.0.1:10128/admin/storage/maintenance \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"vacuum": true}'
```

The response includes `integrity_check`, `knowledge_count`, and whether `vacuumed` ran.

---

## 🌐 Web UI

| Page | URL | Purpose |
|------|-----|---------|
| **Access Guide** | `/access` | Onboarding page for new nodes (Token issuance, quality rules) |
| **Dashboard** | `/dashboard` | Visual stats, knowledge growth, node analytics; legacy `/dashboard?token=xxx` exchanges for a short-lived cookie and redirects to a token-free URL |
| **Admin Panel** | `/admin` | Knowledge CRUD, node management, audit log (admin login required) |
| **Health Check** | `/health` | Service status |

**Language switching**: Click the language button in any UI page, or append `?lang=en` / `?lang=zh` to the URL. Language preference is stored in cookies (1 year).

---

## 🔌 API Reference

### Public Endpoints (No Auth)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/access` | GET | Access guide / onboarding page |
| `/dashboard` | GET | Visual dashboard (token required) |
| `/admin` | GET | Admin panel (admin login required) |
| `/lang` | GET | Switch language (`?lang=en`) |
| `/i18n.js` | GET | Translation JSON for frontend |

### Authenticated Endpoints

Require `Authorization: Bearer <token>` header.

| Endpoint | Method | Description | Min Role |
|----------|--------|-------------|----------|
| `/query` | POST | Unified knowledge search | reader |
| `/ingest` | POST | Submit knowledge items | writer |
| `/sync` | POST | Incremental/full sync | writer |
| `/stats` | GET | Hub global statistics | reader |
| `/usage-stats` | GET | Knowledge usage stats (local + hub) | reader |
| `/node-stats` | GET | Per-node query statistics | reader |
| `/tokens` | GET | List node tokens | admin |

> Security note: `/tokens` returns node credentials and requires admin privileges. Prefer the admin login session for browser access and `Authorization: Bearer <admin-token>` for automation.

### Admin Endpoints

| Endpoint | Method | Description | Min Role |
|----------|--------|-------------|----------|
| `/admin/item/{id}` | PUT | Update a knowledge item | admin |
| `/admin/item/{id}` | DELETE | Delete a knowledge item | admin |
| `/admin/node` | POST | Create new node | admin |
| `/admin/node/{name}/reset-token` | POST | Reset node token | admin |
| `/admin/log` | GET | View audit log | admin |

### Node Roles

| Role | Permissions |
|------|-------------|
| `admin` | Full control: read, write, delete, manage nodes, view audit log |
| `writer` | Read, write, sync |
| `reader` | Read-only access |

---

## 🤖 Agent Integration

### Configuration

```bash
export KNOWLEDGE_HUB_URL="http://<hub-ip>:10128"
export KNOWLEDGE_HUB_TOKEN="<your-node-token>"
```

### Register a Node

```python
import requests

HUB = "http://127.0.0.1:10128"
ADMIN_TOKEN = "<admin-token-from-config>"

r = requests.post(f"{HUB}/admin/node",
    headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    json={"name": "my-agent", "role": "writer", "description": "My AI Agent"}
)
print(r.json())
# → {"status": "ok", "name": "my-agent", "token": "xxx"}
```

### Query & Ingest

```python
# Query
r = requests.post(f"{HUB}/query",
    headers={"Authorization": f"Bearer <your-token>"},
    json={"query": "data trading policy", "limit": 5})

# Ingest (writer+ only)
r = requests.post(f"{HUB}/ingest",
    headers={"Authorization": f"Bearer <your-token>"},
    json={"items": [{
        "title": "Knowledge Title",
        "summary": "Detailed summary...",
        "url": "https://source-url.com"
    }]})
```

---

## 🏗️ Architecture

```
┌──────────────┐     push/pull     ┌──────────────┐
│  Local Agent │ ─────────────────▶│              │
│  Knowledge   │                   │  Knowledge   │
└──────────────┘                   │     Hub      │
                                   │   (HTTP API) │
┌──────────────┐     ingest/query  │              │
│ Remote Agent │ ─────────────────▶│              │
└──────────────┘                   └──────────────┘
                                      │
                               ┌──────┴──────┐
                               │  Admin Panel │
                               │  Dashboard   │
                               │  Audit Log   │
                               └─────────────┘
```

**Sync strategy:**

| Direction | Trigger | Mechanism |
|-----------|---------|-----------|
| Local → Hub | Manual push | quality ≥ 60 knowledge pushed to Hub |
| Hub → Local | Scheduled pull (every 6h) | External knowledge auto-pulled back |
| External Agent → Hub | Approved ingest | Requires writer+ permission, admin review |

---

## 📊 Quality Evaluation

Knowledge Hub automatically evaluates knowledge quality (0-100) — **it does not trust node-submitted scores**.

| Dimension | Bonus | Penalty |
|-----------|-------|---------|
| Title length (10-50 chars) | +5 | <8 chars: -10 |
| Summary length (50+ chars) | +15 max | <50 chars: -15 |
| URL source (https/http) | +5 | — |
| Low-quality signals | — | -5 per signal |
| Very short content | — | Title+summary <30 chars: -20 |

**Threshold**: `quality ≥ 60` for acceptance. Below threshold returns `quality_too_low` error.

See [`data_dictionary.md`](data_dictionary.md) for the 7-category classification taxonomy.

---

## 🧠 Knowledge Storage Model

Knowledge Hub stores newly ingested data with the v2 knowledge schema while remaining compatible with legacy fields. Query, dashboard, and sync APIs still expose common fields such as `title`, `summary`, `topics`, and `quality`; v2 fields add the structure needed for stronger knowledge asset management.

### Core Fields

| Field | Description |
|-------|-------------|
| `schema_version` | Knowledge schema version, currently `2.0` |
| `id` | Unique knowledge ID, generated from content hash when omitted |
| `title` | Knowledge title |
| `summary` | Summary; compact query responses return up to 200 characters |
| `content` | Full text or reusable content; omitted from compact query responses by default |
| `chunks` | Automatically generated content chunks for retrieval, citations, and future embeddings |
| `content_type` | Content type, for example `article`, `policy`, `report`, `faq`, `dataset`, `code`, `note` |
| `category` | One of the 7 knowledge categories |
| `topics` / `tags` / `entities` | Topics, tags, and entities for retrieval and aggregation |
| `metadata` | Domain-specific extension object |

### Provenance and Evidence

| Field | Description |
|-------|-------------|
| `source` | Source object with `name`, `type`, `url`, `publisher`, `published_at`, `collected_at` |
| `source_name` | Source-name compatibility field |
| `assets` | Original materials or attachments, including webpages, PDFs, Word files, images, and spreadsheets |
| `provenance.source_node` | Node that submitted the knowledge |
| `provenance.original_id` | External source-system ID |
| `provenance.content_hash` | Deduplication hash |
| `provenance.archive_url` | Archive or snapshot URL |
| `provenance.evidence` | Evidence-chain extension list |

### Quality, Access, and Lifecycle

| Field | Description |
|-------|-------------|
| `quality` | Numeric quality score kept for legacy compatibility |
| `quality_detail` | Quality detail with `score`, `confidence`, `review_status`, `reasons` |
| `access.visibility` | Visibility: `private`, `team`, or `public` |
| `access.allowed_nodes` | Explicitly allowed node list |
| `lifecycle.status` | Status: `draft`, `active`, `deprecated`, `archived`, `deleted` |
| `lifecycle.version` | Knowledge version, incremented on sync updates |
| `lifecycle.valid_from` / `valid_until` | Validity window |
| `lifecycle.review_at` | Suggested review time |
| `relations` | Knowledge relations such as cites, replaces, conflicts-with, derived-from |

`quality_detail.reasons` records the automatic scoring reasons. Items below the threshold are rejected by `/ingest` or `/sync` with `quality_too_low` and include `quality_detail` so the submitting node can fix the title, summary, or source and retry.

### Admin List API

The admin panel uses a dedicated paginated list API instead of loading the whole database through `/query`:

```bash
curl -H "Authorization: Bearer <admin-token>" \
  "http://127.0.0.1:10128/admin/items?q=coal&category=数据资产&page=1&size=20"
```

Supported parameters: `q`, `category`, `node`, `min_quality`, `page`, and `size`. `size` is capped at 200.

### Querying Full Content and Chunks

`/query` returns compact results by default and omits full content and chunks to keep responses small. Request them explicitly when needed:

```json
{
  "query": "keyword",
  "limit": 5,
  "search_mode": "semantic",
  "include_content": true,
  "include_chunks": true
}
```

Parameters:

| Parameter | Description |
|-----------|-------------|
| `search_mode` | `keyword` keyword search, `semantic` local vector search, or `hybrid` keyword-first plus semantic results |
| `include_content` | Return full `content` |
| `include_chunks` | Return generated `chunks` |

### Vector Search

Knowledge Hub includes a local vector-search baseline with no external service dependency:

- Deterministic feature hashing generates local embeddings.
- Ingestion creates `embedding` data for knowledge records and chunks.
- `/query` with `search_mode: "semantic"` ranks results by vector similarity and returns `semantic_score`.
- This is a default runnable baseline; later deployments can replace `embedding.provider/model` with a real embedding service and vector database.

### Attachment Parsing

`assets` can register original materials and extract their text into `content` during ingestion:

| Type | Support |
|------|---------|
| `.txt`, `.md`, `.markdown`, `.log` | Built in |
| `.html`, `.htm` | Built-in HTML text extraction |
| `.json` | Built-in structured text extraction |
| `.csv` | Built-in table text extraction |
| `.pdf` | Supported when `pypdf` is installed |
| `.docx` | Supported when `python-docx` is installed |

Parsing writes back `assets[].parse_status` and `assets[].text_length`. Parse failures do not block ingestion; `parse_error` is recorded instead.

Security boundaries:

- `asset_allowed_dirs` is empty by default, so local `assets[].path` is not read.
- Only files under configured `asset_allowed_dirs` can be parsed.
- Files must match `asset_allowed_suffixes` and stay under `asset_max_bytes`.
- URL assets are registered as provenance material; the server does not actively fetch remote content.

### Automatic Ingestion Annotation

`/ingest` and `/sync` automatically enrich accepted items after quality validation:

| Field | Rule |
|-------|------|
| `category` | Preserves a submitted category; otherwise classifies with `category_rules` and built-in keyword rules |
| `topics` | Uses `topic_map` against title, summary, content, and tags, then merges with submitted topics |
| `tags` | Extracts frequent keywords, abbreviations, and numeric indicators from title, summary, and content; limited by `max_auto_tags` |
| `entities` | Extracts companies, policies, solutions, indices, prices, markets, abbreviations, numeric indicators, URL domains, and source names; limited by `max_auto_entities` |

Automatic annotation does not depend on an LLM. It is deterministic, explainable, testable, and configurable. LLMs can be added later as an enhancement, but they are not a default runtime dependency.

Example:

```json
{
  "schema_version": "2.0",
  "title": "Policy Knowledge",
  "summary": "Reusable summary",
  "content": "Full text or structured reusable content",
  "content_type": "policy",
  "category": "行业政策",
  "topics": ["数据要素"],
  "chunks": [
    {
      "id": "abc123-chunk-0000",
      "knowledge_id": "abc123",
      "chunk_index": 0,
      "text": "Full text or structured reusable content",
      "embedding_status": "pending"
    }
  ],
  "source": {
    "name": "Government Website",
    "type": "web",
    "url": "https://example.com/policy",
    "published_at": "2026-06-01",
    "collected_at": "2026-06-14 10:00:00"
  },
  "assets": [
    {
      "id": "asset-0000",
      "kind": "file",
      "url": "https://example.com/policy.pdf",
      "mime_type": "application/pdf"
    }
  ],
  "provenance": {
    "source_node": "writer-node",
    "content_hash": "abc123"
  },
  "quality": 82,
  "quality_detail": {
    "score": 82,
    "confidence": 1.0,
    "review_status": "auto",
    "reasons": []
  },
  "access": {
    "visibility": "team",
    "allowed_nodes": []
  },
  "lifecycle": {
    "status": "active",
    "version": 1
  },
  "relations": [
    {
      "type": "cites",
      "target_id": "kb-source"
    }
  ],
  "metadata": {
    "region": "CN"
  }
}
```

---

## 📁 Project Structure

```
kb-hub/
├── hub_server.py           # Main FastAPI server (single-file core)
├── hub_sync.py             # Bi-directional sync script
├── install.sh              # One-click install script
├── start.sh                # Startup script
├── config.example.json     # Example configuration
├── data_dictionary.md      # Knowledge classification taxonomy
├── i18n/                   # Internationalization
│   ├── __init__.py
│   ├── zh.json             # Chinese translations
│   └── en.json             # English translations
├── static/                 # Static assets (logos, etc.)
├── scripts/                # Utility scripts
├── hub_tinydb/             # Hub database (gitignored)
├── logs/                   # Server logs (gitignored)
├── .venv/                  # Python virtual environment (gitignored)
└── README.md               # This file
```

---

## 🔒 Security

- Token-based authentication for all API endpoints
- Role-based access control (admin/writer/reader)
- Audit logging for all operations
- Content size limits (default 10KB per item)
- Secure token generation via `secrets.token_urlsafe`
- Admin passwords are stored as salted hashes only
- Subpath deployment support avoids broken reverse-proxy routes for APIs and static assets

---

## 🧯 Troubleshooting

### `docker compose` is missing

The machine does not have the Docker Compose v2 plugin. Install Compose v2, or use the manual non-Docker deployment flow above.

### The login page opens, but submitting the form returns 404

This usually means a subpath deployment is missing `public_base_path`. Make sure `config.json` matches the exact external gateway path.

### The page opens, but logos or API requests return 404

Check `public_base_path`. Static assets and frontend API requests must use the same external prefix as the page URL.

### `ModuleNotFoundError: fastapi`

Runtime dependencies are not installed:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

If the default PyPI index is slow, use an available mirror.

### `Admin session required`

Admin APIs require an admin login cookie, or an admin node token:

```bash
curl -H "Authorization: Bearer <admin-token>" http://127.0.0.1:10128/tokens
```

---

## 🤝 Contributing

Issues and PRs welcome. For major changes, please open an issue first to discuss.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🏢 About

Knowledge Hub is a core component of multi-agent knowledge management, supporting distributed AI agent collaboration through shared, quality-controlled knowledge bases.

**个人开源项目** — 欢迎贡献、Star、Issue。
