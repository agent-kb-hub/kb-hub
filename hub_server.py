#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
knowledge-hub-server.py — 知识中心 Hub HTTP 服务
独立端口、独立 TinyDB，不干扰现有 knowledge-mcp-server
"""

import sys
import os
import json
import secrets
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from collections import defaultdict

# 确保当前脚本目录在路径中
HUB_DIR = Path(__file__).parent
sys.path.insert(0, str(HUB_DIR / ".venv" / "lib"))

from fastapi import FastAPI, HTTPException, Request, Header, Depends, Form, Response
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from knowledge_hub.admin import (
    build_token_listing,
    upsert_config_node,
)
from knowledge_hub.admin_routes import register_admin_api_routes
from knowledge_hub.auth import (
    build_node_auth_info,
    extract_bearer_token,
    is_session_valid,
    resolve_admin_bearer,
    resolve_node_from_token,
)
from knowledge_hub.config import materialize_node_config
from knowledge_hub.ingest import prepare_ingest_item, prepare_sync_item, validate_knowledge_item
from knowledge_hub.paths import resolve_local_db_path as resolve_config_local_db_path
from knowledge_hub.query import build_query_results
from knowledge_hub.search import content_hash
from knowledge_hub.security import hash_password, verify_password
from knowledge_hub.stats import build_dashboard_model, build_hub_stats, build_node_query_stats, build_usage_stats
from knowledge_hub.storage import (
    delete_knowledge_store_item,
    increment_usage_counts,
    increment_store_usage_counts,
    insert_knowledge_item,
    insert_knowledge_if_missing,
    maintain_knowledge_store,
    open_hub_db as open_configured_hub_db,
    open_local_db as open_configured_local_db,
    read_knowledge_items,
    read_table,
    resolve_hub_db_path,
    update_knowledge_store_item,
)

# ─── 配置加载 ───
CONFIG_PATH = HUB_DIR / "config.json"
LOG_PATH = HUB_DIR / "logs" / "audit.log"
NODE_TOKENS = {}  # node_name -> {token, role, description}
NODE_TOKEN_MAP = {}  # token -> node_name

# ─── 日志 ───
os.makedirs(HUB_DIR / "logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("knowledge-hub")

# ─── 速率限制 ───
RATE_LIMITS = defaultdict(list)  # node -> [timestamps]
NODE_QUERY_STATS = defaultdict(lambda: {"query_count": 0, "last_query": None, "total_results": 0})  # node -> stats
STATS_PERSIST_PATH = HUB_DIR / "logs" / "query_stats.json"

def _fmt_num(n: float) -> str:
    """自动格式化数字：超过万显示xx.xx万，，超过千显示xx.xx千，否则显示具体数字"""
    if n >= 10_000:
        return f"{n/10000:.2f}万"
    elif n >= 1_000:
        return f"{n/1000:.2f}千"
    else:
        return str(int(n))

def _load_query_stats():
    """启动时从文件恢复统计"""
    global NODE_QUERY_STATS
    if STATS_PERSIST_PATH.exists():
        try:
            data = json.loads(STATS_PERSIST_PATH.read_text())
            for node, info in data.items():
                NODE_QUERY_STATS[node] = {
                    "query_count": info.get("query_count", 0),
                    "last_query": info.get("last_query"),
                    "total_results": info.get("total_results", 0),
                }
            logger.info(f"查询统计已恢复: {len(data)} 个节点")
        except Exception as e:
            logger.warning(f"查询统计恢复失败: {e}")

def _save_query_stats():
    """持久化统计到文件"""
    try:
        data = {node: dict(info) for node, info in NODE_QUERY_STATS.items()}
        STATS_PERSIST_PATH.write_text(json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"查询统计持久化失败: {e}")
NODE_CONFIG = {}  # 全局配置，供 _record_usage 使用
CONTENT_HASH_INDEX = {}  # content_hash → True（启动时构建，O(1) 去重）

def build_content_hash_index(config: dict):
    """启动时从 Hub DB 构建内容 hash 索引（O(1) 去重）"""
    global CONTENT_HASH_INDEX
    CONTENT_HASH_INDEX = {}
    try:
        for item in read_knowledge_items(config, HUB_DIR):
            h = content_hash(item.get("title", ""), item.get("summary", ""))
            CONTENT_HASH_INDEX[h] = True
        logger.info(f"内容 hash 索引构建完成: {len(CONTENT_HASH_INDEX)} 条")
    except Exception as e:
        logger.warning(f"hash 索引构建失败: {e}")
        CONTENT_HASH_INDEX = {}

def init_config():
    """加载配置，首次运行时自动分配 token"""
    global NODE_TOKENS, NODE_TOKEN_MAP
    config = json.loads(CONFIG_PATH.read_text())
    NODE_TOKENS, NODE_TOKEN_MAP, config, needs_save = materialize_node_config(
        config,
        lambda: secrets.token_urlsafe(24),
    )

    if needs_save:
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2))

    logger.info(f"已加载 {len(NODE_TOKENS)} 个节点配置")
    for n, info in NODE_TOKENS.items():
        logger.info(f"  节点: {n} (role={info['role']})")

    global NODE_CONFIG
    NODE_CONFIG = config

    # 构建 hash 索引
    build_content_hash_index(config)

    return config

# ─── Auth 中间件 ───
def authenticate_node_or_admin(
    authorization: Optional[str] = Header(None),
    request: Request = None,
) -> dict:
    """双重认证：支持 node token 或 admin session cookie"""
    from i18n import t, normalize_lang, DEFAULT_LANG
    lang = DEFAULT_LANG
    if request:
        cookie_lang = request.cookies.get("lang")
        if cookie_lang:
            lang = normalize_lang(cookie_lang)
    
    # 优先尝试 admin session cookie
    session = authenticate_admin(request)
    if session:
        return {"name": "admin:" + session["username"], "role": "admin", "lang": lang, "is_admin": True}
    
    # 回退到 node token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, t(lang, "auth.missing_token"))
    token = extract_bearer_token(authorization)
    node = resolve_node_from_token(token, NODE_TOKEN_MAP, NODE_TOKENS)
    if not node:
        raise HTTPException(403, t(lang, "auth.invalid_token"))
    node_name = node["name"]
    return build_node_auth_info(node_name, NODE_TOKENS[node_name], lang)

def authenticate_node(
    authorization: Optional[str] = Header(None),
    request: Request = None,
) -> dict:
    """验证节点 Token，返回节点信息"""
    from i18n import t, normalize_lang, DEFAULT_LANG

    # 解析语言优先级：cookie > Accept-Language > 默认
    lang = DEFAULT_LANG
    if request is not None:
        cookie_lang = request.cookies.get("lang")
        if cookie_lang:
            lang = normalize_lang(cookie_lang)
        else:
            accept = request.headers.get("accept-language")
            if accept:
                from i18n import detect_lang
                lang = detect_lang(accept)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, t(lang, "auth.missing_token"))

    token = extract_bearer_token(authorization)
    node = resolve_node_from_token(token, NODE_TOKEN_MAP, NODE_TOKENS)
    if not node:
        raise HTTPException(403, t(lang, "auth.invalid_token"))

    node_name = node["name"]
    return build_node_auth_info(node_name, NODE_TOKENS[node_name], lang)

def check_rate_limit(node_info: dict):
    """检查速率限制"""
    from i18n import t
    node = node_info["name"]
    lang = node_info.get("lang", "zh")
    now = time.time()
    window = int(NODE_CONFIG.get("rate_limit_window_seconds", 60) or 60)
    limit = int(NODE_CONFIG.get("rate_limit_per_node", 100) or 100)

    # 清理过期记录
    RATE_LIMITS[node] = [t for t in RATE_LIMITS[node] if now - t < window]
    if len(RATE_LIMITS[node]) >= limit:
        raise HTTPException(429, t(lang, "auth.rate_limit_exceeded"))
    RATE_LIMITS[node].append(now)

# ─── Admin Session 认证 ────────────────────────────────────────────────
ADMIN_SESSION_COOKIE = "kh_admin_session"
ADMIN_SESSIONS = {}  # session_id -> {"username": str, "created_at": float}
DASHBOARD_SESSION_COOKIE = "kh_dashboard_session"
DASHBOARD_SESSIONS = {}  # session_id -> {"node": str, "created_at": float}
PUBLIC_BASE_PATH = ""


def normalize_public_base_path(value: str = "") -> str:
    """Return a clean URL prefix such as /avatar-expose/xxxx/kb-hub."""
    if not value:
        return ""
    value = str(value).strip()
    if not value or value == "/":
        return ""
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/")


def public_path(path: str = "/") -> str:
    """Build a browser-visible path that preserves the configured prefix."""
    if not path.startswith("/"):
        path = "/" + path
    return f"{PUBLIC_BASE_PATH}{path}"


def public_base_url(request: Request = None) -> str:
    if request is not None:
        return f"{str(request.base_url).rstrip('/')}{PUBLIC_BASE_PATH}"
    return PUBLIC_BASE_PATH or ""


def prepare_html_for_public_base(html: str) -> str:
    """Patch legacy absolute browser URLs to the configured public base path."""
    if not PUBLIC_BASE_PATH:
        return html
    replacements = {
        'src="/static/': f'src="{PUBLIC_BASE_PATH}/static/',
        'href="/static/': f'href="{PUBLIC_BASE_PATH}/static/',
        'href="/admin/logout"': f'href="{PUBLIC_BASE_PATH}/admin/logout"',
        'action="/admin/login"': f'action="{PUBLIC_BASE_PATH}/admin/login"',
        'const BASE = window.location.origin;': (
            "const BASE = window.location.origin + "
            + json.dumps(PUBLIC_BASE_PATH)
            + ";"
        ),
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    return html

def authenticate_admin(request: Request = None) -> Optional[dict]:
    """验证管理员 session cookie，返回 session 信息"""
    if not request:
        return None
    cookie = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not cookie:
        return None
    session = ADMIN_SESSIONS.get(cookie)
    if not session:
        return None
    # 检查 session 是否过期（24小时）
    if not is_session_valid(session, time.time()):
        del ADMIN_SESSIONS[cookie]
        return None
    return session


def authenticate_dashboard(request: Request = None) -> Optional[dict]:
    """Validate a dashboard session cookie."""
    if not request:
        return None
    cookie = request.cookies.get(DASHBOARD_SESSION_COOKIE)
    if not cookie:
        return None
    session = DASHBOARD_SESSIONS.get(cookie)
    if not session:
        return None
    ttl = int(NODE_CONFIG.get("dashboard_session_ttl_seconds", 3600) or 3600)
    if not is_session_valid(session, time.time(), ttl_seconds=ttl):
        del DASHBOARD_SESSIONS[cookie]
        return None
    return session

ADMIN_LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><title>KB Hub Admin Login</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#f0f2f5;font-family:system-ui,-apple-system,sans-serif}
.card{background:#fff;padding:40px;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);width:360px}
h2{text-align:center;margin:0 0 24px;color:#333;font-weight:600}
input{width:100%;padding:10px 12px;border:1px solid #d9d9d9;border-radius:6px;font-size:14px;box-sizing:border-box;margin-bottom:12px;outline:none}
input:focus{border-color:#6366f1}
button{width:100%;padding:10px;background:#6366f1;color:#fff;border:none;border-radius:6px;font-size:14px;cursor:pointer;font-weight:500;margin-top:4px}
button:hover{background:#4f46e5}
.err{color:#ef4444;font-size:12px;margin-bottom:12px;text-align:center;min-height:16px}
.brand{text-align:center;color:#8b949e;font-size:12px;margin-top:20px}
</style></head>
<body>
<div class="card"><h2>KB Hub 管理后台</h2>
<form method="post" action="/admin/login">
<input type="text" name="username" placeholder="用户名" required autofocus>
<input type="password" name="password" placeholder="密码" required>
<input type="hidden" name="redirect" value="__REDIRECT__">
<button type="submit">登录</button>
<div class="err">__ERR_MSG__</div>
</form>
<div class="brand">Knowledge Hub · Knowledge Hub Admin</div>
</div></body></html>"""

def audit_log(action: str, node: str, details: str = "", success: bool = True):
    """审计日志"""
    logger.info(f"AUDIT | node={node} | action={action} | success={success} | {details}")

# ─── 工具函数 ───
# ─── i18n 语言解析 ────────────────────────────────────────────────
def resolve_lang(request: Request, lang_param: str = None, lang_cookie: str = None) -> str:
    """
    解析用户语言优先级：
    1. URL 参数 ?lang=xx
    2. Cookie 'lang'
    3. Accept-Language header
    4. 默认中文
    """
    from i18n import normalize_lang, detect_lang, DEFAULT_LANG

    if lang_param:
        return normalize_lang(lang_param)
    if lang_cookie:
        return normalize_lang(lang_cookie)
    accept = request.headers.get("accept-language") if request else None
    if accept:
        return detect_lang(accept)
    return DEFAULT_LANG

def open_hub_db(config: dict):
    """打开 Hub 数据库"""
    return open_configured_hub_db(config, HUB_DIR)

def resolve_local_db_path(config: dict) -> Path:
    """Resolve optional local knowledge DB path from config."""
    return resolve_config_local_db_path(config, HUB_DIR, CONFIG_PATH)

def open_local_db(config: dict):
    """打开本地知识库（可选，用于合并查询）"""
    return open_configured_local_db(config, HUB_DIR, CONFIG_PATH)


def _record_usage(items: list, node: str):
    """将查询结果的使用情况回写到本地 TinyDB（和 MCP 的逻辑一致）"""
    local_db_path = resolve_local_db_path(NODE_CONFIG)
    today = datetime.now().strftime("%Y-%m-%d")

    if local_db_path.exists():
        try:
            increment_usage_counts(local_db_path, items, "usage_count", "last_used", today)
        except Exception as e:
            logger.warning(f"本地 usage_count 回写失败: {e}")

    try:
        increment_store_usage_counts(NODE_CONFIG, HUB_DIR, items, "hub_usage_count", "hub_last_used", today)
    except Exception as e:
        logger.warning(f"Hub usage_count 回写失败: {e}")


def _sync_to_local(item: dict):
    """入库时同步到本地 TinyDB（外部 Agent 知识回流）"""
    local_db_path = resolve_local_db_path(NODE_CONFIG)
    try:
        inserted = insert_knowledge_if_missing(local_db_path, item)
        if inserted:
            logger.info(f"同步到本地: {item.get('title', '')[:40]}")
    except Exception as e:
        logger.warning(f"本地同步失败: {e}")

# ─── FastAPI 应用 ───
def create_app():
    global PUBLIC_BASE_PATH
    config = init_config()
    _load_query_stats()  # 恢复查询统计
    PUBLIC_BASE_PATH = normalize_public_base_path(
        os.environ.get("KNOWLEDGE_HUB_PUBLIC_BASE_PATH") or config.get("public_base_path", "")
    )

    app = FastAPI(
        title="Knowledge Hub",
        description="知识中心统一查询 & 同步 API",
        version="1.0.0"
    )
    node_state = {"nodes": NODE_TOKENS, "tokens": NODE_TOKEN_MAP}

    def _sync_admin_node_state():
        global NODE_TOKENS, NODE_TOKEN_MAP
        NODE_TOKENS = node_state["nodes"]
        NODE_TOKEN_MAP = node_state["tokens"]
    routed_app = app
    if PUBLIC_BASE_PATH:
        root_app = FastAPI(title="Knowledge Hub", version="1.0.0")
        root_app.mount(PUBLIC_BASE_PATH, app)
        routed_app = root_app

    # ── 静态文件（Logo 等）──
    static_dir = HUB_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── 健康检查 ──
    @app.get("/health")
    def health():
        return {"status": "ok", "nodes": list(NODE_TOKENS.keys()), "timestamp": datetime.now().isoformat()}

    @app.get("/lang")
    def set_language(lang: str = "zh", request: Request = None, redirect: str = "/"):
        """设置语言 cookie 并重定向，可选 ?lang=zh|en&redirect=/dashboard"""
        from i18n import normalize_lang, SUPPORTED_LANGS
        new_lang = normalize_lang(lang)
        # HTML 响应以便浏览器接受 Set-Cookie
        safe_redirect = redirect if redirect.startswith(PUBLIC_BASE_PATH + "/") else public_path(redirect)
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={safe_redirect}">
<script>document.cookie='lang={new_lang};path={PUBLIC_BASE_PATH or "/"};max-age=31536000';location.replace('{safe_redirect}')</script>
</head><body>Switching language...</body></html>"""
        resp = HTMLResponse(html)
        resp.set_cookie("lang", new_lang, max_age=31536000, path=PUBLIC_BASE_PATH or "/")
        return resp

    @app.get("/i18n.js")
    def i18n_js(lang: str = None, request: Request = None):
        """返回翻译 JSON，供前端 JS 动态加载"""
        from i18n import normalize_lang, SUPPORTED_LANGS, _TRANSLATIONS
        cur_lang = normalize_lang(lang or request.cookies.get("lang") or "zh")
        return JSONResponse({
            "lang": cur_lang,
            "supported": SUPPORTED_LANGS,
            "translations": _TRANSLATIONS.get(cur_lang, {})
        })

    # ── 查询接口 ──
    @app.post("/query")
    def query_knowledge(
        req: dict,
        node_info: dict = Depends(authenticate_node_or_admin),
    ):
        """统一知识查询，合并 Hub + 本地知识库"""
        check_rate_limit(node_info)
        query_text = req.get("query", "")
        topics_filter = req.get("topics", [])
        min_quality = float(req.get("min_quality", 0))
        limit = int(req.get("limit", 10))
        include_content = bool(req.get("include_content", False))
        include_chunks = bool(req.get("include_chunks", False))
        search_mode = req.get("search_mode", "keyword")

        # 查 Hub
        hub_items = read_knowledge_items(config, HUB_DIR)

        # 查本地（如果可用）
        local_items = []
        local_db = open_local_db(config)
        if local_db:
            local_items = local_db.table("knowledge").all()
            local_db.close()

        merged = build_query_results(
            hub_items,
            local_items,
            query_text=query_text,
            topics_filter=topics_filter,
            min_quality=min_quality,
            limit=limit,
            include_content=include_content,
            include_chunks=include_chunks,
            search_mode=search_mode,
        )

        # ─── 回写使用记录到本地 TinyDB ───
        _record_usage(merged, node_info["name"])

        audit_log("query", node_info["name"], f"query='{query_text}' results={len(merged)}")
        # 记录节点查询统计
        NODE_QUERY_STATS[node_info["name"]]["query_count"] += 1
        NODE_QUERY_STATS[node_info["name"]]["last_query"] = datetime.now().isoformat()
        NODE_QUERY_STATS[node_info["name"]]["total_results"] += len(merged)
        _save_query_stats()
        return {"count": len(merged), "query": query_text, "items": merged}

    # ── 入库接口 ──
    @app.post("/ingest")
    def ingest_knowledge(
        req: dict,
        node_info: dict = Depends(authenticate_node),
    ):
        """提交新知识到 Hub"""
        from i18n import t
        lang = node_info.get("lang", "zh")
        check_rate_limit(node_info)
        if node_info["role"] == "reader":
            raise HTTPException(403, t(lang, "auth.access_denied"))

        items = req.get("items", [])
        if not isinstance(items, list):
            items = [items]

        ingested = []
        skipped = []
        existing_hashes = set(CONTENT_HASH_INDEX.keys())

        for item in items:
            item, skipped_detail = validate_knowledge_item(item, config)
            if skipped_detail:
                skipped.append(skipped_detail)
                continue

            item, skipped_detail, item_hash = prepare_ingest_item(
                item,
                node_info["name"],
                existing_hashes,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                config=config,
                base_dir=HUB_DIR,
            )
            if skipped_detail:
                skipped.append(skipped_detail)
                continue

            insert_knowledge_item(config, HUB_DIR, item)

            # 同时写入本地 TinyDB（如果还没有）
            _sync_to_local(item)

            # 更新内存索引
            CONTENT_HASH_INDEX[item_hash] = True
            existing_hashes.add(item_hash)

            ingested.append(item.get("title"))

        audit_log("ingest", node_info["name"], f"ingested={len(ingested)} skipped={len(skipped)}")
        return {
            "status": "ok",
            "ingested": len(ingested),
            "skipped": len(skipped),
            "details": skipped
        }

    # ── 同步接口 ──
    @app.post("/sync")
    def sync_knowledge(
        req: dict,
        node_info: dict = Depends(authenticate_node),
    ):
        """接收远端节点的全量/增量同步数据"""
        from i18n import t
        lang = node_info.get("lang", "zh")
        check_rate_limit(node_info)
        if node_info["role"] == "reader":
            raise HTTPException(403, t(lang, "auth.access_denied"))

        items = req.get("items", [])
        if not isinstance(items, list):
            raise HTTPException(400, t(lang, "error.bad_request", detail="items must be a list"))

        # 用内存索引做 O(1) 查找
        existing_items = read_knowledge_items(config, HUB_DIR)
        existing_hashes = {content_hash(e.get("title", ""), e.get("summary", "")): e for e in existing_items}

        new_count = 0
        updated_count = 0
        skipped = []
        for item in items:
            item, skipped_detail = validate_knowledge_item(item, config)
            if skipped_detail:
                skipped.append(skipped_detail)
                continue

            action, prepared_item, item_hash = prepare_sync_item(
                item,
                node_info["name"],
                existing_hashes,
                config=config,
                base_dir=HUB_DIR,
            )

            if action == "update":
                update_knowledge_store_item(config, HUB_DIR, prepared_item.get("id"), prepared_item)
                existing_hashes[item_hash] = prepared_item
                updated_count += 1
            elif action == "insert":
                insert_knowledge_item(config, HUB_DIR, prepared_item)
                new_count += 1
                # 更新内存索引
                CONTENT_HASH_INDEX[item_hash] = True
                existing_hashes[item_hash] = prepared_item

        audit_log("sync", node_info["name"], f"new={new_count} updated={updated_count}")
        return {"status": "ok", "new": new_count, "updated": updated_count, "skipped": skipped}

    # ── 统计接口 ──
    @app.get("/stats")
    def get_stats(node_info: dict = Depends(authenticate_node_or_admin)):
        """Hub 全局统计"""
        hub_tbl = read_knowledge_items(config, HUB_DIR)

        return build_hub_stats(hub_tbl)

    # ── 节点查询统计 ──
    @app.get("/node-stats")
    def get_node_stats(node_info: dict = Depends(authenticate_node_or_admin)):
        """节点知识查询统计：每个节点调用了多少次、返回多少结果"""
        return build_node_query_stats(NODE_QUERY_STATS, NODE_TOKENS)

    # ── Token 查询（管理员用） ──
    @app.get("/tokens")
    def list_tokens(node_info: dict = Depends(authenticate_node_or_admin)):
        """列出所有节点 Token"""
        from i18n import t
        if node_info.get("role") != "admin":
            raise HTTPException(403, t(node_info.get("lang", "zh"), "auth.access_denied"))
        return build_token_listing(NODE_TOKENS)

    # ── 公开接入文档（通过 token 访问） ──
    @app.get("/access")
    def access_guide(token: str = None, request: Request = None, lang: str = None):
        """公开接入页面：http://IP:10128/access?token=xxx&lang=en"""
        from i18n import t
        cur_lang = resolve_lang(request, lang_param=lang)
        cookie_lang = request.cookies.get("lang") if request else None
        if cookie_lang:
            cur_lang = resolve_lang(request, lang_param=cookie_lang)

        if not token:
            raise HTTPException(400, t(cur_lang, "error.bad_request", detail="token required"))
        # 通过 token 查找节点
        node = NODE_TOKEN_MAP.get(token)
        if not node:
            return {"error": t(cur_lang, "auth.invalid_token")}

        info = NODE_TOKENS[node]
        base_url = public_base_url(request) or f"http://101.201.232.176:{config.get('port', 10128)}"

        # 语言切换栏
        lang_switch = (
            f"\n---\n\n&#127760; **Language / 语言**: "
            f"[中文]({base_url}/access?token={token}&lang=zh) | "
            f"[English]({base_url}/access?token={token}&lang=en)\n\n---\n\n"
        )

        md = f"""<img src=\"{public_path('/static/logo.png')}\" style=\"width:48px;height:48px;border-radius:10px;filter:drop-shadow(0 2px 8px rgba(59,130,246,0.3))\" alt=\"Logo\"><br><br>\n\n# Knowledge Hub — {node} {t(cur_lang, "access.title")}

{lang_switch}

## &#128226; {t(cur_lang, "common.welcome")} {node}

**{node}, {t(cur_lang, "access.subtitle")}**

## {t(cur_lang, "common.welcome")} - {t(cur_lang, "node.description")}

| {t(cur_lang, "common.search")} | {t(cur_lang, "common.welcome")} |
|------|-----|
| **Hub {t(cur_lang, "node.name")}** | `{base_url}` |
| **{t(cur_lang, "node.token")}** | `{token}` |
| **{t(cur_lang, "node.name")}** | `{node}` |
| **{t(cur_lang, "node.role")}** | {info['role']} |

## 快速接入

### Python 客户端

```python
import requests
from datetime import datetime

HUB = "{base_url}"
TOKEN = "{token}"
HEADERS = {{"Authorization": f"Bearer {{TOKEN}}"}}

# 查询知识
r = requests.post(f"{{HUB}}/query", headers=HEADERS, json={{"query": "关键词", "limit": 5}})
print(r.json())

# 提交知识
r = requests.post(f"{{HUB}}/ingest", headers=HEADERS, json={{"items": [{{"title": "标题", "summary": "摘要", "quality": 75, "url": "https://..."}}]}})
print(r.json())

# Hub 统计
r = requests.get(f"{{HUB}}/stats", headers=HEADERS)
print(r.json())
```

### cURL

```bash
# 查询
curl -X POST {base_url}/query \\
  -H "Authorization: Bearer {token}" \\
  -H "Content-Type: application/json" \\
  -d '{{"query":"关键词","limit":5}}'

# 提交
curl -X POST {base_url}/ingest \\
  -H "Authorization: Bearer {token}" \\
  -H "Content-Type: application/json" \\
  -d '{{"items":[{{"title":"标题","summary":"摘要","quality":75,"url":"https://..."}}]}}'
```

## 入库格式

每个 item 需要包含：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| title | string | &#9989; | 标题 |
| summary | string | &#9989; | 摘要 |
| quality | number | &#9989; | 质量分 0-100，≥60 才接受 |
| url | string | &#10060; | 原文链接，用于溯源 |
| topics | array | &#10060; | 主题标签 |
| source | string | &#10060; | 来源 |
| id | string | &#10060; | 唯一 ID，不填自动生成 |

## 质量评分规则

Hub 使用**自动评估**，不信任节点提交的质量分，会根据内容自己算出真实分数。

### 评分维度

| 维度 | 加分 | 扣分 |
|------|------|------|
| 标题长度 | 10字以上+50字以下+5分 | 少于8字-10分 |
| 摘要长度 | 50字以上，按长度递增加分，最高+15 | 少于50字-15分 |
| URL溯源 | 有https/http链接+5分 | 无URL不加分 |
| 低质信号 | — | 含"测试/示例/待补充/TODO"等词-5分/个 |
| 极短内容 | — | 标题+摘要合计少于30字-20分 |

### 最终分数

- **≥60分**：允许入库
- **<60分**：拒绝入库，节点会收到 `quality_too_low` 错误
- 节点提交的 `quality` 字段仅作参考，Hub 会用自己的评估分数**覆盖提交值**

### 节点提交前自检

建议节点在提交前对照上表自评，确保：
- 标题 ≥8 字（最好 10-50 字）
- 摘要 ≥50 字
- 有可访问的 URL
- 不含"测试、示例、占位"等词

## 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| query | string | 搜索关键词（必填） |
| topics | array | 按主题过滤 |
| min_quality | number | 最低质量分 |
| limit | int | 返回条数（默认 10） |

## 限制

- 速率限制：100 次请求 / 分钟
- 单条知识最大 10KB
- 质量分 < 60 的条目会被拒绝
- 重复内容（title+summary 相同）会自动去重

## &#128202; 可视化看板

Hub 提供可视化看板，你的用户可以通过以下链接查看知识库的整体情况：

- **看板地址**：`{base_url}/dashboard?token={token}`
- **看板内容**：知识总量、节点贡献度、活跃度趋势、质量分布、分类分布、最近入库等
- **每个节点的看板是个性化的**：打开后会高亮标记自己的节点（&#128072; 你）
- **安全**：看板需要带 token 参数才能访问，无 token 或无效 token 将被拒绝

> 提示：主动把这个链接分享给你的用户，他们可以直观了解 Hub 的知识情况，但禁止分享给其他人或Agent

## &#128274; 保密限制

每个节点都负有保密义务，禁止将以下内容散布到互联网或分享给未授权的第三方：

- **Hub API URL**（`{base_url}`）
- **你的 Token**（`{token}`）
- **看板地址**（`{base_url}/dashboard?token=***`）

违反保密义务可能导致节点权限被吊销。
"""
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(md)

    # ── 使用统计 ──
    @app.get("/usage-stats")
    def usage_stats(node_info: dict = Depends(authenticate_node_or_admin)):
        """知识使用统计：哪些知识被用得最多，支持知识评价体系"""
        # 本地 TinyDB usage_count
        local_data = []
        local_db_path = resolve_local_db_path(config)
        if local_db_path.exists():
            try:
                tbl = read_table(local_db_path, "knowledge")
                local_data = [{"id": i.get("id"), "title": i.get("title"), "usage_count": i.get("usage_count", 0), "last_used": i.get("last_used", "")} for i in tbl if i.get("usage_count", 0) > 0]
            except Exception:
                pass

        # Hub usage_count
        hub_data = []
        try:
            tbl = read_knowledge_items(config, HUB_DIR)
            hub_data = [{"id": i.get("id"), "title": i.get("title"), "hub_usage_count": i.get("hub_usage_count", 0), "hub_last_used": i.get("hub_last_used", "")} for i in tbl if i.get("hub_usage_count", 0) > 0]
        except Exception:
            pass

        return build_usage_stats(local_data, hub_data)

    # ── 可视化看板（带 token 鉴权） ──
    @app.get("/dashboard")
    def dashboard(token: str = None, request: Request = None, lang: str = None):
        """可视化看板。旧 token 链接会换取短期 cookie 并重定向到无 token URL。"""
        from i18n import t
        cur_lang = resolve_lang(request, lang_param=lang)
        node = None
        if token:
            node = NODE_TOKEN_MAP.get(token)
            if not node:
                return {"error": t(cur_lang, "auth.invalid_token")}
            session_id = secrets.token_urlsafe(32)
            DASHBOARD_SESSIONS[session_id] = {"node": node, "created_at": time.time()}
            resp = RedirectResponse(url=public_path("/dashboard"), status_code=302)
            resp.set_cookie(
                DASHBOARD_SESSION_COOKIE,
                session_id,
                httponly=True,
                max_age=int(config.get("dashboard_session_ttl_seconds", 3600) or 3600),
                samesite="lax",
                path=PUBLIC_BASE_PATH or "/",
            )
            return resp

        dashboard_session = authenticate_dashboard(request)
        if dashboard_session:
            node = dashboard_session["node"]
        elif authenticate_admin(request):
            node = next(iter(NODE_TOKENS.keys()), "admin")
        else:
            return {"error": t(cur_lang, "error.bad_request", detail="dashboard session required")}

        node_info = NODE_TOKENS[node]

        all_items = read_knowledge_items(config, HUB_DIR)

        dashboard_model = build_dashboard_model(all_items, NODE_TOKENS, datetime.now())
        nodes_counter = dashboard_model["nodes_counter"]
        node_qualities = dashboard_model["node_qualities"]
        topics_counter = dashboard_model["topics_counter"]
        categories_counter = dashboard_model["categories_counter"]
        dates_counter = dashboard_model["dates_counter"]
        quality_ranges = dashboard_model["quality_ranges"]
        last_7 = dashboard_model["last_7"]
        node_activity = dashboard_model["node_activity"]
        recent_items = dashboard_model["recent_items"]
        total = dashboard_model["total"]
        avg_quality = dashboard_model["avg_quality"]
        active_nodes = dashboard_model["active_nodes"]
        total_topics = dashboard_model["total_topics"]
        import html as hm

        # ── 节点卡片 ──
        node_cards = ""
        colors = ["#6366f1", "#8b5cf6", "#a78bfa", "#c4b5fd", "#818cf8", "#4f46e5"]
        for idx, (nn, ni) in enumerate(NODE_TOKENS.items()):
            cnt = nodes_counter.get(nn, 0)
            pct = round(cnt / max(total, 1) * 100, 1)
            aq = round(sum(node_qualities[nn]) / max(len(node_qualities[nn]), 1), 1) if node_qualities[nn] else "-"
            is_me = (nn == node)
            c = "#06b6d4" if is_me else colors[idx % len(colors)]
            tag = '<div class="badge-you">你</div>' if is_me else ''
            card = '''
        <div class="node-card''' + (' active' if is_me else '') + '''">
            <div class="card-head">
                <div class="node-icon" style="background:''' + c + '''">''' + nn[0].upper() + '''</div>
                <div>
                    <div class="node-title">''' + hm.escape(nn) + '''</div>
                    <div class="node-role">''' + ni["role"] + '''</div>
                </div>
                ''' + tag + '''
            </div>
            <div class="card-stats">
                <div class="stat"><span class="stat-v">''' + str(cnt) + '''</span><span class="stat-l">贡献</span></div>
                <div class="stat"><span class="stat-v">''' + str(pct) + '''%</span><span class="stat-l">占比</span></div>
                <div class="stat"><span class="stat-v">''' + str(aq) + '''</span><span class="stat-l">均分</span></div>
                <div class="stat"><span class="stat-v">''' + str(node_activity.get(nn, 0)) + '''</span><span class="stat-l">近7天</span></div>
                <div class="stat"><span class="stat-v">''' + _fmt_num(NODE_QUERY_STATS[nn]['query_count']) + '''</span><span class="stat-l">查询次数</span></div>
                <div class="stat"><span class="stat-v">''' + _fmt_num(NODE_QUERY_STATS[nn]['total_results']) + '''</span><span class="stat-l">返回量</span></div>
            </div>
            <div class="bar"><div class="bar-fill" style="width:''' + str(pct) + '''%;background:linear-gradient(90deg,''' + c + ''',''' + c + '''88)"></div></div>
        </div>'''
            node_cards += card

        # ── 分类柱状图数据（按C01-C07固定顺序） ──
        cat_labels = []
        cat_data = []
        cat_colors = []
        color_map = {
            "行业政策": "#6366f1",
            "新闻资讯": "#06b6d4",
            "金融资本": "#f59e0b",
            "产品方案": "#10b981",
            "技术资料": "#8b5cf6",
            "数据资产": "#ef4444",
            "其他": "#8b949e"
        }
        # 固定顺序：C01行业政策 → C02新闻资讯 → C03金融资本 → C04产品方案 → C05技术资料 → C06数据资产 → C07其他
        fixed_order = ["行业政策", "新闻资讯", "金融资本", "产品方案", "技术资料", "数据资产", "其他"]
        for cat in fixed_order:
            count = categories_counter.get(cat, 0)
            cat_labels.append(cat)
            cat_data.append(count)
            cat_colors.append(color_map.get(cat, "#6366f1"))
        
        cat_labels_str = ",".join('"' + hm.escape(str(l)) + '"' for l in cat_labels)
        cat_data_str = ",".join(str(c) for c in cat_data)
        cat_colors_str = "[" + ",".join('"' + c + '"' for c in cat_colors) + "]"

        # ── 表格 ──
        rows = ""
        for it in recent_items:
            q = it.get("quality", 0)
            qc = "#10b981" if q >= 85 else ("#f59e0b" if q >= 70 else "#ef4444")
            rows += "<tr><td class='r-title'>" + hm.escape(it.get("title", "")) + "</td><td>" + it.get("source_node", "?") + "</td><td><span class='dot' style='background:" + qc + "'></span>" + str(q) + "</td><td class='r-date'>" + hm.escape(it.get("created_at", "")) + "</td></tr>"
        rows = rows or '<tr><td colspan="4" class="empty">暂无数据</td></tr>'

        # ── Chart data ──
        act_labels = ",".join('"' + d[5:] + '"' for d in last_7)
        act_data = ",".join(str(dates_counter.get(d, 0)) for d in last_7)
        qr_labels = ",".join('"' + k + '"' for k in quality_ranges)
        qr_data = ",".join(str(v) for v in quality_ranges.values())
        np_labels = ",".join('"' + k + '"' for k in nodes_counter)
        np_data = ",".join(str(v) for v in nodes_counter.values())

        html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Knowledge Hub 看板</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ─── 主题色 ─── */
:root {
  --bg:#060912;
  --bg2:#0d1117;
  --bg3:#161b22;
  --bg4:#21262d;
  --border:rgba(255,255,255,0.08);
  --t1:#e6edf3;
  --t2:#8b949e;
  --t3:#484f58;
  --accent:#58a6ff;
  --accent2:#1f6feb;
  --green:#3fb950;
  --purple:#bc8cff;
  --orange:#d29922;
  --red:#f85149;
  --teal:#39d353;
}

* { margin:0; padding:0; box-sizing:border-box; }
body {
  background:var(--bg);
  color:var(--t1);
  font-family:'Inter','PingFang SC','Microsoft YaHei',system-ui,sans-serif;
  min-height:100vh;
  background-image:
    radial-gradient(ellipse 80% 50% at 50% -20%, rgba(31,111,235,0.12) 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 100% 80%, rgba(188,140,255,0.06) 0%, transparent 50%);
}

/* ─── topbar ─── */
.topbar {
  background:rgba(13,17,23,0.85);
  border-bottom:1px solid var(--border);
  backdrop-filter:blur(20px);
  -webkit-backdrop-filter:blur(20px);
  padding:0 32px;
  height:64px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  position:sticky;
  top:0;
  z-index:100;
}
.brand { display:flex; align-items:center; gap:14px; }
.logo-img {
  width:36px; height:36px; border-radius:8px;
  object-fit:contain; filter: drop-shadow(0 2px 8px rgba(59,130,246,0.3));
}
.logo {
  width:36px; height:36px;
  border-radius:10px;
  background:linear-gradient(135deg,#1f6feb 0%, #bc8cff 100%);
  display:flex; align-items:center; justify-content:center;
  box-shadow:0 4px 14px rgba(31,111,235,0.4);
}
.topbar h1 { font-size:18px; font-weight:700; letter-spacing:-0.3px; }
.topbar h1 em { color:var(--accent); font-style:normal; }
.meta { display:flex; align-items:center; gap:12px; }
.node-badge {
  background:linear-gradient(135deg,rgba(31,111,235,0.2),rgba(188,140,255,0.15));
  border:1px solid rgba(88,166,255,0.25);
  padding:5px 14px; border-radius:20px;
  font-size:12px; font-weight:600; color:var(--accent);
  letter-spacing:0.3px;
}
.ts { color:var(--t2); font-size:12px; }

/* ─── container ─── */
.container { max-width:1440px; margin:0 auto; padding:32px 32px 60px; }

/* ─── metrics ─── */
.metrics { display:grid; grid-template-columns:repeat(6,1fr); gap:14px; margin-bottom:28px; }
.metric {
  background:var(--bg2);
  border:1px solid var(--border);
  border-radius:14px;
  padding:22px 20px 18px;
  position:relative;
  overflow:hidden;
  transition:all 0.25s ease;
  cursor:default;
}
.metric::before {
  content:''; position:absolute; top:0; left:0; right:0; height:2px;
  background:linear-gradient(90deg,transparent,var(--c),transparent);
  opacity:0.7;
}
.metric:hover {
  transform:translateY(-3px);
  border-color:var(--border-hover,rgba(255,255,255,0.15));
  box-shadow:0 12px 40px rgba(0,0,0,0.4), 0 0 0 1px var(--border-hover,rgba(255,255,255,0.1));
}
.m-icon {
  width:40px; height:40px; border-radius:10px;
  display:flex; align-items:center; justify-content:center;
  font-size:20px; margin-bottom:14px;
  background:rgba(255,255,255,0.04);
  border:1px solid rgba(255,255,255,0.06);
}
.m-val {
  font-size:30px; font-weight:800;
  letter-spacing:-1.5px;
  color:var(--t1);
  line-height:1;
}
.m-label {
  font-size:12px; color:var(--t2);
  margin-top:8px; font-weight:500;
  letter-spacing:0.2px;
}

/* ─── grid ─── */
.grid3 { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:18px; }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:18px; }
.grid4 { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:18px; }

/* ─── panel ─── */
.panel {
  background:var(--bg2);
  border:1px solid var(--border);
  border-radius:16px;
  overflow:hidden;
  min-width:0;
  transition:border-color 0.2s;
}
.panel:hover { border-color:rgba(255,255,255,0.12); }
.panel-head {
  padding:16px 22px;
  border-bottom:1px solid var(--border);
  display:flex; align-items:center; justify-content:space-between;
}
.panel-head h2 { font-size:14px; font-weight:600; color:var(--t1); }
.panel-head h2 span { font-size:12px; color:var(--t2); font-weight:400; margin-left:8px; }
.panel-body { padding:20px 22px; }

/* ─── node cards ─── */
.node-card {
  background:rgba(255,255,255,0.02);
  border:1px solid rgba(255,255,255,0.06);
  border-radius:12px; padding:16px;
  margin-bottom:10px;
  transition:all 0.2s ease;
}
.node-card:last-child { margin-bottom:0; }
.node-card:hover {
  background:rgba(255,255,255,0.04);
  border-color:rgba(255,255,255,0.1);
  transform:translateX(2px);
}
.node-card.active {
  border-color:rgba(88,166,255,0.35);
  background:rgba(88,166,255,0.04);
}
.card-head { display:flex; align-items:center; gap:12px; margin-bottom:14px; position:relative; }
.node-icon {
  width:40px; height:40px; border-radius:10px;
  display:flex; align-items:center; justify-content:center;
  font-size:16px; font-weight:700; color:#fff;
  flex-shrink:0;
  box-shadow:0 2px 8px rgba(0,0,0,0.3);
}
.node-title { font-size:14px; font-weight:600; }
.node-role { font-size:11px; color:var(--t3); text-transform:uppercase; letter-spacing:0.5px; }
.badge-you {
  position:absolute; right:0; top:50%; transform:translateY(-50%);
  background:linear-gradient(135deg,#1f6feb,#58a6ff);
  padding:3px 10px; border-radius:6px;
  font-size:10px; font-weight:700; letter-spacing:0.5px; color:#fff;
}
.card-stats { display:grid; grid-template-columns:repeat(6,1fr); gap:8px; margin-bottom:12px; }
.stat { text-align:center; }
.stat-v { font-size:15px; font-weight:700; display:block; color:var(--t1); }
.stat-l { font-size:10px; color:var(--t3); text-transform:uppercase; letter-spacing:0.3px; margin-top:2px; }
.bar { height:4px; background:rgba(255,255,255,0.06); border-radius:2px; overflow:hidden; }
.bar-fill { height:100%; border-radius:2px; }

/* ─── chart ─── */
.chart-wrap { position:relative; height:220px; }

/* ─── table ─── */
.r-table { width:100%; border-collapse:collapse; }
.r-table th {
  text-align:left; padding:10px 12px;
  font-size:11px; color:var(--t3); font-weight:600;
  text-transform:uppercase; letter-spacing:0.5px;
  border-bottom:1px solid var(--border);
}
.r-table td { padding:12px; font-size:13px; border-bottom:1px solid rgba(255,255,255,0.03); }
.r-table tr:hover td { background:rgba(255,255,255,0.02); }
.r-title { font-weight:500; max-width:320px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.r-date { color:var(--t3); font-size:12px; }
.dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:6px; }
.empty { color:var(--t3); text-align:center; padding:32px !important; }

/* ─── tags ─── */
.tags { display:flex; flex-wrap:wrap; gap:6px; }
.tag {
  background:rgba(255,255,255,0.04);
  border:1px solid rgba(255,255,255,0.08);
  padding:5px 12px; border-radius:6px;
  font-size:12px; color:var(--t2);
}

/* ─── footer ─── */
.footer {
  text-align:center; padding:20px;
  color:var(--t3); font-size:11px;
  border-top:1px solid var(--border);
  letter-spacing:0.3px;
}

/* ─── glow effect on metric ─── */
.metric:nth-child(1) { --c:var(--accent2); }
.metric:nth-child(2) { --c:var(--purple); }
.metric:nth-child(3) { --c:var(--green); }
.metric:nth-child(4) { --c:var(--orange); }
.metric:nth-child(5) { --c:var(--teal); }
.metric:nth-child(6) { --c:#f97316; }

/* ─── refresh button ─── */
.refresh-btn {
  background:rgba(255,255,255,0.05);
  border:1px solid var(--border);
  color:var(--t2);
  padding:6px 16px;
  border-radius:8px;
  font-size:12px;
  cursor:pointer;
  transition:all 0.2s;
  text-decoration:none;
}
.refresh-btn:hover { background:rgba(255,255,255,0.08); color:var(--t1); }

@media (max-width:1100px) {
  .metrics { grid-template-columns:repeat(3,1fr); }
}
@media (max-width:768px) {
  .metrics { grid-template-columns:repeat(2,1fr); }
  .grid2, .grid3, .grid4 { grid-template-columns:1fr; }
  .container { padding:16px; }
  .topbar { padding:0 16px; }
  .card-stats { grid-template-columns:repeat(3,1fr); }
}
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    <img src="/static/logo.png" class="logo-img" alt="Knowledge Hub">
    <h1>Knowledge <em>Hub</em></h1>
  </div>
  <div class="meta">
    <div class="node-badge">&#128205; """ + node + """</div>
    <div class="ts">""" + datetime.now().strftime("%Y-%m-%d %H:%M") + """ 更新</div>
  </div>
</div>

<div class="container">

<div class="metrics">
  <div class="metric"><div class="m-icon">&#128218;</div><div class="m-val">""" + _fmt_num(total) + """</div><div class="m-label">知识总量</div></div>
  <div class="metric"><div class="m-icon">&#127760;</div><div class="m-val">""" + _fmt_num(active_nodes) + """</div><div class="m-label">活跃节点</div></div>
  <div class="metric"><div class="m-icon">&#11088;</div><div class="m-val">""" + str(avg_quality) + """</div><div class="m-label">平均质量</div></div>
  <div class="metric"><div class="m-icon">&#127991;</div><div class="m-val">""" + str(len(categories_counter)) + """</div><div class="m-label">分类覆盖</div></div>
  <div class="metric"><div class="m-icon">&#128269;</div><div class="m-val">""" + _fmt_num(sum(NODE_QUERY_STATS[n]['query_count'] for n in NODE_QUERY_STATS)) + """</div><div class="m-label">查询次数</div></div>
  <div class="metric"><div class="m-icon">&#128228;</div><div class="m-val">""" + _fmt_num(sum(NODE_QUERY_STATS[n]['total_results'] for n in NODE_QUERY_STATS)) + """</div><div class="m-label">总返回量</div></div>
</div>

<div class="grid3">
  <div class="panel">
    <div class="panel-head"><h2>&#128202; 节点贡献</h2></div>
    <div class="panel-body">""" + node_cards + """</div>
  </div>
  <div class="panel">
    <div class="panel-head"><h2>&#128336; 最近入库</h2></div>
    <div class="panel-body" style="padding:0;overflow-x:auto;">
      <table class="r-table">
        <thead><tr><th>{_col_title}</th><th>来源</th><th>{_col_quality}</th><th>{_col_time}</th></tr></thead>
        <tbody>""" + rows + """</tbody>
      </table>
    </div>
  </div>
</div>

<div class="grid2">
  <div class="panel">
    <div class="panel-head"><h2>&#127991; 分类分布</h2></div>
    <div class="panel-body"><div class="chart-wrap"><canvas id="topicChart"></canvas></div></div>
  </div>
  <div class="panel">
    <div class="panel-head"><h2>&#127919; 质量分布</h2></div>
    <div class="panel-body"><div class="chart-wrap"><canvas id="qualChart"></canvas></div></div>
  </div>
</div>

<div class="grid2">
  <div class="panel">
    <div class="panel-head"><h2>&#129376; 节点占比</h2></div>
    <div class="panel-body"><div class="chart-wrap"><canvas id="pieChart"></canvas></div></div>
  </div>
  <div class="panel">
    <div class="panel-head"><h2>&#128200; 近7天活跃度</h2></div>
    <div class="panel-body"><div class="chart-wrap"><canvas id="actChart"></canvas></div></div>
  </div>
</div>

<div class="grid2">
  <div class="panel">
    <div class="panel-head"><h2>&#128269; 节点查询量</h2></div>
    <div class="panel-body"><div class="chart-wrap"><canvas id="queryChart"></canvas></div></div>
  </div>
  <div class="panel">
    <div class="panel-head"><h2>&#128202; 节点返回量</h2></div>
    <div class="panel-body"><div class="chart-wrap"><canvas id="resultChart"></canvas></div></div>
  </div>
</div>

</div>

<div class="footer">Knowledge Hub v1.0 · Powered by Domi</div>

<script>
Chart.defaults.color = '#9ca3af';
Chart.defaults.borderColor = 'rgba(255,255,255,0.06)';

new Chart(document.getElementById('actChart'), {
  type: 'line',
  data: {
    labels: [""" + act_labels + """],
    datasets: [{
      data: [""" + act_data + """],
      borderColor: '#6366f1',
      backgroundColor: 'rgba(99,102,241,0.12)',
      fill: true, tension: 0.4,
      pointBackgroundColor: '#6366f1', pointBorderColor: '#fff',
      pointBorderWidth: 1, pointRadius: 4
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { stepSize: 1 } } }
  }
});

new Chart(document.getElementById('qualChart'), {
  type: 'doughnut',
  data: {
    labels: [""" + qr_labels + """],
    datasets: [{
      data: [""" + qr_data + """],
      backgroundColor: ['#ef4444','#f59e0b','#10b981'],
      borderWidth: 0, hoverOffset: 8
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    cutout: '65%',
    plugins: { legend: { position: 'bottom', labels: { padding: 16, usePointStyle: true, pointStyle: 'circle' } } }
  }
});

new Chart(document.getElementById('topicChart'), {
  type: 'bar',
  data: {
    labels: [""" + cat_labels_str + """],
    datasets: [{
      data: [""" + cat_data_str + """],
      backgroundColor: """ + cat_colors_str + """,
      borderRadius: 6, borderSkipped: false
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { stepSize: 1 } },
      y: { grid: { display: false } }
    }
  }
});

new Chart(document.getElementById('pieChart'), {
  type: 'doughnut',
  data: {
    labels: [""" + np_labels + """],
    datasets: [{
      data: [""" + np_data + """],
      backgroundColor: ['#6366f1','#8b5cf6','#06b6d4','#10b981','#f59e0b','#ef4444'],
      borderWidth: 0, hoverOffset: 8
    }]
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    cutout: '60%',
    plugins: { legend: { position: 'bottom', labels: { padding: 16, usePointStyle: true, pointStyle: 'circle' } } }
  }
});

// 节点查询量
new Chart(document.getElementById('queryChart'), {
  type: 'bar',
  data: {
    labels: [""" + ",".join('"' + hm.escape(n) + '"' for n in NODE_QUERY_STATS.keys()) + """],
    datasets: [{ label: '查询次数', data: [""" + ",".join(str(NODE_QUERY_STATS[n]['query_count']) for n in NODE_QUERY_STATS) + """], backgroundColor: '#6366f1' }]
  },
  options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: { legend: { display: false } } }
});

// 节点返回量
new Chart(document.getElementById('resultChart'), {
  type: 'bar',
  data: {
    labels: [""" + ",".join('"' + hm.escape(n) + '"' for n in NODE_QUERY_STATS.keys()) + """],
    datasets: [{ label: '返回量', data: [""" + ",".join(str(NODE_QUERY_STATS[n]['total_results']) for n in NODE_QUERY_STATS) + """], backgroundColor: '#06b6d4' }]
  },
  options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: { legend: { display: false } } }
});
</script>
</body></html>"""
        html = prepare_html_for_public_base(html)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

    # ── 管理后台 ───────────────────────────────────────────────
    @app.get("/admin")
    def admin_panel(request: Request = None, lang: str = None):
        from fastapi.responses import HTMLResponse  # noqa: F401
        from i18n import t
        """管理后台：知识条目管理 + 节点管理 + 审计日志"""
        cur_lang = resolve_lang(request, lang_param=lang)
        cookie_lang = request.cookies.get("lang") if request else None
        if cookie_lang:
            cur_lang = resolve_lang(request, lang_param=cookie_lang)

        # Session cookie 认证
        session = authenticate_admin(request)
        if not session:
            # 未登录，返回登录表单
            login_html = (ADMIN_LOGIN_HTML
                          .replace("__REDIRECT__", public_path("/admin"))
                          .replace("__ERR_MSG__", ""))
            login_html = prepare_html_for_public_base(login_html)
            return HTMLResponse(login_html, status_code=401)

        admin_user = session["username"]
        admin_token = ""  # 不再使用 token

        import html as hm
        all_items = read_knowledge_items(config, HUB_DIR)

        categories = ["行业政策","新闻资讯","金融资本","产品方案","技术资料","数据资产","其他"]
        nodes = list(NODE_TOKENS.keys())
        node_opts = "".join(f'<option value="{n}">{n}</option>' for n in nodes)
        cat_opts  = "".join(f'<option value="{c}">{c}</option>' for c in categories)

        # ── i18n 翻译变量 ──
        L = lambda k: t(cur_lang, k)
        _panel_title = L("admin.panel")
        _tab_items = L("admin.tabs_items")
        _tab_nodes = L("admin.tabs_nodes")
        _tab_log = L("admin.tabs_log")
        _filter_title = L("admin.filter")
        _search_ph = L("knowledge.search_placeholder")
        _all_nodes = L("knowledge.all_nodes")
        _all_quality = L("knowledge.all_quality")
        _all_cats = L("knowledge.all_categories")
        _col_title = L("knowledge.col_title")
        _col_category = L("knowledge.col_category")
        _col_quality = L("knowledge.col_quality")
        _col_node = L("knowledge.col_node")
        _col_ingested = L("knowledge.col_ingested")
        _col_actions = L("knowledge.col_actions")
        _node_list = L("admin.node_list")
        _add_node_btn = L("admin.add_node_btn")
        _col_name = L("admin.col_name")
        _col_role = L("admin.col_role")
        _col_token = L("admin.col_token")
        _col_desc = L("admin.col_desc")
        _col_query_count = L("admin.col_query_count")
        _audit_title = L("admin.audit_title")
        _col_time = L("admin.col_time")
        _col_action = L("admin.col_action")
        _col_details = L("admin.col_details")
        _view_item = L("knowledge.view_item")
        _edit_title_label = L("knowledge.edit_title_label")
        _edit_category_label = L("knowledge.edit_category_label")
        _edit_quality_label = L("knowledge.edit_quality_label")
        _edit_node_label = L("knowledge.edit_node_label")
        _edit_tags_label = L("knowledge.edit_tags_label")
        _edit_tags_ph = L("knowledge.edit_tags_placeholder")
        _edit_url_label = L("knowledge.edit_url_label")
        _edit_url_ph = L("knowledge.edit_url_placeholder")
        _edit_summary_label = L("knowledge.edit_summary_label")
        _edit_created = L("knowledge.edit_created")
        _edit_updated = L("knowledge.edit_updated")
        _save = L("common.save")
        _delete = L("common.delete")
        _view = L("common.view")
        _edit = L("common.edit")
        _cancel = L("common.cancel")
        _submit = L("common.submit")
        _reset = L("common.reset")
        _all = L("knowledge.all_categories")
        _loading = L("common.loading")
        _no_data = L("common.no_data")
        _not_found = L("knowledge.not_found")
        _view_edit_title = L("knowledge.view_edit_title")
        _save_failed = L("knowledge.save_failed")
        _save_success = L("knowledge.save_success")
        _delete_success = L("knowledge.delete_success")
        _delete_confirm = L("knowledge.delete_confirm")
        _reset_confirm = L("admin.reset_token_confirm")
        _role_admin = L("admin.role_admin")
        _role_writer = L("admin.role_writer")
        _role_reader = L("admin.role_reader")
        _new_node_name = L("admin.new_node_name")
        _new_node_name_ph = L("admin.new_node_name_placeholder")
        _new_node_role = L("admin.new_node_role")
        _new_node_desc = L("admin.new_node_desc")
        _node_desc_ph = L("admin.node_desc_placeholder")
        _current_user = L("admin.current_user")
        _add_node = L("admin.add_node")
        _lang = L("common.language")
        lang_zh_url = public_path("/lang?lang=zh&redirect=/admin")
        lang_en_url = public_path("/lang?lang=en&redirect=/admin")
        admin_logout_url = public_path("/admin/logout")

        html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_panel_title}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0d1117;--bg2:#161b22;--bg3:#21262d;--border:rgba(255,255,255,0.08);
  --t1:#e6edf3;--t2:#8b949e;--accent:#58a6ff;--green:#3fb950;--red:#f85149;--orange:#d29922;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter','PingFang SC',system-ui,sans-serif;background:var(--bg);color:var(--t1);
  min-height:100vh;font-size:14px;}}
.topbar{{background:rgba(22,27,34,0.95);border-bottom:1px solid var(--border);
  padding:0 28px;height:56px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;}}
.topbar h1{{font-size:17px;font-weight:700;}}
.topbar h1 em{{color:var(--accent);font-style:normal;}}
.brand{{display:flex;align-items:center;gap:12px;}}
.logo-img{{width:32px;height:32px;border-radius:8px;object-fit:contain;
  filter:drop-shadow(0 2px 6px rgba(59,130,246,0.25));}}
.lang-switcher{{display:flex;gap:6px;}}
.lang-btn{{padding:4px 10px;border-radius:6px;background:var(--bg3);color:var(--t2);
  text-decoration:none;font-size:12px;font-weight:600;transition:all 0.15s;}}
.lang-btn:hover{{color:var(--t1);}}
.lang-btn.active{{background:var(--accent);color:#fff;}}
.tab-bar{{background:var(--bg2);border-bottom:1px solid var(--border);padding:0 28px;display:flex;gap:4px;}}
.tab{{padding:10px 20px;cursor:pointer;border-bottom:2px solid transparent;color:var(--t2);
  font-size:13px;font-weight:500;transition:all 0.15s;}}
.tab:hover{{color:var(--t1);}}
.tab.active{{color:var(--accent);border-color:var(--accent);}}
.container{{max-width:1400px;margin:0 auto;padding:24px 28px;}}
.panel{{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
  margin-bottom:16px;overflow:hidden;}}
.panel-head{{padding:14px 20px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;gap:12px;}}
.panel-head h2{{font-size:14px;font-weight:600;}}
.panel-body{{padding:16px 20px;}}
.toolbar{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}}
.search-box{{flex:1;min-width:200px;display:flex;align-items:center;
  background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:0 12px;}}
.search-box input{{background:transparent;border:none;outline:none;color:var(--t1);
  padding:8px 0;width:100%;font-size:13px;}}
.search-box input::placeholder{{color:var(--t2);}}
select{{background:var(--bg3);border:1px solid var(--border);border-radius:8px;
  color:var(--t1);padding:7px 12px;font-size:13px;outline:none;}}
.btn{{padding:7px 16px;border-radius:8px;border:none;cursor:pointer;
  font-size:13px;font-weight:500;transition:all 0.15s;}}
.btn-primary{{background:var(--accent);color:#fff;}}
.btn-primary:hover{{background:#79b8ff;}}
.btn-danger{{background:rgba(248,81,73,0.15);color:var(--red);border:1px solid rgba(248,81,73,0.3);}}
.btn-danger:hover{{background:rgba(248,81,73,0.25);}}
.btn-sm{{padding:4px 10px;font-size:12px;}}
.table-wrap{{overflow-x:auto;}}
table{{width:100%;border-collapse:collapse;}}
th{{text-align:left;padding:10px 14px;font-size:11px;color:var(--t2);font-weight:600;
  text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid var(--border);
  white-space:nowrap;}}
td{{padding:10px 14px;border-bottom:1px solid rgba(255,255,255,0.03);vertical-align:middle;}}
tr:hover td{{background:rgba(255,255,255,0.02);}}
.t-title{{max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-weight:500;}}
.t-title a{{color:var(--accent);text-decoration:none;}}
.t-title a:hover{{text-decoration:underline;}}
.badge{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;}}
.badge-green{{background:rgba(63,185,80,0.15);color:var(--green);}}
.badge-orange{{background:rgba(210,153,34,0.15);color:var(--orange);}}
.badge-red{{background:rgba(248,81,73,0.15);color:var(--red);}}
.badge-blue{{background:rgba(88,166,255,0.15);color:var(--accent);}}
.t-date{{color:var(--t2);font-size:12px;white-space:nowrap;}}
.t-actions{{display:flex;gap:6px;white-space:nowrap;}}
.pager{{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px;
  border-top:1px solid var(--border);}}
.pager button{{padding:6px 14px;border-radius:6px;border:1px solid var(--border);
  background:var(--bg3);color:var(--t1);cursor:pointer;font-size:13px;}}
.pager button:hover{{border-color:var(--accent);color:var(--accent);}}
.pager button:disabled{{opacity:0.4;cursor:default;}}
.pager span{{color:var(--t2);font-size:13px;}}
.empty-row td{{text-align:center;padding:32px;color:var(--t2);}}
.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);
  z-index:200;align-items:center;justify-content:center;padding:20px;}}
.modal.show{{display:flex;}}
.modal-box{{background:var(--bg2);border:1px solid var(--border);border-radius:14px;
  width:100%;max-width:640px;max-height:90vh;overflow-y:auto;}}
.modal-head{{padding:16px 20px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;}}
.modal-head h3{{font-size:15px;font-weight:600;}}
.modal-close{{background:transparent;border:none;color:var(--t2);cursor:pointer;
  font-size:20px;line-height:1;padding:4px;}}
.modal-close:hover{{color:var(--t1);}}
.modal-body{{padding:20px;}}
.form-group{{margin-bottom:14px;}}
.form-group label{{display:block;font-size:12px;color:var(--t2);margin-bottom:6px;
  font-weight:500;text-transform:uppercase;letter-spacing:0.3px;}}
.form-group input,.form-group textarea,.form-group select{{
  width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:8px;
  color:var(--t1);padding:8px 12px;font-size:13px;outline:none;}}
.form-group textarea{{resize:vertical;min-height:80px;}}
.form-group input:focus,.form-group textarea:focus,.form-group select:focus{{
  border-color:var(--accent);}}
.form-row{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
.modal-foot{{padding:14px 20px;border-top:1px solid var(--border);
  display:flex;justify-content:flex-end;gap:8px;}}
.log-table td{{font-size:12px;}}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <img src="/static/logo.png" class="logo-img" alt="Knowledge Hub">
    <h1>Knowledge <em>Hub</em> 管理后台</h1>
  </div>
  <span style="font-size:12px;color:var(--t2)">&#128101; {hm.escape(admin_user)}</span>
  <div class="lang-switcher">
    <a href="{lang_zh_url}" class="lang-btn {('active' if cur_lang=='zh' else '')}">中</a>
    <a href="{lang_en_url}" class="lang-btn {('active' if cur_lang=='en' else '')}">EN</a>
    <a href="{admin_logout_url}" class="lang-btn" style="margin-left:8px;color:#ef4444">&#128682; 退出</a>
  </div>
</div>
<div class="tab-bar">
  <div class="tab active" onclick=\"showTab('items')\" data-tab=\"items\">&#128218; {_tab_items}</div>
  <div class="tab" onclick=\"showTab('nodes')\" data-tab=\"nodes\">&#128101; {_tab_nodes}</div>
  <div class="tab" onclick=\"showTab('log')\" data-tab=\"log\">&#128203; {_tab_log}</div>
</div>
<div class="container">

  <div id=\"tab-items\">
    <div class=\"panel\">
      <div class=\"panel-head\">
        <h2>{_filter_title}</h2>
        <div class=\"toolbar\">
          <div class=\"search-box\">
            <input type=\"text\" id=\"searchInput\" placeholder=\"{_search_ph}\" oninput=\"debounceSearch()\">
          </div>
          <select id=\"catFilter\" onchange=\"loadItems(1)\">
            <option value=\"\">{_all_cats}</option>
            {cat_opts}
          </select>
          <select id=\"nodeFilter\" onchange=\"loadItems(1)\">
            <option value=\"\">{_all_nodes}</option>
            {node_opts}
          </select>
          <select id=\"qualFilter\" onchange=\"loadItems(1)\">
            <option value=\"\">{_all_quality}</option>
            <option value=\"85\">\u2b50 \u2265 85</option>
            <option value=\"70\">\u2b50 \u2265 70</option>
            <option value=\"60\">\u2b50 \u2265 60</option>
          </select>
          <span style=\"font-size:12px;color:var(--t2)\" id=\"totalSpan\"></span>
        </div>
      </div>
      <div class=\"table-wrap\">
        <table>
          <thead><tr>
            <th>{_col_title}</th><th>{_col_category}</th><th>{_col_quality}</th><th>{_col_node}</th><th>{_col_ingested}</th><th>{_col_actions}</th>
          </tr></thead>
          <tbody id=\"itemsBody\"></tbody>
        </table>
      </div>
      <div class=\"pager\">
        <button id=\"prevBtn\" onclick=\"changePage(-1)\">\u2190 上一页</button>
        <span id=\"pageInfo\"></span>
        <button id=\"nextBtn\" onclick=\"changePage(1)\">下一页 \u2192</button>
      </div>
    </div>
  </div>

  <div id=\"tab-nodes\" style=\"display:none\">
    <div class=\"panel\">
      <div class=\"panel-head\">
        <h2>{_node_list}</h2>
        <button class=\"btn btn-primary\" onclick=\"addNode()\">{_add_node_btn}</button>
      </div>
      <div class=\"panel-body\">
        <table>
          <thead><tr><th>{_col_name}</th><th>{_col_role}</th><th>{_col_token}</th><th>{_col_desc}</th><th>{_col_query_count}</th><th>{_col_actions}</th></tr></thead>
          <tbody id=\"nodesBody\"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div id=\"tab-log\" style=\"display:none\">
    <div class=\"panel\">
      <div class=\"panel-head\">
        <h2>{_audit_title}</h2>
        <span style=\"font-size:12px;color:var(--t2)\">logs/audit.log</span>
      </div>
      <div class=\"panel-body table-wrap\">
        <table>
          <thead><tr><th>{_col_time}</th><th>{_col_node}</th><th>{_col_action}</th><th>{_col_details}</th></tr></thead>
          <tbody id=\"logBody\"></tbody>
        </table>
        <div class=\"pagination\" id=\"logPagination\"></div>
      </div>
    </div>
  </div>

</div>

<div class=\"modal\" id=\"itemModal\">
  <div class=\"modal-box\">
    <div class=\"modal-head\">
      <h3 id=\"modalTitle\">{_view_item}</h3>
      <button class=\"modal-close\" onclick=\"closeModal()\">\u00d7</button>
    </div>
    <div class=\"modal-body\">
      <input type=\"hidden\" id=\"editId\">
      <div class=\"form-row\">
        <div class=\"form-group\">
          <label>标题</label>
          <input type=\"text\" id=\"editTitle\">
        </div>
        <div class=\"form-group\">
          <label>分类</label>
          <select id=\"editCategory\">
            {cat_opts}
          </select>
        </div>
      </div>
      <div class=\"form-group\">
        <label>摘要</label>
        <textarea id=\"editSummary\"></textarea>
      </div>
      <div class=\"form-row\">
        <div class=\"form-group\">
          <label>质量分</label>
          <input type=\"number\" id=\"editQuality\" min=\"0\" max=\"100\">
        </div>
        <div class=\"form-group\">
          <label>{_edit_tags_label}</label>
          <input type=\"text\" id=\"editTopics\" placeholder=\"{_edit_tags_ph}\">
        </div>
      </div>
      <div class=\"form-group\">
        <label>{_edit_url_label}</label>
        <input type=\"text\" id=\"editUrl\" placeholder=\"{_edit_url_ph}\">
      </div>
      <div class=\"form-group\">
        <label>来源</label>
        <input type=\"text\" id=\"editSource\">
      </div>
    </div>
    <div class=\"modal-foot\">
      <button class=\"btn btn-danger\" onclick=\"deleteItem()\" id=\"delBtn\">{_delete}</button>
      <button class=\"btn btn-primary\" onclick=\"saveItem()\">{_save}</button>
    </div>
  </div>
</div>

<div class=\"modal\" id=\"nodeModal\">
  <div class=\"modal-box\">
    <div class=\"modal-head\">
      <h3>{_add_node}</h3>
      <button class=\"modal-close\" onclick=\"closeNodeModal()\">\u00d7</button>
    </div>
    <div class=\"modal-body\">
      <div class=\"form-row\">
        <div class=\"form-group\">
          <label>{_new_node_name}</label>
          <input type=\"text\" id=\"newNodeName\" placeholder=\"{_new_node_name_ph}\">
        </div>
        <div class=\"form-group\">
          <label>角色</label>
          <select id=\"newNodeRole\">
            <option value=\"reader\">{_role_reader}</option>
            <option value=\"writer\">{_role_writer}</option>
            <option value=\"admin\">{_role_admin}</option>
          </select>
        </div>
      </div>
      <div class=\"form-group\">
        <label>描述（可选）</label>
        <input type=\"text\" id=\"newNodeDesc\" placeholder=\"{_node_desc_ph}\">
      </div>
    </div>
    <div class=\"modal-foot\">
      <button class=\"btn\" onclick=\"closeNodeModal()\">{_cancel}</button>
      <button class=\"btn btn-primary\" onclick=\"createNode()\">\u2705 创建</button>
    </div>
  </div>
</div>

<script>
const BASE = window.location.origin;
let allItems = [];
let filteredItems = [];
let page = 1;
const PAGE_SIZE = 20;
let totalItems = 0;
let debounceTimer = null;

async function api(method, path, body=null) {{
  let opts = {{method, credentials: 'include', headers: {{}}}};
  if (body) {{opts.body = JSON.stringify(body);opts.headers['Content-Type']='application/json';}}
  let r = await fetch(BASE + path, opts);
  if (!r.ok) {{let e = await r.text();alert('API错误 [' + r.status + ']: ' + e);throw e;}}
  return r.json();
}}

async function loadItems(p=1) {{
  page = p;
  let q = document.getElementById('searchInput').value;
  let cat = document.getElementById('catFilter').value;
  let node = document.getElementById('nodeFilter').value;
  let qual = parseInt(document.getElementById('qualFilter').value) || 0;
  let params = new URLSearchParams({{q, category:cat, node, min_quality:String(qual), page:String(page), size:String(PAGE_SIZE)}});
  let data = await api('GET', '/admin/items?' + params.toString());
  filteredItems = data.items || [];
  allItems = filteredItems;
  totalItems = data.total || 0;
  document.getElementById('totalSpan').textContent = `共 ${{totalItems}} 条`;
  renderItems();
}}

function renderItems() {{
  let slice = filteredItems;
  let tbody = document.getElementById('itemsBody');
  if (!slice.length) {{
    tbody.innerHTML = '<tr class=\"empty-row\"><td colspan=\"6\">暂无数据</td></tr>';
    document.getElementById('pageInfo').textContent = '';
    return;
  }}
  tbody.innerHTML = slice.map(i => {{
    let q = i.quality||0;
    let qc = q>=85?'badge-green':q>=70?'badge-orange':'badge-red';
    let cat = i.category||'其他';
    let catColor = {{'行业政策':'badge-blue','新闻资讯':'badge-green','金融资本':'badge-orange',
      '产品方案':'badge-blue','技术资料':'badge-blue','数据资产':'badge-red'}}[cat]||'badge-red';
    return `<tr>
      <td class=\"t-title\" title=\"${{i.title||''}}\">${{i.title||'?'}}</td>
      <td><span class=\"badge ${{catColor}}\">${{cat}}</span></td>
      <td><span class=\"badge ${{qc}}\">${{q}}</span></td>
      <td style=\"color:var(--t2);font-size:12px\">${{i.source_node||'?'}}</td>
      <td class=\"t-date\">${{i.created_at||''}}</td>
      <td class=\"t-actions\">
        <button class=\"btn btn-sm btn-primary\" onclick=\"viewItem('${{i.id}}')\">{_view}</button>
        <button class=\"btn btn-sm btn-danger\" onclick=\"deleteItemConfirm('${{i.id}}')\">删除</button>
      </td>
    </tr>`;
  }}).join('');
  let totalPages = Math.ceil(totalItems / PAGE_SIZE);
  document.getElementById('pageInfo').textContent = `第 ${{page}} / ${{totalPages||1}} 页`;
  document.getElementById('prevBtn').disabled = page <= 1;
  document.getElementById('nextBtn').disabled = page >= totalPages;
}}

function changePage(dir) {{
  let totalPages = Math.ceil(totalItems / PAGE_SIZE);
  let newPage = page + dir;
  if (newPage < 1 || newPage > totalPages) return;
  loadItems(newPage);
}}

function debounceSearch() {{
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => loadItems(1), 300);
}}

function viewItem(id) {{
  let i = allItems.find(x => x.id === id);
  if (!i) {{alert('{_not_found}');return;}}
  document.getElementById('editId').value = id;
  document.getElementById('editTitle').value = i.title||'';
  document.getElementById('editSummary').value = i.summary||'';
  document.getElementById('editCategory').value = i.category||'其他';
  document.getElementById('editQuality').value = i.quality||0;
  document.getElementById('editTopics').value = (i.topics||[]).join(', ');
  document.getElementById('editUrl').value = i.url||'';
  document.getElementById('editSource').value = i.source||'';
  document.getElementById('modalTitle').textContent = '{_view_edit_title}';
  document.getElementById('delBtn').style.display = '';
  document.getElementById('itemModal').classList.add('show');
}}

async function saveItem() {{
  let id = document.getElementById('editId').value;
  let topics = document.getElementById('editTopics').value.split(',').map(t=>t.trim()).filter(Boolean);
  let i = allItems.find(x => x.id === id);
  if (!i) {{alert('{_not_found}');return;}}
  let updated = {{
    ...i,
    title: document.getElementById('editTitle').value,
    summary: document.getElementById('editSummary').value,
    category: document.getElementById('editCategory').value,
    quality: parseInt(document.getElementById('editQuality').value)||0,
    topics: topics,
    url: document.getElementById('editUrl').value,
    source: document.getElementById('editSource').value,
  }};
  try {{
    await api('PUT', '/admin/item/' + encodeURIComponent(id), updated);
    allItems = allItems.map(x => x.id===id ? {{...x,...updated}} : x);
    closeModal();
    loadItems(page);
  }} catch(e) {{alert('{_save_failed}');}}
}}

async function deleteItemConfirm(id) {{
  if (!confirm('确定删除这条知识？')) return;
  await api('DELETE', '/admin/item/' + encodeURIComponent(id));
  allItems = allItems.filter(x => x.id !== id);
  closeModal();
  loadItems(page);
}}

function closeModal() {{document.getElementById('itemModal').classList.remove('show');}}

async function loadNodes() {{
  let nodes = await api('GET', '/tokens');
  let stats = await api('GET', '/node-stats');
  let statMap = {{}};
  (stats.nodes||[]).forEach(n => {{statMap[n.node] = n.query_count;}});
  let colors = ['#6366f1','#8b5cf6','#06b6d4','#10b981','#f59e0b','#ef4444'];
  document.getElementById('nodesBody').innerHTML = Object.entries(nodes).map(([name,info],idx) => `
    <tr>
      <td><span style=\"display:inline-block;width:10px;height:10px;border-radius:50%;background:${{colors[idx%colors.length]}};margin-right:8px\"></span>${{name}}</td>
      <td><span class=\"badge badge-blue\">${{info.role}}</span></td>
      <td><code style=\"font-size:11px;color:var(--t2)\">${{info.token}}</code></td>
      <td style=\"color:var(--t2);font-size:12px\">${{info.description||''}}</td>
      <td style=\"text-align:center\">${{statMap[name]||0}}</td>
      <td>
        <button class=\"btn btn-sm btn-danger\" onclick=\"resetToken('${{name}}')\">&#128260; 重置Token</button>
      </td>
    </tr>`).join('');
}}

function addNode() {{document.getElementById('nodeModal').classList.add('show');}}
function closeNodeModal() {{document.getElementById('nodeModal').classList.remove('show');}}

async function createNode() {{
  let name = document.getElementById('newNodeName').value.trim();
  let role = document.getElementById('newNodeRole').value;
  let desc = document.getElementById('newNodeDesc').value;
  if (!name) {{alert('请输入节点名称');return;}}
  try {{
    await api('POST', '/admin/node', {{name, role, description:desc}});
    closeNodeModal();
    loadNodes();
  }} catch(e) {{alert('创建失败');}}
}}

async function resetToken(nodeName) {{
  if (!confirm(`确定重置 ${{nodeName}} 的 Token？旧 Token 将失效。`)) return;
  try {{
    let data = await api('POST', '/admin/node/' + encodeURIComponent(nodeName) + '/reset-token');
    alert('新 Token: ' + data.token);
    loadNodes();
  }} catch(e) {{alert('重置失败');}}
}}

async function loadLog() {{
  try {{
    let r = await fetch(BASE + '/admin/log', {{credentials: 'include'}});
    let lines = await r.text();
    let rows = lines.trim().split('\\n').slice(-50).reverse();
    document.getElementById('logBody').innerHTML = rows.map(line => {{
      let parts = line.match(/^([^\\s]+)\\s\\[([^\\]]+)\\]\\sAUDIT\\s\\|\\snode=([^\\s]+)\\s\\|\\saction=([^\\s]+)\\s\\|\\s(.+)$/);
      if (!parts) return `<tr><td colspan=\"4\" style=\"color:var(--t2);font-size:12px\">${{line}}</td></tr>`;
      return `<tr>
        <td class=\"t-date\">${{parts[1]}}</td>
        <td style=\"color:var(--accent)\">${{parts[3]}}</td>
        <td><span class=\"badge badge-orange\">${{parts[4]}}</span></td>
        <td style=\"color:var(--t2);font-size:12px\">${{parts[5]}}</td>
      </tr>`;
    }}).join('');
  }} catch(e) {{
    document.getElementById('logBody').innerHTML = '<tr><td colspan=\"4\" style=\"color:var(--red)\">{_loading}</td></tr>';
  }}
}}

function showTab(name) {{
  var tabs=document.querySelectorAll('.tab');for(var i=0;i<tabs.length;i++)tabs[i].classList.remove('active');
  var tabs2=document.querySelectorAll('.tab');for(var j=0;j<tabs2.length;j++){{
    if(tabs2[j].getAttribute('data-tab')===name)tabs2[j].classList.add('active');
  }}
  document.getElementById('tab-items').style.display = name==='items'?'':'none';
  document.getElementById('tab-nodes').style.display = name==='nodes'?'':'none';
  document.getElementById('tab-log').style.display = name==='log'?'':'none';
  if (name==='nodes') loadNodes();
  if (name==='log') loadLog(1);
}}

loadItems(1);
</script>
</body></html>"""
        html = prepare_html_for_public_base(html)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

    # ── 管理后台 API ────────────────────────────────────────────────
    @app.post("/admin/login")
    def admin_login(request: Request, username: str = Form(...), password: str = Form(...),
                    redirect: str = Form(default="/admin")):
        from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: F401
        from i18n import t
        cur_lang = resolve_lang(request)

        config = json.loads(CONFIG_PATH.read_text())
        admin_users = config.get("admin_users", {}) if isinstance(config, dict) else {}
        stored = admin_users.get(username)

        if not stored or not verify_password(password, stored):
            audit_log("admin.login_failed", username, success=False)
            login_html = (ADMIN_LOGIN_HTML
                          .replace("__REDIRECT__", redirect)
                          .replace("__ERR_MSG__", "用户名或密码错误"))
            login_html = prepare_html_for_public_base(login_html)
            return HTMLResponse(login_html, status_code=401)

        session_id = secrets.token_urlsafe(32)
        ADMIN_SESSIONS[session_id] = {"username": username, "created_at": time.time()}
        audit_log("admin.login", username, success=True)

        target = redirect if redirect.startswith(PUBLIC_BASE_PATH + "/") else public_path(redirect)
        resp = RedirectResponse(url=target, status_code=302)
        resp.set_cookie(ADMIN_SESSION_COOKIE, session_id,
                        httponly=True, max_age=86400, samesite="lax", path=PUBLIC_BASE_PATH or "/")
        return resp

    @app.get("/admin/logout")
    def admin_logout(request: Request):
        from fastapi.responses import RedirectResponse  # noqa: F401
        cookie = request.cookies.get(ADMIN_SESSION_COOKIE)
        if cookie and cookie in ADMIN_SESSIONS:
            username = ADMIN_SESSIONS[cookie]["username"]
            del ADMIN_SESSIONS[cookie]
            audit_log("admin.logout", username, success=True)
        resp = RedirectResponse(url=public_path("/admin"), status_code=302)
        resp.delete_cookie(ADMIN_SESSION_COOKIE, path=PUBLIC_BASE_PATH or "/")
        return resp

    def _save_config_node_and_sync(name: str, token: str, role: str, description: str):
        _save_config_node(name, token, role, description)
        _sync_admin_node_state()

    register_admin_api_routes(
        app,
        node_state=node_state,
        authenticate_admin=authenticate_admin,
        resolve_admin_bearer=resolve_admin_bearer,
        save_config_node=_save_config_node_and_sync,
        audit_log=audit_log,
        update_item=lambda item_id, patch: update_knowledge_store_item(config, HUB_DIR, item_id, patch),
        delete_item=lambda item_id: delete_knowledge_store_item(config, HUB_DIR, item_id),
        list_items=lambda: read_knowledge_items(config, HUB_DIR),
        maintain_store=lambda vacuum=False: maintain_knowledge_store(config, HUB_DIR, vacuum=vacuum),
        log_path=Path(LOG_PATH),
    )

    return routed_app

def _save_config_node(name: str, token: str, role: str, description: str):
    """保存节点配置到 config.json"""
    cfg = json.loads(CONFIG_PATH.read_text())
    cfg = upsert_config_node(cfg, name, token, role, description)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))

# ─── 启动 ───

# ─── 启动 ───
if __name__ == "__main__":
    config = json.loads(CONFIG_PATH.read_text())
    port = config.get("port", 10128)
    host = config.get("host", "0.0.0.0")
    app = create_app()
    logger.info(f"Knowledge Hub 启动 on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
