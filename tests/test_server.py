"""Pruebas de integración del servidor (sin red, con el test_client de Flask-SocketIO).

    .venv/bin/python -m unittest discover -s tests -v
"""
import base64
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

try:
    from app import create_app
    from protocol import PROTOCOL_VERSION
except ImportError as exc:  # Flask no instalado: se saltan estos tests
    create_app = None
    IMPORT_ERROR = str(exc)

from game.rules import GameRules  # noqa: E402

ONE_OF_EACH = ["dragon", "warrior", "mage"]
# Reglas "clásicas": mazo de 3, todo en la mano, nada que robar (determinista).
CLASSIC = GameRules(initial_hand=3, deck_min=3)


def msg(type_, payload=None, action_id=None):
    m = {"v": PROTOCOL_VERSION, "type": type_, "payload": payload or {}}
    if action_id:
        m["action_id"] = action_id
    return m


class FakeDetector:
    def __init__(self, markers):
        self.markers = markers

    def detect_jpeg(self, data: bytes):
        return list(self.markers)


@unittest.skipIf(create_app is None, "Flask/Flask-SocketIO no instalados")
class ServerTests(unittest.TestCase):
    def setUp(self):
        self.app, self.socketio, self.server = create_app(grace_seconds=0.2, rules=CLASSIC,
                                                          detector=FakeDetector([2, 77]))

    def client(self):
        return self.socketio.test_client(self.app)

    @staticmethod
    def received(client, type_=None):
        out = [r["args"][0] for r in client.get_received() if r["name"] == "msg"]
        return [m for m in out if type_ is None or m["type"] == type_]

    def join(self, name, token=None):
        c = self.client()
        payload = {"name": name, "deck": ONE_OF_EACH}
        if token:
            payload["session_token"] = token
        c.emit("msg", msg("join", payload))
        welcome = self.received(c, "welcome")[0]["payload"]
        return c, welcome

    def two_players(self):
        a, wa = self.join("Ana")
        b, wb = self.join("Luis")
        self.received(a), self.received(b)  # vaciar colas
        return a, wa, b, wb

    def last_state(self, client):
        updates = [m for m in self.received(client) if m["type"] in ("state_update", "state_sync")]
        return updates[-1]

    # ---------------------------------------------------------------- tests
    def test_welcome_contains_identity_and_catalog(self):
        _, w = self.join("Ana")
        self.assertTrue(w["session_token"])
        self.assertEqual(len(w["catalog"]["cards"]), 3)
        self.assertTrue(w["vision_available"])

    def test_play_card_reaches_both_players_with_seq(self):
        a, wa, b, wb = self.two_players()
        a.emit("msg", msg("play_card", {"card_id": "mage", "expected_turn": 1}, "act-1"))
        ua, ub = self.last_state(a), self.last_state(b)
        self.assertEqual(ua["seq"], ub["seq"])
        self.assertEqual([e["type"] for e in ub["payload"]["events"]],
                         ["card_played", "player_damaged", "turn_changed"])
        rival_view = {p["player_id"]: p for p in ub["payload"]["state"]["players"]}
        start = rival_view[wb["player_id"]]["max_life"]
        self.assertEqual(rival_view[wb["player_id"]]["life"], start - 40)
        self.assertNotIn("hand", rival_view[wa["player_id"]])   # B no ve la mano de A

    def test_error_goes_only_to_sender_with_resync(self):
        a, _, b, _ = self.two_players()
        b.emit("msg", msg("play_card", {"card_id": "mage"}, "x"))
        got = self.received(b)
        self.assertEqual(got[0]["type"], "error")
        self.assertEqual(got[0]["payload"]["code"], "not_your_turn")
        self.assertEqual(got[0]["action_id"], "x")
        self.assertEqual(got[1]["type"], "state_sync")
        self.assertEqual(self.received(a), [])

    def test_duplicate_action_resyncs_without_error(self):
        a, _, b, _ = self.two_players()
        m = msg("play_card", {"card_id": "mage", "expected_turn": 1}, "dup")
        a.emit("msg", m)
        self.received(a), self.received(b)
        a.emit("msg", m)
        self.assertEqual([x["type"] for x in self.received(a)], ["state_sync"])
        self.assertEqual(self.received(b), [])

    def test_drawn_card_is_hidden_from_rival_over_network(self):
        app, socketio, _ = create_app(detector=None)          # reglas por defecto: hay robo
        a, b = socketio.test_client(app), socketio.test_client(app)
        a.emit("msg", msg("join", {"name": "A"}))
        b.emit("msg", msg("join", {"name": "B"}))
        state_a = self.last_state(a)["payload"]["state"]
        self.received(b)
        me = next(p for p in state_a["players"] if "hand" in p)
        a.emit("msg", msg("play_card", {"card_id": me["hand"][0], "expected_turn": 1}, "d1"))

        def drawn(client):
            update = self.last_state(client)["payload"]
            return next(e for e in update["events"] if e["type"] == "card_drawn")["payload"], update["state"]

        seen_by_b, state_b = drawn(b)
        seen_by_a, _ = drawn(a)
        hand_b = next(p for p in state_b["players"] if "hand" in p)["hand"]
        self.assertEqual(seen_by_b["card"]["card_id"], hand_b[-1])   # B ve lo que robó
        self.assertIsNone(seen_by_a["card"])                          # A no
        self.assertNotIn("_private_to", str(seen_by_a) + str(seen_by_b))

    def test_invalid_deck_rejected(self):
        c = self.client()
        c.emit("msg", msg("join", {"name": "X", "deck": ["mage", "mage", "mage"]}))
        err = self.received(c, "error")[0]["payload"]
        self.assertEqual(err["code"], "invalid_deck")

    def test_bad_messages(self):
        c = self.client()
        c.emit("msg", {"v": 99, "type": "join"})
        self.assertEqual(self.received(c)[0]["payload"]["code"], "unsupported_version")
        c.emit("msg", msg("play_card", {"card_id": "mage"}))
        self.assertEqual(self.received(c)[0]["payload"]["code"], "not_joined")

    def test_frame_detection_maps_markers_to_cards(self):
        a, _ = self.join("Ana")
        img = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8fake").decode()
        a.emit("msg", msg("frame", {"image": img, "frame_id": 7}))
        det = self.received(a, "card_detected")[0]["payload"]
        self.assertEqual(det["frame_id"], 7)
        self.assertEqual(det["marker_ids"], [2, 77])
        self.assertEqual([c["card_id"] for c in det["cards"]], ["mage"])  # 77 se ignora

    def test_reconnect_with_token_keeps_seat(self):
        a, wa, b, _ = self.two_players()
        a.disconnect()
        self.assertIn("player_disconnected",
                      [e["type"] for e in self.last_state(b)["payload"]["events"]])
        a2, w2 = self.join("", token=wa["session_token"])
        self.assertEqual(w2["player_id"], wa["player_id"])
        time.sleep(0.4)  # más que la gracia: NO debe perder porque volvió
        a2.emit("msg", msg("sync"))
        state = self.last_state(a2)["payload"]["state"]
        self.assertEqual(state["status"], "in_progress")

    def test_abandon_after_grace_gives_victory(self):
        a, wa, b, wb = self.two_players()
        a.disconnect()
        time.sleep(0.5)
        state = self.last_state(b)["payload"]["state"]
        self.assertEqual(state["status"], "finished")
        self.assertEqual(state["winner_id"], wb["player_id"])
        self.assertEqual(state["end_reason"], "last_standing")
        # El que abandonó libera su puesto; el ganador conserva su resultado.
        self.assertEqual([p["player_id"] for p in state["players"]], [wb["player_id"]])

    def test_both_players_vanish_leaves_empty_room(self):
        a, _, b, _ = self.two_players()
        a.disconnect()
        b.disconnect()
        time.sleep(0.5)
        game = self.server.manager.get("default")
        self.assertEqual(game.players, [])
        c, _ = self.join("Nuevo")          # un jugador real ya no choca con fantasmas
        self.assertEqual(game.status.value, "waiting")


if __name__ == "__main__":
    unittest.main()
