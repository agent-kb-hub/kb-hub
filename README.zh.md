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
| 🚀 **轻量部署** | 单文件服务，TinyDB 存储，总体积 < 10MB |

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
3. ✅ 安装依赖（`fastapi`、`uvicorn`、`tinydb`、`requests`）
4. ✅ 为各角色生成安全 Token
5. ✅ 初始化空数据库
6. ✅ 配置 systemd 服务（Linux）或启动脚本（macOS）
7. ✅ 启动服务
8. ✅ 运行健康检查

### 手动安装

```bash
git clone https://github.com/agent-kb-hub/kb-hub.git
cd kb-hub
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn tinydb requests
python3 hub_server.py
```

### 健康检查

```bash
curl http://127.0.0.1:10128/health
# → {"status": "ok", "nodes": ["admin-node"], ...}
```

---

## 🌐 Web 界面

| 页面 | URL | 用途 |
|------|-----|---------|
| **接入指南** | `/access` | 新节点引导页（Token 发放、质量规则）|
| **可视化看板** | `/dashboard?token=xxx` | 实时统计、知识增长、节点分析 |
| **管理后台** | `/admin?token=xxx` | 知识增删改查、节点管理、审计日志 |
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
| `/admin` | GET | 管理后台（需 admin Token）|
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
| `/tokens` | GET | 节点 Token 列表 | reader |

### 管理接口

| 接口 | 方法 | 说明 | 最低角色 |
|----------|--------|-------------|----------|
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