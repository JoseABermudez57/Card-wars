"""Smoke test por red: simula dos teléfonos contra un servidor ya arrancado.

    .venv/bin/python backend/app.py                       # terminal 1
    .venv/bin/python tests/smoke_lan.py https://localhost:5000   # terminal 2

Fuerza transporte WebSocket (sin long-polling) para validar el camino real.
"""
import sys
import threading
import uuid

import socketio

URL = sys.argv[1] if len(sys.argv) > 1 else "https://localhost:5000"


class FakePhone:
    def __init__(self, name):
        self.name = name
        self.sio = socketio.Client(ssl_verify=False)
        self.welcome = None
        self.state = None
        self.last_seq = 0
        self.got = threading.Event()
        self.sio.on("msg", self.on_msg)

    def on_msg(self, m):
        if m["type"] == "welcome":
            self.welcome = m["payload"]
        elif m["type"] in ("state_update", "state_sync"):
            if m["type"] == "state_sync" or m["seq"] > self.last_seq:
                self.last_seq, self.state = m["seq"], m["payload"]["state"]
                evs = [e["type"] for e in m["payload"].get("events", [])]
                print(f"  [{self.name}] seq={m['seq']} eventos={evs}")
                self.got.set()
        elif m["type"] == "error":
            print(f"  [{self.name}] ERROR {m['payload']}")

    def send(self, type_, payload=None, action=False):
        m = {"v": 1, "type": type_, "payload": payload or {}}
        if action:
            m["action_id"] = str(uuid.uuid4())
        self.got.clear()
        self.sio.emit("msg", m)

    def wait(self):
        assert self.got.wait(5), f"{self.name}: sin respuesta"


a, b = FakePhone("A"), FakePhone("B")
for p in (a, b):
    p.sio.connect(URL, transports=["websocket"])
    print(f"{p.name} conectado por {p.sio.transport()}")
    p.send("join", {"name": p.name})
    p.wait()

turn = a.state["turn_number"]
card = next(p for p in a.state["players"] if "hand" in p)["hand"][0]   # una carta de MI mano
attack = next(c for c in a.welcome["catalog"]["cards"] if c["card_id"] == card)["attack"]
b.got.clear()
a.send("play_card", {"card_id": card, "expected_turn": turn, "source": "ui"}, action=True)
b.wait()
start = b.state["players"][0]["max_life"]
lives = {p["name"]: p["life"] for p in b.state["players"]}
print(f"A juega {card} (ataque {attack}). Vidas vistas por B:", lives)
assert lives == {"A": start, "B": start - attack}, lives
for p in (a, b):
    p.sio.disconnect()
print("OK: evento en tiempo real recibido por el otro jugador")
