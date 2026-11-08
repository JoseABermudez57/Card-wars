"""Regresión de equilibrio: avisa si un cambio de cartas, mazos o reglas desequilibra el juego.

Si falla tras retocar algo, mira el informe completo:
    .venv/bin/python tools/balance_report.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import balance_report as br  # noqa: E402
from game.rules import DEFAULT_RULES  # noqa: E402


class BalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = br.simulate(DEFAULT_RULES, 2000, seed=11)

    def test_seat_advantage_is_small(self):
        p1 = self.report["wins"]["P1"] / self.report["n"]
        self.assertGreater(p1, 0.42, f"P1 gana solo {p1:.0%}: el segundo jugador domina")
        self.assertLess(p1, 0.60, f"P1 gana {p1:.0%}: el primer jugador domina")

    def test_both_win_conditions_matter(self):
        """La vida y el desgaste de criaturas deben decidir partidas."""
        n = self.report["n"]
        self.assertGreater(self.report["ends"]["vida"] / n, 0.15)
        self.assertGreater(self.report["ends"]["sin criaturas"] / n, 0.15)

    def test_no_single_opening_dominates(self):
        for seat, stats in self.report["first_card"].items():
            for card, c in stats.items():
                rate = c["win"] / (c["win"] + c["loss"])
                self.assertLess(rate, 0.75, f"{seat} abriendo con {card} gana {rate:.0%}")

    def test_decisions_matter(self):
        """Un experto debe ganar claramente a un jugador aleatorio: si no, es una lotería."""
        edge = br.skill_edge(DEFAULT_RULES, 120, seed=5)
        self.assertGreater(edge, 0.65, f"el experto solo gana {edge:.0%} al aleatorio")


if __name__ == "__main__":
    unittest.main()
