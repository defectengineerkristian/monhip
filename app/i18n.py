"""Oberflächensprache und Übersetzungen; Modell-Prompts und Nutzerdaten bleiben unverändert."""

import ctypes
import json
import locale
import os
import re
import string
import sys
from pathlib import Path

from i18n_en import ENGLISH


LANGUAGES = {"Deutsch": "de", "English": "en"}
_language = "de"


def system_language() -> str:
    """Windows-Anzeigesprache bevorzugen; unbekannte Sprachen fallen auf Englisch zurück."""
    if sys.platform == "win32":
        try:
            language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if language_id:
                return "de" if language_id & 0x3ff == 0x07 else "en"
        except (AttributeError, OSError):
            pass
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value:
            return "de" if value.split(".")[0].replace("-", "_").split("_")[0].lower() == "de" else "en"
    try:
        value = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        value = ""
    return "de" if value.replace("-", "_").split("_")[0].lower() in ("de", "german") else "en"


def resolve_language(value=None) -> str:
    return value if isinstance(value, str) and value in LANGUAGES.values() else system_language()


def initialize(config_file: Path) -> str:
    """Gespeicherte Auswahl vor dem Import der Oberflächenmodule anwenden."""
    global _language
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        value = config.get("ui_language") if isinstance(config, dict) else None
    except (OSError, ValueError):
        value = None
    _language = resolve_language(value)
    return _language


def get_language() -> str:
    return _language


def tr(text: str, *args, **kwargs) -> str:
    """Deutschen Originaltext oder englische Übersetzung mit denselben Platzhaltern liefern."""
    translated = ENGLISH.get(text, text) if _language == "en" else text
    args = tuple(error_text(arg) if isinstance(arg, BaseException) else arg for arg in args)
    kwargs = {key: error_text(value) if isinstance(value, BaseException) else value for key, value in kwargs.items()}
    return translated.format(*args, **kwargs) if args or kwargs else translated


def tr_in(language: str, text: str, *args) -> str:
    """Wie tr, aber in einer bestimmten Sprache – z. B. der Hinweis beim Wechsel in der gerade gewählten Sprache."""
    translated = ENGLISH.get(text, text) if language == "en" else text
    return translated.format(*args) if args else translated


_error_patterns = None


def error_text(error) -> str:
    """Bereits formatierte Fehlermeldungen nur für die Anzeige übersetzen, nie für Protokolle."""
    global _error_patterns
    text = str(error)
    if _language != "en":
        return text
    if text in ENGLISH:
        return ENGLISH[text]
    if text.startswith("Fehler: "):
        return tr("Fehler: {0}", error_text(text[len("Fehler: "):]))
    if _error_patterns is None:
        patterns = []
        formatter = string.Formatter()
        for source, target in ENGLISH.items():
            parts = list(formatter.parse(source))
            if not any(field is not None for _, field, _, _ in parts):
                continue
            if sum(len(literal) for literal, _, _, _ in parts) < 12:
                continue
            fields = []
            pattern = ""
            for literal, field, _, _ in parts:
                pattern += re.escape(literal)
                if field is not None:
                    if field in fields:
                        pattern += f"(?P=v{fields.index(field)})"
                    else:
                        pattern += f"(?P<v{len(fields)}>.*?)"
                        fields.append(field)
            patterns.append((re.compile(pattern, re.DOTALL), fields, source, target))
        _error_patterns = patterns
    for pattern, fields, source, target in _error_patterns:
        match = pattern.fullmatch(text)
        if match:
            values = {field: match.group(f"v{index}") for index, field in enumerate(fields)}
            # Diese Werte sind feste Programmmeldungen, keine Dateipfade oder Nutzerinhalte.
            if source.startswith("Kontextfenster voll:") or source == "Das ist {0}.":
                values = {field: error_text(value) for field, value in values.items()}
            # Werte sind schon formatiert: Zahlen, Dateipfade und Nutzereingaben unverändert einsetzen.
            return "".join(literal + (values.get(field, "") if field is not None else "")
                           for literal, field, _, _ in string.Formatter().parse(target))
    return text
