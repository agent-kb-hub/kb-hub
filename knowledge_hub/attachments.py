import csv
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_ALLOWED_SUFFIXES = {
    ".txt", ".md", ".markdown", ".log", ".html", ".htm", ".json", ".csv", ".pdf", ".docx"
}


@dataclass
class AssetPolicy:
    allowed_dirs: list
    max_bytes: int = 5 * 1024 * 1024
    allowed_suffixes: set = None

    def __post_init__(self):
        self.allowed_dirs = [Path(path).expanduser().resolve() for path in self.allowed_dirs or []]
        self.allowed_suffixes = set(self.allowed_suffixes or DEFAULT_ALLOWED_SUFFIXES)


def build_asset_policy(config: dict = None, base_dir: Path = None) -> AssetPolicy:
    config = config or {}
    allowed_dirs = config.get("asset_allowed_dirs") or []
    if base_dir is not None:
        allowed_dirs = [
            str((base_dir / path).resolve()) if not Path(path).is_absolute() else path
            for path in allowed_dirs
        ]
    return AssetPolicy(
        allowed_dirs=allowed_dirs,
        max_bytes=int(config.get("asset_max_bytes", 5 * 1024 * 1024) or 5 * 1024 * 1024),
        allowed_suffixes=set(config.get("asset_allowed_suffixes") or DEFAULT_ALLOWED_SUFFIXES),
    )


def validate_asset_path(path, policy: AssetPolicy) -> Path:
    file_path = Path(path).expanduser().resolve()
    if not policy.allowed_dirs:
        raise ValueError("local asset paths are disabled; configure asset_allowed_dirs")
    if not any(file_path == allowed or allowed in file_path.parents for allowed in policy.allowed_dirs):
        raise ValueError("asset path is outside allowed directories")
    if file_path.suffix.lower() not in policy.allowed_suffixes:
        raise ValueError("asset suffix is not allowed")
    if not file_path.exists() or not file_path.is_file():
        raise ValueError("asset file does not exist")
    if file_path.stat().st_size > policy.max_bytes:
        raise ValueError("asset file exceeds asset_max_bytes")
    return file_path


class _HTMLTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def _json_to_text(value) -> str:
    if isinstance(value, dict):
        return " ".join(_json_to_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_json_to_text(item) for item in value)
    return str(value)


def extract_text_from_file(path) -> str:
    """Extract text from a local attachment using standard-library parsers where possible."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".log"}:
        return _read_text(file_path).strip()
    if suffix in {".html", ".htm"}:
        parser = _HTMLTextParser()
        parser.feed(_read_text(file_path))
        return parser.text().strip()
    if suffix == ".json":
        return _json_to_text(json.loads(_read_text(file_path))).strip()
    if suffix == ".csv":
        rows = []
        with file_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                rows.append(" ".join(cell for cell in row if cell))
        return "\n".join(rows).strip()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception:
            return ""
        reader = PdfReader(str(file_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if suffix == ".docx":
        try:
            import docx
        except Exception:
            return ""
        document = docx.Document(str(file_path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    return ""


def extract_asset_text(asset: dict, policy: AssetPolicy = None) -> tuple[str, dict]:
    """Extract text for one asset descriptor and return updated asset metadata."""
    updated = dict(asset or {})
    text = ""
    path = updated.get("path")
    inline_text = updated.get("text")
    if inline_text:
        text = str(inline_text)
    elif path:
        try:
            safe_path = validate_asset_path(path, policy or AssetPolicy([]))
            text = extract_text_from_file(safe_path)
        except Exception as exc:
            updated["parse_status"] = "error"
            updated["parse_error"] = str(exc)
            return "", updated

    text = re.sub(r"\s+", " ", text or "").strip()
    if text:
        updated["parse_status"] = "parsed"
        updated["text_length"] = len(text)
    else:
        updated.setdefault("parse_status", "skipped")
        updated.setdefault("text_length", 0)
    return text, updated


def extract_assets_text(assets: list, policy: AssetPolicy = None) -> tuple[str, list]:
    texts = []
    updated_assets = []
    for asset in assets or []:
        text, updated = extract_asset_text(asset, policy=policy)
        if text:
            texts.append(text)
        updated_assets.append(updated)
    return "\n\n".join(texts), updated_assets
