#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hub_sync.py — 双向同步脚本
用法：python3 hub_sync.py [push|pull|full]
"""

import sys
import os
import json
import hashlib
import requests
from datetime import datetime, timedelta
from pathlib import Path
from tinydb import TinyDB

HUB_DIR    = Path(__file__).parent
CONFIG_PATH = HUB_DIR / "config.json"

def load_config():
    config = json.loads(CONFIG_PATH.read_text())
    nodes  = config.get("nodes", {})
    local_node = nodes.get("domi-cloud", {})
    token = local_node.get("token", "")
    if not token:
        raise RuntimeError("Token 未初始化，请先启动 hub_server 生成 config")
    return config, token

def get_base_url(config):
    host = config.get("host", "127.0.0.1")
    port = config.get("port", 10128)
    if host == "0.0.0.0": host = "127.0.0.1"
    return f"http://{host}:{port}"

def content_hash(title: str, summary: str) -> str:
    raw = f"{title.strip().lower()}|||{summary.strip().lower()[:200]}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def push_to_hub(config, token):
    """把本地新增知识推到 Hub（最近 24 小时创建的）"""
    local_db_path = Path(config["local_db_path"])
    if not local_db_path.exists():
        print(f"本地数据库不存在: {local_db_path}")
        return 0

    local_db = TinyDB(str(local_db_path))
    local_items = local_db.table("knowledge").all()
    local_db.close()

    hub_db_path = HUB_DIR / config["hub_db_path"]
    os.makedirs(hub_db_path.parent, exist_ok=True)
    hub_db = TinyDB(str(hub_db_path))
    hub_hashes = {content_hash(e.get("title",""), e.get("summary","")) for e in hub_db.table("knowledge").all()}
    hub_db.close()

    yesterday = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d")
    new_items = [
        item for item in local_items
        if content_hash(item.get("title",""), item.get("summary","")) not in hub_hashes
        and (item.get("created_at","") or item.get("source_date","")) >= yesterday
    ]
    if not new_items:
        print("没有需要同步的新增知识")
        return 0

    base_url = get_base_url(config)
    resp = requests.post(
        f"{base_url}/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={"items": new_items},
        timeout=30,
    )
    result = resp.json()
    print(f"推送 Hub: {result.get('ingested',0)} 条新增, {result.get('skipped',0)} 条跳过")
    return result.get("ingested", 0)

def pull_from_hub(config, token):
    """从 Hub 拉取统计信息（只读）"""
    base_url = get_base_url(config)
    resp = requests.get(f"{base_url}/stats", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    stats = resp.json()
    print(f"Hub 总条目: {stats.get('total',0)}, 节点分布: {stats.get('source_nodes',{})}")
    return stats

def full_sync(config, token):
    """全量同步：把本地所有知识推到 Hub"""
    local_db_path = Path(config["local_db_path"])
    if not local_db_path.exists():
        print(f"本地数据库不存在: {local_db_path}")
        return

    local_db = TinyDB(str(local_db_path))
    local_items = local_db.table("knowledge").all()
    local_db.close()

    hub_db_path = HUB_DIR / config["hub_db_path"]
    os.makedirs(hub_db_path.parent, exist_ok=True)
    hub_db = TinyDB(str(hub_db_path))
    hub_hashes = {content_hash(e.get("title",""), e.get("summary","")) for e in hub_db.table("knowledge").all()}
    hub_db.close()

    new_items = [
        item for item in local_items
        if content_hash(item.get("title",""), item.get("summary","")) not in hub_hashes
    ]
    if not new_items:
        print("本地知识已全部在 Hub 中，无需同步")
        return 0

    base_url = get_base_url(config)
    batch_size = 50
    total = 0
    for i in range(0, len(new_items), batch_size):
        batch = new_items[i:i+batch_size]
        resp = requests.post(
            f"{base_url}/ingest",
            headers={"Authorization": f"Bearer {token}"},
            json={"items": batch},
            timeout=30,
        )
        result = resp.json()
        total += result.get("ingested", 0)
        print(f"  批次 {i//batch_size+1}: {result.get('ingested',0)} 条新增, {result.get('skipped',0)} 条跳过")

    print(f"全量同步完成: 共 {total} 条入库")
    return total

def main():
    config, token = load_config()
    mode = sys.argv[1] if len(sys.argv) > 1 else "push"
    if mode == "push":   push_to_hub(config, token)
    elif mode == "pull": pull_from_hub(config, token)
    elif mode == "full": full_sync(config, token)
    else: print("用法: python3 hub_sync.py [push|pull|full]")

if __name__ == "__main__":
    main()