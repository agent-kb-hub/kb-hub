from knowledge_hub.embedding import semantic_search
from knowledge_hub.search import content_hash, simple_search
from knowledge_hub.schema import quality_score


def format_query_item(item: dict, include_content: bool = False, include_chunks: bool = False) -> dict:
    """Return the public query response shape for one knowledge item."""
    formatted = {
        "id": item.get("id"),
        "title": item.get("title"),
        "summary": (item.get("summary") or "")[:200],
        "schema_version": item.get("schema_version", "1.0"),
        "content_type": item.get("content_type"),
        "category": item.get("category", "其他"),
        "source": item.get("source"),
        "source_name": item.get("source_name"),
        "source_date": item.get("source_date"),
        "url": item.get("url"),
        "topics": item.get("topics", []),
        "tags": item.get("tags", []),
        "entities": item.get("entities", []),
        "quality": quality_score(item),
        "quality_detail": item.get("quality_detail"),
        "source_node": item.get("source_node", "unknown"),
        "archive_url": item.get("archive_url"),
        "assets": item.get("assets", []),
        "relations": item.get("relations", []),
        "provenance": item.get("provenance"),
        "lifecycle": item.get("lifecycle"),
        "access": item.get("access"),
        "metadata": item.get("metadata", {}),
    }
    if "semantic_score" in item:
        formatted["semantic_score"] = item.get("semantic_score")
    if include_content:
        formatted["content"] = item.get("content")
    if include_chunks:
        formatted["chunks"] = item.get("chunks", [])
    return formatted


def build_query_results(
    hub_items: list,
    local_items: list,
    query_text: str = "",
    topics_filter: list | None = None,
    min_quality: float = 0,
    limit: int = 10,
    include_content: bool = False,
    include_chunks: bool = False,
    search_mode: str = "keyword",
) -> list:
    """Search Hub and local items, merge by content hash, and format public results."""
    all_items = hub_items + local_items
    if search_mode == "semantic":
        raw_results = semantic_search(all_items, query_text, limit=max(limit * 3, limit))
        raw_results = simple_search(raw_results, "", topics_filter or [], min_quality)
    elif search_mode == "hybrid":
        keyword_results = simple_search(all_items, query_text, topics_filter or [], min_quality)
        semantic_results = semantic_search(all_items, query_text, limit=max(limit * 3, limit))
        raw_results = keyword_results + semantic_results
    else:
        raw_results = simple_search(all_items, query_text, topics_filter or [], min_quality)

    seen = set()
    merged = []
    for item in raw_results:
        item_hash = content_hash(item.get("title", ""), item.get("summary", ""))
        if item_hash in seen:
            continue
        seen.add(item_hash)
        merged.append(format_query_item(
            item,
            include_content=include_content,
            include_chunks=include_chunks,
        ))
        if len(merged) >= limit:
            break
    return merged
