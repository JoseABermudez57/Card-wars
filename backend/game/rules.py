"""Parámetros de reglas y mazos.

GameRules agrupa los números que definen el equilibrio. Se ajustan con datos
(tools/balance_report.py), no a ojo; tests/test_balance.py protege el resultado.

Los mazos son listas de card_id. El mazo inicial vive en data/decks.json; un
cliente puede enviar el suyo en `join` y aquí se valida.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .cards import CardCatalog

DEFAULT_DECKS_PATH = Path(__file__).resolve().parents[2] / "data" / "decks.json"


@dataclass(frozen=True)
class GameRules:
    """Valores por defecto medidos con tools/balance_report.py (mazo inicial de 6):

    * Vida 90: el punto donde se compensan las dos ventajas de asiento. Con vida
      baja decide el daño directo y el primer golpe de P1 domina (vida 80: P1 ~74 %);
      con vida alta decide el desgaste de criaturas y domina P2 (vida 100: P1 ~39 %).
      Con 90: P1 ~55 % y ~30 % de partidas decididas por vida. Los daños son
      múltiplos de 10, así que la vida solo tiene saltos de 10.
    * Mano inicial 3: P1 ~55 % (con 2, ~54 %) y más decisiones: un jugador experto
      gana ~88 % a uno aleatorio (con 2, ~87 %).
    """
    starting_life: int = 90
    initial_hand: int = 3        # cartas que se reparten al empezar
    draw_per_turn: int = 1       # cartas que se roban al empezar cada turno
    first_turn_draw: bool = False  # ¿roba el primer jugador en su primer turno?
    first_turn_attack: bool = True  # ¿ataca la criatura que juega P1 en el turno 1?
    deck_min: int = 6
    deck_max: int = 12
    max_copies: int = 2          # copias máximas de una misma carta en un mazo


DEFAULT_RULES = GameRules()


class DeckError(ValueError):
    """Mazo inválido (el servidor lo traduce a un error con code='invalid_deck')."""


def validate_deck(deck: list[str], catalog: CardCatalog, rules: GameRules) -> list[str]:
    if not isinstance(deck, list) or not all(isinstance(c, str) for c in deck):
        raise DeckError("El mazo debe ser una lista de card_id")
    if not rules.deck_min <= len(deck) <= rules.deck_max:
        raise DeckError(f"El mazo debe tener entre {rules.deck_min} y {rules.deck_max} cartas")
    unknown = sorted({c for c in deck if not catalog.has(c)})
    if unknown:
        raise DeckError(f"Cartas desconocidas: {', '.join(unknown)}")
    too_many = sorted(c for c, n in Counter(deck).items() if n > rules.max_copies)
    if too_many:
        raise DeckError(f"Máximo {rules.max_copies} copias por carta: {', '.join(too_many)}")
    return list(deck)


def load_decks(path: Path | str = DEFAULT_DECKS_PATH) -> dict[str, list[str]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["decks"]


_starter: list[str] | None = None


def starter_deck() -> list[str]:
    global _starter
    if _starter is None:
        _starter = load_decks()["starter"]
    return list(_starter)
