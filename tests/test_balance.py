"""Regresión de equilibrio: avisa si un cambio de cartas o reglas desequilibra el juego.

Si falla tras retocar cartas, mira el informe completo:
    .venv/bin/python tools/balance_report.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import balance_report as br  # noqa: E402


class BalanceTests(unittest.TestCase):
    def test_seat_advantage_is_small_with_random_players(self):
        r = br.random_games(1500, seed=11)
        p1 = r["wins"]["P1"] / r["n"]
        self.assertGreater(p1, 0.40, f"P1 gana solo {p1:.0%}: el segundo jugador domina")
        self.assertLess(p1, 0.60, f"P1 gana {p1:.0%}: el primer jugador domina")

    def test_fixed_orders_matrix_not_lopsided(self):
        totals, _, perms = br.fixed_order_matrix()
        total = len(perms) ** 2
        self.assertGreaterEqual(totals["P1"], total * 0.35, dict(totals))
        self.assertGreaterEqual(totals["P2"], total * 0.35, dict(totals))

    def test_both_win_conditions_matter(self):
        """La vida debe decidir partidas: si no, el daño directo no sirve de nada."""
        r = br.random_games(1500, seed=12)
        share = r["ends"]["vida"] / r["n"]
        self.assertGreater(share, 0.15, f"solo {share:.0%} de partidas terminan por vida")
        self.assertGreater(r["ends"]["sin criaturas"] / r["n"], 0.15)

    def test_no_single_opening_always_wins(self):
        r = br.random_games(1500, seed=13)
        for seat, stats in r["first_card"].items():
            for card, c in stats.items():
                rate = c["win"] / (c["win"] + c["loss"])
                self.assertLess(rate, 0.80, f"{seat} abriendo con {card} gana {rate:.0%}")


if __name__ == "__main__":
    unittest.main()
