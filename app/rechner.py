"""Exakter Rechner (Werkzeug rechnen): Kleine Modelle verrechnen sich oft – hier rechnet Python, und zwar mit Brüchen
statt Gleitkommazahlen (0.1 + 0.2 = 0.3, nicht 0.30000000000000004). Nur wo es nicht exakt geht (Wurzeln, Logarithmen,
Winkel), wird gerundet und mit „≈“ gekennzeichnet.

Sicher: Ausdrücke werden mit ast geparst und nur erlaubte Knoten ausgewertet – kein eval, keine Attribute, keine
Importe. Riesenzahlen (10**10**10) werden vorher abgelehnt.

Kann: + - * / // mod ** (auch ^), Prozent (19% = 0.19, „19% von 200“), Variablen über mehrere Zeilen, Vergleiche,
kaufmännisches Runden, Statistik, Einheiten, Datumsrechnung, Zinsen und Kreditraten."""

import ast
import math
import re
from datetime import date, timedelta
from fractions import Fraction

MAX_LEN = 4000
MAX_NODES = 1000
MAX_BITS = 200_000          # Zahlen bis etwa 60 000 Stellen
MAX_DIGITS = 60             # längere Ergebnisse als gerundete Zahl mit Stellenzahl
TODAY = None                # für Tests: festes „heute“
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


class RechenError(Exception):
    """Fehler, den das Modell als verständlichen Satz bekommt (wie agent.ToolError)."""


# ---------------------------------------------------------------- Zahlen

def _exact(v) -> Fraction:
    """Gleitkommazahl so, wie sie geschrieben wurde (0.1 → 1/10, nicht 3602879701896397/36028797018963968)."""
    if isinstance(v, Fraction):
        return v
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise RechenError("Hier wird eine Zahl erwartet.")
    if isinstance(v, float) and not math.isfinite(v):
        raise RechenError("Das Ergebnis ist unendlich groß bzw. keine Zahl.")
    return Fraction(repr(v)) if isinstance(v, float) else Fraction(v)


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (Fraction, float)):
        raise RechenError(f"Hier wird eine Zahl erwartet, nicht {_show(v)[0]!r}.")
    return v


def _int(v, what="Wert", lo=None, hi=None) -> int:
    v = _num(v)
    if isinstance(v, float) or v.denominator != 1:
        raise RechenError(f"{what} muss eine ganze Zahl sein.")
    n = int(v)
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        raise RechenError(f"{what} muss zwischen {lo} und {hi} liegen.")
    return n


def _float(v) -> float:
    try:
        return float(_num(v))
    except OverflowError:
        raise RechenError("Die Zahl ist zu groß für diese Funktion.") from None


def _check(v):
    """Riesenzahlen ablehnen – nach jeder Rechenoperation und jedem Funktionsaufruf (z. B. produkt)."""
    if isinstance(v, Fraction) and max(v.numerator.bit_length(), v.denominator.bit_length()) > MAX_BITS:
        raise RechenError("Das Ergebnis wäre zu groß (mehr als etwa 60 000 Stellen).")
    return v


def _approx(x: float):
    if isinstance(x, complex):
        raise RechenError("Das Ergebnis ist keine reelle Zahl (z. B. Wurzel aus einer negativen Zahl).")
    if not math.isfinite(x):
        raise RechenError("Das Ergebnis ist unendlich groß bzw. keine Zahl.")
    return 0.0 if abs(x) < 1e-13 else x  # sin(pi) ist 0, nicht 1.2e-16


def _power(a, b):
    a, b = _num(a), _num(b)
    if isinstance(b, Fraction) and b.denominator == 1 and isinstance(a, Fraction):
        bits = max(a.numerator.bit_length(), a.denominator.bit_length()) * abs(b.numerator)
        if bits > MAX_BITS:
            raise RechenError("Das Ergebnis wäre zu groß (mehr als etwa 60 000 Stellen).")
        if a == 0 and b < 0:
            raise RechenError("Division durch 0.")
        return a ** int(b)
    # 8 ** (2/3) = 4 exakt – nur bei kleinen Wurzelexponenten (wie wurzel), sonst prüft c ** n Riesenzahlen
    if isinstance(b, Fraction) and isinstance(a, Fraction) and a >= 0 and b.denominator <= 1000:
        root = _exact_root(a, b.denominator)
        if root is not None:
            return _power(root, Fraction(b.numerator))
    if a < 0 and (isinstance(b, float) or b.denominator != 1):
        raise RechenError("Negative Zahl hoch Bruch ist keine reelle Zahl – für ungerade Wurzeln wurzel(x, 3).")
    try:
        return _approx(_float(a) ** _float(b))
    except OverflowError:
        raise RechenError("Das Ergebnis wäre zu groß.") from None


def _exact_root(x: Fraction, n: int):
    def iroot(k: int):
        if k < 0:
            return None
        r = round(k ** (1 / n)) if k.bit_length() < 1000 else math.isqrt(k) if n == 2 else None
        if r is None:
            return None
        for c in (r - 1, r, r + 1):
            if c >= 0 and c ** n == k:
                return c
        return None
    num, den = iroot(x.numerator), iroot(x.denominator)
    return Fraction(num, den) if num is not None and den is not None else None


# ---------------------------------------------------------------- Ausgabe

def _group(digits: str, sep: str) -> str:
    sign = "-" if digits.startswith("-") else ""
    digits = digits.lstrip("-")
    out = ""
    while len(digits) > 3:
        digits, out = digits[:-3], sep + digits[-3:] + out
    return sign + digits + out


def _digits(n: int) -> int:
    """Stellenzahl ohne str() – Python wandelt sehr große Zahlen nicht mehr in Text um (Grenze 4300 Stellen)."""
    n = abs(n)
    d = max(1, int(n.bit_length() * 0.30102999566398))
    return d + 1 if n >= 10 ** d else d


def _approx_text(v: Fraction) -> tuple[str, str]:
    """12 gültige Stellen, bei sehr großen bzw. kleinen Zahlen mit Zehnerpotenz – ohne float, also auch für
    Riesenzahlen."""
    if v == 0:
        return "0", "0"
    sign, v = ("-" if v < 0 else ""), abs(v)
    exp10 = _digits(v.numerator) - _digits(v.denominator)
    while True:
        m = round(v * Fraction(10) ** (11 - exp10))
        if m >= 10 ** 12:
            exp10 += 1
        elif m < 10 ** 11:
            exp10 -= 1
        else:
            break
    digits = str(m)
    if -5 <= exp10 < 12:
        if exp10 >= 0:
            head, tail = digits[:exp10 + 1], digits[exp10 + 1:].rstrip("0")
        else:
            head, tail = "0", ("0" * (-exp10 - 1) + digits).rstrip("0")
        return (sign + head + ("." + tail if tail else ""),
                sign + _group(head, ".") + ("," + tail if tail else ""))
    mant = digits[0] + ("." + digits[1:].rstrip("0") if digits[1:].rstrip("0") else "")
    return f"{sign}{mant}e{exp10:+d}", f"{sign}{mant.replace('.', ',')}e{exp10:+d}"


def _show(v) -> tuple[str, str, str]:
    """(international, deutsch, Hinweis) – z. B. ('1234.5', '1.234,5', ''), ungefähre Werte mit '≈'."""
    if isinstance(v, bool):
        return ("wahr" if v else "falsch"), ("wahr" if v else "falsch"), ""
    if isinstance(v, str):
        return v, v, ""
    if isinstance(v, list):
        shown = [_show(x) for x in v]
        return "[" + ", ".join(s[0] for s in shown) + "]", "[" + "; ".join(s[1] for s in shown) + "]", ""
    if isinstance(v, float):
        en, de = _approx_text(Fraction(v))
        return "≈ " + en, "≈ " + de, ""
    if v.denominator == 1:
        if _digits(v.numerator) > MAX_DIGITS:
            en, de = _approx_text(v)
            return "≈ " + en, "≈ " + de, f"ganze Zahl mit {_digits(v.numerator)} Stellen"
        en = str(v.numerator)
        return en, _group(en, "."), ""
    d, twos, fives = v.denominator, 0, 0
    while d % 2 == 0:
        d, twos = d // 2, twos + 1
    while d % 5 == 0:
        d, fives = d // 5, fives + 1
    places = max(twos, fives)
    if d == 1 and places <= 30 and _digits(v.numerator) <= MAX_DIGITS:  # endliche Dezimalzahl: exakt ausschreiben
        scaled = abs(v.numerator) * 10 ** places // v.denominator
        head, tail = divmod(scaled, 10 ** places)
        tail = str(tail).rjust(places, "0").rstrip("0")
        sign = "-" if v < 0 else ""
        return f"{sign}{head}.{tail}", f"{sign}{_group(str(head), '.')},{tail}", ""
    small = v.denominator < 10 ** 9 and _digits(v.numerator) <= 30
    en, de = _approx_text(v)
    return "≈ " + en, "≈ " + de, f"exakt {v.numerator}/{v.denominator}" if small else ""


def _line(name: str, v) -> str:
    en, de, note = _show(v)
    sep = " " if en.startswith("≈") else " = "
    extra = [f"deutsch: {de.removeprefix('≈ ')}"] if de != en else []
    if note:
        extra.append(note)
    return f"{name}{sep}{en}" + (f"  ({'; '.join(extra)})" if extra else "")


# ---------------------------------------------------------------- Funktionen

def _values(args) -> list:
    out = []
    for a in args:
        out += [_num(x) for x in a] if isinstance(a, list) else [_num(a)]
    if not out:
        raise RechenError("Keine Werte angegeben.")
    return out


def _runden(x, n=Fraction(0)):
    """Kaufmännisch: 2.675 → 2.68, 2.5 → 3, -2.5 → -3 (Pythons round rundet 2.5 auf 2)."""
    n = _int(n, "Stellen", -15, 30)
    x = _exact(_num(x))
    q = Fraction(10) ** n
    r = math.floor(abs(x) * q + Fraction(1, 2))
    return Fraction(r) / q * (1 if x >= 0 else -1)


def _abrunden(x, n=Fraction(0)):
    q = Fraction(10) ** _int(n, "Stellen", -15, 30)
    return Fraction(math.floor(_exact(_num(x)) * q)) / q


def _aufrunden(x, n=Fraction(0)):
    q = Fraction(10) ** _int(n, "Stellen", -15, 30)
    return Fraction(math.ceil(_exact(_num(x)) * q)) / q


def _wurzel(x, n=Fraction(2)):
    x, n = _num(x), _int(n, "Wurzelexponent", 2, 1000)
    if x < 0:
        if n % 2 == 0:
            raise RechenError("Gerade Wurzel aus einer negativen Zahl ist keine reelle Zahl.")
        return -_wurzel(-x, Fraction(n))
    if isinstance(x, Fraction):
        exact = _exact_root(x, n)
        if exact is not None:
            return exact
    return _approx(_float(x) ** (1 / n))


def _log(x, basis=None):
    if basis is None:
        raise RechenError("log braucht eine Basis: ln(x) natürlich, log10(x) bzw. lg(x) zur Basis 10, log(x, 2) "
                          "zur Basis 2.")
    x, b = _num(x), _num(basis)
    if x <= 0 or b <= 0 or b == 1:
        raise RechenError("Logarithmus nur für positive Zahlen und eine Basis > 0 und ≠ 1.")
    r = math.log(_float(x)) / math.log(_float(b))
    k = round(r)
    if isinstance(x, Fraction) and isinstance(b, Fraction) and abs(k) < 10_000 and _power(b, Fraction(k)) == x:
        return Fraction(k)  # log(8, 2) = 3 exakt
    return _approx(r)


def _ln(x):
    if _num(x) <= 0:
        raise RechenError("ln nur für positive Zahlen.")
    return Fraction(0) if x == 1 else _approx(math.log(_float(x)))


def _sum(v: list):
    return sum(v[1:], v[0])  # Startwert v[0], damit Brüche Brüche bleiben


def _produkt(*args):
    out = Fraction(1)
    for x in _values(args):
        out = _check(out * x)  # schrittweise, sonst entsteht die Riesenzahl erst ganz
    return out


def _mean(*args):
    v = _values(args)
    return _sum(v) / len(v)


def _median(*args):
    v = sorted(_values(args))
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


def _stdabw(*args):
    """Stichproben-Standardabweichung (n − 1), wie STABW.S in Excel."""
    v = _values(args)
    if len(v) < 2:
        raise RechenError("stdabw braucht mindestens zwei Werte.")
    m = _mean(v)
    return _wurzel(sum(((x - m) ** 2 for x in v[1:]), (v[0] - m) ** 2) / (len(v) - 1))


def _trig(fn):
    return lambda x: _approx(fn(_float(x)))


def _fak(n):
    return Fraction(math.factorial(_int(n, "n", 0, 5000)))


def _binom(n, k):
    return Fraction(math.comb(_int(n, "n", 0, 100_000), _int(k, "k", 0, 100_000)))


def _ggt(*args):
    return Fraction(math.gcd(*[_int(a, "ggt-Wert") for a in _values(args)]))


def _kgv(*args):
    return Fraction(math.lcm(*[_int(a, "kgv-Wert") for a in _values(args)]))


def _prozent_von(p, wert):
    return _num(wert) * _num(p) / 100


def _prozentsatz(teil, ganzes):
    if _num(ganzes) == 0:
        raise RechenError("Division durch 0.")
    return _num(teil) / ganzes * 100


def _aenderung(alt, neu):
    if _num(alt) == 0:
        raise RechenError("Von 0 aus gibt es keine prozentuale Änderung.")
    return (_num(neu) - alt) / abs(alt) * 100


def _netto(brutto, satz=Fraction(19)):
    return _num(brutto) / (1 + _num(satz) / 100)


def _brutto(netto, satz=Fraction(19)):
    return _num(netto) * (1 + _num(satz) / 100)


def _zinseszins(kapital, zins, jahre):
    return _num(kapital) * _power(1 + _num(zins) / 100, _num(jahre))


def _kreditrate(betrag, zins_pa, monate):
    """Monatliche Rate eines Annuitätendarlehens."""
    b, n = _num(betrag), _int(monate, "monate", 1, 1200)
    i = _num(zins_pa) / 1200
    if i == 0:
        return b / n
    return b * i / (1 - _power(1 + i, Fraction(-n)))


# ---- Einheiten (Faktor zur Grundeinheit, exakt)

def _units() -> dict:
    table = {
        "Länge": {"mm": "0.001", "cm": "0.01", "dm": "0.1", "m": "1", "km": "1000", "in": "0.0254",
                  "zoll": "0.0254", "ft": "0.3048", "fuß": "0.3048", "yd": "0.9144", "mi": "1609.344",
                  "meile": "1609.344", "sm": "1852", "seemeile": "1852"},
        "Fläche": {"mm²": "0.000001", "cm²": "0.0001", "m²": "1", "a": "100", "ar": "100", "ha": "10000",
                   "km²": "1000000", "ft²": "0.09290304", "acre": "4046.8564224"},
        "Volumen": {"ml": "0.001", "cl": "0.01", "dl": "0.1", "l": "1", "hl": "100", "cm³": "0.001",
                    "m³": "1000", "gal": "3.785411784", "floz": "0.0295735295625"},
        "Masse": {"mg": "0.000001", "g": "0.001", "kg": "1", "t": "1000", "lb": "0.45359237",
                  "pfund": "0.5", "oz": "0.028349523125"},
        "Zeit": {"ms": "0.001", "s": "1", "min": "60", "h": "3600", "std": "3600", "tag": "86400", "d": "86400",
                 "woche": "604800", "jahr": "31536000"},
        "Geschwindigkeit": {"m/s": "1", "km/h": "5/18", "mph": "0.44704", "kn": "463/900", "knoten": "463/900"},
        "Datenmenge": {"bit": "0.125", "byte": "1", "kb": "1000", "mb": "1000000", "gb": "1000000000",
                       "tb": "1000000000000", "kib": "1024", "mib": "1048576", "gib": "1073741824",
                       "tib": "1099511627776"},
        "Energie": {"j": "1", "kj": "1000", "mj": "1000000", "wh": "3600", "kwh": "3600000", "cal": "4.184",
                    "kcal": "4184"},
        "Leistung": {"w": "1", "kw": "1000", "mw": "1000000", "ps": "735.49875"},
        "Druck": {"pa": "1", "hpa": "100", "kpa": "1000", "bar": "100000", "mbar": "100", "psi": "6894.757293168"},
    }
    out = {}
    for dim, units in table.items():
        for name, factor in units.items():
            out[name] = (dim, Fraction(factor))
    for a, b in (("m2", "m²"), ("cm2", "cm²"), ("mm2", "mm²"), ("km2", "km²"), ("qm", "m²"), ("m3", "m³"),
                 ("cm3", "cm³"), ("liter", "l"), ("sek", "s"), ("sekunde", "s"), ("minute", "min"),
                 ("stunde", "h"), ("tage", "tag"), ("wochen", "woche"), ("jahre", "jahr"), ("b", "byte"),
                 ("tonne", "t"), ("gramm", "g"), ("meter", "m"), ("kilometer", "km"), ("ft2", "ft²")):
        out[a] = out[b]
    return out


UNITS = _units()
TEMPS = {"c": "°C", "°c": "°C", "celsius": "°C", "f": "°F", "°f": "°F", "fahrenheit": "°F", "k": "K",
         "kelvin": "K"}


def _einheit(wert, von, nach):
    if not isinstance(von, str) or not isinstance(nach, str):
        raise RechenError("Einheiten als Text in Anführungszeichen: einheit(5, 'km', 'mi').")
    x = _num(wert)
    a, b = von.strip().lower().replace(" ", ""), nach.strip().lower().replace(" ", "")
    if a in TEMPS or b in TEMPS:
        if a not in TEMPS or b not in TEMPS:
            raise RechenError("Temperatur nur in °C, °F oder K umrechnen.")
        a, b = TEMPS[a], TEMPS[b]
        k = {"°C": lambda v: v + Fraction("273.15"), "°F": lambda v: (v - 32) * Fraction(5, 9) + Fraction("273.15"),
             "K": lambda v: v}[a](x)
        return {"°C": lambda v: v - Fraction("273.15"), "°F": lambda v: (v - Fraction("273.15")) * Fraction(9, 5) + 32,
                "K": lambda v: v}[b](k)
    for u in (a, b):
        if u not in UNITS:
            raise RechenError(f"Einheit '{u}' kenne ich nicht. Bekannt: "
                              + ", ".join(sorted({n for n in UNITS if not n.isascii() or len(n) <= 4})) + ".")
    (da, fa), (db, fb) = UNITS[a], UNITS[b]
    if da != db:
        raise RechenError(f"{von} ({da}) lässt sich nicht in {nach} ({db}) umrechnen.")
    return x * fa / fb


# ---- Datum

def _today() -> date:
    return TODAY or date.today()


def _date(s) -> date:
    if not isinstance(s, str):
        raise RechenError("Daten als Text in Anführungszeichen: '24.12.2026' oder '2026-12-24'.")
    t = s.strip().lower()
    special = {"heute": 0, "morgen": 1, "übermorgen": 2, "gestern": -1}
    if t in special:
        return _today() + timedelta(days=special[t])
    try:
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})?", t)
        if m:
            year = int(m.group(3)) if m.group(3) else _today().year
            return date(year + 2000 if year < 100 else year, int(m.group(2)), int(m.group(1)))
        m = re.fullmatch(r"(?:[a-z]+,\s*)?(\d{4})-(\d{1,2})-(\d{1,2})", t)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"[a-z]{2},\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", t)  # eigene Ausgabe „Do, 24.12.2026“
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        raise RechenError(f"Das Datum '{s}' gibt es nicht.") from None
    raise RechenError(f"Datum '{s}' verstehe ich nicht – z. B. '24.12.2026', '2026-12-24' oder 'heute'.")


def _show_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()][:2]}, {d.day:02d}.{d.month:02d}.{d.year}"


def _tage(a, b=None):
    """Tage von a bis b (mit einem Datum: von heute bis dahin)."""
    start, end = (_today(), _date(a)) if b is None else (_date(a), _date(b))
    return Fraction((end - start).days)


def _datum_plus(d, tage):
    try:
        return _show_date(_date(d) + timedelta(days=_int(tage, "tage", -1_000_000, 1_000_000)))
    except OverflowError:
        raise RechenError("Das Datum liegt außerhalb des Kalenders.") from None


def _monate_plus(d, monate):
    """Monate addieren – am Monatsende auf den letzten Tag (31.01. + 1 Monat = 28.02.)."""
    start, n = _date(d), _int(monate, "monate", -12000, 12000)
    month = start.month - 1 + n
    year, month = start.year + month // 12, month % 12 + 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return _show_date(date(year, month, min(start.day, last)))


def _wochentag(d):
    return WEEKDAYS[_date(d).weekday()]


def _arbeitstage(a, b):
    """Montag bis Freitag von a bis b, beide mitgezählt (Feiertage nicht berücksichtigt)."""
    start, end = _date(a), _date(b)
    if end < start:
        start, end = end, start
    days = (end - start).days + 1
    weeks, rest = divmod(days, 7)
    return Fraction(weeks * 5 + sum((start.weekday() + i) % 7 < 5 for i in range(rest)))


def _alter(geburt, stichtag="heute"):
    g, s = _date(geburt), _date(stichtag)
    return Fraction(s.year - g.year - ((s.month, s.day) < (g.month, g.day)))


FUNCS = {
    "wurzel": _wurzel, "sqrt": _wurzel, "abs": lambda x: abs(_num(x)), "betrag": lambda x: abs(_num(x)),
    "runden": _runden, "round": _runden, "abrunden": _abrunden, "floor": _abrunden, "aufrunden": _aufrunden,
    "ceil": _aufrunden, "ln": _ln, "log": _log, "log10": lambda x: _log(x, Fraction(10)),
    "lg": lambda x: _log(x, Fraction(10)), "log2": lambda x: _log(x, Fraction(2)),
    "exp": lambda x: _approx(math.exp(_float(x))) if _num(x) != 0 else Fraction(1),
    "sin": _trig(math.sin), "cos": _trig(math.cos), "tan": _trig(math.tan), "asin": _trig(math.asin),
    "acos": _trig(math.acos), "atan": _trig(math.atan),
    "grad": lambda x: _approx(math.degrees(_float(x))), "rad": lambda x: _approx(math.radians(_float(x))),
    "fak": _fak, "fakultaet": _fak, "factorial": _fak, "binom": _binom, "ggt": _ggt, "gcd": _ggt, "kgv": _kgv,
    "lcm": _kgv, "min": lambda *a: min(_values(a)), "max": lambda *a: max(_values(a)),
    "summe": lambda *a: _sum(_values(a)), "sum": lambda *a: _sum(_values(a)),
    "produkt": _produkt, "mittelwert": _mean, "mean": _mean, "median": _median,
    "stdabw": _stdabw,
    "prozent_von": _prozent_von, "prozentsatz": _prozentsatz, "aenderung": _aenderung, "netto": _netto,
    "brutto": _brutto, "zinseszins": _zinseszins, "kreditrate": _kreditrate, "einheit": _einheit,
    "tage": _tage, "datum_plus": _datum_plus, "monate_plus": _monate_plus, "wochentag": _wochentag,
    "arbeitstage": _arbeitstage, "alter": _alter, "heute": lambda: _show_date(_today()),
}
CONSTS = {"pi": math.pi, "e": math.e}


# ---------------------------------------------------------------- Auswerten

def _prepare(text: str) -> str:
    """Schreibweisen von Menschen und Modellen in Python übersetzen: ^ → **, ×/· → *, „19% von 200“, 19% → (19/100)."""
    t = text.replace("×", "*").replace("·", "*").replace("÷", "/").replace("−", "-").replace("^", "**")
    t = re.sub(r"\bmod\b", "%", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*von\b", r"(\1/100)*", t)
    return re.sub(r"(\d+(?:\.\d+)?|\b[a-zA-Z_]\w*)[ \t]*%(?![ \t]*[\w(.\[])", r"(\1/100)", t)


class _Eval:
    OPS = {ast.Add: lambda a, b: _num(a) + _num(b), ast.Sub: lambda a, b: _num(a) - _num(b),
           ast.Mult: lambda a, b: _num(a) * _num(b), ast.Div: lambda a, b: _num(a) / _num(b),
           ast.FloorDiv: lambda a, b: Fraction(math.floor(_num(a) / _num(b))),
           ast.Mod: lambda a, b: _num(a) % _num(b), ast.Pow: _power}
    CMP = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: _num(a) < _num(b),
           ast.LtE: lambda a, b: _num(a) <= _num(b), ast.Gt: lambda a, b: _num(a) > _num(b),
           ast.GtE: lambda a, b: _num(a) >= _num(b)}

    def __init__(self):
        self.vars: dict = {}

    def run(self, node, top=False):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float, str)):
                raise RechenError(f"{node.value!r} ist hier nicht erlaubt.")
            return node.value if isinstance(node.value, str) else _exact(node.value)
        if isinstance(node, ast.Name):
            if node.id in self.vars:
                return self.vars[node.id]
            if node.id in CONSTS:
                return CONSTS[node.id]
            if node.id in FUNCS:
                raise RechenError(f"{node.id} ist eine Funktion – mit Klammern aufrufen: {node.id}(…).")
            raise RechenError(f"'{node.id}' ist unbekannt – Variablen erst zuweisen (z. B. {node.id} = 5).")
        if isinstance(node, ast.BinOp) and type(node.op) in self.OPS:
            try:
                return _check(self.OPS[type(node.op)](self.run(node.left), self.run(node.right)))
            except ZeroDivisionError:
                raise RechenError("Division durch 0.") from None
            except OverflowError:
                raise RechenError("Das Ergebnis wäre zu groß.") from None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = _num(self.run(node.operand))
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Compare):
            left, result = self.run(node.left), True
            for op, right_node in zip(node.ops, node.comparators):
                if type(op) not in self.CMP:
                    raise RechenError("Nur Vergleiche mit ==, !=, <, <=, >, >= sind erlaubt.")
                right = self.run(right_node)
                result = result and self.CMP[type(op)](left, right)
                left = right
            return result
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
                name = node.func.id if isinstance(node.func, ast.Name) else "?"
                # die Werkzeug-Beschreibung nennt nur die wichtigsten Funktionen (spart Tokens) – hier alle
                raise RechenError(f"Die Funktion '{name}' gibt es nicht. Verfügbar: {', '.join(sorted(FUNCS))}.")
            if node.keywords:
                raise RechenError(f"Argumente ohne name= angeben: {node.func.id}(…).")
            args = [self.run(a) for a in node.args]
            try:
                return _check(FUNCS[node.func.id](*args))
            except TypeError:
                raise RechenError(f"Falsche Anzahl Argumente für {node.func.id}(…).") from None
            except ValueError:
                raise RechenError(f"{node.func.id}: Wert außerhalb des erlaubten Bereichs.") from None
            except OverflowError:
                raise RechenError(f"{node.func.id}: Das Ergebnis wäre zu groß.") from None
        if isinstance(node, ast.List) or (isinstance(node, ast.Tuple) and not top):
            return [self.run(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            raise RechenError("Komma als Dezimaltrenner? Bitte Dezimalpunkt verwenden (1.5 statt 1,5) – Kommas "
                              "trennen nur Funktionsargumente.")
        raise RechenError(f"Das ist im Rechner nicht erlaubt: {type(node).__name__}.")


def rechnen(ausdruck: str) -> str:
    """Ausdruck bzw. mehrere Zeilen mit Zuweisungen auswerten. → Text fürs Modell, letzte Zeile = Ergebnis."""
    text = str(ausdruck or "").strip()
    if not text:
        raise RechenError("ausdruck ist leer.")
    if len(text) > MAX_LEN:
        raise RechenError(f"Höchstens {MAX_LEN} Zeichen.")
    prepared = _prepare(text)
    parts = [p.strip() for p in re.split(r"[;\n]", prepared) if p.strip()]
    try:
        tree = ast.parse("\n".join(parts), mode="exec")
    except SyntaxError as e:
        hint = " (Dezimalpunkt statt Komma?)" if re.search(r"\d,\d", text) else ""
        raise RechenError(f"Kann den Ausdruck nicht lesen{hint}: {e.msg}, Zeile {e.lineno}.") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise RechenError("Der Ausdruck ist zu lang – in mehrere Schritte aufteilen.")
    ev, lines, result = _Eval(), [], None
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            name = stmt.targets[0].id  # eigener Namensraum: netto = 1200 und netto(119) gehen beide
            if name.startswith("_"):
                raise RechenError(f"'{name}' ist als Variablenname nicht erlaubt.")
            result = ev.vars[name] = ev.run(stmt.value, top=True)
            lines.append(_line(name, result))
        elif isinstance(stmt, ast.Expr):
            result = ev.run(stmt.value, top=True)
        else:
            raise RechenError("Erlaubt sind nur Ausdrücke und Zuweisungen wie netto = 1200.")
    # nur wenn umgeschrieben wurde (19% → (19/100) …), damit das Modell sieht, wie es verstanden wurde
    head = [f"Gerechnet als: {'; '.join(parts)}"] if prepared != text else []
    if isinstance(tree.body[-1], ast.Expr) or len(lines) > 1:
        lines.append(_line("Ergebnis:", result).replace("Ergebnis: = ", "Ergebnis: "))
    return "\n".join(head + lines)
