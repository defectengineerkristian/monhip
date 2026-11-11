"""Tests für app/gitwork.py ohne echtes git und ohne Netz: python -m unittest discover -s progress/tests -p test_gitwork.py"""
import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("gitwork", Path(__file__).resolve().parents[2] / "app" / "gitwork.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def git_result(code=0, out=b"", err=b""):
    return lambda *a, **k: subprocess.CompletedProcess(a, code, out, err)


class Urls(unittest.TestCase):
    def test_github_urls(self):
        assert g.parse_github("https://github.com/besitzer/monhip") == ("besitzer", "monhip")
        assert g.parse_github("https://github.com/a/b.git") == ("a", "b")
        assert g.parse_github("https://user:tok@github.com/a/my.repo.git/") == ("a", "my.repo")
        assert g.parse_github("git@github.com:a/b.git") == ("a", "b")
        assert g.parse_github("https://gitlab.com/a/b") is None
        assert g.parse_github("https://github.com.evil.com/a/b") is None

    def test_credentials_never_shown(self):
        assert g.safe_url("https://user:ghp_secret@github.com/a/b") == "https://github.com/a/b"
        assert g.safe_url("https://github.com/a/b") == "https://github.com/a/b"


class PullRequests(unittest.TestCase):
    def test_target_fork_goes_to_original(self):
        calls = []

        def fake_api(method, path, tok, data=None):
            calls.append((method, path, data))
            if path == "/repos/mitwirkender/monhip":
                return {"fork": True, "full_name": "mitwirkender/monhip",
                        "parent": {"full_name": "besitzer/monhip", "default_branch": "main"}}
            if path == "/repos/k/own":
                return {"fork": False, "full_name": "k/own", "default_branch": "master"}
            return {"number": 7, "html_url": "https://github.com/x/pull/7"}

        with mock.patch.object(g, "api", fake_api):
            t = g.pr_target("mitwirkender", "monhip", "feature/git", "TOKEN")
            assert t == {"repo": "besitzer/monhip", "head": "mitwirkender:feature/git", "base": "main"}, t
            t2 = g.pr_target("k", "own", "fix", "TOKEN")
            assert t2 == {"repo": "k/own", "head": "fix", "base": "master"}, t2
            g.create_pull_request(t, "Titel", "Text", "TOKEN")
        assert calls[-1] == ("POST", "/repos/besitzer/monhip/pulls",
                             {"title": "Titel", "body": "Text", "head": "mitwirkender:feature/git", "base": "main"})


class Git(unittest.TestCase):
    def test_token_from_credential_manager(self):
        seen = {}

        def fake_run(cwd, *args, timeout=60, stdin=None):
            seen["args"], seen["stdin"] = args, stdin
            return subprocess.CompletedProcess(args, 0, b"protocol=https\nhost=github.com\nusername=d\npassword=gho_abc\n",
                                               b"")

        with mock.patch.object(g, "run", fake_run):
            assert g.token() == "gho_abc"
        assert seen["args"] == ("credential", "fill") and "host=github.com" in seen["stdin"]
        with mock.patch.object(g, "run", git_result()), self.assertRaises(g.GitError) as cm:
            g.token()  # ohne Anmeldung
        assert "Browser" in str(cm.exception)

    def test_git_errors_carry_the_message(self):
        with mock.patch.object(g, "run", git_result(1, err=b"fatal: not a git repository\r\n")):
            with self.assertRaises(g.GitError) as cm:
                g.out(".", "status")
            assert str(cm.exception) == "fatal: not a git repository"
            with self.assertRaises(g.GitError) as cm:
                g.toplevel("/x")
            assert "kein Git-Repository" in str(cm.exception)

    def test_environment(self):
        """Keine Rückfrage im Terminal, ssh im Batch-Modus, eigene Einstellung bleibt erhalten."""
        env = {"GIT_SSH_COMMAND": g.SSH_DEFAULT, **{"GIT_SSH_COMMAND": "plink"}, **g.ENV}
        assert env["GIT_SSH_COMMAND"] == "plink" and env["GIT_TERMINAL_PROMPT"] == "0"


if __name__ == "__main__":
    unittest.main()
