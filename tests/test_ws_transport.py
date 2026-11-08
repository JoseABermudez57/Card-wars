"""WebSocket puro (/ws) contra un servidor real en un puerto efímero.
Incluye una partida mixta: un jugador por Socket.IO (web) y otro por /ws (Unity).

    .venv/bin/python -m unittest tests.test_ws_transport -v
"""
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

try:
    import simple_websocket
    import socketio as sio_client
    from werkzeug.serving import make_server

    from app import create_app
except ImportError:
    simple_websocket = None

from game.rules import GameRules  # noqa: E402

ONE_OF_EACH = ["dragon", "warrior", "mage"]
# Reglas "clásicas": mazo de 3, todo en la mano, nada que robar (determinista).
CLASSIC = GameRules(initial_hand=3, deck_min=3)


def msg(type_, payload=None, action_id=None):
    m = {"v": 1, "type": type_, "payload": payload or {}}
    if action_id:
        m["action_id"] = action_id
    return m


class WsPlayer:
    def __init__(self, url):
        self.ws = simple_websocket.Client.connect(url)

    def send(self, m):
        self.ws.send(json.dumps(m))

    def recv_until(self, type_, timeout=3):
        while True:
            data = self.ws.receive(timeout=timeout)
            if data is None:
                raise AssertionError(f"timeout esperando {type_}")
            m = json.loads(data)
            if m["type"] == type_:
                return m

    def close(self):
        self.ws.close()


@unittest.skipIf(simple_websocket is None, "dependencias del servidor no instaladas")
class WsTransportTests(unittest.TestCase):
    def setUp(self):
        self.app, self.socketio, self.server = create_app(grace_seconds=0.3, detector=None, rules=CLASSIC)
        self.http = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.port = self.http.server_port
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.ws_url = f"ws://127.0.0.1:{self.port}/ws"

    def tearDown(self):
        self.http.shutdown()

    def test_invalid_json_gets_error(self):
        p = WsPlayer(self.ws_url)
        p.ws.send("esto no es json")
        self.assertEqual(p.recv_until("error")["payload"]["code"], "bad_message")
        p.close()

    def test_two_native_players(self):
        a, b = WsPlayer(self.ws_url), WsPlayer(self.ws_url)
        a.send(msg("join", {"name": "A", "deck": ONE_OF_EACH}))
        wa = a.recv_until("welcome")["payload"]
        b.send(msg("join", {"name": "B", "deck": ONE_OF_EACH}))
        b.recv_until("welcome")
        a.send(msg("play_card", {"card_id": "mage", "expected_turn": 1}, "x1"))
        while True:
            up = b.recv_until("state_update")
            if any(e["type"] == "card_played" for e in up["payload"]["events"]):
                break
        players = up["payload"]["state"]["players"]
        start = players[0]["max_life"]
        lives = {p["name"]: p["life"] for p in players}
        self.assertEqual(lives, {"A": start, "B": start - 40})
        self.assertTrue(wa["session_token"])
        a.close(), b.close()

    def test_mixed_web_and_native_players(self):
        web = sio_client.Client()
        web_msgs = []
        web.on("msg", web_msgs.append)
        web.connect(f"http://127.0.0.1:{self.port}", transports=["websocket"])
        web.emit("msg", msg("join", {"name": "Web", "deck": ONE_OF_EACH}))
        for _ in range(30):                      # garantizar que el web entra primero
            if any(m["type"] == "welcome" for m in web_msgs):
                break
            web.sleep(0.1)

        native = WsPlayer(self.ws_url)
        native.send(msg("join", {"name": "Unity", "deck": ONE_OF_EACH}))
        native.recv_until("welcome")
        native.recv_until("state_update")      # game_started

        # El jugador web abre (entró primero) y el nativo recibe el golpe.
        web.emit("msg", msg("play_card", {"card_id": "dragon", "expected_turn": 1}, "w1"))
        up = native.recv_until("state_update")
        types = [e["type"] for e in up["payload"]["events"]]
        self.assertEqual(types, ["card_played", "player_damaged", "turn_changed"])

        # Y al revés: el nativo ataca y el web lo recibe.
        native.send(msg("play_card", {"card_id": "warrior", "expected_turn": 2}, "n1"))
        native.recv_until("state_update")
        web.sleep(0.3)
        last = [m for m in web_msgs if m["type"] == "state_update"][-1]
        self.assertEqual(last["payload"]["events"][0]["payload"]["card"]["card_id"], "warrior")
        web.disconnect(), native.close()

    def test_native_disconnect_expires_seat(self):
        a, b = WsPlayer(self.ws_url), WsPlayer(self.ws_url)
        a.send(msg("join", {"name": "A", "deck": ONE_OF_EACH}))
        a.recv_until("welcome")
        b.send(msg("join", {"name": "B", "deck": ONE_OF_EACH}))
        b.recv_until("welcome")
        a.close()
        while True:
            up = b.recv_until("state_update")
            if up["payload"]["state"]["status"] == "finished":
                break
        self.assertEqual(up["payload"]["state"]["end_reason"], "last_standing")
        b.close()


if __name__ == "__main__":
    unittest.main()
