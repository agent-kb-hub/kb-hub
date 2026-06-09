"""
i18n module for Knowledge Hub
Loads language files and provides translation functions.
"""
import json
from pathlib import Path
from typing import Optional

I18N_DIR = Path(__file__).parent
DEFAULT_LANG = "zh"
SUPPORTED_LANGS = ["zh", "en"]

_TRANSLATIONS: dict = {}
_LOADED = False


def load_translations() -> None:
    """Load all language files into memory."""
    global _TRANSLATIONS, _LOADED
    _TRANSLATIONS = {}
    for lang in SUPPORTED_LANGS:
        path = I18N_DIR / f"{lang}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                _TRANSLATIONS[lang] = json.load(f)
        else:
            _TRANSLATIONS[lang] = {}
    _LOADED = True


def get_translation(lang: str, key: str, **kwargs) -> str:
    """
    Get translated string for a dot-separated key.
    Falls back to default language if key not found, then to key itself.
    Supports {placeholder} substitution via kwargs.
    """
    if not _LOADED:
        load_translations()

    if lang not in _TRANSLATIONS:
        lang = DEFAULT_LANG

    parts = key.split(".")
    value = _TRANSLATIONS[lang]
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            # Fallback to default language
            value = _TRANSLATIONS.get(DEFAULT_LANG, {})
            for fallback_part in parts:
                if isinstance(value, dict) and fallback_part in value:
                    value = value[fallback_part]
                else:
                    return key  # Return key as last resort

    if not isinstance(value, str):
        return key

    # Substitute {placeholder} with kwargs
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value

    return value


def t(lang: str, key: str, **kwargs) -> str:
    """Shorthand for get_translation."""
    return get_translation(lang, key, **kwargs)


def normalize_lang(lang: Optional[str]) -> str:
    """Normalize language code, return default if unsupported."""
    if not lang:
        return DEFAULT_LANG
    lang = lang.lower().strip()
    # Handle variants like zh-CN, en-US
    lang = lang.split("-")[0].split("_")[0]
    if lang in SUPPORTED_LANGS:
        return lang
    return DEFAULT_LANG


def detect_lang(accept_language: Optional[str]) -> str:
    """Detect language from Accept-Language header."""
    if not accept_language:
        return DEFAULT_LANG
    # Parse "zh-CN,zh;q=0.9,en;q=0.8"
    parts = [p.strip() for p in accept_language.split(",")]
    for part in parts:
        # Extract language code (before ;)
        code = part.split(";")[0].strip()
        code = code.lower()
        code = code.split("-")[0]
        if code in SUPPORTED_LANGS:
            return code
    return DEFAULT_LANG


# Load on import
load_translations()
