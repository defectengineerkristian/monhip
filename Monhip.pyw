"""Startet Monhip. Der eigentliche Code liegt im Ordner app/."""

import runpy
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent / "app"
sys.path.insert(0, str(APP))
runpy.run_path(str(APP / "monhip.py"), run_name="__main__")
