import copy
import json

from knowledge_hub.classification import auto_annotate_item
from knowledge_hub.quality import auto_evaluate_quality, evaluate_quality_detail
from knowledge_hub.search import content_hash
from knowledge_hub.schema import normalize_knowledge_item, quality_score


def validate_knowledge_item(item: dict, config: dict) -> tuple[dict | None, dict | None]:
    """
    Validate one submitted knowledge item.

    Returns (prepared_item, None) when accepted, or (None, skipped_detail) when rejected.
    The prepared item is a shallow deep copy with hub-owned quality applied.
    """
    size = len(json.dumps(item, ensure_ascii=False))
    if size > config.get("max_item_size_bytes", 10240):
        return None, {"title": item.get("title"), "reason": "too_large"}

    quality_detail = evaluate_quality_detail(item)
    auto_quality = quality_detail["score"]
    submitted_quality = quality_score(item)
    if auto_quality < config.get("quality_threshold", 60):
        return None, {
            "title": item.get("title"),
            "reason": "quality_too_low",
            "auto_score": auto_quality,
            "submitted_score": submitted_quality,
            "quality_detail": quality_detail,
        }

    prepared = copy.deepcopy(item)
    prepared["quality"] = auto_quality
    prepared["quality_detail"] = quality_detail
    prepared = auto_annotate_item(prepared, config)
    return prepared, None


def prepare_ingest_item(
    item: dict,
    source_node: str,
    existing_hashes: set,
    created_at: str,
    config: dict = None,
    base_dir=None,
) -> tuple[dict | None, dict | None, str | None]:
    """
    Add ingest metadata and check duplicate content.

    Returns (prepared_item, None, item_hash) when accepted, or
    (None, skipped_detail, item_hash) when duplicate.
    """
    prepared = copy.deepcopy(item)
    item_hash = content_hash(prepared.get("title", ""), prepared.get("summary", ""))
    prepared = normalize_knowledge_item(
        prepared,
        source_node=source_node,
        now=created_at,
        content_hash_value=item_hash,
        config=config,
        base_dir=base_dir,
    )
    asset_errors = [
        asset.get("parse_error")
        for asset in prepared.get("assets", [])
        if asset.get("parse_status") == "error"
    ]
    if asset_errors:
        return None, {"title": prepared.get("title"), "reason": "asset_invalid", "details": asset_errors}, item_hash

    if not prepared.get("id"):
        prepared["id"] = f"hub-{item_hash}"
    if "created_at" not in prepared:
        prepared["created_at"] = created_at

    if item_hash in existing_hashes:
        return None, {"title": prepared.get("title"), "reason": "duplicate"}, item_hash

    return prepared, None, item_hash


def prepare_sync_item(
    item: dict,
    source_node: str,
    existing_items_by_hash: dict,
    config: dict = None,
    base_dir=None,
) -> tuple[str, dict | None, str]:
    """
    Prepare a validated sync item and decide whether it should be inserted or updated.

    Returns:
    - ("insert", prepared_item, item_hash)
    - ("update", merged_item, item_hash)
    - ("skip", None, item_hash)
    """
    prepared = copy.deepcopy(item)
    item_hash = content_hash(prepared.get("title", ""), prepared.get("summary", ""))
    prepared = normalize_knowledge_item(
        prepared,
        source_node=source_node,
        content_hash_value=item_hash,
        config=config,
        base_dir=base_dir,
    )
    if any(asset.get("parse_status") == "error" for asset in prepared.get("assets", [])):
        return "skip", None, item_hash

    existing_item = existing_items_by_hash.get(item_hash)
    if existing_item:
        if quality_score(prepared) > quality_score(existing_item):
            merged = copy.deepcopy(existing_item)
            merged.update(prepared)
            merged["lifecycle"] = {
                **(existing_item.get("lifecycle") or {}),
                **(prepared.get("lifecycle") or {}),
                "version": (existing_item.get("lifecycle") or {}).get("version", 1) + 1,
            }
            return "update", merged, item_hash
        return "skip", None, item_hash

    prepared["id"] = f"hub-sync-{item_hash}"
    return "insert", prepared, item_hash
