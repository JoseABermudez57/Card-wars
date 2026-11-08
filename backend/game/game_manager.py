"""Reglas y estado de la partida (servidor autoritativo). Python puro.

Recibe *intenciones*, las valida, modifica el estado y devuelve un
GameUpdate(seq, events). `seq` sube en cada cambio confirmado: los clientes
descartan cualquier actualización con seq <= la última aplicada.

Reglas del POC (v2):
  1. Cada jugador empieza con 100 de vida y una mano con una carta de cada tipo.
  2. En tu turno haces UNA acción:
       - play_card: solo si NO tienes criatura en mesa. La carta sale de tu mano,
         entra en mesa y ataca inmediatamente.
       - attack:    si tienes criatura en mesa, ataca.
  3. El ataque golpea a la criatura rival; si la mata, el daño sobrante pasa
     al jugador. Sin criatura rival, el golpe va directo al jugador.
     Las criaturas destruidas van al descarte (no vuelven a la mano).
  4. Pierdes si tu vida llega a 0, o si empieza tu turno sin criatura ni cartas.
  5. La partida termina siempre: cada turno hace >= 20 de daño y no hay curación.

Concurrencia: `self.lock` (RLock). La capa de red lo mantiene durante
"aplicar acción + emitir", para que el orden de envío respete el de seq.
"""
from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum

from .cards import CardCatalog, CardInstance, default_catalog
from .player import Player


class GameStatus(str, Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class GameError(Exception):
    """Acción inválida. `code` es estable y legible por máquinas (Unity)."""

    def __init__(self, message: str, code: str = "invalid_action") -> None:
        super().__init__(message)
        self.code = code


class DuplicateActionError(GameError):
    """El action_id ya se procesó (reintento o doble toque). No es un fallo."""

    def __init__(self, action_id: str) -> None:
        super().__init__(f"Acción ya procesada: {action_id}", "duplicate_action")


def event(type_: str, **payload) -> dict:
    """Todos los eventos tienen la forma {type, payload}: fácil de tipar en C#."""
    return {"type": type_, "payload": payload}


@dataclass(frozen=True)
class GameUpdate:
    seq: int
    events: list[dict]


class Game:
    MAX_REMEMBERED_ACTIONS = 256

    def __init__(self, game_id: str = "default", catalog: CardCatalog | None = None,
                 max_players: int = 2) -> None:
        self.game_id = game_id
        self.catalog = catalog or default_catalog()
        self.max_players = max_players
        self.lock = threading.RLock()
        self.seq = 0
        self.players: list[Player] = []
        self.status = GameStatus.WAITING
        self.turn_index = 0
        self.turn_number = 0
        self.winner_id: str | None = None
        self.end_reason: str | None = None
        self._next_uid = 1
        self._seen_actions: OrderedDict[str, int] = OrderedDict()

    # ---------------------------------------------------------------- helpers
    def _commit(self, events: list[dict]) -> GameUpdate:
        self.seq += 1
        return GameUpdate(self.seq, events)

    def _new_uid(self) -> int:
        uid, self._next_uid = self._next_uid, self._next_uid + 1
        return uid

    def get_player(self, player_id: str) -> Player | None:
        return next((p for p in self.players if p.player_id == player_id), None)

    def find_by_token(self, token: str) -> Player | None:
        return next((p for p in self.players
                     if secrets.compare_digest(p.session_token, token)), None)

    @property
    def current_player(self) -> Player | None:
        if self.status != GameStatus.IN_PROGRESS:
            return None
        return self.players[self.turn_index]

    # -------------------------------------------------------------- jugadores
    def join(self, name: str, session_token: str | None = None) -> tuple[Player, GameUpdate]:
        """Entrar en la partida, o reconectar si se presenta un token válido."""
        with self.lock:
            if session_token and (player := self.find_by_token(session_token)):
                player.connected = True
                return player, self._commit([event("player_reconnected",
                                                   player_id=player.player_id)])
            if self.status == GameStatus.IN_PROGRESS or len(self.players) >= self.max_players:
                raise GameError("La partida está llena", "game_full")
            if self.status == GameStatus.FINISHED:
                # Hay un hueco porque alguien se fue: la sala vuelve a esperar.
                self.status, self.winner_id, self.end_reason = GameStatus.WAITING, None, None
                self.turn_number = 0
            name = (name or "").strip()[:20] or f"Jugador {len(self.players) + 1}"
            player_id = secrets.token_hex(4)
            while self.get_player(player_id):
                player_id = secrets.token_hex(4)
            player = Player(player_id=player_id, name=name,
                            session_token=secrets.token_urlsafe(24))
            self.players.append(player)
            events = [event("player_joined", player_id=player_id, name=name)]
            if len(self.players) == self.max_players:
                events += self._start()
            return player, self._commit(events)

    def mark_disconnected(self, player_id: str) -> GameUpdate | None:
        with self.lock:
            player = self.get_player(player_id)
            if not player or not player.connected:
                return None
            player.connected = False
            return self._commit([event("player_disconnected", player_id=player_id)])

    def leave(self, player_id: str) -> GameUpdate | None:
        """Quita a un jugador fuera de partida (sala de espera o partida acabada).
        Si la partida había terminado, se conserva el resultado (el ganador sigue
        viendo su victoria) hasta que entre un jugador nuevo."""
        with self.lock:
            player = self.get_player(player_id)
            if not player or self.status == GameStatus.IN_PROGRESS:
                return None
            self.players.remove(player)
            for p in self.players:
                p.wants_rematch = False
            return self._commit([event("player_left", player_id=player_id)])

    def forfeit(self, player_id: str, reason: str = "abandon") -> GameUpdate | None:
        with self.lock:
            player = self.get_player(player_id)
            if self.status != GameStatus.IN_PROGRESS or not player or not player.is_active:
                return None
            was_current = player is self.current_player
            player.eliminated = True
            events = [event("player_eliminated", player_id=player_id, reason=reason)]
            events += self._check_victory()
            if self.status == GameStatus.IN_PROGRESS and was_current:
                events += self._advance_turn()
            return self._commit(events)

    def request_rematch(self, player_id: str) -> GameUpdate:
        with self.lock:
            player = self.get_player(player_id)
            if not player:
                raise GameError("No perteneces a esta partida", "not_in_game")
            if self.status != GameStatus.FINISHED:
                raise GameError("La partida no ha terminado", "not_finished")
            if len(self.players) < self.max_players:
                raise GameError("Tu rival se fue: espera a un jugador nuevo", "rival_left")
            player.wants_rematch = True
            events = [event("rematch_requested", player_id=player_id)]
            if all(p.wants_rematch for p in self.players):
                events += self._start()
            return self._commit(events)

    # ----------------------------------------------------------------- turnos
    def _start(self) -> list[dict]:
        for p in self.players:
            p.reset_for_new_game(self.catalog.ids())
        self.status = GameStatus.IN_PROGRESS
        self.winner_id = self.end_reason = None
        self.turn_index, self.turn_number = 0, 1
        self._next_uid = 1
        return [event("game_started", current_player_id=self.players[0].player_id,
                      turn_number=1)]

    def _finish(self, winner: Player | None, reason: str) -> list[dict]:
        self.status = GameStatus.FINISHED
        self.winner_id = winner.player_id if winner else None
        self.end_reason = reason
        return [event("game_over", winner_id=self.winner_id, reason=reason)]

    def _check_victory(self) -> list[dict]:
        events = []
        for p in self.players:
            if p.life <= 0 and not p.eliminated:
                p.eliminated = True
                events.append(event("player_eliminated", player_id=p.player_id, reason="life"))
        active = [p for p in self.players if p.is_active]
        if len(active) <= 1:
            events += self._finish(active[0] if active else None, "last_standing")
        return events

    def _advance_turn(self) -> list[dict]:
        """Pasa al siguiente jugador activo. Elimina a quien no pueda actuar."""
        events: list[dict] = []
        n = len(self.players)
        idx = self.turn_index
        for _ in range(n):
            idx = (idx + 1) % n
            candidate = self.players[idx]
            if not candidate.is_active:
                continue
            if not candidate.can_act:
                candidate.eliminated = True
                events.append(event("player_eliminated", player_id=candidate.player_id,
                                    reason="no_creatures"))
                events += self._check_victory()
                if self.status != GameStatus.IN_PROGRESS:
                    return events
                continue
            self.turn_index = idx
            self.turn_number += 1
            events.append(event("turn_changed", current_player_id=candidate.player_id,
                                 turn_number=self.turn_number))
            return events
        return events

    def _end_turn(self) -> list[dict]:
        events = self._check_victory()
        if self.status == GameStatus.IN_PROGRESS:
            events += self._advance_turn()
        return events

    # --------------------------------------------------------------- acciones
    def _begin_action(self, player_id: str, action_id: str | None,
                      expected_turn: int | None) -> Player:
        if action_id and action_id in self._seen_actions:
            raise DuplicateActionError(action_id)
        if self.status != GameStatus.IN_PROGRESS:
            raise GameError("La partida no está en curso", "not_in_progress")
        player = self.get_player(player_id)
        if player is None:
            raise GameError("No perteneces a esta partida", "not_in_game")
        if player is not self.current_player:
            raise GameError("No es tu turno", "not_your_turn")
        if expected_turn is not None and expected_turn != self.turn_number:
            raise GameError("Acción obsoleta: el turno ya cambió", "stale_action")
        return player

    def _finish_action(self, action_id: str | None, events: list[dict]) -> GameUpdate:
        update = self._commit(events)
        if action_id:
            self._seen_actions[action_id] = update.seq
            while len(self._seen_actions) > self.MAX_REMEMBERED_ACTIONS:
                self._seen_actions.popitem(last=False)
        return update

    def _resolve_target(self, player: Player, target_id: str | None) -> Player:
        opponents = [p for p in self.players if p is not player and p.is_active]
        if target_id is None:
            if len(opponents) == 1:
                return opponents[0]
            raise GameError("Debes elegir un objetivo", "target_required")
        target = next((p for p in opponents if p.player_id == target_id), None)
        if target is None:
            raise GameError("Objetivo inválido", "invalid_target")
        return target

    def play_card(self, player_id: str, card_id: str, *, action_id: str | None = None,
                  expected_turn: int | None = None, source: str = "ui",
                  target_id: str | None = None) -> GameUpdate:
        with self.lock:
            player = self._begin_action(player_id, action_id, expected_turn)
            if player.creature is not None:
                raise GameError("Ya tienes una criatura en mesa: ataca con ella",
                                "creature_in_play")
            if not self.catalog.has(card_id):
                raise GameError(f"Carta desconocida: {card_id}", "unknown_card")
            if card_id not in player.hand:
                raise GameError("Esa carta no está en tu mano", "card_not_in_hand")
            target = self._resolve_target(player, target_id)
            # --- a partir de aquí, todo validado: mutamos ---
            player.hand.remove(card_id)
            creature = CardInstance(self.catalog.get(card_id), uid=self._new_uid())
            player.creature = creature
            events = [event("card_played", player_id=player_id, card=creature.to_dict(),
                            source=source)]
            events += self._attack(creature, target)
            events += self._end_turn()
            return self._finish_action(action_id, events)

    def attack(self, player_id: str, *, action_id: str | None = None,
               expected_turn: int | None = None, target_id: str | None = None) -> GameUpdate:
        with self.lock:
            player = self._begin_action(player_id, action_id, expected_turn)
            if player.creature is None:
                raise GameError("No tienes criatura en mesa", "no_creature")
            target = self._resolve_target(player, target_id)
            events = self._attack(player.creature, target)
            events += self._end_turn()
            return self._finish_action(action_id, events)

    def _attack(self, attacker: CardInstance, target: Player) -> list[dict]:
        damage = attacker.definition.attack
        events: list[dict] = []
        defender = target.creature
        if defender is not None:
            overflow = defender.take_damage(damage)
            events.append(event("creature_damaged", attacker_uid=attacker.uid,
                                target_uid=defender.uid, damage=damage - overflow,
                                remaining_hp=defender.hp))
            if not defender.is_alive:
                target.creature = None
                target.discard.append(defender.definition.card_id)
                events.append(event("creature_destroyed", uid=defender.uid,
                                    owner_id=target.player_id))
            damage = overflow
        if damage > 0:
            target.take_damage(damage)
            events.append(event("player_damaged", attacker_uid=attacker.uid,
                                player_id=target.player_id, damage=damage,
                                remaining_life=target.life))
        return events

    # ------------------------------------------------------------ serializar
    def view(self, viewer_id: str | None = None) -> dict:
        """Snapshot completo filtrado para `viewer_id` (información oculta)."""
        with self.lock:
            cp = self.current_player
            return {
                "game_id": self.game_id,
                "seq": self.seq,
                "status": self.status.value,
                "max_players": self.max_players,
                "turn_number": self.turn_number,
                "current_player_id": cp.player_id if cp else None,
                "winner_id": self.winner_id,
                "end_reason": self.end_reason,
                "players": [p.to_dict(viewer_id) for p in self.players],
            }


class GameManager:
    """Registro de partidas. Hoy una ("default"); mañana salas/lobbies."""

    def __init__(self, catalog: CardCatalog | None = None) -> None:
        self.catalog = catalog or default_catalog()
        self._games: dict[str, Game] = {}
        self._lock = threading.Lock()

    def get(self, game_id: str) -> Game | None:
        return self._games.get(game_id)

    def get_or_create(self, game_id: str = "default") -> Game:
        with self._lock:
            if game_id not in self._games:
                self._games[game_id] = Game(game_id, self.catalog)
            return self._games[game_id]

    def remove(self, game_id: str) -> None:
        with self._lock:
            self._games.pop(game_id, None)
