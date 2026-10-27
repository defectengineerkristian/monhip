"""Tests für app/prozesse.py mit kleinen Python-Programmen statt PowerShell: python tests/test_prozesse.py"""
import importlib.util
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))  # prozesse importiert backend (Job-Objekt)
spec = importlib.util.spec_from_file_location("prozesse", Path(__file__).resolve().parent.parent / "app" / "prozesse.py")
pz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pz)
cwd = tempfile.gettempdir()


def py(code):
    return [sys.executable, "-c", code]


# Kurzer Prozess: Ausgabe und Exit-Code
p = pz.start(py("print('hallo'); import sys; sys.exit(3)"), cwd, "kurz")
p.wait_end(10)
assert not p.running() and "Exit-Code 3" in p.status(), p.status()
assert p.read_new() == "hallo"
assert p.read_new() == "", "schon Gelesenes kommt nicht noch einmal"

# Langer Prozess (wie ein Webserver): läuft weiter, neue Ausgabe nach und nach, Stoppen
code = "import time\nprint('Server auf http://localhost:8000', flush=True)\nfor i in range(100):\n time.sleep(0.2); print('anfrage', i, flush=True)"
s = pz.start(py(code), cwd, "Webserver")
s.wait_end(1)
assert s.running() and "läuft seit" in s.status()
first = s.read_new()
assert first.startswith("Server auf http://localhost:8000"), first
t = time.time()
more = s.read_new(wait=5)
assert "anfrage" in more and time.time() - t < 4, "wartet nur, bis Neues da ist"
assert "[2] Webserver" in pz.listing() and "Laufende" in pz.prompt_block()
s.stop()
assert not s.running()
assert "[2]" not in pz.prompt_block()

# Viel Ausgabe: nur das Neueste, mit Hinweis
pz.READ_CHARS = 100
b = pz.start(py("print('x' * 5000)"), cwd, "viel")
b.wait_end(10)
out = b.read_new()
assert out.startswith("…(ältere Ausgabe ausgelassen)") and len(out) < 200, out[:80]
pz.READ_CHARS = 4000

# Höchstens MAX_RUNNING gleichzeitig
pz.MAX_RUNNING = 1
w = pz.start(py("import time; time.sleep(30)"), cwd, "wartet")
try:
    pz.start(py("pass"), cwd, "zu viel"); raise AssertionError
except pz.ProzessError as e:
    assert "prozess_stoppen" in str(e)
w.stop()
pz.MAX_RUNNING = 5

# Nummern auch als "#2" oder "[2]"; unbekannte Nummer mit Liste
assert pz.get("#2") is s and pz.get("[2]") is s and pz.get(2) is s
try:
    pz.get(99); raise AssertionError
except pz.ProzessError as e:
    assert "Hintergrund-Prozesse" in str(e)

# stop_all beim Beenden der App
x = pz.start(py("import time; time.sleep(30)"), cwd, "läuft noch")
pz.stop_all()
assert not x.running()
print("alle prozesse-Tests bestanden")
