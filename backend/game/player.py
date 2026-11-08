"""Jugador de una partida.

No conoce sockets ni Flask. Dos identificadores distintos:
* player_id:     público, se envía a todos (quién atacó a quién).
* session_token: secreto, solo lo conoce su dueño; sirve para reconectar.
                 Con cuentas de usuario será sustituido por el token de auth.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .cards import CardInstance

STARTING_LIFE = 100


@dataclass
class Player:
    player_id: str
    name: str
    session_token: str = field(repr=False)
    life: int = STARTING_LIFE
    # Cartas que puede jugar. En el POC: una de cada (las físicas que tiene).
    # Mañana se rellena desde su mazo persistido.
    hand: list[str] = field(default_factory=list)
    # Una criatura en mesa. Se envía como lista para poder pasar a varios slots
    # sin romper el protocolo.
    creature: CardInstance | None = None
    discard: list[str] = field(default_factory=list)
    connected: bool = True
    eliminated: bool = False
    wants_rematch: bool = False

    @property
    def is_active(self) -> bool:
        """Sigue en la partida."""
        return self.life > 0 and not self.eliminated

    @property
    def can_act(self) -> bool:
        """Tiene algo que hacer en su turno: atacar o jugar una carta."""
        return (self.creature is not None and self.creature.is_alive) or bool(self.hand)

    def take_damage(self, amount: int) -> None:
        self.life = max(0, self.life - amount)

    def reset_for_new_game(self, hand: list[str]) -> None:
        self.life = STARTING_LIFE
        self.hand = list(hand)
        self.creature = None
        self.discard = []
        self.eliminated = False
        self.wants_rematch = False

    def to_dict(self, viewer_id: str | None = None) -> dict:
        """Vista del jugador para `viewer_id`: la mano solo la ve su dueño."""
        data = {
            "player_id": self.player_id,
            "name": self.name,
            "life": self.life,
            "field": [self.creature.to_dict()] if self.creature else [],
            "discard": list(self.discard),
            "hand_count": len(self.hand),
            "connected": self.connected,
            "eliminated": self.eliminated,
            "wants_rematch": self.wants_rematch,
        }
        if viewer_id == self.player_id:
            data["hand"] = list(self.hand)
        return data
