"""Tests für app/gitwork.py ohne echtes git und ohne Netz: python tests/test_gitwork.py"""
import importlib.util, subprocess, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("gitwork", Path(__file__).resolve().parent.parent / "app" / "gitwork.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

# GitHub-URLs erkennen
assert g.parse_github("https://github.com/besitzer/monhip") == ("besitzer", "monhip")
assert g.parse_github("https://github.com/a/b.git") == ("a", "b")
assert g.parse_github("https://user:tok@github.com/a/my.repo.git/") == ("a", "my.repo")
assert g.parse_github("git@github.com:a/b.git") == ("a", "b")
assert g.parse_github("https://gitlab.com/a/b") is None
assert g.parse_github("https://github.com.evil.com/a/b") is None
# Zugangsdaten nie anzeigen
assert g.safe_url("https://user:ghp_secret@github.com/a/b") == "https://github.com/a/b"
assert g.safe_url("https://github.com/a/b") == "https://github.com/a/b"

# Pull-Request-Ziel: Fork → Original-Repository
calls = []
def fake_api(method, path, tok, data=None):
    calls.append((method, path, data))
    if path == "/repos/mitwirkender/monhip":
        return {"fork": True, "full_name": "mitwirkender/monhip",
                "parent": {"full_name": "besitzer/monhip", "default_branch": "main"}}
    if path == "/repos/k/own":
        return {"fork": False, "full_name": "k/own", "default_branch": "master"}
    return {"number": 7, "html_url": "https://github.com/x/pull/7"}
g.api = fake_api
t = g.pr_target("mitwirkender", "monhip", "feature/git", "TOKEN")
assert t == {"repo": "besitzer/monhip", "head": "mitwirkender:feature/git", "base": "main"}, t
t2 = g.pr_target("k", "own", "fix", "TOKEN")
assert t2 == {"repo": "k/own", "head": "fix", "base": "master"}, t2
g.create_pull_request(t, "Titel", "Text", "TOKEN")
assert calls[-1] == ("POST", "/repos/besitzer/monhip/pulls",
                     {"title": "Titel", "body": "Text", "head": "mitwirkender:feature/git", "base": "main"})

# Token aus dem Credential Manager lesen (git-Aufruf simuliert)
seen = {}
def fake_run(cwd, *args, timeout=60, stdin=None):
    seen["args"], seen["stdin"] = args, stdin
    return subprocess.CompletedProcess(args, 0, b"protocol=https\nhost=github.com\nusername=d\npassword=gho_abc\n", b"")
g.run = fake_run
assert g.token() == "gho_abc"
assert seen["args"] == ("credential", "fill") and "host=github.com" in seen["stdin"]
g.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b"")
try:
    g.token(); raise AssertionError("ohne Anmeldung muss GitError kommen")
except g.GitError as e:
    assert "Browser" in str(e)

# Fehler von git kommen als GitError mit der Meldung
g.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"fatal: not a git repository\r\n")
try:
    g.out(".", "status"); raise AssertionError
except g.GitError as e:
    assert str(e) == "fatal: not a git repository"
try:
    g.toplevel("/x"); raise AssertionError
except g.GitError as e:
    assert "kein Git-Repository" in str(e)

# Umgebung: keine Rückfrage im Terminal, ssh im Batch-Modus, eigene Einstellung bleibt erhalten
import os
env = {"GIT_SSH_COMMAND": g.SSH_DEFAULT, **{"GIT_SSH_COMMAND": "plink"}, **g.ENV}
assert env["GIT_SSH_COMMAND"] == "plink" and env["GIT_TERMINAL_PROMPT"] == "0"
print("alle gitwork-Tests bestanden")
