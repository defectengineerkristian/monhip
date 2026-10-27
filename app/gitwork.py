"""Git und GitHub für den Agenten: git-Aufrufe ohne Rückfragen im Terminal, GitHub-Zugangsdaten aus dem
Git Credential Manager (das Modell sieht sie nie) und Pull Requests über die GitHub-API."""

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
API = "https://api.github.com"
# https://github.com/owner/repo(.git) oder git@github.com:owner/repo(.git)
GITHUB_URL = re.compile(r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
# Ohne Rückfrage im Terminal (es gibt keins) – das Anmeldefenster des Credential Managers erscheint trotzdem.
# Englische Meldungen (überall gleich), kein Pager; ssh fragt nicht nach einer Passphrase, sondern bricht ab.
ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "PAGER": "cat", "LC_ALL": "C.UTF-8"}
SSH_DEFAULT = "ssh -o BatchMode=yes"
# Optionen statt Konfiguration: Umlaute in Dateinamen lesbar, keine Farbcodes; kein fsmonitor – den könnte die
# .git/config eines fremden Repositorys auf ein beliebiges Programm setzen (git status liefe ohne Rückfrage)
OPTS = ["-c", "core.quotepath=false", "-c", "color.ui=never", "-c", "core.fsmonitor=false"]


class GitError(Exception):
    """Fehler, den das Modell als verständlichen Satz bekommt (wie agent.ToolError)."""


def available() -> bool:
    return bool(shutil.which("git"))


def run(cwd, *args, timeout=60, stdin: str | None = None) -> subprocess.CompletedProcess:
    if not available():
        raise GitError("Git ist auf diesem PC nicht installiert (https://git-scm.com/download/win).")
    return subprocess.run(["git", *OPTS, *args], cwd=cwd, capture_output=True, timeout=timeout,
                          input=stdin.encode("utf-8") if stdin is not None else None,
                          stdin=None if stdin is not None else subprocess.DEVNULL,
                          creationflags=NO_WINDOW,
                          env={"GIT_SSH_COMMAND": SSH_DEFAULT, **os.environ, **ENV})


def text(r: subprocess.CompletedProcess) -> str:
    return (r.stdout + r.stderr).decode("utf-8", "replace").replace("\r\n", "\n").strip()


def out(cwd, *args, timeout=60) -> str:
    """stdout eines git-Aufrufs; bei Fehler GitError mit der Meldung von git."""
    r = run(cwd, *args, timeout=timeout)
    if r.returncode:
        raise GitError(text(r) or f"git {args[0]} ist fehlgeschlagen (Exit-Code {r.returncode}).")
    return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n").strip()


def toplevel(path) -> str:
    r = run(path, "rev-parse", "--show-toplevel")
    if r.returncode:
        raise GitError(f"{path} ist kein Git-Repository. Mit git_clone ein Repository holen.")
    return r.stdout.decode("utf-8", "replace").strip()


def current_branch(repo) -> str:
    name = out(repo, "branch", "--show-current")
    if not name:
        raise GitError("Kein Branch ausgecheckt (losgelöster HEAD). Erst mit git_branch einen Branch wählen.")
    return name


def upstream(repo) -> str | None:
    r = run(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return r.stdout.decode("utf-8", "replace").strip() if not r.returncode else None


def check_branch_name(name: str) -> str:
    name = (name or "").strip()
    if not name or name.startswith("-") or run(".", "check-ref-format", "--branch", name).returncode:
        raise GitError(f"'{name}' ist kein gültiger Branch-Name (z. B. 'feature/git-werkzeuge').")
    return name


def parse_github(url: str) -> tuple[str, str] | None:
    m = GITHUB_URL.match((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


def safe_url(url: str) -> str:
    """URL ohne eingebettete Zugangsdaten (https://name:token@github.com/… → https://github.com/…)."""
    return re.sub(r"^(https?://)[^@/]+@", r"\1", (url or "").strip())


def origin(repo) -> tuple[str, tuple[str, str] | None]:
    """(URL von origin, (owner, repo) falls GitHub)."""
    url = out(repo, "remote", "get-url", "origin")
    return url, parse_github(url)


# ---------------------------------------------------------------- GitHub-API

def token() -> str:
    """GitHub-Token aus dem Git Credential Manager (dieselbe Anmeldung wie für git push). Geht nie ans Modell."""
    r = run(".", "credential", "fill", stdin="protocol=https\nhost=github.com\n\n", timeout=300)
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("password="):
            return line.removeprefix("password=")
    raise GitError("Keine GitHub-Anmeldung gefunden. Einmal ein git_push ausführen – dabei meldet sich der "
                   "Nutzer im Browser bei GitHub an.")


def api(method: str, path: str, tok: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(data).encode("utf-8") if data is not None else None,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "Monhip",
                                          "X-GitHub-Api-Version": "2022-11-28", "Authorization": f"Bearer {tok}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            body = {}
        details = "; ".join(err.get("message") or err.get("code", "") for err in body.get("errors", [])
                            if isinstance(err, dict))
        msg = body.get("message") or e.reason
        if e.code == 401:
            msg = "GitHub-Anmeldung ungültig oder abgelaufen – beim nächsten git_push neu anmelden"
        raise GitError(f"GitHub meldet {e.code}: {msg}" + (f" ({details})" if details else "")) from None
    except urllib.error.URLError as e:
        raise GitError(f"GitHub nicht erreichbar: {e.reason}") from None


def pr_target(owner: str, name: str, branch: str, tok: str) -> dict:
    """Wohin ein Pull Request geht: bei einem Fork an das Original-Repository (head = 'owner:branch'),
    sonst an das Repository selbst. {"repo", "head", "base"}."""
    info = api("GET", f"/repos/{owner}/{name}", tok)
    parent = info.get("parent") if info.get("fork") else None
    if parent:
        return {"repo": parent["full_name"], "head": f"{owner}:{branch}", "base": parent.get("default_branch", "main")}
    return {"repo": info.get("full_name", f"{owner}/{name}"), "head": branch,
            "base": info.get("default_branch", "main")}


def create_pull_request(target: dict, title: str, body: str, tok: str) -> dict:
    return api("POST", f"/repos/{target['repo']}/pulls", tok,
               {"title": title, "body": body, "head": target["head"], "base": target["base"]})
