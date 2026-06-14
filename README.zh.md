# 知识中枢（Knowledge Hub）

> 多智能体知识库中枢 — 面向 AI Agent 的分布式知识汇聚、查询与同步

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)

一款轻量级、自托管的知识汇聚服务器，专为**多智能体环境**设计。提供统一的查询、接入、同步、可视化看板与管理后台能力。

**🤖 为 Agent 而生**：安装、配置、运维全程可由 AI Agent 完成，**无需人工介入**。

🌐 **中英双语 UI**：完整中文（默认）与英文界面，一键切换。

[English Documentation](README.md)

---

## ✨ 核心特性

| | |
|---|---|
| 🔍 **统一查询** | 跨节点检索，支持关键词 + 质量过滤 |
| 📥 **知识接入** | 提交知识条目，自动质量评估（≥60 准入）|
| 🔄 **双向同步** | Hub 与本地知识库互通，含使用量回写 |
| 📊 **可视化看板** | 实时统计、图表、知识增长、节点分析 |
| 🛡️ **管理后台** | 知识增删改查、节点管理、审计日志、Tab 切换 |
| 🌐 **国际化** | 中英双语 UI，Cookie 持久化，支持 URL 覆盖 |
| 🔐 **Token 鉴权** | 节点级访问控制，角色权限（admin/writer/reader）|
| 📋 **审计日志** | 全量操作历史，便于合规与排错 |
| 🎨 **现代 UI** | 暗色主题看板，Chart.js 可视化 |
| 🚀 **轻量部署** | 单服务部署，支持 TinyDB 轻量模式与 SQLite 生产基础模式 |

---

## 🚀 快速开始

### 一键安装（Agent 友好）

```bash
git clone https://github.com/agent-kb-hub/kb-hub.git
cd kb-hub
bash install.sh
```

`install.sh` 自动完成：
1. ✅ 检查 Python 3.11+
2. ✅ 创建虚拟环境
3. ✅ 安装 `requirements.txt` 中的依赖
4. ✅ 为各角色生成安全 Token
5. ✅ 生成管理员登录密码，配置文件中仅保存加盐哈希
6. ✅ 初始化空数据库
7. ✅ 配置 systemd 服务（Linux）或启动脚本（macOS）
8. ✅ 启动服务
9. ✅ 运行健康检查

### 手动安装

```bash
git clone https://github.com/agent-kb-hub/kb-hub.git
cd kb-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
mkdir -p hub_tinydb logs
```

编辑 `config.json`：

- 将 `admin_users.admin` 替换为真实管理员密码哈希。
- 将 `nodes.*.token` 替换为随机 Token。
- 按需调整 `port`、`host`、`hub_db_path`、`local_db_path`。

生成管理员密码哈希：

```bash
python3 - <<'PY'
from knowledge_hub.security import hash_password
print(hash_password("replace-with-strong-password"))
PY
```

生成节点 Token：

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
```

启动服务：

```bash
python3 hub_server.py
```

后台启动：

```bash
setsid .venv/bin/python hub_server.py > logs/server.out 2>&1 < /dev/null &
echo $! > logs/server.pid
```

停止后台服务：

```bash
kill "$(cat logs/server.pid)"
```

### Docker 部署

需要安装 Docker 和 Compose v2 插件（`docker compose`）。

启动容器前先准备生产配置：

```bash
cp .env.example .env
cp config.docker.example.json config.json
mkdir -p hub_tinydb logs
```

编辑 `config.json`，替换所有占位 token 和管理员密码哈希。可以用下面命令生成密码哈希：

```bash
python3 - <<'PY'
from knowledge_hub.security import hash_password
print(hash_password("replace-with-strong-password"))
PY
```

启动服务：

```bash
docker compose up -d --build
```

健康检查：

```bash
curl http://127.0.0.1:10128/health
```

运行数据会持久化在 `hub_tinydb/` 和 `logs/`。`config.json` 与 `.env` 包含部署密钥，不要提交到版本库。

### 路径前缀部署

如果服务被挂载在子路径下，例如平台网关、Ingress 或反向代理访问路径为：

```text
/avatar-expose/12345678/kb-hub
```

需要在 `config.json` 中配置：

```json
{
  "public_base_path": "/avatar-expose/12345678/kb-hub"
}
```

配置后，页面、静态资源、登录跳转和前端 API 请求都会使用此前缀。验证命令也要带上前缀：

```bash
curl http://127.0.0.1:10128/avatar-expose/12345678/kb-hub/health
```

也可以通过环境变量覆盖：

```bash
KNOWLEDGE_HUB_PUBLIC_BASE_PATH=/avatar-expose/12345678/kb-hub python3 hub_server.py
```

### 健康检查与自测

```bash
curl http://127.0.0.1:10128/health
# → {"status": "ok", "nodes": ["admin-node"], ...}
```

验证管理员 Token：

```bash
curl -H "Authorization: Bearer <admin-token>" \
  http://127.0.0.1:10128/tokens
```

验证查询接口：

```bash
curl -X POST http://127.0.0.1:10128/query \
  -H "Authorization: Bearer <reader-or-admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"query":"","limit":5}'
```

运行测试：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests -q
python -m py_compile hub_server.py hub_sync.py scripts/reclassify_v6.py i18n/__init__.py knowledge_hub/*.py
```

---

## ⚙️ 配置参考

核心配置文件为 `config.json`：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `host` | `0.0.0.0` | 服务监听地址 |
| `port` | `10128` | 服务监听端口 |
| `public_base_path` | 空 | 子路径部署前缀，例如 `/avatar-expose/12345678/kb-hub` |
| `storage_backend` | `tinydb` | Hub 存储后端，可选 `tinydb` 或 `sqlite` |
| `hub_db_path` | `hub_tinydb/knowledge-index.json` | Hub 主库路径；`sqlite` 模式下建议设为 `hub_sqlite/knowledge.sqlite3` |
| `sqlite_db_path` | `hub_sqlite/knowledge.sqlite3` | TinyDB 迁移脚本默认 SQLite 目标路径 |
| `tinydb_source_path` | `hub_tinydb/knowledge-index.json` | TinyDB 迁移脚本默认源路径 |
| `local_db_path` | 空 | 可选，本地知识库路径，用于合并查询与使用量回写 |
| `log_path` | `logs/audit.log` | 审计日志路径 |
| `rate_limit_per_node` | `100` | 单节点限流次数 |
| `rate_limit_window_seconds` | `60` | 限流窗口秒数 |
| `dashboard_session_ttl_seconds` | `3600` | 看板短期会话有效期；旧 token 链接会换取 Cookie 后重定向到无 token URL |
| `quality_threshold` | `60` | 知识准入质量分 |
| `max_item_size_bytes` | `10240` | 单条知识最大 JSON 大小 |
| `asset_allowed_dirs` | `[]` | 允许读取本地附件的目录；为空时禁用 `assets[].path` |
| `asset_max_bytes` | `5242880` | 单个本地附件最大字节数 |
| `asset_allowed_suffixes` | 文本/PDF/Docx 等 | 允许解析的本地附件后缀 |
| `max_auto_tags` | `12` | 自动生成标签数量上限 |
| `max_auto_entities` | `20` | 自动抽取实体数量上限 |
| `admin_users` | `{}` | 管理后台账号，值为 `sha256:<salt>:<hash>` |
| `nodes` | `{}` | 节点 Token、角色、描述 |
| `topic_map` | `{}` | 主题关键词映射 |
| `category_rules` | 内置规则 | 一级分类关键词规则 |

生产环境建议：

- 不要使用示例 Token、示例密码或固定测试凭证。
- `config.json`、`.env`、`hub_tinydb/`、`logs/` 不提交到 Git。
- 对外暴露时优先使用 HTTPS。
- `/tokens` 会返回节点凭证，只授予管理员角色。

### SQLite 存储模式与迁移

默认 `tinydb` 适合本地演示和小规模单机使用；如果知识库会持续增长，建议切到 `sqlite`。SQLite 后端保留完整 JSON 文档，同时为 `id`、`category`、`source_node`、`created_at`、`content_hash` 建索引，管理后台编辑、删除、入库、同步、统计和使用量回写都会走统一存储接口。

从旧 TinyDB 迁移到 SQLite：

```bash
source .venv/bin/activate
python scripts/migrate_to_sqlite.py \
  --tinydb hub_tinydb/knowledge-index.json \
  --sqlite hub_sqlite/knowledge.sqlite3
```

迁移脚本可重复执行，已存在的 `id` 会跳过，不会重复写入。迁移完成后修改 `config.json`：

```json
{
  "storage_backend": "sqlite",
  "hub_db_path": "hub_sqlite/knowledge.sqlite3"
}
```

重启服务后执行 `/health`、`/stats` 和一次 `/query` 验证即可。TinyDB 文件建议保留一段时间作为回滚备份。

SQLite 维护检查：

```bash
curl -X POST http://127.0.0.1:10128/admin/storage/maintenance \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"vacuum": true}'
```

返回结果包含 `integrity_check`、`knowledge_count` 和是否执行 `vacuumed`。

---

## 🌐 Web 界面

| 页面 | URL | 用途 |
|------|-----|---------|
| **接入指南** | `/access` | 新节点引导页（Token 发放、质量规则）|
| **可视化看板** | `/dashboard` | 实时统计、知识增长、节点分析；旧 `/dashboard?token=xxx` 会换取短期 Cookie 后跳转到无 token URL |
| **管理后台** | `/admin` | 知识增删改查、节点管理、审计日志（需管理员登录）|
| **健康检查** | `/health` | 服务状态 |

**语言切换**：点击页面右上角语言按钮，或在 URL 末尾追加 `?lang=en` / `?lang=zh`。语言偏好写入 Cookie（1 年有效）。

---

## 🔌 API 参考

### 公共接口（无需鉴权）

| 接口 | 方法 | 说明 |
|----------|--------|-------------|
| `/health` | GET | 健康检查 |
| `/access` | GET | 接入引导页 |
| `/dashboard` | GET | 可视化看板（需 Token）|
| `/admin` | GET | 管理后台（需管理员登录）|
| `/lang` | GET | 切换语言（`?lang=en`）|
| `/i18n.js` | GET | 前端翻译 JSON |

### 鉴权接口

请求头需携带 `Authorization: Bearer <token>`。

| 接口 | 方法 | 说明 | 最低角色 |
|----------|--------|-------------|----------|
| `/query` | POST | 统一知识检索 | reader |
| `/ingest` | POST | 提交知识条目 | writer |
| `/sync` | POST | 增量/全量同步 | writer |
| `/stats` | GET | Hub 全局统计 | reader |
| `/usage-stats` | GET | 知识使用统计（本地 + Hub）| reader |
| `/node-stats` | GET | 节点查询统计 | reader |
| `/tokens` | GET | 节点 Token 列表 | admin |

> 安全说明：`/tokens` 会返回节点凭证，必须具备管理员权限。浏览器访问建议使用管理员登录态，自动化调用使用 `Authorization: Bearer <admin-token>`。

### 管理接口

| 接口 | 方法 | 说明 | 最低角色 |
|----------|--------|-------------|----------|
| `/admin/item/{id}` | PUT | 更新知识条目 | admin |
| `/admin/item/{id}` | DELETE | 删除知识条目 | admin |
| `/admin/node` | POST | 创建新节点 | admin |
| `/admin/node/{name}/reset-token` | POST | 重置节点 Token | admin |
| `/admin/log` | GET | 查看审计日志 | admin |

### 节点角色

| 角色 | 权限 |
|------|-------------|
| `admin` | 全权：读、写、删、节点管理、审计日志 |
| `writer` | 读、写、同步 |
| `reader` | 只读 |

---

## 🤖 Agent 集成

### 配置

```bash
export KNOWLEDGE_HUB_URL="http://<hub-ip>:10128"
export KNOWLEDGE_HUB_TOKEN="<your-node-token>"
```

### 注册节点

```python
import requests

HUB = "http://127.0.0.1:10128"
ADMIN_TOKEN = "<admin-token-from-config>"

r = requests.post(f"{HUB}/admin/node",
    headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    json={"name": "my-agent", "role": "writer", "description": "我的 AI Agent"}
)
print(r.json())
# → {"status": "ok", "name": "my-agent", "token": "xxx"}
```

### 查询与接入

```python
# 查询
r = requests.post(f"{HUB}/query",
    headers={"Authorization": f"Bearer <your-token>"},
    json={"query": "数据交易政策", "limit": 5})

# 接入（需 writer+ 权限）
r = requests.post(f"{HUB}/ingest",
    headers={"Authorization": f"Bearer <your-token>"},
    json={"items": [{
        "title": "知识标题",
        "summary": "详细摘要...",
        "url": "https://source-url.com"
    }]})
```

---

## 🏗️ 架构

```
┌──────────────┐     push/pull     ┌──────────────┐
│  本地 Agent  │ ─────────────────▶│              │
│  知识库      │                   │  Knowledge   │
└──────────────┘                   │     Hub      │
                                   │   (HTTP API) │
┌──────────────┐     ingest/query  │              │
│ 远程 Agent   │ ─────────────────▶│              │
└──────────────┘                   └──────────────┘
                                      │
                               ┌──────┴──────┐
                               │  管理后台   │
                               │  可视化看板 │
                               │  审计日志   │
                               └─────────────┘
```

**同步策略**：

| 方向 | 触发 | 机制 |
|-----------|---------|---------|
| 本地 → Hub | 手动推送 | 质量 ≥ 60 的知识推送至 Hub |
| Hub → 本地 | 定时拉取（每 6 小时）| 自动回流外部知识 |
| 外部 Agent → Hub | 审批后接入 | 需 writer+ 权限，管理员审核 |

---

## 📊 质量评估

Knowledge Hub 自动评估知识质量（0-100 分），**不信任节点自报分数**。

| 维度 | 加分 | 减分 |
|-----------|-------|---------|
| 标题长度（10-50 字）| +5 | <8 字：-10 |
| 摘要长度（≥50 字）| +15（封顶）| <50 字：-15 |
| URL 来源（https/http）| +5 | — |
| 低质量信号 | — | 每个 -5 |
| 内容过短 | — | 标题+摘要 <30 字：-20 |

**门槛**：`quality ≥ 60` 准入。低于门槛返回 `quality_too_low` 错误。

7 大分类标准见 [`data_dictionary.md`](data_dictionary.md)。

---

## 🧠 知识存储模型

Knowledge Hub 使用 v2 知识结构保存新入库数据，同时兼容旧版字段。查询、看板和同步接口仍保留 `title`、`summary`、`topics`、`quality` 等常用字段，新增字段用于支撑更完整的知识资产管理。

### 核心字段

| 字段 | 说明 |
|------|------|
| `schema_version` | 知识结构版本，当前为 `2.0` |
| `id` | 知识唯一 ID，未提供时由内容 hash 生成 |
| `title` | 知识标题 |
| `summary` | 摘要，查询响应默认返回最多 200 字 |
| `content` | 完整正文或可复用内容，默认不在紧凑查询响应中返回 |
| `chunks` | 正文自动分块结果，用于检索、引用片段和后续向量化 |
| `content_type` | 内容类型，例如 `article`、`policy`、`report`、`faq`、`dataset`、`code`、`note` |
| `category` | 7 大知识分类之一 |
| `topics` / `tags` / `entities` | 主题、标签、实体，用于检索和聚合 |
| `metadata` | 领域扩展字段，允许存储业务自定义结构 |

### 溯源与证据

| 字段 | 说明 |
|------|------|
| `source` | 来源对象，包含 `name`、`type`、`url`、`publisher`、`published_at`、`collected_at` |
| `source_name` | 来源名称兼容字段 |
| `assets` | 原始材料或附件列表，支持网页、PDF、Word、图片、表格等登记 |
| `provenance.source_node` | 提交知识的节点 |
| `provenance.original_id` | 外部系统原始 ID |
| `provenance.content_hash` | 内容去重 hash |
| `provenance.archive_url` | 归档或快照地址 |
| `provenance.evidence` | 证据链扩展列表 |

### 质量、权限与生命周期

| 字段 | 说明 |
|------|------|
| `quality` | 兼容旧接口的数值质量分 |
| `quality_detail` | 质量详情，包含 `score`、`confidence`、`review_status`、`reasons` |
| `access.visibility` | 可见范围：`private`、`team`、`public` |
| `access.allowed_nodes` | 允许访问的节点列表 |
| `lifecycle.status` | 状态：`draft`、`active`、`deprecated`、`archived`、`deleted` |
| `lifecycle.version` | 知识版本号，同步更新时递增 |
| `lifecycle.valid_from` / `valid_until` | 有效期 |
| `lifecycle.review_at` | 建议复核时间 |
| `relations` | 知识关系，例如引用、替代、冲突、派生 |

`quality_detail.reasons` 会记录自动评分的加减分原因。低于阈值的条目会在 `/ingest` 或 `/sync` 返回 `quality_too_low`，并带上 `quality_detail`，方便节点修正标题、摘要、来源后重试。

### 管理后台列表接口

后台列表使用专用分页接口，不再通过 `/query` 拉全库：

```bash
curl -H "Authorization: Bearer <admin-token>" \
  "http://127.0.0.1:10128/admin/items?q=煤价&category=数据资产&page=1&size=20"
```

支持参数：`q`、`category`、`node`、`min_quality`、`page`、`size`。`size` 最大 200。

### 查询正文与分块

`/query` 默认返回紧凑结果，不返回完整正文和分块，避免响应过大。需要完整内容时传入：

```json
{
  "query": "关键词",
  "limit": 5,
  "search_mode": "semantic",
  "include_content": true,
  "include_chunks": true
}
```

字段说明：

| 参数 | 说明 |
|------|------|
| `search_mode` | `keyword` 关键词检索，`semantic` 本地向量检索，`hybrid` 关键词优先并补充语义结果 |
| `include_content` | 返回 `content` 完整正文 |
| `include_chunks` | 返回 `chunks` 分块结果 |

### 向量检索

系统内置一个无外部服务依赖的本地向量检索基线：

- 使用确定性 feature hashing 生成本地 embedding。
- 入库时为知识主记录和分块生成 `embedding`。
- `/query` 使用 `search_mode: "semantic"` 时按向量相似度排序，并返回 `semantic_score`。
- 该实现适合作为默认可运行能力；后续可把 `embedding.provider/model` 替换为真实 embedding 服务和向量数据库。

### 附件内容解析

`assets` 支持登记原始材料并在入库时抽取文本合入 `content`：

| 类型 | 支持情况 |
|------|----------|
| `.txt`、`.md`、`.markdown`、`.log` | 内置支持 |
| `.html`、`.htm` | 内置 HTML 文本抽取 |
| `.json` | 内置结构文本抽取 |
| `.csv` | 内置表格文本抽取 |
| `.pdf` | 安装 `pypdf` 后支持 |
| `.docx` | 安装 `python-docx` 后支持 |

解析结果会写回 `assets[].parse_status` 和 `assets[].text_length`。解析失败不会阻断入库，会记录 `parse_error`。

安全边界：

- 默认 `asset_allowed_dirs` 为空，本地 `assets[].path` 不会被读取。
- 只有配置在 `asset_allowed_dirs` 内的文件才允许解析。
- 文件必须匹配 `asset_allowed_suffixes`，并且大小不能超过 `asset_max_bytes`。
- URL 资产只登记为溯源材料，不会由服务端主动抓取远程内容。

### 入库自动标注

`/ingest` 和 `/sync` 会在质量校验通过后自动补充分类与标签：

| 字段 | 规则 |
|------|------|
| `category` | 如果提交方已提供则保留；否则根据 `category_rules` 和内置关键词规则判定一级分类 |
| `topics` | 根据 `topic_map` 命中标题、摘要、正文、标签后补充标准主题，并与提交方已有主题去重合并 |
| `tags` | 从标题、摘要、正文中抽取高频关键词、英文缩写、数字指标，数量受 `max_auto_tags` 限制 |
| `entities` | 抽取公司/集团/政策/方案/指数/价格/行情、英文缩写、数字指标、URL 域名和来源名称，数量受 `max_auto_entities` 限制 |

自动标注不依赖 LLM，规则可解释、可测试、可配置。LLM 可作为后续增强，但不是默认运行依赖。

示例：

```json
{
  "schema_version": "2.0",
  "title": "某政策知识",
  "summary": "可复用摘要",
  "content": "完整正文或结构化内容",
  "content_type": "policy",
  "category": "行业政策",
  "topics": ["数据要素"],
  "chunks": [
    {
      "id": "abc123-chunk-0000",
      "knowledge_id": "abc123",
      "chunk_index": 0,
      "text": "完整正文或结构化内容",
      "embedding_status": "pending"
    }
  ],
  "source": {
    "name": "政府网站",
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

## 📁 项目结构

```
kb-hub/
├── hub_server.py           # FastAPI 主服务（单文件核心）
├── hub_sync.py             # 双向同步脚本
├── install.sh              # 一键安装脚本
├── start.sh                # 启动脚本
├── config.example.json     # 配置示例
├── data_dictionary.md      # 知识分类标准
├── README.md               # 英文文档
├── README.zh.md            # 中文文档（本文件）
├── i18n/                   # 国际化
│   ├── __init__.py
│   ├── zh.json             # 中文翻译
│   └── en.json             # 英文翻译
├── static/                 # 静态资源（Logo 等）
├── scripts/                # 工具脚本
├── hub_tinydb/             # Hub 数据库（git 忽略）
├── logs/                   # 服务日志（git 忽略）
├── .venv/                  # Python 虚拟环境（git 忽略）
└── .gitignore              # Git 忽略配置
```

---

## 🔒 安全

- 全 API Token 鉴权
- 基于角色的访问控制（admin/writer/reader）
- 全量操作审计日志
- 单条内容大小限制（默认 10KB）
- Token 使用 `secrets.token_urlsafe` 安全生成
- 管理员密码只保存加盐哈希，不保存明文
- 支持子路径部署，避免反向代理路径错配导致接口或静态资源暴露异常

---

## 🧯 常见问题

### `docker compose` 不存在

当前机器缺少 Compose v2 插件。可以安装 Docker Compose v2，或使用上面的“手动安装”方式直接运行。

### 登录页能打开，但提交后 404

通常是子路径部署没有配置 `public_base_path`。请确认 `config.json` 中的 `public_base_path` 与网关实际路径完全一致。

### 页面打开但 Logo、接口请求 404

同样检查 `public_base_path`。前端静态资源和 API 请求必须与外部访问前缀一致。

### `ModuleNotFoundError: fastapi`

没有安装运行依赖：

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

如果默认 PyPI 网络较慢，可以使用可用的镜像源。

### `Admin session required`

管理接口需要管理员登录 Cookie，或使用管理员节点 Token：

```bash
curl -H "Authorization: Bearer <admin-token>" http://127.0.0.1:10128/tokens
```

---

## 🤝 贡献

欢迎提 Issue 与 PR。重大变更请先开 Issue 讨论。

---

## 📄 开源协议

MIT 协议 — 详见 [LICENSE](LICENSE)。

---

## 🏢 关于

**个人开源项目** — 欢迎贡献、Star、Issue。

Knowledge Hub 是多 Agent 知识管理的核心组件，通过共享的、质量受控的知识库，支撑分布式 AI Agent 协作。
