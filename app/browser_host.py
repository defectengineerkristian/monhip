"""Browser der Seitenleiste in einem eigenen Prozess (pywebview: unter Windows WebView2/Edge, unter Linux WebKitGTK).
Monhip startet ihn mit browser.Host und spricht über JSON-Zeilen mit ihm: Befehle über stdin
({"id": 1, "op": "open", "url": …}), Antworten ({"id": 1, "ok": true, "data": …}) und Ereignisse ({"event": "loaded",
…}) über stdout. Aufruf: python browser_host.py <Speicherordner> <eingebettet 0|1> [Breite Höhe x y [Startseite]]

Eigener Prozess, weil pywebview seine eigene Ereignisschleife im Hauptthread braucht – die hat in Monhip schon Tk.
Anmeldungen und Cookies bleiben im Speicherordner (nicht im privaten Modus)."""

import json
import sys
import threading
import time

import webview

LOAD_TIMEOUT = 30   # Sekunden, die open/back/… höchstens auf das Laden der Seite warten
CLICK_SETTLE = 2.5  # nach einem Klick so lange auf eine neue Seite warten (sonst gilt: Seite hat sich nur geändert)
SETTLE_TIMEOUT = 15  # hat danach schon eine neue Seite begonnen, höchstens so lange, bis sie fertig ist

_out = threading.Lock()


def send(**msg):
    with _out:
        sys.stdout.write(json.dumps(msg) + "\n")  # nur ASCII: unter Windows schreibt stdout sonst in der Codepage
        sys.stdout.flush()


# Liest die Seite wie ein Mensch: sichtbarer Text, nummerierte Bedienelemente (Nummer als data-monhip-nr am Element,
# damit klicken/eingeben genau das Gezählte treffen), Hinweise auf Passwortfeld und Captcha
READ_JS = r"""
(() => {
  const visible = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const clean = t => (t || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  document.querySelectorAll('[data-monhip-nr]').forEach(el => el.removeAttribute('data-monhip-nr'));
  const found = Array.from(document.querySelectorAll(
    'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [contenteditable=true]'))
    .filter(visible).slice(0, 150);
  const items = found.map((el, i) => {
    el.setAttribute('data-monhip-nr', String(i + 1));
    const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    let kind = 'field';
    if (tag === 'a' || role === 'link') kind = 'link';
    else if (tag === 'button' || role === 'button' || ['submit', 'button', 'reset', 'image'].includes(type)) kind = 'button';
    else if (tag === 'select') kind = 'select';
    else if (type === 'password') kind = 'password';
    else if (type === 'checkbox' || type === 'radio') kind = type;
    let label = clean(el.getAttribute('aria-label') || el.innerText || el.title || el.alt);
    if (!label && el.labels && el.labels.length) label = clean(el.labels[0].innerText);
    if (!label) label = clean(el.placeholder || el.name || el.id);
    const value = kind === 'password' ? '' : clean(tag === 'select' ? (el.selectedOptions[0] || {}).text : el.value);
    return {nr: i + 1, kind, label, value, href: tag === 'a' ? el.href : '',
            checked: kind === 'checkbox' || kind === 'radio' ? !!el.checked : null};
  });
  const captcha = !!document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], ' +
    'iframe[src*="challenges.cloudflare"], .g-recaptcha, .h-captcha, .cf-turnstile, #captcha, [name*="captcha" i]');
  return JSON.stringify({url: location.href, title: document.title,
                         text: document.body ? document.body.innerText : '', items, captcha,
                         password: !!document.querySelector('input[type=password]')});
})()
"""

CLICK_JS = r"""
((nr) => {
  const el = document.querySelector('[data-monhip-nr="' + nr + '"]');
  if (!el) return 'missing';
  el.scrollIntoView({block: 'center'});
  el.focus();
  el.click();
  return 'ok';
})(%s)
"""

TYPE_JS = r"""
((nr, text, enter) => {
  const el = document.querySelector('[data-monhip-nr="' + nr + '"]');
  if (!el) return 'missing';
  if ((el.getAttribute('type') || '').toLowerCase() === 'password') return 'password';
  el.scrollIntoView({block: 'center'});
  el.focus();
  if (el.isContentEditable) {
    el.innerText = text;
  } else {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype :
                  el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;  // so merken es auch React & Co.
    setter.call(el, text);
  }
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  if (enter) {
    for (const t of ['keydown', 'keypress', 'keyup'])
      el.dispatchEvent(new KeyboardEvent(t, {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
    if (el.form) { if (el.form.requestSubmit) el.form.requestSubmit(); else el.form.submit(); }
  }
  return 'ok';
})(%s, %s, %s)
"""


class Host:
    def __init__(self, win):
        self.win = win
        self.loads = 0                      # wie oft schon eine Seite fertig geladen wurde
        self.url = ""                       # zuletzt geladene Adresse
        self.loaded = threading.Condition()

    def on_loaded(self):
        try:
            url = self.win.get_current_url() or ""
        except Exception:  # noqa: BLE001
            url = ""
        with self.loaded:
            self.loads, self.url = self.loads + 1, url
            self.loaded.notify_all()
        try:
            send(event="loaded", url=url, title=self.js("document.title") or "")
        except Exception:  # noqa: BLE001 – ein Ereignis darf den Browser nie beenden
            pass

    def wait_load(self, since: int, timeout: float) -> bool:
        """Wartet auf eine neu geladene Seite (die leere Startseite about:blank zählt nicht)."""
        with self.loaded:
            return self.loaded.wait_for(lambda: self.loads > since and self.url != "about:blank", timeout)

    def js(self, code: str):
        return self.win.evaluate_js(code)

    def settle(self, timeout: float = SETTLE_TIMEOUT) -> bool:
        """Wartet, bis die Seite fertig geladen ist – für Klicks, nach denen die neue Seite länger als CLICK_SETTLE
        braucht (bleibt alles beim Alten, ist sie sofort fertig)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                if (self.js("document.readyState") == "complete"
                        and (self.js("location.href") or "") not in ("", "about:blank")):
                    return True
            except Exception:  # noqa: BLE001 – mitten im Wechsel der Seite
                pass
            time.sleep(0.25)
        return False

    def navigate(self, action, timeout=LOAD_TIMEOUT):
        since = self.loads
        action()
        return self.wait_load(since, timeout)

    def handle(self, cmd: dict):
        op = cmd.get("op")
        if op == "open":
            loaded = self.navigate(lambda: self.win.load_url(cmd["url"]))
            return {"loaded": self.settle() and loaded}  # leitet die Seite gleich weiter (Google), auch darauf warten
        if op == "settle":
            return {"ready": self.settle(float(cmd.get("timeout", SETTLE_TIMEOUT)))}
        if op in ("back", "forward", "reload"):
            code = {"back": "history.back()", "forward": "history.forward()", "reload": "location.reload()"}[op]
            return {"loaded": self.navigate(lambda: self.js(code), cmd.get("timeout", 8))}
        if op == "read":
            return json.loads(self.js(READ_JS) or "{}")
        if op == "click":
            since = self.loads
            result = self.js(CLICK_JS % int(cmd["nr"]))
            navigated = result == "ok" and self.wait_load(since, CLICK_SETTLE)
            if result == "ok" and not navigated:
                self.settle()
            return {"result": result, "navigated": navigated or self.loads > since}
        if op == "type":
            since = self.loads
            enter = bool(cmd.get("enter"))
            result = self.js(TYPE_JS % (int(cmd["nr"]), json.dumps(str(cmd["text"])), "true" if enter else "false"))
            navigated = enter and result == "ok" and self.wait_load(since, CLICK_SETTLE)
            if enter and result == "ok" and not navigated:
                self.settle()
            return {"result": result, "navigated": navigated or self.loads > since}
        if op == "show":
            (self.win.show if cmd.get("visible", True) else self.win.hide)()
            return {}
        raise ValueError(f"unbekannter Befehl {op!r}")

    def control(self):
        """Läuft in einem eigenen Thread (pywebview ruft ihn nach dem Start auf): Fenster melden, Befehle abarbeiten."""
        hwnd = None
        if sys.platform == "win32":
            for _ in range(200):
                try:
                    hwnd = int(self.win.native.Handle.ToInt64())
                    break
                except Exception:  # noqa: BLE001 – das Fenster entsteht gerade erst
                    threading.Event().wait(0.05)
        send(event="ready", hwnd=hwnd)
        for line in sys.stdin:
            try:
                cmd = json.loads(line)
            except ValueError:
                continue
            if cmd.get("op") == "quit":
                break
            try:
                send(id=cmd.get("id"), ok=True, data=self.handle(cmd))
            except Exception as e:  # noqa: BLE001 – Fehler gehen als Antwort zurück, der Browser läuft weiter
                send(id=cmd.get("id"), ok=False, error=f"{type(e).__name__}: {e}")
        self.win.destroy()


def main():
    storage, embedded = sys.argv[1], sys.argv[2] == "1"
    w, h, x, y = (int(v) for v in (sys.argv[3:7] if len(sys.argv) >= 7 else (900, 800, 0, 0)))
    try:  # Startseite von Monhip (Suchfeld und Hinweis, im Design der App)
        start = open(sys.argv[7], encoding="utf-8").read() if len(sys.argv) > 7 else None
    except OSError:
        start = None
    win = webview.create_window("Monhip – Browser", None if start else "about:blank", html=start, width=w, height=h,
                                x=None if embedded else x, y=None if embedded else y,
                                frameless=embedded, hidden=embedded, focus=True,
                                text_select=True, zoomable=True)  # wie in jedem Browser: markieren, Strg+Mausrad
    host = Host(win)
    win.events.loaded += host.on_loaded
    win.events.closed += lambda: send(event="closed")
    webview.start(host.control, private_mode=False, storage_path=storage)


if __name__ == "__main__":
    main()
