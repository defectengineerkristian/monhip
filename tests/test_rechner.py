"""Tests für app/rechner.py: python tests/test_rechner.py"""
import importlib.util
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location("rechner", Path(__file__).resolve().parent.parent / "app" / "rechner.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
r.TODAY = date(2026, 10, 27)  # ein Dienstag


def result(expr: str) -> str:
    """Nur das Ergebnis, wie es das Modell liest (ohne deutsche Schreibweise und Hinweise)."""
    last = r.rechnen(expr).splitlines()[-1]
    return last.split(":", 1)[1].split("  (")[0].strip() if last.startswith("Ergebnis") else last


def fails(expr: str, hint: str):
    try:
        r.rechnen(expr)
    except r.RechenError as e:
        assert hint in str(e), (expr, str(e))
        return
    raise AssertionError(f"kein Fehler bei {expr!r}")


# ---- exakt statt Gleitkomma
assert result("0.1 + 0.2") == "0.3"
assert result("0.1 + 0.2 == 0.3") == "wahr"
assert result("summe(0.1, 0.2, 0.3)") == "0.6"
assert result("2/3 * 3") == "2"
assert result("123456789 * 987654321") == "121932631112635269"
assert result("1e-20 * 3") == "0.00000000000000000003"
out = r.rechnen("1/3")
assert "≈ 0.333333333333" in out and "exakt 1/3" in out and "deutsch: 0,333333333333" in out

# ---- Schreibweisen von Menschen und Modellen
assert result("1200 * 19%") == "228" and "Gerechnet als: 1200 * (19/100)" in r.rechnen("1200 * 19%")
assert result("19% von 200") == "38"
assert result("2^10") == "1024" and result("2 × 3 · 4") == "24" and result("10 mod 3") == "1"
assert result("10 % 3") == "1", "% mit Zahl dahinter bleibt Modulo"
assert result("-3 % 5") == "2" and result("7 // 2") == "3"
assert result("netto = 1200\nmwst = netto * 19%\nnetto + mwst") == "1428"
assert result("a = 2; b = a ^ 3;  b + 1") == "9", "Leerzeichen nach ; sind egal"
assert result("netto = 119\nnetto(netto)") == "100", "Variablen und Funktionen getrennt"
assert "deutsch: 1.234.567,891" in r.rechnen("1234567.891")
lines = r.rechnen("netto = 1200\nmwst = netto * 19%\nnetto + mwst").splitlines()
assert lines == ["Gerechnet als: netto = 1200; mwst = netto * (19/100); netto + mwst",
                 "netto = 1200  (deutsch: 1.200)", "mwst = 228", "Ergebnis: 1428  (deutsch: 1.428)"], lines
assert r.rechnen("x = 5") == "x = 5", "eine Zuweisung: keine doppelte Ergebniszeile"

# ---- Runden (kaufmännisch, nicht wie Pythons round)
assert result("runden(2.675, 2)") == "2.68" and result("runden(2.5)") == "3" and result("round(0.5)") == "1"
assert result("runden(-2.5)") == "-3" and result("runden(1234.5, -2)") == "1200"
assert result("abrunden(2.99)") == "2" and result("aufrunden(2.01)") == "3" and result("aufrunden(1.231, 2)") == "1.24"

# ---- Potenzen, Wurzeln, Logarithmen, Winkel
assert result("8 ** (2/3)") == "4" and result("wurzel(16)") == "4" and result("wurzel(-8, 3)") == "-2"
assert result("wurzel(2)") == "≈ 1.41421356237" and result("2 ** 0.5") == "≈ 1.41421356237"
assert result("wurzel(9/4)") == "1.5" and result("2 ** -2") == "0.25"
assert result("log(8, 2)") == "3" and result("log10(1000)") == "3" and result("ln(1)") == "0"
assert result("sin(pi)") == "≈ 0" and result("sin(rad(30))") == "≈ 0.5" and result("grad(pi)") == "≈ 180"
assert result("fak(5)") == "120" and result("binom(49, 6)") == "13983816"
assert result("ggt(12, 18)") == "6" and result("kgv(4, 6)") == "12"
big = r.rechnen("2 ** 1000")
assert "≈ 1.07150860719e+301" in big and "302 Stellen" in big
assert "4300" not in r.rechnen("fak(3000)"), "Riesenzahlen ohne Pythons Text-Grenze"

# ---- Statistik und Prozent
assert result("mittelwert(1, 2, 3, 4)") == "2.5" and result("median([3, 1, 2])") == "2"
assert result("median(1, 2, 3, 4)") == "2.5" and result("min(3, 1.5, 2)") == "1.5" and result("max([1, 7], 3)") == "7"
assert result("stdabw(2, 4, 4, 4, 5, 5, 7, 9)") == "≈ 2.1380899353"
assert result("prozent_von(19, 200)") == "38" and result("prozentsatz(38, 200)") == "19"
assert result("aenderung(80, 100)") == "25" and result("aenderung(100, 80)") == "-20"
assert result("netto(119)") == "100" and result("brutto(100, 7)") == "107"
assert result("zinseszins(1000, 5, 2)") == "1102.5"
assert result("runden(kreditrate(200000, 3.5, 360), 2)") == "898.09"
assert result("kreditrate(1200, 0, 12)") == "100"

# ---- Einheiten
assert result("einheit(0, '°C', '°F')") == "32" and result("einheit(100, 'C', 'K')") == "373.15"
assert result("einheit(98.6, 'F', 'C')") == "37"
assert result("einheit(1, 'GiB', 'MB')") == "1073.741824" and result("einheit(8, 'bit', 'B')") == "1"
assert "exakt 250/9" in r.rechnen("einheit(100, 'km/h', 'm/s')")
assert result("einheit(1, 'mi', 'km')") == "1.609344" and result("einheit(2, 'h', 'min')") == "120"
assert result("einheit(1, 'kWh', 'J')") == "3600000" and result("einheit(1, 'ha', 'm2')") == "10000"

# ---- Datum (heute = Di, 27.10.2026)
assert result("tage('27.10.2026', '24.12.2026')") == "58" and result("tage('24.12.')") == "58"
assert result("tage('2026-12-24', '27.10.2026')") == "-58"
assert result("wochentag('24.12.2026')") == "Donnerstag" and result("wochentag('heute')") == "Dienstag"
assert result("datum_plus('heute', 30)") == "Do, 26.11.2026"
assert result("datum_plus(datum_plus('1.3.2026', -1), 0)") == "Sa, 28.02.2026", "eigene Ausgabe wieder lesbar"
assert result("monate_plus('31.1.2026', 1)") == "Sa, 28.02.2026" and result("monate_plus('31.1.2028', 1)") == "Di, 29.02.2028"
assert result("monate_plus('15.11.2026', 3)") == "Mo, 15.02.2027" and result("monate_plus('15.1.2026', -1)") == "Mo, 15.12.2025"
assert result("arbeitstage('26.10.2026', '6.11.2026')") == "10" and result("arbeitstage('31.10.2026', '1.11.2026')") == "0"
assert result("alter('15.6.2000')") == "26" and result("alter('28.10.2000')") == "25"

# ---- Fehler: verständlich, nichts Gefährliches
for expr, hint in (("1,5 * 2", "Dezimalpunkt"), ("1/0", "Division durch 0"), ("10 ** 10 ** 10", "zu groß"),
                   ("9 ** 9 ** 9", "zu groß"), ("2 ** -1000000", "zu groß"), ("__import__('os')", "gibt es nicht"),
                   ("open('x')", "gibt es nicht"), ("(1).__class__", "nicht erlaubt"), ("lambda: 1", "nicht erlaubt"),
                   ("[x for x in [1]]", "nicht erlaubt"), ("x + 1", "unbekannt"), ("sum", "mit Klammern"),
                   ("log(8)", "Basis"), ("wurzel(-4)", "keine reelle Zahl"), ("(-8) ** (1/2)", "keine reelle Zahl"),
                   ("einheit(1, 'km', 'kg')", "nicht in kg"), ("einheit(1, 'parsec', 'km')", "kenne ich nicht"),
                   ("tage('31.2.2026')", "gibt es nicht"), ("tage('morgen früh')", "verstehe ich nicht"),
                   ("fak(2.5)", "ganze Zahl"), ("asin(2)", "außerhalb"), ("'a' + 1", "Zahl erwartet"), ("", "leer"),
                   ("a = 1; b = a +", "nicht lesen"), ("_x = 1", "nicht erlaubt"), ("x += 1", "nur Ausdrücke"),
                   ("max(key=1)", "ohne name="), ("wurzel()", "Anzahl Argumente"), ("1" * 5000, "Höchstens"),
                   ("+".join(["1"] * 600), "zu lang"), ("1e999", "unendlich"), ("2 ** 100000 * 2 ** 100000 * 2 ** 100000",
                                                                            "zu groß")):
    fails(expr, hint)
print("alle rechner-Tests bestanden")
