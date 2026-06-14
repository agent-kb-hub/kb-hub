import re
from urllib.parse import urlparse

CATEGORIES = ["行业政策", "新闻资讯", "金融资本", "产品方案", "技术资料", "数据资产", "其他"]

CATEGORY_RULES = [
    ("行业政策", ["政策", "规划", "通知", "公告", "管理办法", "行动方案", "行动计划", "意见", "条例", "标准"]),
    ("新闻资讯", ["新闻", "资讯", "动态", "报道", "快讯", "发布", "消息", "会议", "签约"]),
    ("金融资本", ["融资", "投资", "资本", "财报", "估值", "基金", "上市", "并购", "股权", "债券"]),
    ("产品方案", ["产品", "方案", "平台", "系统", "解决方案", "应用", "服务", "功能", "模块"]),
    ("技术资料", ["技术", "架构", "接口", "api", "模型", "部署", "代码", "算法", "数据库", "工程"]),
    ("数据资产", ["数据集", "指标", "数据库", "报表", "指数", "价格", "行情", "监测", "统计", "煤价"]),
]

STOPWORDS = {
    "this", "that", "with", "from", "into", "and", "or", "the", "for", "a", "an",
    "一个", "一种", "进行", "通过", "以及", "相关", "可以", "用于", "支持", "提供",
    "知识", "内容", "摘要", "详细", "信息", "数据",
}

ENTITY_PATTERNS = [
    re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,30}(?:公司|集团|科技|能源|煤业|电力|银行|证券|基金)"),
    re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,40}(?:政策|规划|方案|办法|条例|标准|指数|价格|行情)"),
    re.compile(r"[A-Z]{2,}[A-Za-z0-9]{0,12}"),
    re.compile(r"\d+(?:\.\d+)?(?:K|k|万吨|元/吨|%|MW|GW|kWh|MWh)?"),
]


def _list_value(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _dedupe(values: list, limit: int = None) -> list:
    seen = set()
    result = []
    for value in values:
        if value is None:
            continue
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if limit and len(result) >= limit:
            break
    return result


def knowledge_text(item: dict) -> str:
    return " ".join([
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        str(item.get("content") or ""),
        " ".join(str(tag) for tag in _list_value(item.get("tags"))),
        " ".join(str(topic) for topic in _list_value(item.get("topics"))),
    ]).lower()


def classify_category(item: dict, rules: dict = None) -> str:
    if item.get("category"):
        return item["category"]
    text = knowledge_text(item)
    configured_rules = rules or {}
    if configured_rules:
        iterable = configured_rules.items()
    else:
        iterable = CATEGORY_RULES
    best_category = "其他"
    best_score = 0
    for category, keywords in iterable:
        score = sum(1 for keyword in keywords if str(keyword).lower() in text)
        if score > best_score:
            best_category = category
            best_score = score
    return best_category if best_category in CATEGORIES else "其他"


def infer_topics(item: dict, topic_map: dict = None) -> list:
    text = knowledge_text(item)
    inferred = []
    for topic, aliases in (topic_map or {}).items():
        candidates = [topic] + list(aliases or [])
        if any(str(alias).lower() in text for alias in candidates if alias):
            inferred.append(topic)
    return _dedupe(_list_value(item.get("topics")) + inferred, limit=20)


def extract_tags(item: dict, max_tags: int = 12) -> list:
    text = " ".join([str(item.get("title") or ""), str(item.get("summary") or ""), str(item.get("content") or "")])
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,30}|[\u4e00-\u9fff]{2,8}|\d+(?:\.\d+)?%?", text)
    scored = {}
    for token in tokens:
        normalized = token.strip()
        if not normalized or normalized.lower() in STOPWORDS or normalized in STOPWORDS:
            continue
        scored[normalized] = scored.get(normalized, 0) + 1
    ordered = sorted(scored, key=lambda token: (-scored[token], -len(token), token))
    return _dedupe(_list_value(item.get("tags")) + ordered, limit=max_tags)


def extract_entities(item: dict, max_entities: int = 20) -> list:
    text = " ".join([str(item.get("title") or ""), str(item.get("summary") or ""), str(item.get("content") or "")])
    entities = []
    for pattern in ENTITY_PATTERNS:
        entities.extend(match.group(0) for match in pattern.finditer(text))
    for field in ("url", "archive_url"):
        url = item.get(field)
        if url:
            domain = urlparse(url).netloc
            if domain:
                entities.append(domain)
    source = item.get("source")
    if isinstance(source, dict) and source.get("name"):
        entities.append(source["name"])
    elif isinstance(source, str):
        entities.append(source)
    return _dedupe(_list_value(item.get("entities")) + entities, limit=max_entities)


def auto_annotate_item(item: dict, config: dict = None) -> dict:
    """Add deterministic category, topics, tags, and entities without overwriting user intent."""
    config = config or {}
    annotated = dict(item)
    annotated["category"] = classify_category(annotated, config.get("category_rules"))
    annotated["topics"] = infer_topics(annotated, config.get("topic_map") or {})
    annotated["tags"] = extract_tags(annotated, max_tags=int(config.get("max_auto_tags", 12) or 12))
    annotated["entities"] = extract_entities(annotated, max_entities=int(config.get("max_auto_entities", 20) or 20))
    return annotated
