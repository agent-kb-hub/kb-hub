SESSION_TTL_SECONDS = 86400


def extract_bearer_token(authorization: str | None) -> str | None:
    """Extract a bearer token from an Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[7:]


def resolve_node_from_token(token: str | None, token_map: dict, node_tokens: dict) -> dict | None:
    """Resolve a node token to a node info dict."""
    if not token:
        return None
    node_name = token_map.get(token)
    if not node_name:
        return None
    node_info = node_tokens[node_name]
    return {"name": node_name, **node_info}


def build_node_auth_info(node_name: str, node_info: dict, lang: str, is_admin: bool = False) -> dict:
    """Build the auth info object used by route handlers."""
    return {"name": node_name, "lang": lang, **node_info, "is_admin": is_admin}


def is_session_valid(session: dict | None, now: float, ttl_seconds: int = SESSION_TTL_SECONDS) -> bool:
    """Return True if an admin session exists and has not expired."""
    if not session:
        return False
    created_at = session.get("created_at")
    if created_at is None:
        return False
    return now - created_at <= ttl_seconds


def resolve_admin_bearer(authorization: str | None, token_map: dict, node_tokens: dict) -> dict | None:
    """Return a synthetic admin session when an admin bearer token is supplied."""
    token = extract_bearer_token(authorization)
    node = resolve_node_from_token(token, token_map, node_tokens)
    if node and node.get("role") == "admin":
        return {"username": f"token:{node['name']}"}
    return None

