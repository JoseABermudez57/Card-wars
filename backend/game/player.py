"""Jugador de una partida.

No conoce sockets ni Flask. Dos identificadores distintos:
* player_id:     público, se envía a todos (quién atacó a quién).
* session_token: secreto, solo lo conoce su dueño; sirve para reconectar.
                 Con cuentas de usuario será sustituido por el token de auth.

Cartas del jugador:
* deck_list: el mazo que registró (composición; se reutiliza en la revancha).
* deck:      la pila de robo barajada (OCULTA para todos, incluido su dueño).
* hand:      cartas que puede jugar (solo la ve su dueño).
* discard:   criaturas destruidas (pública).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .cards import CardInstance
from .rules import DEFAULT_RULES

# Vida inicial por defecto (la de una partida concreta está en GameRules.starting_life).
STARTING_LIFE = DEFAULT_RULES.starting_life


@dataclass
class Player:
    player_id: str
    name: str
    session_token: str = field(repr=False)
    life: int = STARTING_LIFE
    max_life: int = STARTING_LIFE
    deck_list: list[str] = field(default_factory=list)
    deck: list[str] = field(default_factory=list, repr=False)
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

    def reset_for_new_game(self, life: int, shuffled_deck: list[str]) -> None:
        self.life = life
        self.max_life = life
        self.deck = list(shuffled_deck)
        self.hand = []
        self.creature = None
        self.discard = []
        self.eliminated = False
        self.wants_rematch = False

    def draw(self) -> str | None:
        """Roba la carta de arriba del mazo (o None si está vacío)."""
        if not self.deck:
            return None
        card = self.deck.pop()
        self.hand.append(card)
        return card

    def to_dict(self, viewer_id: str | None = None) -> dict:
        """Vista del jugador para `viewer_id`: la mano solo la ve su dueño;
        del mazo solo se publica cuántas cartas quedan."""
        data = {
            "player_id": self.player_id,
            "name": self.name,
            "life": self.life,
            "max_life": self.max_life,   # los clientes dibujan la barra con esto
            "field": [self.creature.to_dict()] if self.creature else [],
            "discard": list(self.discard),
            "hand_count": len(self.hand),
            "deck_count": len(self.deck),
            "connected": self.connected,
            "eliminated": self.eliminated,
            "wants_rematch": self.wants_rematch,
        }
        if viewer_id == self.player_id:
            data["hand"] = list(self.hand)
        return data
