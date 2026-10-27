"""Sprachwahl darf Werkzeugausführung und das bestehende Teamwork-Protokoll nicht verändern."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import agent
import i18n
import room


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.language = i18n._language

    def tearDown(self):
        i18n._language = self.language

    def test_tool_prompts_identifiers_and_error_detection_do_not_change(self):
        with tempfile.TemporaryDirectory() as directory:
            original_tools = copy.deepcopy(agent.FILE_TOOLS)
            worker = agent.Agent(lambda *_: "no", files=True, workspace=directory)
            i18n._language = "de"
            german_prompt = worker.system_prompt()
            german_error = worker.execute("read_file", '{"path":"missing.txt"}')
            i18n._language = "en"
            self.assertEqual(worker.system_prompt(), german_prompt)
            self.assertEqual(worker.execute("read_file", '{"path":"missing.txt"}'), german_error)
            self.assertFalse(agent.result_ok(german_error))
            self.assertEqual(agent.FILE_TOOLS, original_tools)

    def test_real_room_keeps_task_states_and_user_content(self):
        i18n._language = "en"
        server = room.RoomServer("Test room", room.new_key(), bind="127.0.0.1", port=0)
        server.start()
        try:
            client = room.RoomClient("127.0.0.1", server.port, server.key,
                                     {"name": "Tester", "ai": "Assistant"}, lambda *_: None)
            client.join()
            created = client.task("add", text="Eigener deutscher Auftrag")
            self.assertEqual(created["task"]["status"], "offen")
            nr = created["task"]["nr"]
            claimed = client.task("claim", nr=nr)
            self.assertEqual(claimed["task"]["status"], "in Arbeit")
            completed = client.task("done", nr=nr, note="Eigene Notiz")
            self.assertEqual(completed["task"]["status"], "erledigt")
            self.assertEqual(completed["task"]["text"], "Eigener deutscher Auftrag")
            self.assertEqual(completed["task"]["note"], "Eigene Notiz")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
