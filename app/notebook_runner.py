"""Führt ein Jupyter-Notebook aus – gestartet von Monhip (notebook.execute) mit dem Python des Nutzers, in dem Jupyter
installiert ist (Monhip selbst braucht dafür nichts). Läuft auch mit älteren Python-Versionen (ab 3.8).

    python notebook_runner.py <notebook> <ziel> <bis_zelle> <zeitlimit>

Von oben in einem frischen Kernel, wie „Restart Kernel and Run All“ in Jupyter; hält an der ersten Zelle mit Fehler.
bis_zelle 0 = alle. Das Ergebnis kommt nach <ziel> (Monhip übernimmt es erst danach – mit Checkpoint). Lässt sich der
Kernel aus dem Notebook nicht starten (anderer Rechner, kaputte Kernel-Angabe), läuft es mit diesem Python als Kernel.
Letzte Zeile der Ausgabe: JSON {"ok", "kernel", "executed", "error_cell", "error", "note"}."""

import json
import os
import shutil
import sys
import tempfile


class StartError(Exception):
    """Der Kernel ließ sich nicht starten (noch keine Zelle gelaufen)."""


def run(nb, kernel_name, until, timeout, folder, status):
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError

    client = NotebookClient(nb, timeout=timeout, kernel_name=kernel_name, allow_errors=False, record_timing=False,
                            resources={"metadata": {"path": folder}})
    started = False
    try:
        with client.setup_kernel():
            started = True
            for index, cell in enumerate(nb.cells[:until] if until > 0 else nb.cells):
                try:
                    client.execute_cell(cell, index)
                except CellExecutionError:
                    status.update(ok=False, error_cell=index + 1, error="")  # Meldung steht in der Ausgabe der Zelle
                    return
                except Exception as e:  # Zeitlimit, Kernel abgestürzt …
                    status.update(ok=False, error_cell=index + 1, error="%s: %s" % (type(e).__name__, e))
                    return
                finally:
                    status["executed"] = index + 1
    except Exception as e:
        if not started:
            raise StartError("%s: %s" % (type(e).__name__, e)) from e
        if status["ok"]:  # beim Beenden des Kernels – die Zellen sind gelaufen
            status["note"] = "Kernel nicht sauber beendet: %s" % e


def own_kernel():
    """Kernel-Angabe für genau dieses Python in einem eigenen Ordner (JUPYTER_PATH hat Vorrang)."""
    folder = tempfile.mkdtemp(prefix="monhip-kernel-")
    spec = os.path.join(folder, "kernels", "monhip-python")
    os.makedirs(spec)
    with open(os.path.join(spec, "kernel.json"), "w", encoding="utf-8") as f:
        json.dump({"argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                   "display_name": "Python (Monhip)", "language": "python"}, f)
    os.environ["JUPYTER_PATH"] = os.pathsep.join(filter(None, [folder, os.environ.get("JUPYTER_PATH")]))
    return folder


def main():
    source, target, until, timeout = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    os.environ.setdefault("PYDEVD_DISABLE_FILE_VALIDATION", "1")  # Debugger-Warnung des Kernels bei jedem Start
    import nbformat

    nb = nbformat.read(source, as_version=4)
    wanted = (nb.metadata.get("kernelspec") or {}).get("name") or ""
    status = {"ok": True, "kernel": wanted or "python3", "executed": 0, "error_cell": None, "error": "", "note": ""}
    folder = os.path.dirname(os.path.abspath(source))
    extra = None
    try:
        try:
            run(nb, wanted, until, timeout, folder, status)
        except StartError as e:
            extra = own_kernel()
            status.update(kernel="monhip-python", note="Kernel %r ließ sich nicht starten (%s) – ausgeführt mit %s"
                          % (wanted or "python3", str(e)[:300], sys.executable))
            try:
                run(nb, "monhip-python", until, timeout, folder, status)
            except StartError as e2:
                status.update(ok=False, error="Kernel startet nicht: %s" % e2)
    finally:
        if extra:
            shutil.rmtree(extra, ignore_errors=True)
    nbformat.write(nb, target)
    print(json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
