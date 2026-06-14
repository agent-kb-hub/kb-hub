import hashlib
import secrets


def hash_password(password: str) -> str:
    """Return a salted SHA256 password hash in sha256:<salt>:<hash> format."""
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"sha256:{salt}:{digest}"


def verify_password(password: str, stored: str) -> bool:
    """Return True when password matches a stored salted SHA256 hash."""
    if not stored or not stored.startswith("sha256:"):
        return False
    parts = stored.split(":")
    if len(parts) != 3:
        return False
    _, salt, expected = parts
    digest = hashlib.sha256((salt + password).encode()).hexdigest()
    return digest == expected

