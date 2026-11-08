"""Contrato de mensajes cliente <-> servidor (independiente del transporte).

Todos los mensajes viajan por UN solo canal ("msg" en Socket.IO; un frame de
texto si mañana se usa WebSocket puro) con este sobre JSON:

    {"v": 1, "type": "<tipo>", "action_id": "<uuid opcional>", "seq": <int opcional>,
     "payload": {...}}

Cliente -> servidor
    join       {name, session_token?, game_id?}
    play_card  {card_id, expected_turn, source: "ui"|"camera", target_id?}  + action_id
    attack     {expected_turn, target_id?}                                  + action_id
    rematch    {}
    sync       {}
    frame      {image: <jpeg base64 / data URL>, frame_id}

Servidor -> cliente
    welcome        {player_id, session_token, game_id, catalog, vision_available}
    state_update   {events: [{type, payload}], state}     + seq  (aplicar si seq > último)
    state_sync     {state}                                + seq  (aplicar siempre)
    card_detected  {frame_id, marker_ids, cards}
    error          {code, message}                        + action_id

Regla de oro: no usar funciones propias de Socket.IO (acks, rooms en el
cliente...) en la lógica, para que Unity pueda hablar con WebSocket puro.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PROTOCOL_VERSION = 1

CLIENT_MESSAGE_TYPES = {"join", "play_card", "attack", "rematch", "sync", "frame"}


class ProtocolError(Exception):
    def __init__(self, message: str, code: str = "bad_message") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ClientMessage:
    type: str
    payload: dict = field(default_factory=dict)
    action_id: str | None = None


def parse_client_message(raw) -> ClientMessage:
    if not isinstance(raw, dict):
        raise ProtocolError("El mensaje debe ser un objeto JSON")
    if raw.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(f"Versión de protocolo no soportada: {raw.get('v')!r} "
                            f"(servidor: {PROTOCOL_VERSION})", "unsupported_version")
    msg_type = raw.get("type")
    if msg_type not in CLIENT_MESSAGE_TYPES:
        raise ProtocolError(f"Tipo de mensaje desconocido: {msg_type!r}", "unknown_type")
    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        raise ProtocolError("payload debe ser un objeto")
    action_id = raw.get("action_id")
    if action_id is not None and (not isinstance(action_id, str) or len(action_id) > 64):
        raise ProtocolError("action_id inválido")
    return ClientMessage(msg_type, payload, action_id)


def envelope(msg_type: str, payload: dict | None = None, *, seq: int | None = None,
             action_id: str | None = None) -> dict:
    msg = {"v": PROTOCOL_VERSION, "type": msg_type, "payload": payload or {}}
    if seq is not None:
        msg["seq"] = seq
    if action_id is not None:
        msg["action_id"] = action_id
    return msg


def require(payload: dict, key: str, kind: type):
    value = payload.get(key)
    if not isinstance(value, kind) or isinstance(value, bool) and kind is int:
        raise ProtocolError(f"Campo '{key}' obligatorio de tipo {kind.__name__}")
    return value


def optional(payload: dict, key: str, kind: type):
    value = payload.get(key)
    if value is not None and not isinstance(value, kind):
        raise ProtocolError(f"Campo '{key}' debe ser {kind.__name__}")
    return value
