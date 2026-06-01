from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .constants import SUPPORTED_LANGUAGES
from .texts import UI_TEXTS


def normalize_lang(lang: str | None, fallback: str = "uk") -> str:
    value = (lang or fallback).lower()
    return value if value in SUPPORTED_LANGUAGES else fallback


def t(lang: str | None, key: str, **kwargs) -> str:
    language = normalize_lang(lang)
    template = UI_TEXTS.get(language, UI_TEXTS["ru"]).get(key) or UI_TEXTS["ru"].get(key, key)
    return template.format(**kwargs)


def ui_variants(key: str) -> list[str]:
    return [UI_TEXTS[code][key] for code in ("uk", "ru", "en") if key in UI_TEXTS[code]]


def language_picker_kb(current_lang: str | None = None, origin: str = "set") -> InlineKeyboardMarkup:
    current = normalize_lang(current_lang)
    callback_origin = origin if origin in {"set", "start"} else "set"
    labels = {
        "uk": "Українська",
        "ru": "Русский",
        "en": "English",
    }
    flags = {
        "uk": "🇺🇦",
        "ru": "🇷🇺",
        "en": "🇬🇧",
    }
    kb = InlineKeyboardBuilder()
    for code in ("uk", "ru", "en"):
        prefix = "✅ " if code == current else ""
        kb.button(text=f"{prefix}{flags[code]} {labels[code]}", callback_data=f"lang:{callback_origin}:{code}")
    kb.adjust(1)
    return kb.as_markup()


def language_changed_text(lang: str) -> str:
    return t(lang, "language_changed")
