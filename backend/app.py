"""Servidor del POC: Flask (archivos) + dos transportes de tiempo real:
  * Socket.IO  (canal "msg")  -> cliente web del navegador
  * WebSocket puro en /ws     -> clientes nativos (Unity). Mismo protocolo v1.

Esta capa es solo TRANSPORTE: traduce mensajes del protocolo a llamadas a
`game/` y emite los resultados. No contiene reglas de juego.

Uso:
    python backend/app.py                 # HTTPS :5000 (web) + HTTP :5001 (Unity, ws://…/ws)
    python backend/app.py --no-https      # todo por HTTP en :5000 (cámara web solo en localhost)
"""
from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import ipaddress
import json
import logging
import secrets
import socket
import sys
import threading
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_sock import Sock
from flask_socketio import SocketIO
from simple_websocket import ConnectionClosed

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
CLIENT_DIR = ROOT_DIR / "client"
CERT_DIR = BACKEND_DIR / "certs"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR))  # para importar el paquete vision/

from game.game_manager import DuplicateActionError, Game, GameError, GameManager, GameUpdate  # noqa: E402
from protocol import (PROTOCOL_VERSION, ClientMessage, ProtocolError, envelope,  # noqa: E402
                      optional, parse_client_message, require)

log = logging.getLogger("card_ar_poc")

MAX_FRAME_BYTES = 1_000_000          # un JPEG de 640px ronda 30-60 KB
DISCONNECT_GRACE_SECONDS = 60


def load_detector():
    """La visión es opcional: si OpenCV no está, el resto del juego funciona."""
    try:
        from vision.card_detector import CardDetector
        return CardDetector(), None
    except Exception as exc:  # ImportError, cv2 ausente, etc.
        return None, str(exc)


class WebSocketConnection:
    """Conexión WebSocket pura. El lock evita que dos hilos (p. ej. la jugada
    del rival y la respuesta a un frame) entrelacen bytes en el mismo socket."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.lock = threading.Lock()

    def send(self, msg: dict) -> None:
        try:
            with self.lock:
                self.ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception:
            pass  # ya cerrada: el bucle de recepción hace la limpieza


class GameServer:
    def __init__(self, socketio: SocketIO, manager: GameManager, detector,
                 grace_seconds: float) -> None:
        self.socketio = socketio
        self.manager = manager
        self.detector = detector
        self.grace_seconds = grace_seconds
        self._lock = threading.Lock()
        self.sessions: dict[str, tuple[str, str]] = {}         # sid -> (game_id, player_id)
        self.player_sids: dict[tuple[str, str], str] = {}      # (game_id, player_id) -> sid
        self.disconnect_epoch: dict[tuple[str, str], int] = {}
        # Conexiones WebSocket puras. "cid" (connection id) = sid de Socket.IO o "ws-…".
        self.ws_connections: dict[str, WebSocketConnection] = {}
        self.handlers = {
            "join": self.on_join,
            "play_card": self.on_play_card,
            "attack": self.on_attack,
            "rematch": self.on_rematch,
            "sync": self.on_sync,
            "frame": self.on_frame,
        }
        socketio.on_event("msg", lambda raw: self.handle_message(request.sid, raw))
        socketio.on_event("disconnect", lambda *_: self.handle_disconnect(request.sid))

    # ------------------------------------------------------------- emisión
    def send(self, sid: str, msg_type: str, payload: dict | None = None, **kw) -> None:
        """Envía por el transporte que tenga esa conexión. La lógica no lo sabe."""
        msg = envelope(msg_type, payload, **kw)
        conn = self.ws_connections.get(sid)
        if conn is not None:
            conn.send(msg)
        else:
            self.socketio.emit("msg", msg, to=sid)

    def broadcast(self, game: Game, update: GameUpdate | None) -> None:
        """Llamar con game.lock tomado: así el orden de envío == orden de seq.
        Cada jugador recibe SU vista (información oculta filtrada)."""
        if update is None:
            return
        for p in game.players:
            sid = self.player_sids.get((game.game_id, p.player_id))
            if sid:
                self.send(sid, "state_update",
                          {"events": update.events, "state": game.view(p.player_id)},
                          seq=update.seq)

    def send_sync(self, sid: str, game: Game, player_id: str) -> None:
        with game.lock:
            self.send(sid, "state_sync", {"state": game.view(player_id)}, seq=game.seq)

    # ------------------------------------------------------------- entrada
    def handle_message(self, sid: str, raw) -> None:
        action_id = raw.get("action_id") if isinstance(raw, dict) else None
        try:
            msg = parse_client_message(raw)
            self.handlers[msg.type](sid, msg)
        except DuplicateActionError:
            # Reintento de algo ya aplicado: no es error, solo re-sincronizamos.
            game, player_id = self._session(sid)
            self.send_sync(sid, game, player_id)
        except (ProtocolError, GameError) as exc:
            self.send(sid, "error", {"code": exc.code, "message": str(exc)}, action_id=action_id)
            if isinstance(exc, GameError) and sid in self.sessions:
                game, player_id = self._session(sid)
                self.send_sync(sid, game, player_id)   # el cliente vuelve a la verdad
        except Exception:
            log.exception("Error procesando mensaje")
            self.send(sid, "error", {"code": "internal", "message": "Error interno"},
                      action_id=action_id)

    def _session(self, sid: str) -> tuple[Game, str]:
        try:
            game_id, player_id = self.sessions[sid]
        except KeyError:
            raise ProtocolError("Primero envía 'join'", "not_joined") from None
        return self.manager.get_or_create(game_id), player_id

    # ------------------------------------------------------------- handlers
    def on_join(self, sid: str, msg: ClientMessage) -> None:
        if sid in self.sessions:
            raise ProtocolError("Ya estás en una partida", "already_joined")
        name = optional(msg.payload, "name", str) or ""
        token = optional(msg.payload, "session_token", str)
        game_id = (optional(msg.payload, "game_id", str) or "default")[:32]
        game = self.manager.get_or_create(game_id)
        with game.lock:
            player, update = game.join(name, token)
            key = (game_id, player.player_id)
            with self._lock:
                old_sid = self.player_sids.get(key)
                if old_sid and old_sid != sid:
                    self.sessions.pop(old_sid, None)   # otra pestaña: la nueva gana
                self.sessions[sid] = key
                self.player_sids[key] = sid
            self.send(sid, "welcome", {
                "player_id": player.player_id,
                "session_token": player.session_token,
                "game_id": game_id,
                "protocol_version": PROTOCOL_VERSION,
                "catalog": game.catalog.to_dict(),
                "vision_available": self.detector is not None,
            })
            self.broadcast(game, update)
        log.info("join %s (%s) -> %s", player.name, player.player_id, game_id)

    def on_play_card(self, sid: str, msg: ClientMessage) -> None:
        game, player_id = self._session(sid)
        card_id = require(msg.payload, "card_id", str)
        source = optional(msg.payload, "source", str) or "ui"
        with game.lock:
            update = game.play_card(player_id, card_id, action_id=msg.action_id,
                                    expected_turn=optional(msg.payload, "expected_turn", int),
                                    source=source if source in ("ui", "camera") else "ui",
                                    target_id=optional(msg.payload, "target_id", str))
            self.broadcast(game, update)

    def on_attack(self, sid: str, msg: ClientMessage) -> None:
        game, player_id = self._session(sid)
        with game.lock:
            update = game.attack(player_id, action_id=msg.action_id,
                                 expected_turn=optional(msg.payload, "expected_turn", int),
                                 target_id=optional(msg.payload, "target_id", str))
            self.broadcast(game, update)

    def on_rematch(self, sid: str, msg: ClientMessage) -> None:
        game, player_id = self._session(sid)
        with game.lock:
            self.broadcast(game, game.request_rematch(player_id))

    def on_sync(self, sid: str, msg: ClientMessage) -> None:
        game, player_id = self._session(sid)
        self.send_sync(sid, game, player_id)

    def on_frame(self, sid: str, msg: ClientMessage) -> None:
        game, _ = self._session(sid)
        frame_id = msg.payload.get("frame_id")
        if self.detector is None:
            raise ProtocolError("Visión no disponible en el servidor", "vision_unavailable")
        image = require(msg.payload, "image", str)
        if "," in image[:64]:                    # admite data URLs "data:image/jpeg;base64,..."
            image = image.split(",", 1)[1]
        if len(image) > MAX_FRAME_BYTES * 4 // 3 + 4:
            raise ProtocolError("Frame demasiado grande", "frame_too_large")
        try:
            data = base64.b64decode(image, validate=True)
        except (binascii.Error, ValueError):
            raise ProtocolError("Imagen base64 inválida", "bad_frame") from None
        # Fuera del lock de la partida: la visión es CPU y no toca el estado.
        try:
            marker_ids = self.detector.detect_jpeg(data)
        except ValueError:
            raise ProtocolError("La imagen no es un JPEG/PNG válido", "bad_frame") from None
        cards = [c.to_dict() for m in marker_ids if (c := game.catalog.from_marker(m))]
        # Se responde SIEMPRE (aunque no haya cartas): el cliente lo usa como
        # señal para enviar el siguiente frame (control de flujo).
        self.send(sid, "card_detected",
                  {"frame_id": frame_id, "marker_ids": marker_ids, "cards": cards})

    # -------------------------------------------------------- desconexión
    def serve_websocket(self, ws) -> None:
        """Bucle de una conexión WebSocket pura: un frame de texto = un mensaje."""
        sid = "ws-" + secrets.token_hex(8)
        self.ws_connections[sid] = WebSocketConnection(ws)
        try:
            while True:
                text = ws.receive()
                try:
                    raw = json.loads(text)
                except (TypeError, ValueError):
                    self.send(sid, "error", {"code": "bad_message", "message": "JSON inválido"})
                    continue
                self.handle_message(sid, raw)
        except ConnectionClosed:
            pass
        finally:
            self.handle_disconnect(sid)
            self.ws_connections.pop(sid, None)

    def handle_disconnect(self, sid: str) -> None:
        with self._lock:
            key = self.sessions.pop(sid, None)
            if key is None or self.player_sids.get(key) != sid:
                return                           # sin partida, o ya sustituido por otra conexión
            del self.player_sids[key]
            epoch = self.disconnect_epoch[key] = self.disconnect_epoch.get(key, 0) + 1
        game = self.manager.get(key[0])
        if game is None:
            return
        with game.lock:
            self.broadcast(game, game.mark_disconnected(key[1]))
        self.socketio.start_background_task(self._expire_disconnected, key, epoch)

    def _expire_disconnected(self, key: tuple[str, str], epoch: int) -> None:
        self.socketio.sleep(self.grace_seconds)
        if self.disconnect_epoch.get(key) != epoch:
            return                               # se volvió a desconectar: manda el timer nuevo
        game = self.manager.get(key[0])
        if game is None:
            return
        with game.lock:
            player = game.get_player(key[1])
            if player is None or player.connected:
                return
            # Si estaba jugando, pierde por abandono; y en cualquier caso libera
            # su puesto para que pueda entrar otro jugador.
            self.broadcast(game, game.forfeit(key[1]))
            self.broadcast(game, game.leave(key[1]))
        log.info("jugador %s expirado tras %ss desconectado", key[1], self.grace_seconds)


def create_app(grace_seconds: float = DISCONNECT_GRACE_SECONDS, detector="auto"):
    app = Flask(__name__, static_folder=None)
    socketio = SocketIO(app, async_mode="threading", max_http_buffer_size=2 * MAX_FRAME_BYTES)
    if detector == "auto":
        detector, error = load_detector()
        if error:
            log.warning("Visión desactivada: %s", error)
    server = GameServer(socketio, GameManager(), detector, grace_seconds)

    # WebSocket puro para clientes nativos. ping_interval detecta móviles dormidos.
    app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 20,
                                         "max_message_size": 2 * MAX_FRAME_BYTES}
    sock = Sock(app)

    @sock.route("/ws")
    def ws_endpoint(ws):
        server.serve_websocket(ws)

    @app.get("/")
    def index():
        return send_from_directory(CLIENT_DIR, "index.html")

    @app.get("/<path:path>")
    def client_files(path: str):
        if not (CLIENT_DIR / path).is_file():
            abort(404)
        return send_from_directory(CLIENT_DIR, path)

    @app.get("/health")
    def health():
        return jsonify(ok=True, protocol_version=PROTOCOL_VERSION,
                       vision_available=server.detector is not None)

    return app, socketio, server


# ----------------------------------------------------------------- arranque
def local_ip() -> str:
    """IP de la LAN (no envía paquetes: solo consulta la tabla de rutas)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def ensure_certificate(ip: str) -> tuple[str, str]:
    """Certificado autofirmado persistente (aceptas el aviso una vez por dispositivo).
    Se regenera si cambia la IP de la LAN."""
    cert, key, ip_file = CERT_DIR / "cert.pem", CERT_DIR / "key.pem", CERT_DIR / "ip.txt"
    if cert.exists() and key.exists() and ip_file.exists() and ip_file.read_text() == ip:
        return str(cert), str(key)
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    CERT_DIR.mkdir(exist_ok=True)
    private_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "card-ar-poc")])
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.IPAddress(ipaddress.ip_address(ip)),
        ]), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    key.write_bytes(private_key.private_bytes(serialization.Encoding.PEM,
                                              serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    ip_file.write_text(ip)
    return str(cert), str(key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor del POC de cartas")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-https", action="store_true", help="servir por HTTP")
    parser.add_argument("--native-port", type=int, default=5001,
                        help="puerto HTTP sin cifrar para clientes nativos (Unity); 0 = desactivar")
    parser.add_argument("--grace", type=float, default=DISCONNECT_GRACE_SECONDS,
                        help="segundos de gracia tras desconexión antes de perder")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app, socketio, _ = create_app(grace_seconds=args.grace)
    ip = local_ip()
    ssl_context = None if args.no_https else ensure_certificate(ip)
    scheme = "http" if args.no_https else "https"
    native_url = f"ws://{ip}:{args.port}/ws"
    if ssl_context and args.native_port:
        # Una app nativa no necesita HTTPS para la cámara, y Unity rechaza
        # certificados autofirmados: le damos un puerto HTTP aparte.
        from werkzeug.serving import make_server
        native = make_server(args.host, args.native_port, app, threaded=True)
        threading.Thread(target=native.serve_forever, daemon=True).start()
        native_url = f"ws://{ip}:{args.native_port}/ws"
    print(f"\n  Abre en los teléfonos:  {scheme}://{ip}:{args.port}\n"
          f"  En este PC:             {scheme}://localhost:{args.port}\n"
          f"  Unity / nativo:         {native_url}\n")
    socketio.run(app, host=args.host, port=args.port, ssl_context=ssl_context,
                 allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
