#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库重新分类脚本
严格按 data_dictionary.md 标准分类
用法：python3 scripts/reclassify_v6.py
"""

import sys
from pathlib import Path
from tinydb import TinyDB

# 动态定位 HUB_DIR（支持从任何目录运行）
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DB_PATH = PROJECT_DIR / "hub_tinydb" / "knowledge-index.json"

def classify(title: str, summary: str = "", source: str = "") -> str:
    """
    按数据字典标准分类
    决策顺序：C06数据资产 → C01行业政策 → C03金融资本 →
              C05技术资料 → C04产品方案 → C02新闻资讯 → C07其他
    """
    text = title + " " + summary

    # C06 数据资产
    if any(kw in text for kw in [
        "数据目录", "数据包", "数据清单", "数据明细",
        "数据资产目录", "数据资产清单", "数据资产明细",
        "数据资源目录", "数据资源清单",
    ]):
        return "数据资产"

    # C01 行业政策
    policy_patterns = [
        "关于印发", "关于发布", "关于公布", "关于公示",
        "的通知", "的意见", "的方案", "的规定", "的条例",
        "管理办法", "实施细则", "工作方案", "实施方案",
        "指导意见", "实施纲要", "发展规划", "的公告",
    ]
    exclude_policy = ["招标网站", "投标人", "神器盘点", "效率太低"]
    if any(p in title for p in policy_patterns) and not any(e in title for e in exclude_policy):
        return "行业政策"

    # C03 金融资本
    if any(kw in title for kw in [
        "上市", "IPO", "融资", "市值", "股价", "ABS",
        "并购", "收购", "财报", "营收", "业绩", "亿",
    ]):
        return "金融资本"

    # C05 技术资料
    if any(kw in title for kw in [
        "技术", "研究", "算法", "架构", "模型", "专利", "原理",
    ]):
        return "技术资料"

    # C04 产品方案
    if any(kw in title for kw in [
        "产品", "介绍", "手册", "画册", "白皮书", "案例",
    ]):
        return "产品方案"

    # C02 新闻资讯
    if any(kw in title for kw in [
        "新闻", "资讯", "日报", "动态", "趋势", "观察",
        "要闻", "热点", "解读", "聚焦", "前沿",
        "获悉", "讯", "报道", "发布", "启动", "上线",
    ]):
        return "新闻资讯"

    if source == "data-market-insight":
        return "新闻资讯"

    return "其他"

def main():
    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}")
        sys.exit(1)

    db = TinyDB(str(DB_PATH))
    tbl = db.table("knowledge")
    all_items = list(tbl.all())
    print(f"共 {len(all_items)} 条知识，开始分类...")

    stats = {c: 0 for c in ["行业政策","新闻资讯","金融资本","产品方案","技术资料","数据资产","其他"]}

    for item in all_items:
        cat = classify(item.get("title",""), item.get("summary",""), item.get("source",""))
        stats[cat] += 1
        tbl.update({"category": cat}, doc_ids=[item.doc_id])

    print("\n分类结果统计：")
    for c, n in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}条")

    print("\n各分类样例：")
    for cat in ["行业政策","新闻资讯","金融资本","产品方案","技术资料","数据资产","其他"]:
        items = [i for i in all_items if i.get("category") == cat]
        print(f"\n【{cat}】({len(items)}条)")
        for item in items[:5]:
            print(f"  • {item.get('title','')[:65]}")

    db.close()
    print("\n✅ 分类完成")

if __name__ == "__main__":
    main()