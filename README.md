# Knowledge Hub

> Multi-Agent Knowledge Base Hub — Distributed knowledge aggregation, query, and synchronization for AI agents

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)

A lightweight, self-hosted knowledge aggregation server designed for **multi-agent environments**. Unified query, ingestion, synchronization, visual dashboard, and admin panel for distributed knowledge bases.

**🤖 Built for Agents**: Install, configure, and operate entirely via AI agents — zero human interaction required.

🌐 **Bilingual UI**: Full Chinese (默认) and English interface with one-click switching.

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
| 🚀 **Lightweight** | Single-file server, TinyDB storage, < 10MB total |

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
3. ✅ Installs dependencies (`fastapi`, `uvicorn`, `tinydb`, `requests`)
4. ✅ Generates secure tokens for all node roles
5. ✅ Initializes empty database
6. ✅ Configures systemd service (Linux) or creates startup script (macOS)
7. ✅ Starts the service
8. ✅ Runs health check

### Manual Install

```bash
git clone https://github.com/agent-kb-hub/kb-hub.git
cd kb-hub
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn tinydb requests
python3 hub_server.py
```

### Verify

```bash
curl http://127.0.0.1:10128/health
# → {"status": "ok", "nodes": ["admin-node"], ...}
```

---

## 🌐 Web UI

| Page | URL | Purpose |
|------|-----|---------|
| **Access Guide** | `/access` | Onboarding page for new nodes (Token issuance, quality rules) |
| **Dashboard** | `/dashboard?token=xxx` | Visual stats, knowledge growth, node analytics |
| **Admin Panel** | `/admin?token=xxx` | Knowledge CRUD, node management, audit log |
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
| `/admin` | GET | Admin panel (admin token required) |
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
| `/tokens` | GET | List node tokens | reader |

### Admin Endpoints

| Endpoint | Method | Description | Min Role |
|----------|--------|-------------|----------|
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