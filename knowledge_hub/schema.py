import copy

from pathlib import Path

from knowledge_hub.attachments import build_asset_policy, extract_assets_text
from knowledge_hub.embedding import ensure_item_embedding

SCHEMA_VERSION = "2.0"
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 120


def _list_value(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def quality_score(item: dict) -> float:
    quality = item.get("quality", 0)
    if isinstance(quality, dict):
        return quality.get("score", 0) or 0
    return quality or 0


def legacy_quality_value(item: dict) -> float:
    return quality_score(item)


def build_content_chunks(
    content: str,
    knowledge_id: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list:
    """Split full content into deterministic chunks for retrieval and future embeddings."""
    text = (content or "").strip()
    if not text:
        return []
    chunk_size = max(int(chunk_size or DEFAULT_CHUNK_SIZE), 100)
    overlap = max(min(int(overlap or 0), chunk_size - 1), 0)
    chunks = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end]
        chunks.append({
            "id": f"{knowledge_id}-chunk-{index:04d}",
            "knowledge_id": knowledge_id,
            "chunk_index": index,
            "text": chunk_text,
            "char_start": start,
            "char_end": end,
            "embedding_status": "pending",
        })
        if end >= len(text):
            break
        start = end - overlap
        index += 1
    return chunks


def normalize_asset(asset, index: int, now: str = None) -> dict:
    """Normalize a raw source asset or attachment descriptor."""
    if isinstance(asset, str):
        asset_obj = {"url": asset}
    else:
        asset_obj = copy.deepcopy(asset or {})
    url = asset_obj.get("url") or asset_obj.get("href") or asset_obj.get("path")
    kind = asset_obj.get("kind")
    if not kind:
        if url and str(url).startswith(("http://", "https://")):
            lower_url = str(url).lower()
            kind = "file" if any(lower_url.endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg"]) else "web"
        elif asset_obj.get("path"):
            kind = "file"
        else:
            kind = "source"
    asset_obj["id"] = asset_obj.get("id") or f"asset-{index:04d}"
    asset_obj["kind"] = kind
    if url:
        asset_obj["url"] = url
    asset_obj.setdefault("title", asset_obj.get("name"))
    asset_obj.setdefault("mime_type", asset_obj.get("content_type"))
    if now:
        asset_obj.setdefault("collected_at", now)
    return asset_obj


def normalize_relation(relation) -> dict:
    """Normalize relations to an object form."""
    if isinstance(relation, str):
        return {"type": "related", "target_id": relation}
    relation_obj = copy.deepcopy(relation or {})
    relation_obj.setdefault("type", "related")
    return relation_obj


def normalize_knowledge_item(
    item: dict,
    source_node: str = None,
    now: str = None,
    content_hash_value: str = None,
    config: dict = None,
    base_dir: Path = None,
) -> dict:
    """Normalize a submitted item to the v2 knowledge schema while keeping legacy fields."""
    normalized = copy.deepcopy(item)
    source = normalized.get("source")
    if isinstance(source, dict):
        source_obj = copy.deepcopy(source)
        source_name = source_obj.get("name")
    else:
        source_obj = {"name": source} if source else {}
        source_name = source

    if normalized.get("url") and not source_obj.get("url"):
        source_obj["url"] = normalized.get("url")
    if normalized.get("source_date") and not source_obj.get("published_at"):
        source_obj["published_at"] = normalized.get("source_date")
    if now and not source_obj.get("collected_at"):
        source_obj["collected_at"] = now
    if not source_obj.get("type"):
        source_obj["type"] = normalized.get("source_type") or ("web" if source_obj.get("url") else "agent")

    provenance = copy.deepcopy(normalized.get("provenance") or {})
    if source_node:
        provenance["source_node"] = source_node
        normalized["source_node"] = source_node
    elif normalized.get("source_node"):
        provenance.setdefault("source_node", normalized.get("source_node"))
    if content_hash_value:
        provenance["content_hash"] = content_hash_value
    if normalized.get("archive_url"):
        provenance.setdefault("archive_url", normalized.get("archive_url"))

    score = quality_score(normalized)
    quality = normalized.get("quality")
    if isinstance(quality, dict):
        quality_obj = copy.deepcopy(quality)
        quality_obj["score"] = quality_score(quality_obj)
    else:
        quality_obj = {"score": score}
    quality_obj.setdefault("confidence", normalized.get("confidence", 1.0))
    quality_obj.setdefault("review_status", normalized.get("review_status", "auto"))
    quality_obj.setdefault("reasons", normalized.get("quality_reasons", []))

    lifecycle = copy.deepcopy(normalized.get("lifecycle") or {})
    lifecycle.setdefault("status", normalized.get("status", "active"))
    lifecycle.setdefault("version", normalized.get("version", 1))
    lifecycle.setdefault("valid_from", normalized.get("valid_from"))
    lifecycle.setdefault("valid_until", normalized.get("valid_until"))
    lifecycle.setdefault("review_at", normalized.get("review_at"))

    access = copy.deepcopy(normalized.get("access") or {})
    access.setdefault("visibility", normalized.get("visibility", "team"))
    access.setdefault("allowed_nodes", _list_value(normalized.get("allowed_nodes")))

    metadata = copy.deepcopy(normalized.get("metadata") or {})
    if normalized.get("domain") and "domain" not in metadata:
        metadata["domain"] = normalized.get("domain")

    assets = _list_value(normalized.get("assets"))
    if source_obj.get("url") and not assets:
        assets = [{"url": source_obj.get("url"), "title": source_obj.get("name"), "kind": source_obj.get("type")}]
    normalized_assets = [normalize_asset(asset, index, now=now) for index, asset in enumerate(assets)]
    asset_text, parsed_assets = extract_assets_text(
        normalized_assets,
        policy=build_asset_policy(config or {}, base_dir=base_dir),
    )

    content_parts = [
        normalized.get("content") or normalized.get("full_text") or normalized.get("summary", ""),
        asset_text,
    ]
    content = "\n\n".join(part for part in content_parts if part).strip()
    knowledge_id = normalized.get("id") or content_hash_value or "pending"

    normalized["schema_version"] = SCHEMA_VERSION
    normalized["content"] = content
    normalized["content_type"] = normalized.get("content_type", "article")
    normalized["chunks"] = _list_value(normalized.get("chunks")) or build_content_chunks(content, knowledge_id)
    normalized["assets"] = parsed_assets
    normalized["topics"] = _list_value(normalized.get("topics"))
    normalized["tags"] = _list_value(normalized.get("tags"))
    normalized["entities"] = _list_value(normalized.get("entities"))
    normalized["relations"] = [normalize_relation(relation) for relation in _list_value(normalized.get("relations"))]
    normalized["source"] = source_obj
    normalized["source_name"] = source_name
    normalized["provenance"] = provenance
    normalized["quality"] = score
    normalized["quality_detail"] = quality_obj
    normalized["access"] = access
    normalized["lifecycle"] = lifecycle
    normalized["metadata"] = metadata
    if now:
        normalized.setdefault("created_at", now)
        normalized["updated_at"] = normalized.get("updated_at") or now
    return ensure_item_embedding(normalized)
