"""Tests für app/arbeitsplan.py und app/anweisungen.py: python tests/test_arbeitsplan_anweisungen.py"""
import importlib.util
import shutil
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def load(name):
    spec = importlib.util.spec_from_file_location(name, APP / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


plan, anw = load("arbeitsplan"), load("anweisungen")

# ---- Arbeitsplan
steps = plan.normalize([{"text": "Code lesen", "status": "erledigt"}, {"text": "Fehler beheben", "status": "in_progress"},
                        {"text": "Tests laufen lassen", "status": "offen"}])
assert [s["status"] for s in steps] == ["erledigt", "in_arbeit", "offen"], "englische Status werden übersetzt"
out = plan.render(steps)
assert out.splitlines()[0] == "Arbeitsplan (1/3 erledigt):"
assert "☑ 1. Code lesen" in out and "▶ 2. Fehler beheben" in out and out.endswith("Jetzt: Fehler beheben")
assert plan.render(plan.normalize(["a", "b"])).endswith("Jetzt: a"), "bloße Texte sind offene Schritte"
assert plan.normalize('[{"text": "x", "status": "done"}]')[0]["status"] == "erledigt", "JSON als Text"
assert plan.render(plan.normalize([{"text": "x", "status": "erledigt"}])).endswith("fasse dem Nutzer das Ergebnis zusammen.")
assert plan.current([{"text": "a", "status": "erledigt"}, {"text": "b", "status": "in_arbeit"}]) == "b"
assert plan.current("kaputt [") == "" and plan.current(None) == "", "Kopfzeile verträgt alles"
for bad, hint in (([], "mindestens"), ([{"text": "a", "status": "in_arbeit"}, {"text": "b", "status": "in_arbeit"}], "Nur ein"),
                  ([{"text": "", "status": "offen"}], "Text"), ([{"text": "a", "status": "vielleicht"}], "erlaubt"),
                  (["s"] * 21, "Höchstens")):
    try:
        plan.normalize(bad); raise AssertionError(bad)
    except plan.PlanError as e:
        assert hint in str(e), (hint, str(e))

# ---- Projekt-Anweisungen
tmp = Path(tempfile.mkdtemp())
try:
    a, b, leer = tmp / "a", tmp / "b", tmp / "leer"
    for d in (a, b, leer):
        d.mkdir()
    (a / "CLAUDE.md").write_text("Claude-Regeln", encoding="utf-8")
    (a / "MONHIP.md").write_text("Monhip-Regeln {mit Klammern}", encoding="utf-8")
    (b / "AGENTS.md").write_text("﻿Agenten-Regeln", encoding="utf-8")
    assert anw.prompt_block([leer]) == ""
    block = anw.prompt_block([a, b, leer])
    assert "Monhip-Regeln {mit Klammern}" in block and "Claude-Regeln" not in block, "MONHIP.md hat Vorrang"
    assert "Agenten-Regeln" in block and "﻿" not in block
    anw.MAX_CHARS = 20
    (b / "AGENTS.md").write_text("zeile\n" * 50, encoding="utf-8")
    assert "weiter mit read_file, start_line=4" in anw.prompt_block([b])
    anw.MAX_CHARS, anw.TOTAL_CHARS = 6000, 30
    block = anw.prompt_block([a, b])
    assert "Monhip-Regeln" in block and "Weitere Anweisungen in" in block and "zeile" not in block
    print("alle arbeitsplan- und anweisungen-Tests bestanden")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
