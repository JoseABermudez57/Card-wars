"""Catálogo de cartas.

* CardDefinition: plantilla inmutable (lo impreso en la carta física).
* CardCatalog:    el conjunto de definiciones, cargado desde data/cards.json.
                  Ese JSON es la ÚNICA fuente de verdad: el servidor lo carga
                  y lo envía a los clientes (web hoy, Unity mañana) al conectar.
* CardInstance:   una copia concreta en mesa, con vida actual. Su `uid` lo
                  asigna la partida (contador por partida, determinista).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "cards.json"


@dataclass(frozen=True)
class CardDefinition:
    card_id: str      # identificador estable, usado en red
    name: str
    max_hp: int
    attack: int
    marker_id: int    # id del marcador ArUco impreso en la carta física
    model_key: str    # clave del asset (sprite hoy, Addressable/modelo 3D en Unity)

    @classmethod
    def from_dict(cls, d: dict) -> "CardDefinition":
        return cls(
            card_id=str(d["card_id"]),
            name=str(d["name"]),
            max_hp=int(d["max_hp"]),
            attack=int(d["attack"]),
            marker_id=int(d["marker_id"]),
            model_key=str(d.get("model_key", d["card_id"])),
        )

    def to_dict(self) -> dict:
        return asdict(self)


class CardCatalog:
    def __init__(self, cards: list[CardDefinition], version: int = 1) -> None:
        self.version = version
        self._by_id: dict[str, CardDefinition] = {}
        self._by_marker: dict[int, CardDefinition] = {}
        for card in cards:
            if card.card_id in self._by_id:
                raise ValueError(f"card_id duplicado: {card.card_id}")
            if card.marker_id in self._by_marker:
                raise ValueError(f"marker_id duplicado: {card.marker_id}")
            self._by_id[card.card_id] = card
            self._by_marker[card.marker_id] = card

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CATALOG_PATH) -> "CardCatalog":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([CardDefinition.from_dict(c) for c in data["cards"]], data.get("version", 1))

    def has(self, card_id: str) -> bool:
        return card_id in self._by_id

    def get(self, card_id: str) -> CardDefinition:
        try:
            return self._by_id[card_id]
        except KeyError:
            raise ValueError(f"Carta desconocida: {card_id!r}") from None

    def from_marker(self, marker_id: int) -> CardDefinition | None:
        return self._by_marker.get(marker_id)

    def ids(self) -> list[str]:
        return list(self._by_id)

    def to_dict(self) -> dict:
        return {"version": self.version, "cards": [c.to_dict() for c in self._by_id.values()]}


_default_catalog: CardCatalog | None = None


def default_catalog() -> CardCatalog:
    global _default_catalog
    if _default_catalog is None:
        _default_catalog = CardCatalog.load()
    return _default_catalog


@dataclass
class CardInstance:
    definition: CardDefinition
    uid: int
    hp: int = field(init=False)

    def __post_init__(self) -> None:
        self.hp = self.definition.max_hp

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    def take_damage(self, amount: int) -> int:
        """Aplica daño y devuelve el sobrante (overflow) si la criatura muere."""
        overflow = max(0, amount - self.hp)
        self.hp = max(0, self.hp - amount)
        return overflow

    def to_dict(self) -> dict:
        return {**self.definition.to_dict(), "uid": self.uid, "hp": self.hp}
