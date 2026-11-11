"""Browser in der Seitenleiste (app/browser.py, app/browserpanel.py, Werkzeuge in app/agent.py) ohne pywebview und
ohne Netz: Adressen, Aufbereitung einer Seite fürs Modell, das Protokoll mit einem Ersatz-Browser-Prozess, das Warten
auf den Nutzer und die Werkzeuge des Modells: python -m unittest discover -s progress/tests -p test_browser.py"""

import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import agent
import browser
import browserpanel

PAGE = {"url": "https://example.org/login", "title": "Anmelden", "text": "Willkommen\n\n\n\nBitte anmelden.",
        "items": [{"nr": 1, "kind": "link", "label": "Startseite", "value": "", "href": "https://example.org/",
                   "checked": None},
                  {"nr": 2, "kind": "field", "label": "E-Mail", "value": "a@b.de", "href": "", "checked": None},
                  {"nr": 3, "kind": "password", "label": "Passwort", "value": "", "href": "", "checked": None},
                  {"nr": 4, "kind": "checkbox", "label": "Angemeldet bleiben", "value": "", "href": "",
                   "checked": True},
                  {"nr": 5, "kind": "button", "label": "Anmelden", "value": "", "href": "", "checked": None}],
        "captcha": True, "password": True}


class Urls(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(browser.normalize_url("example.org/a?b=1"), "https://example.org/a?b=1")
        self.assertEqual(browser.normalize_url(" HTTP://x.de "), "HTTP://x.de")
        self.assertEqual(browser.normalize_url("localhost:8000/app"), "http://localhost:8000/app")
        self.assertEqual(browser.normalize_url("127.0.0.1"), "http://127.0.0.1")

    def test_only_http(self):
        for bad in ("", "javascript:alert(1)", "file:///C:/Windows/win.ini", "data:text/html,<b>x</b>"):
            with self.subTest(url=bad), self.assertRaises(browser.BrowserError):
                browser.normalize_url(bad)


class PageText(unittest.TestCase):
    def test_controls_and_hints(self):
        out = browser.page_text(PAGE)
        self.assertTrue(out.startswith("Seite: Anmelden\nAdresse: https://example.org/login\n\nWillkommen\n\nBitte"))
        self.assertIn("[1] Link: Startseite", out)
        self.assertIn("[2] Eingabefeld: E-Mail (Inhalt: a@b.de)", out)
        self.assertIn("[3] Passwortfeld: Passwort – gibt der Nutzer selbst ein", out)
        self.assertIn("[4] Kästchen: Angemeldet bleiben (an)", out)
        self.assertIn("ein Passwortfeld und ein Captcha", out)
        self.assertIn("browser_nutzer_fragen", out)

    def test_long_text_continues_and_lists_controls_once(self):
        page = {**PAGE, "text": "x" * 250, "captcha": False, "password": False}
        first = browser.page_text(page, chars=100, items=2)
        self.assertIn("browser_lesen, start=100; insgesamt 250 Zeichen", first)
        self.assertIn("…und 3 weitere", first)
        self.assertNotIn("Hinweis:", first)
        later = browser.page_text(page, start=200, chars=100)
        self.assertNotIn("Bedienelemente", later)
        self.assertNotIn("weiter mit", later)


FAKE_HOST = r'''
import json, sys, time
print(json.dumps({"event": "ready", "hwnd": 42}), flush=True)
print(json.dumps({"event": "loaded", "url": "about:blank", "title": ""}), flush=True)
for line in sys.stdin:
    cmd = json.loads(line)
    op = cmd.get("op")
    if op == "quit":
        break
    if op == "slow":
        continue
    if op == "die":
        sys.exit(1)
    if op == "fail":
        print(json.dumps({"id": cmd["id"], "ok": False, "error": "kaputt"}), flush=True)
    else:
        print(json.dumps({"id": cmd["id"], "ok": True, "data": {"op": op, "args": cmd}}), flush=True)
'''


class HostProtocol(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        (self.dir / "host.py").write_text(FAKE_HOST, encoding="utf-8")
        self.events = []
        self.host = browser.Host(on_event=self.events.append)
        self.addCleanup(self.host.stop)
        with mock.patch.object(browser, "STORAGE", self.dir / "store"):
            self.host.start(argv=[sys.executable, str(self.dir / "host.py")])

    def test_request_answer_events(self):
        data = self.host.request("read", start=3)
        self.assertEqual(data["op"], "read")
        self.assertEqual(data["args"]["start"], 3)
        self.assertEqual(self.host.hwnd, 42)
        self.assertEqual([e["event"] for e in self.events[:2]], ["ready", "loaded"])

    def test_error_and_timeout(self):
        with self.assertRaisesRegex(browser.BrowserError, "kaputt"):
            self.host.request("fail")
        with self.assertRaisesRegex(browser.BrowserError, "antwortet nicht"):
            self.host.request("slow", timeout=0.3)
        self.assertEqual(self.host.request("read")["op"], "read")  # danach geht es normal weiter

    def test_exit_releases_waiters(self):
        t = time.monotonic()
        with self.assertRaisesRegex(browser.BrowserError, "geschlossen"):
            self.host.request("die", timeout=20)
        self.assertLess(time.monotonic() - t, 10)
        deadline = time.monotonic() + 5
        while self.host.running() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.host.running())
        with self.assertRaises(browser.BrowserError):
            self.host.request("read")


class FakeHost:
    def __init__(self, answers):
        self.answers, self.calls, self.hwnd = answers, [], None

    def running(self):
        return True

    def request(self, op, **args):
        self.calls.append((op, args))
        return self.answers.get(op, {})


class FakePanel:
    """Wie BrowserPanel für BrowserTools: ui() führt sofort aus, ask() merkt sich die Bitte."""

    def __init__(self, answers):
        self.host = FakeHost(answers)
        self.visible = True
        self.url_var = mock.Mock()
        self.asked = []
        self._result = ""
        self._answer = None
        self.app = mock.Mock()
        self.app.ui.side_effect = lambda fn, *a: fn(*a)

    def show(self):
        self.visible = True

    def ask(self, message, answer):
        self.asked.append(message)
        self._answer = answer

    def _finish(self, done):
        self._result = "done" if done else "cancel"
        answer, self._answer = self._answer, None
        if answer:
            answer.set()


@mock.patch.object(browser, "available", return_value=True)
class Tools(unittest.TestCase):
    def tools(self, **answers):
        panel = FakePanel({"read": PAGE, **answers})
        return browserpanel.BrowserTools(panel), panel

    def test_open_reads_the_page(self, _available):
        tools, panel = self.tools(open={"loaded": True})
        out = tools.open("example.org/login")
        self.assertEqual(panel.host.calls[0], ("open", {"url": "https://example.org/login"}))
        self.assertIn("[5] Knopf: Anmelden", out)
        self.assertEqual(tools.describe(5), "[5] Knopf: Anmelden\nAnmelden\nhttps://example.org/login")

    def test_password_and_missing_elements(self, _available):
        tools, _panel = self.tools(type={"result": "password"}, click={"result": "missing"})
        with self.assertRaisesRegex(browser.BrowserError, "Passwörter gibt der Nutzer selbst ein"):
            tools.type(3, "geheim")
        with self.assertRaisesRegex(browser.BrowserError, "gibt es nicht"):
            tools.click(9)

    def test_ask_user_done_cancel_and_stop(self, _available):
        tools, panel = self.tools()
        threading.Timer(0.2, panel._finish, (True,)).start()
        self.assertTrue(tools.ask_user("Bitte anmelden").startswith("Der Nutzer ist fertig."))
        self.assertEqual(panel.asked, ["Bitte anmelden"])
        threading.Timer(0.2, panel._finish, (False,)).start()
        self.assertEqual(tools.ask_user("Captcha"), "Der Nutzer hat abgebrochen.")
        stop = threading.Event()
        threading.Timer(0.2, stop.set).start()
        self.assertIn("gestoppt", tools.ask_user("Warte", stop))
        self.assertIsNone(panel._answer)

    def test_not_installed(self, available):
        available.return_value = False
        tools, _panel = self.tools()
        with self.assertRaisesRegex(browser.BrowserError, "nicht eingerichtet"):
            tools.open("example.org")


class AgentTools(unittest.TestCase):
    def test_only_with_web_access(self):
        tools = mock.Mock()
        tools.is_open.return_value = False
        names = lambda a: {t["function"]["name"] for t in a.tools}  # noqa: E731
        with_web = agent.Agent(lambda *a: "yes", web_access=True, browser=tools)
        self.assertLessEqual({"browser_oeffnen", "browser_nutzer_fragen"}, names(with_web))
        self.assertIn("browser_nutzer_fragen", with_web.system_prompt())
        self.assertIn("googeln", with_web.system_prompt())  # Suchen und Seiten zeigen: im Browser
        self.assertIn("web_search", names(with_web))  # Browser zu: auch die Suche im Hintergrund
        tools.is_open.return_value = True  # offen: das Web nur über den Browser (der Nutzer sieht mit)
        browser_only = agent.Agent(lambda *a: "yes", web_access=True, browser=tools)
        self.assertFalse(names(browser_only) & {"web_search", "fetch_url"})
        self.assertIn("browser_oeffnen", names(browser_only))
        self.assertIn(agent.BROWSER_OPEN_PROMPT, browser_only.system_prompt())
        self.assertNotIn(agent.WEB_PROMPT, browser_only.system_prompt())
        tools.is_open.return_value = False  # Einstellung „über den Browser“: auch wenn er gerade zu ist
        setting = agent.Agent(lambda *a: "yes", web_access=True, browser=tools, browser_only=True)
        self.assertFalse(names(setting) & {"web_search", "fetch_url"})
        self.assertIn("web_search", names(agent.Agent(lambda *a: "yes", web_access=True, browser_only=True)))
        self.assertFalse(names(agent.Agent(lambda *a: "yes", web_access=False, browser=tools)) & {"browser_oeffnen"})
        self.assertFalse(names(agent.Agent(lambda *a: "yes", web_access=True)) & {"browser_oeffnen"})

    def test_click_and_type_ask_first(self):
        tools = mock.Mock()
        tools.is_open.return_value = False
        tools.describe.return_value = "[5] Knopf: Kaufen"
        asked = []
        a = agent.Agent(lambda title, text: asked.append((title, text)) or "no", web_access=True, browser=tools)
        self.assertEqual(a.execute("browser_klicken", json.dumps({"nr": 5})), "Vom Nutzer abgelehnt.")
        self.assertEqual(a.execute("browser_eingeben", json.dumps({"nr": 2, "text": "x"})), "Vom Nutzer abgelehnt.")
        tools.click.assert_not_called()
        tools.type.assert_not_called()
        self.assertEqual(asked[0], ("Im Browser klicken?", "[5] Knopf: Kaufen"))
        tools.read.return_value = "Seite"
        self.assertEqual(a.execute("browser_lesen", "{}"), "Seite")  # lesen fragt nicht
        tools.ask_user.side_effect = browser.BrowserError("weg")
        self.assertEqual(a.execute("browser_nutzer_fragen", json.dumps({"nachricht": "x"})), "Fehler: weg")


class Install(unittest.TestCase):
    def test_command(self):
        with mock.patch.object(browser.os, "access", return_value=False), \
                mock.patch.object(browser.sys, "prefix", browser.sys.base_prefix):
            cmd = browser.install_command()
        self.assertEqual(cmd[1:4], ["-m", "pip", "install"])
        self.assertIn("--user", cmd)
        self.assertEqual(cmd[-1], "pywebview")
        with mock.patch.object(browser.os, "access", return_value=True):
            self.assertNotIn("--user", browser.install_command())

    def test_linux_points_to_packages(self):
        with mock.patch.object(browser.plattform, "WINDOWS", False), \
                self.assertRaisesRegex(browser.BrowserError, "apt install python3-webview"):
            browser.install()


if __name__ == "__main__":
    unittest.main()
