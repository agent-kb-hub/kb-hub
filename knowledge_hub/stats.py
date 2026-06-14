from collections import Counter
from collections import defaultdict
from datetime import timedelta


def build_hub_stats(items: list) -> dict:
    """Build global Hub knowledge statistics."""
    topics = Counter()
    nodes = Counter()
    for item in items:
        for topic in item.get("topics") or []:
            topics[topic] += 1
        nodes[item.get("source_node", "unknown")] += 1
    return {
        "total": len(items),
        "source_nodes": dict(nodes),
        "top_topics": dict(topics.most_common(10)),
    }


def build_node_query_stats(query_stats: dict, node_tokens: dict) -> dict:
    """Build per-node query statistics sorted by query count."""
    stats = []
    for node_name, info in query_stats.items():
        stats.append({
            "node": node_name,
            "role": node_tokens.get(node_name, {}).get("role", "unknown"),
            "query_count": info["query_count"],
            "last_query": info["last_query"],
            "total_results": info["total_results"],
        })
    stats.sort(key=lambda item: item["query_count"], reverse=True)
    return {
        "total_nodes_queried": len(stats),
        "total_queries": sum(item["query_count"] for item in stats),
        "nodes": stats,
    }


def build_usage_stats(local_items: list, hub_items: list, limit: int = 20) -> dict:
    """Merge local and Hub usage counters into a top-used list."""
    merged = {}
    for item in local_items:
        if item.get("usage_count", 0) <= 0:
            continue
        item_id = item.get("id")
        merged[item_id] = {
            "id": item_id,
            "title": item.get("title"),
            "local_usage": item.get("usage_count", 0),
            "local_last_used": item.get("last_used", ""),
            "hub_usage": 0,
            "hub_last_used": "",
        }

    for item in hub_items:
        if item.get("hub_usage_count", 0) <= 0:
            continue
        item_id = item.get("id")
        if item_id in merged:
            merged[item_id]["hub_usage"] = item.get("hub_usage_count", 0)
            merged[item_id]["hub_last_used"] = item.get("hub_last_used", "")
        else:
            merged[item_id] = {
                "id": item_id,
                "title": item.get("title"),
                "local_usage": 0,
                "local_last_used": "",
                "hub_usage": item.get("hub_usage_count", 0),
                "hub_last_used": item.get("hub_last_used", ""),
            }

    top_used = sorted(
        merged.values(),
        key=lambda item: item["local_usage"] + item["hub_usage"],
        reverse=True,
    )[:limit]
    return {
        "total_used": len(top_used),
        "top_used": top_used,
    }


def build_dashboard_model(items: list, node_tokens: dict, now) -> dict:
    """Build aggregate data used by the dashboard page."""
    nodes_counter = Counter()
    node_qualities = defaultdict(list)
    topics_counter = Counter()
    categories_counter = Counter()
    dates_counter = Counter()
    quality_ranges = {"60-70": 0, "70-85": 0, "85-100": 0}

    for item in items:
        source_node = item.get("source_node", "unknown")
        nodes_counter[source_node] += 1
        node_qualities[source_node].append(item.get("quality", 0))

        categories_counter[item.get("category", "其他")] += 1

        for topic in item.get("topics") or []:
            topics_counter[topic] += 1

        created_at = item.get("created_at", "")
        if created_at and len(created_at) >= 10:
            dates_counter[created_at[:10]] += 1

        quality = item.get("quality", 0)
        if quality < 70:
            quality_ranges["60-70"] += 1
        elif quality < 85:
            quality_ranges["70-85"] += 1
        else:
            quality_ranges["85-100"] += 1

    last_7 = [(now - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(6, -1, -1)]
    node_activity = {}
    for node_name in node_tokens:
        node_activity[node_name] = sum(
            1
            for item in items
            if item.get("source_node") == node_name and item.get("created_at", "")[:10] in last_7
        )

    total = len(items)
    return {
        "nodes_counter": nodes_counter,
        "node_qualities": node_qualities,
        "topics_counter": topics_counter,
        "categories_counter": categories_counter,
        "dates_counter": dates_counter,
        "quality_ranges": quality_ranges,
        "last_7": last_7,
        "node_activity": node_activity,
        "recent_items": sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)[:15],
        "total": total,
        "avg_quality": round(sum(item.get("quality", 0) for item in items) / max(total, 1), 1),
        "active_nodes": len(nodes_counter),
        "total_topics": len(topics_counter),
    }
