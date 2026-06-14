from pathlib import Path


def resolve_configured_path(raw_path: str | None, base_dir: Path) -> Path | None:
    """Resolve an optional config path relative to the application base directory."""
    if not raw_path:
        return None
    resolved = Path(raw_path).expanduser()
    if not resolved.is_absolute():
        resolved = base_dir / resolved
    return resolved


def resolve_local_db_path(config: dict, hub_dir: Path, config_path: Path) -> Path:
    """Resolve the optional local knowledge DB path with the legacy fallback."""
    configured = resolve_configured_path(config.get("local_db_path"), hub_dir)
    if configured is not None:
        return configured
    return config_path.parent.parent / "knowledge-management" / "knowledge" / "db" / "knowledge-index.json"

