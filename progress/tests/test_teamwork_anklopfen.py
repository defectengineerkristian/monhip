"""Tests für das Anklopfen im Teamwork (app/teamwork_netz.py): Raumsuche über UDP, Anfrage ohne Schlüssel, Zulassen bzw.
Ablehnen beim Gastgeber, eigener Schlüssel je Teilnehmer (per Diffie-Hellman, geht nie übers Netz), Entziehen –
alles über 127.0.0.1: python -m unittest discover -s progress/tests -p test_teamwork_anklopfen.py"""

import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import teamwork_netz as room


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class KeyExchange(unittest.TestCase):
    def test_both_sides_get_the_same_key_and_code(self):
        a, b = room.dh_private(), room.dh_private()
        secret_a = room.dh_secret(a, room.dh_public(b))
        secret_b = room.dh_secret(b, room.dh_public(a))
        self.assertEqual(secret_a, secret_b)
        key, code = room.guest_key(secret_a, "0123456789abcdef")
        self.assertEqual((key, code), room.guest_key(secret_b, "0123456789abcdef"))
        self.assertRegex(code, r"^\d{4}$")
        self.assertNotEqual(room.guest_key(secret_a, "fedcba9876543210")[0], key)

    def test_invalid_public_keys(self):
        for bad in (0, 1, room.DH_P - 1, room.DH_P):
            with self.assertRaises(ValueError):
                room.dh_secret(room.dh_private(), bad)

    def test_invite_keeps_the_guest_id(self):
        inv = room.parse_invite(room.make_invite("192.168.1.2", 47821, "k", "Raum", guest="0123456789abcdef"))
        self.assertEqual(inv["guest"], "0123456789abcdef")
        self.assertEqual(room.parse_invite(room.make_invite("h", 1, "k", "R"))["guest"], "")


class Knocking(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.server = room.RoomServer("Testraum", room.new_key(), "127.0.0.1", 0, Path(self.dir.name) / "raum.json")
        self.server.owner, self.server.discovery_port = "Anna", free_udp_port()
        self.knocks = []
        self.server.on_knock = self.knocks.append
        self.server.start()
        self.addCleanup(self.server.stop)

    def test_search_finds_the_room(self):
        rooms = room.discover(0.6, self.server.discovery_port, ["127.0.0.1"])
        self.assertEqual(rooms, [{"host": "127.0.0.1", "port": self.server.port, "room": "Testraum", "owner": "Anna"}])

    def test_admit_join_and_revoke(self):
        k = room.Knock("127.0.0.1", self.server.port, "Max", "Max-KI", "client-1")
        self.assertEqual(self.knocks[0]["code"], k.code)
        self.assertEqual(self.knocks[0]["name"], "Max")
        threading.Timer(0.3, lambda: self.server.decide(k.id, True)).start()
        self.assertEqual(k.status(5), "zugelassen")
        inv = room.parse_invite(k.invite())
        self.assertNotEqual(inv["key"], self.server.key)
        client = room.RoomClient("127.0.0.1", self.server.port, inv["key"], {"name": "Max", "ai": "Max-KI"},
                                 lambda *a: None, guest=inv["guest"])
        snap = client.join()
        self.assertEqual([m["name"] for m in snap["members"]], ["Max"])
        forged = room.RoomClient("127.0.0.1", self.server.port, "falsch", {"name": "Eve", "ai": "Eve-KI"},
                                 lambda *a: None, guest=inv["guest"])
        with self.assertRaises(room.RoomError) as e:
            forged.join()
        self.assertEqual(e.exception.code, 401)
        self.assertTrue(self.server.revoke(k.id))
        with self.assertRaises(room.RoomError) as e:
            client._req("POST", "/api/member", {"member": client.member, "busy": False})
        self.assertEqual(e.exception.code, 401)

    def test_admitted_key_survives_a_restart(self):
        k = room.Knock("127.0.0.1", self.server.port, "Max", "Max-KI")
        self.server.decide(k.id, True)
        self.server.stop()
        again = room.RoomServer("Testraum", self.server.key, "127.0.0.1", 0, Path(self.dir.name) / "raum.json")
        again.discoverable = False
        again.start()
        self.addCleanup(again.stop)
        client = room.RoomClient("127.0.0.1", again.port, k.key, {"name": "Max", "ai": "Max-KI"}, lambda *a: None,
                                 guest=k.id)
        self.assertEqual(client.join()["room"], "Testraum")

    def test_decline_and_limits(self):
        k = room.Knock("127.0.0.1", self.server.port, "Eve", "Eve-KI")
        with self.assertRaises(room.RoomError) as e:  # von derselben Adresse wartet schon eine Anfrage
            room.Knock("127.0.0.1", self.server.port, "Eve", "Eve-KI")
        self.assertEqual(e.exception.code, 429)
        self.assertTrue(self.server.decide(k.id, False))
        self.assertFalse(self.server.decide(k.id, True))  # schon entschieden
        self.assertEqual(k.status(1), "abgelehnt")
        with self.assertRaises(room.RoomError) as e:  # gleich wieder: kurze Sperre
            room.Knock("127.0.0.1", self.server.port, "Eve", "Eve-KI")
        self.assertEqual(e.exception.code, 429)
        with self.assertRaises(room.RoomError) as e:
            room.Knock("127.0.0.1", self.server.port, "x", "y")
        self.assertEqual(e.exception.code, 400)

    def test_waiting_times_out_without_decision(self):
        k = room.Knock("127.0.0.1", self.server.port, "Max", "Max-KI")
        t0 = time.monotonic()
        self.assertEqual(k.status(0.5), "wartet")
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(room.Knock.status.__defaults__[0], room.KNOCK_WAIT)


if __name__ == "__main__":
    unittest.main()
