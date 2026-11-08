"""Informe de equilibrio con las reglas REALES de backend/game (mazos barajados).

Ejecutar desde card_ar_poc/ (cada vez que cambien cartas, mazos o reglas):

    .venv/bin/python tools/balance_report.py                 # reglas actuales
    .venv/bin/python tools/balance_report.py --life 70 --hand 2
    .venv/bin/python tools/balance_report.py --sweep         # barrido de parámetros

Mide, con Monte Carlo (cada partida con su barajado):
  1. Ventaja de asiento: % de victorias de P1 entre dos jugadores aleatorios.
  2. Peso de las decisiones: un jugador "experto" contra uno aleatorio, en ambos
     asientos. El experto prueba cada carta jugando partidas hipotéticas hasta el
     final y elige la que más gana, SIN hacer trampa: antes rebaraja lo que no
     puede ver (su mazo, y mano + mazo del rival). Si no gana claramente más que
     el aleatorio, las decisiones no importan y el juego es una lotería.
  3. Cómo terminan las partidas (por vida / sin criaturas) y su duración.
  4. Qué primera carta conviene (ninguna debería ganar casi siempre).

Con azar e información oculta el juego ya no está "resuelto": no hay minimax.
Objetivo práctico: P1 entre ~45 % y ~55 %, codicioso claramente > 50 %, y
ambas formas de ganar presentes.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import random
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from game.game_manager import Game, GameStatus  # noqa: E402
from game.rules import DEFAULT_RULES, GameRules  # noqa: E402


# ------------------------------------------------------------------ políticas
def random_policy(rng: random.Random):
    def choose(game: Game, me) -> str:
        return rng.choice(me.hand)
    return choose


def _clone(game: Game) -> Game:
    lock, game.lock = game.lock, None  # un RLock no se puede copiar
    try:
        twin = copy.deepcopy(game)
    finally:
        game.lock = lock
    twin.lock = threading.RLock()
    return twin


def _determinize(game: Game, me_id: str, rng: random.Random) -> None:
    """Rebaraja lo que `me_id` no puede ver: su mazo, y mano + mazo del rival."""
    for p in game.players:
        if p.player_id == me_id:
            rng.shuffle(p.deck)
        else:
            pool = p.hand + p.deck
            rng.shuffle(pool)
            p.hand, p.deck = pool[:len(p.hand)], pool[len(p.hand):]
    game._rng = random.Random(rng.random())


def expert_policy(rng: random.Random, rollouts: int = 12):
    """Para cada carta distinta de la mano: `rollouts` partidas hipotéticas
    (determinizadas, resto aleatorio); elige la de más victorias."""
    def choose(game: Game, me) -> str:
        options = sorted(set(me.hand))
        if len(options) == 1:
            return options[0]
        best, best_score = options[0], -1
        for card in options:
            score = 0
            for _ in range(rollouts):
                sim = _clone(game)
                _determinize(sim, me.player_id, rng)
                sim.play_card(me.player_id, card)
                while sim.status == GameStatus.IN_PROGRESS:
                    cur = sim.current_player
                    if cur.creature:
                        sim.attack(cur.player_id)
                    else:
                        sim.play_card(cur.player_id, rng.choice(cur.hand))
                score += sim.winner_id == me.player_id
            if score > best_score:
                best, best_score = card, score
        return best
    return choose


# ------------------------------------------------------------------ simulación
def play_game(rules: GameRules, seed: int, policy_p1, policy_p2) -> tuple[Game, str, str, int, dict]:
    g = Game(rules=rules, seed=seed)
    p1, _ = g.join("P1")
    p2, _ = g.join("P2")
    policies = {p1.player_id: policy_p1, p2.player_id: policy_p2}
    firsts: dict[str, str] = {}
    actions = 0
    while g.status == GameStatus.IN_PROGRESS:
        cur = g.current_player
        if cur.creature:
            g.attack(cur.player_id)
        else:
            card = policies[cur.player_id](g, cur)
            firsts.setdefault(cur.player_id, card)
            g.play_card(cur.player_id, card)
        actions += 1
        if actions > 500:
            raise RuntimeError("la partida no termina: revisa las reglas")
    return g, p1.player_id, p2.player_id, actions, firsts


def simulate(rules: GameRules, n: int, seed: int = 7, p1_policy="random", p2_policy="random") -> dict:
    rng = random.Random(seed)
    make = {"random": random_policy, "expert": expert_policy}
    wins: Counter = Counter()
    ends: Counter = Counter()
    first_card = {"P1": defaultdict(Counter), "P2": defaultdict(Counter)}
    total_actions = 0
    for _ in range(n):
        g, p1, p2, actions, firsts = play_game(rules, rng.randrange(2 ** 32),
                                               make[p1_policy](rng), make[p2_policy](rng))
        total_actions += actions
        wins["P1" if g.winner_id == p1 else "P2" if g.winner_id == p2 else "empate"] += 1
        ends["vida" if any(p.life <= 0 for p in g.players) else "sin criaturas"] += 1
        seat = {p1: "P1", p2: "P2"}
        for pid, c in firsts.items():
            first_card[seat[pid]][c]["win" if g.winner_id == pid else "loss"] += 1
    return {"n": n, "wins": wins, "ends": ends, "first_card": first_card, "avg_actions": total_actions / n}


def skill_edge(rules: GameRules, n: int, seed: int = 21) -> float:
    """% de victorias del experto contra el aleatorio, mitad de partidas en cada asiento."""
    a = simulate(rules, n // 2, seed, "expert", "random")
    b = simulate(rules, n // 2, seed + 1, "random", "expert")
    return (a["wins"]["P1"] + b["wins"]["P2"]) / (a["n"] + b["n"])


# ------------------------------------------------------------------ informe
def pct(x: float) -> str:
    return f"{100 * x:5.1f} %"


def report(rules: GameRules, n: int, skill_games: int = 300) -> None:
    print(f"Reglas: vida {rules.starting_life}, mano inicial {rules.initial_hand}, "
          f"roba {rules.draw_per_turn}/turno, P1 roba en turno 1: {rules.first_turn_draw}\n")
    r = simulate(rules, n)
    print(f"1) Ventaja de asiento ({n} partidas aleatorias)")
    print(f"   P1 {pct(r['wins']['P1'] / n)}  ·  P2 {pct(r['wins']['P2'] / n)}  ·  empates {pct(r['wins']['empate'] / n)}")
    print(f"2) Peso de las decisiones: experto vs aleatorio gana {pct(skill_edge(rules, skill_games))}"
          f"  ({skill_games} partidas)")
    print(f"3) Acciones por partida: {r['avg_actions']:.1f}  ·  terminan: " +
          ", ".join(f"{k} {pct(v / n)}" for k, v in r["ends"].most_common()))
    print("4) % de victorias según la primera carta jugada")
    for seat in ("P1", "P2"):
        stats = r["first_card"][seat]
        print(f"   {seat}: " + ", ".join(
            f"{c} {100 * v['win'] / (v['win'] + v['loss']):.0f} %" for c, v in sorted(stats.items())))


def sweep(base: GameRules, n: int) -> None:
    print("vida mano 1er-ataque | P1 gana | por vida | acciones")
    for life in (60, 70, 80, 90, 100, 120):
        for hand in (2, 3):
            for first_attack in (True, False):
                rules = dataclasses.replace(base, starting_life=life, initial_hand=hand,
                                            first_turn_attack=first_attack)
                r = simulate(rules, n)
                print(f"{life:>4} {hand:>4} {str(first_attack):>10} | {pct(r['wins']['P1'] / n)} | "
                      f"{pct(r['ends']['vida'] / n)} | {r['avg_actions']:5.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--life", type=int)
    parser.add_argument("--hand", type=int, help="mano inicial")
    parser.add_argument("--first-draw", action="store_true", help="P1 roba en su primer turno")
    parser.add_argument("--games", type=int, default=4000)
    parser.add_argument("--sweep", action="store_true")
    args = parser.parse_args()
    rules = DEFAULT_RULES
    if args.life:
        rules = dataclasses.replace(rules, starting_life=args.life)
    if args.hand:
        rules = dataclasses.replace(rules, initial_hand=args.hand)
    if args.first_draw:
        rules = dataclasses.replace(rules, first_turn_draw=True)
    if args.sweep:
        sweep(rules, min(args.games, 2000))
    else:
        report(rules, args.games)


if __name__ == "__main__":
    main()
