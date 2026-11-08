"""Informe de equilibrio con las reglas REALES de backend/game.

Ejecutar desde card_ar_poc/ (cada vez que cambien cartas o reglas):

    .venv/bin/python tools/balance_report.py
    .venv/bin/python tools/balance_report.py --life 70     # probar otra vida inicial
    .venv/bin/python tools/balance_report.py --no-minimax  # más rápido

Mide:
  1. Matriz de órdenes fijos: cada jugador fija un orden de cartas y ataca siempre
     que puede; todos contra todos (con 3 cartas, 6 x 6 = 36 enfrentamientos).
  2. Juego perfecto (minimax): árbol completo de decisiones (qué carta jugar).
     Con información completa el juego está "resuelto": siempre hay un ganador
     teórico. Útil para detectar estrategias dominantes, no como objetivo de 50 %.
  3. Monte Carlo con jugadores aleatorios: % de victorias por asiento, duración,
     cómo terminan las partidas y qué primera carta conviene.

Objetivo práctico: P1 entre ~40 % y ~60 % en partidas aleatorias, y que ambas
formas de ganar (vida y "sin criaturas") aparezcan.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import random
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import game.player as player_module  # noqa: E402
from game.game_manager import Game, GameStatus  # noqa: E402


def new_game() -> tuple[Game, str, str]:
    g = Game()
    a, _ = g.join("P1")
    b, _ = g.join("P2")
    return g, a.player_id, b.player_id


def winner_seat(g: Game, p1: str, p2: str) -> str:
    return "P1" if g.winner_id == p1 else "P2" if g.winner_id == p2 else "empate"


def end_kind(g: Game) -> str:
    return "vida" if any(p.life <= 0 for p in g.players) else "sin criaturas"


def play(g: Game, choose) -> int:
    """Juega hasta el final. `choose(player)` elige carta cuando no hay criatura."""
    actions = 0
    while g.status == GameStatus.IN_PROGRESS:
        cur = g.current_player
        if cur.creature:
            g.attack(cur.player_id)
        else:
            g.play_card(cur.player_id, choose(cur))
        actions += 1
        if actions > 500:
            raise RuntimeError("la partida no termina: revisa las reglas")
    return actions


def fixed_order_matrix() -> tuple[Counter, list[tuple[str, list[str]]], list[tuple[str, ...]]]:
    cards = sorted(Game().catalog.ids())
    perms = list(itertools.permutations(cards))
    totals: Counter = Counter()
    rows = []
    for o1 in perms:
        row = []
        for o2 in perms:
            g, p1, p2 = new_game()
            orders = {p1: o1, p2: o2}
            play(g, lambda p: next(c for c in orders[p.player_id] if c in p.hand))
            w = winner_seat(g, p1, p2)
            totals[w] += 1
            row.append({"P1": "1", "P2": "2"}.get(w, "="))
        rows.append(("/".join(c[0].upper() for c in o1), row))
    return totals, rows, perms


def _clone(game: Game) -> Game:
    lock, game.lock = game.lock, None  # un RLock no se puede copiar
    try:
        twin = copy.deepcopy(game)
    finally:
        game.lock = lock
    twin.lock = threading.RLock()
    return twin


def minimax(game: Game, p1: str) -> int:
    """+1 gana P1, -1 gana P2, 0 empate, con juego perfecto de ambos."""
    memo: dict = {}

    def key(g: Game):
        return (g.turn_index, g.status.value, tuple(
            (p.life, tuple(sorted(p.hand)),
             (p.creature.definition.card_id, p.creature.hp) if p.creature else None, p.eliminated)
            for p in g.players))

    def solve(g: Game) -> int:
        k = key(g)
        if k in memo:
            return memo[k]
        if g.status != GameStatus.IN_PROGRESS:
            memo[k] = 1 if g.winner_id == p1 else -1 if g.winner_id else 0
            return memo[k]
        cur = g.current_player
        if cur.creature:
            nxt = _clone(g)
            nxt.attack(cur.player_id)
            v = solve(nxt)
        else:
            values = []
            for card in sorted(set(cur.hand)):
                nxt = _clone(g)
                nxt.play_card(cur.player_id, card)
                values.append(solve(nxt))
            v = max(values) if cur.player_id == p1 else min(values)
        memo[k] = v
        return v

    return solve(game)


def random_games(n: int, seed: int = 7) -> dict:
    rng = random.Random(seed)
    wins: Counter = Counter()
    ends: Counter = Counter()
    first_card = {"P1": defaultdict(Counter), "P2": defaultdict(Counter)}
    total_actions = 0
    for _ in range(n):
        g, p1, p2 = new_game()
        seat = {p1: "P1", p2: "P2"}
        firsts: dict[str, str] = {}

        def choose(p):
            c = rng.choice(p.hand)
            firsts.setdefault(p.player_id, c)
            return c

        total_actions += play(g, choose)
        wins[winner_seat(g, p1, p2)] += 1
        ends[end_kind(g)] += 1
        for pid, c in firsts.items():
            first_card[seat[pid]][c]["win" if g.winner_id == pid else "loss"] += 1
    return {"wins": wins, "ends": ends, "first_card": first_card, "avg_actions": total_actions / n, "n": n}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--life", type=int, help="vida inicial a probar (por defecto la del juego)")
    parser.add_argument("--games", type=int, default=5000, help="partidas aleatorias")
    parser.add_argument("--no-minimax", action="store_true")
    args = parser.parse_args()
    if args.life:
        player_module.STARTING_LIFE = args.life
    print(f"Vida inicial: {player_module.STARTING_LIFE}\n")

    totals, rows, perms = fixed_order_matrix()
    print("1) Matriz de órdenes fijos (fila = P1, columna = P2; celda = asiento ganador)")
    print("        " + " ".join("/".join(c[0].upper() for c in p) for p in perms))
    for label, row in rows:
        print(f"{label}   " + "     ".join(row))
    print(f"   P1 {totals['P1']}  ·  P2 {totals['P2']}  ·  empates {totals['empate']}\n")

    if not args.no_minimax:
        g, p1, _ = new_game()
        print("2) Juego perfecto:", {1: "gana P1", -1: "gana P2", 0: "empate"}[minimax(g, p1)], "\n")

    r = random_games(args.games)
    n = r["n"]
    print(f"3) {n} partidas aleatorias")
    print(f"   P1 gana {100 * r['wins']['P1'] / n:.1f} %  ·  P2 {100 * r['wins']['P2'] / n:.1f} %  ·  "
          f"empates {100 * r['wins']['empate'] / n:.1f} %")
    print(f"   acciones por partida: {r['avg_actions']:.1f}")
    print("   cómo terminan: " + ", ".join(f"{k} {100 * v / n:.0f} %" for k, v in r["ends"].most_common()))
    for seat in ("P1", "P2"):
        stats = r["first_card"][seat]
        print(f"   {seat} según su primera carta: " + ", ".join(
            f"{c} {100 * v['win'] / (v['win'] + v['loss']):.0f} %" for c, v in sorted(stats.items())))


if __name__ == "__main__":
    main()
