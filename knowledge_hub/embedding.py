import hashlib
import math
import re

DEFAULT_VECTOR_DIM = 256
TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def tokenize(text: str) -> list:
    return [token.lower() for token in TOKEN_RE.findall(text or "") if token.strip()]


def embed_text(text: str, dim: int = DEFAULT_VECTOR_DIM) -> list:
    """Build a deterministic local embedding with feature hashing."""
    vector = [0.0] * dim
    for token in tokenize(text):
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list, right: list) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def item_embedding_text(item: dict) -> str:
    chunks = item.get("chunks") or []
    chunk_text = " ".join(chunk.get("text", "") for chunk in chunks)
    return " ".join([
        item.get("title", "") or "",
        item.get("summary", "") or "",
        item.get("content", "") or "",
        chunk_text,
        " ".join(item.get("topics") or []),
        " ".join(item.get("tags") or []),
        " ".join(item.get("entities") or []),
    ])


def ensure_item_embedding(item: dict) -> dict:
    embedding = item.get("embedding")
    if isinstance(embedding, dict) and embedding.get("vector"):
        return item
    item["embedding"] = {
        "provider": "local-hash",
        "model": "feature-hash-v1",
        "dimensions": DEFAULT_VECTOR_DIM,
        "vector": embed_text(item_embedding_text(item)),
    }
    for chunk in item.get("chunks") or []:
        chunk.setdefault("embedding_status", "ready")
        chunk.setdefault("embedding", {
            "provider": "local-hash",
            "model": "feature-hash-v1",
            "dimensions": DEFAULT_VECTOR_DIM,
            "vector": embed_text(chunk.get("text", "")),
        })
    return item


def semantic_search(items: list, query: str, limit: int = 10, min_score: float = 0.0) -> list:
    query_vector = embed_text(query)
    ranked = []
    for item in items:
        ensure_item_embedding(item)
        score = cosine_similarity(query_vector, item["embedding"]["vector"])
        if score >= min_score:
            result = dict(item)
            result["semantic_score"] = score
            ranked.append(result)
    ranked.sort(key=lambda item: item.get("semantic_score", 0), reverse=True)
    return ranked[:limit]
