"""Tests für Spracherkennung, Konfiguration und die Übersetzungsverträge."""

import ast
import json
import os
from pathlib import Path
import string
import sys
import tempfile
import types
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

import i18n
from i18n_en import ENGLISH


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.previous_language = i18n._language
        self.directory = tempfile.TemporaryDirectory()
        self.config = Path(self.directory.name) / "config.json"

    def tearDown(self):
        i18n._language = self.previous_language
        self.directory.cleanup()

    def test_windows_display_language_has_priority(self):
        for language_id, expected in ((0x0407, "de"), (0x0c07, "de"), (0x0409, "en"),
                                      (0x0809, "en"), (0x040c, "en"), (0x0411, "en")):
            with self.subTest(language_id=language_id):
                windll = types.SimpleNamespace(kernel32=types.SimpleNamespace(
                    GetUserDefaultUILanguage=lambda: language_id))
                with mock.patch.object(i18n.sys, "platform", "win32"), \
                        mock.patch.object(i18n.ctypes, "windll", windll, create=True), \
                        mock.patch.dict(os.environ, {"LANG": "de_DE.UTF-8"}, clear=True):
                    self.assertEqual(i18n.system_language(), expected)

    def test_non_windows_locale_and_english_fallback(self):
        for environment, expected in (({"LANG": "de_DE.UTF-8"}, "de"), ({"LANG": "de.UTF-8"}, "de"),
                                      ({"LANG": "en_GB.UTF-8"}, "en"), ({"LANG": "fr_FR.UTF-8"}, "en"),
                                      ({"LC_ALL": "de_AT.UTF-8", "LANG": "en_US.UTF-8"}, "de"),
                                      ({"LC_MESSAGES": "en_US", "LANG": "de_DE"}, "en"),
                                      ({"LANG": "C"}, "en")):
            with self.subTest(environment=environment), mock.patch.object(i18n.sys, "platform", "linux"), \
                    mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(i18n.system_language(), expected)

    def test_locale_failure_falls_back_to_english(self):
        with mock.patch.object(i18n.sys, "platform", "linux"), \
                mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(i18n.locale, "getlocale", side_effect=ValueError):
            self.assertEqual(i18n.system_language(), "en")

    def test_first_start_uses_system_language_without_creating_config(self):
        with mock.patch.object(i18n, "system_language", return_value="de"):
            self.assertEqual(i18n.initialize(self.config), "de")
        self.assertFalse(self.config.exists())

    def test_saved_choice_survives_a_different_system_language(self):
        for saved, detected in (("de", "en"), ("en", "de")):
            content = json.dumps({"ui_language": saved, "system_prompt": "Mein eigener Prompt", "speech_language": "de"})
            self.config.write_text(content, encoding="utf-8")
            with self.subTest(saved=saved), mock.patch.object(i18n, "system_language", return_value=detected):
                self.assertEqual(i18n.initialize(self.config), saved)
                self.assertEqual(self.config.read_text(encoding="utf-8"), content)

    def test_old_invalid_and_corrupt_configuration(self):
        for content in ('{}', '{"ui_language": "fr"}', '{"ui_language": []}', '[]', 'invalid JSON'):
            self.config.write_text(content, encoding="utf-8")
            with self.subTest(content=content), mock.patch.object(i18n, "system_language", return_value="en"):
                self.assertEqual(i18n.initialize(self.config), "en")
                self.assertEqual(self.config.read_text(encoding="utf-8"), content)

    def test_german_original_and_english_translation(self):
        i18n._language = "de"
        self.assertEqual(i18n.tr("Kein Modell geladen"), "Kein Modell geladen")
        i18n._language = "en"
        self.assertEqual(i18n.tr("Kein Modell geladen"), "No model loaded")
        self.assertEqual(i18n.tr("Datei {0}?", i18n.tr("anlegen")), "Create file?")

    def test_formatting_keeps_user_values_and_numeric_specifiers(self):
        i18n._language = "en"
        self.assertEqual(i18n.tr("  ·  Kontext {0:,}", 32768), "  ·  Context 32,768")
        self.assertEqual(i18n.tr("Experte für „{0}“", "Meine Dateien {de}"), "Expert on “Meine Dateien {de}”")

    def test_every_translation_preserves_format_fields(self):
        formatter = string.Formatter()
        def fields(value):
            return sorted((key, spec, conversion) for _, key, spec, conversion in formatter.parse(value)
                          if key is not None)
        for source, translated in ENGLISH.items():
            with self.subTest(source=source):
                self.assertEqual(fields(source), fields(translated))

    def test_every_literal_translation_call_has_an_english_entry(self):
        for path in APP.glob("*.py"):
            if path.name.startswith("i18n"):
                continue
            for node in ast.walk(ast.parse(path.read_bytes())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                        and node.args and isinstance(node.args[0], ast.Constant)):
                    with self.subTest(path=path.name, line=node.lineno):
                        self.assertIn(node.args[0].value, ENGLISH)

    def test_error_display_preserves_numbers_and_file_paths(self):
        original = "Meine Dateien {de}.txt ist keine Datei."
        i18n._language = "de"
        self.assertEqual(i18n.error_text(ValueError(original)), original)
        i18n._language = "en"
        self.assertEqual(i18n.error_text(ValueError(original)), "Meine Dateien {de}.txt is not a file.")
        self.assertEqual(i18n.error_text("Die Datei ist zu groß (130 MB, höchstens 100 MB)."),
                         "The file is too large (130 MB, at most 100 MB).")

    def test_upload_progress_prefix_remains_recognizable(self):
        for language in ("de", "en"):
            i18n._language = language
            self.assertTrue(i18n.tr("Lade {0} {1} hoch …", 2, "files").startswith(i18n.tr("Lade ")))

    def test_tool_and_context_errors_are_translated_only_for_display(self):
        import backend
        i18n._language = "en"
        error = backend.ContextFull(40000, 32768)
        original = str(error)
        translated = i18n.error_text(error)
        self.assertIn("Context window full:", translated)
        self.assertIn("The request needs 40.000 tokens", translated)
        self.assertEqual(str(error), original)
        self.assertEqual(i18n.error_text("Fehler: missing.txt gibt es nicht."),
                         "Error: missing.txt does not exist.")


if __name__ == "__main__":
    unittest.main()
