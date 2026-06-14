import hashlib

from knowledge_hub.schema import quality_score


def content_hash(title: str, summary: str) -> str:
    """Return a stable 12-character hash for deduplicating knowledge content."""
    raw = f"{title.strip().lower()}|||{summary.strip().lower()[:200]}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def simple_search(items: list, query: str = "", topics: list = None, min_quality: float = 0) -> list:
    """Search in-memory knowledge items by keyword, topics, and minimum quality."""
    results = items
    if query and len(query) >= 2:
        q = query.lower()

        def match_item(item):
            fields = [
                item.get("title", ""),
                item.get("summary", ""),
                item.get("content", ""),
                " ".join(item.get("tags", []) or []),
                " ".join(item.get("topics", []) or []),
                " ".join(item.get("entities", []) or []),
            ]
            return any(q in field.lower() for field in fields)

        results = [item for item in results if match_item(item)]
    if topics:
        results = [item for item in results if any(topic in (item.get("topics") or []) for topic in topics)]
    if min_quality > 0:
        results = [item for item in results if quality_score(item) >= min_quality]
    return results
