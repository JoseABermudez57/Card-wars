"""Pruebas de la lógica de juego. Ejecutar desde card_ar_poc/:

    python3 -m unittest discover -s tests -v
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from game.cards import default_catalog  # noqa: E402
from game.game_manager import DuplicateActionError, Game, GameError, GameStatus  # noqa: E402


def types(update):
    return [e["type"] for e in update.events]


class GameTestCase(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.p1, _ = self.game.join("Ana")
        self.p2, self.start_update = self.game.join("Luis")

    def turn(self):
        return self.game.turn_number


class LobbyTests(GameTestCase):
    def test_starts_when_two_players_join(self):
        self.assertIn("game_started", types(self.start_update))
        self.assertEqual(self.game.status, GameStatus.IN_PROGRESS)
        self.assertIs(self.game.current_player, self.p1)
        self.assertEqual(self.p1.hand, ["dragon", "warrior", "mage"])

    def test_full_game_rejects_third_player(self):
        with self.assertRaises(GameError) as ctx:
            self.game.join("Eva")
        self.assertEqual(ctx.exception.code, "game_full")

    def test_reconnect_requires_secret_token(self):
        # Conocer el player_id público NO da acceso: hace falta el token.
        with self.assertRaises(GameError):
            self.game.join("Intruso", session_token=self.p2.player_id)
        self.game.mark_disconnected(self.p2.player_id)
        player, update = self.game.join("", session_token=self.p2.session_token)
        self.assertIs(player, self.p2)
        self.assertTrue(player.connected)
        self.assertEqual(types(update), ["player_reconnected"])

    def test_events_have_type_payload_shape(self):
        for ev in self.start_update.events:
            self.assertEqual(set(ev), {"type", "payload"})


class SyncTests(GameTestCase):
    def test_seq_increases_on_every_change(self):
        s0 = self.game.seq
        u1 = self.game.play_card(self.p1.player_id, "mage")
        u2 = self.game.play_card(self.p2.player_id, "dragon")
        self.assertEqual((u1.seq, u2.seq), (s0 + 1, s0 + 2))
        self.assertEqual(self.game.view()["seq"], u2.seq)

    def test_duplicate_action_is_not_applied_twice(self):
        self.game.play_card(self.p1.player_id, "mage", action_id="a1")
        life = self.p2.life
        with self.assertRaises(DuplicateActionError):
            self.game.play_card(self.p1.player_id, "mage", action_id="a1")
        self.assertEqual(self.p2.life, life)

    def test_stale_action_rejected(self):
        with self.assertRaises(GameError) as ctx:
            self.game.play_card(self.p1.player_id, "mage", expected_turn=self.turn() + 1)
        self.assertEqual(ctx.exception.code, "stale_action")

    def test_hidden_information(self):
        view = self.game.view(self.p1.player_id)
        me, rival = view["players"]
        self.assertIn("hand", me)
        self.assertNotIn("hand", rival)
        self.assertEqual(rival["hand_count"], 3)
        self.assertNotIn("session_token", str(view))


class CombatTests(GameTestCase):
    def test_direct_attack_and_turn_change(self):
        update = self.game.play_card(self.p1.player_id, "mage")
        self.assertEqual(types(update), ["card_played", "player_damaged", "turn_changed"])
        self.assertEqual(self.p2.life, 60)
        self.assertNotIn("mage", self.p1.hand)
        self.assertIs(self.game.current_player, self.p2)

    def test_not_your_turn(self):
        with self.assertRaises(GameError) as ctx:
            self.game.play_card(self.p2.player_id, "dragon")
        self.assertEqual(ctx.exception.code, "not_your_turn")

    def test_card_must_be_in_hand(self):
        self.p1.hand.remove("dragon")
        with self.assertRaises(GameError) as ctx:
            self.game.play_card(self.p1.player_id, "dragon")
        self.assertEqual(ctx.exception.code, "card_not_in_hand")

    def test_cannot_play_with_creature_in_play_must_attack(self):
        self.game.play_card(self.p1.player_id, "mage")
        self.game.play_card(self.p2.player_id, "dragon")      # mago de p1: 80 -> 50
        with self.assertRaises(GameError) as ctx:
            self.game.play_card(self.p1.player_id, "dragon")
        self.assertEqual(ctx.exception.code, "creature_in_play")
        update = self.game.attack(self.p1.player_id)           # dragón de p2: 100 -> 60
        self.assertEqual(types(update), ["creature_damaged", "turn_changed"])
        self.assertEqual(self.p2.creature.hp, 60)

    def test_overflow_kills_creature_and_damages_player(self):
        self.game.play_card(self.p1.player_id, "dragon")       # p2: 100 -> 70
        self.p1.creature.hp = 10
        update = self.game.play_card(self.p2.player_id, "mage")  # 10 a criatura, 30 a p1
        self.assertEqual(types(update), ["card_played", "creature_damaged",
                                         "creature_destroyed", "player_damaged",
                                         "turn_changed"])
        self.assertEqual(self.p1.life, 70)
        self.assertEqual(self.p1.discard, ["dragon"])

    def test_uids_are_per_game(self):
        self.game.play_card(self.p1.player_id, "mage")
        self.game.play_card(self.p2.player_id, "mage")
        self.assertEqual([self.p1.creature.uid, self.p2.creature.uid], [1, 2])

    def test_lose_when_no_creature_and_no_cards(self):
        self.p2.hand.clear()
        update = self.game.play_card(self.p1.player_id, "warrior")
        self.assertEqual(types(update)[-2:], ["player_eliminated", "game_over"])
        self.assertEqual(update.events[-1]["payload"]["winner_id"], self.p1.player_id)

    def test_game_over_by_life(self):
        self.p2.life = 20
        update = self.game.play_card(self.p1.player_id, "warrior")
        self.assertEqual(types(update)[-1], "game_over")
        self.assertEqual(self.game.winner_id, self.p1.player_id)
        with self.assertRaises(GameError):
            self.game.attack(self.p2.player_id)

    def test_random_games_always_terminate(self):
        """Regresión del bug de reglas v1 (partidas infinitas)."""
        rng = random.Random(42)
        for _ in range(200):
            g = Game()
            a, _ = g.join("A")
            g.join("B")
            for _turn in range(200):
                if g.status == GameStatus.FINISHED:
                    break
                p = g.current_player
                if p.creature:
                    g.attack(p.player_id)
                else:
                    g.play_card(p.player_id, rng.choice(p.hand))
            self.assertEqual(g.status, GameStatus.FINISHED)


class LifecycleTests(GameTestCase):
    def test_forfeit_gives_victory_to_rival(self):
        update = self.game.forfeit(self.p1.player_id)
        self.assertEqual(types(update), ["player_eliminated", "game_over"])
        self.assertEqual(self.game.winner_id, self.p2.player_id)

    def test_rematch_needs_both_players(self):
        with self.assertRaises(GameError):
            self.game.request_rematch(self.p1.player_id)   # partida en curso
        self.game.forfeit(self.p2.player_id)
        self.assertEqual(types(self.game.request_rematch(self.p1.player_id)),
                         ["rematch_requested"])
        update = self.game.request_rematch(self.p2.player_id)
        self.assertEqual(types(update), ["rematch_requested", "game_started"])
        self.assertEqual((self.p1.life, self.p2.life), (100, 100))
        self.assertEqual(len(self.p2.hand), 3)

    def test_leave_after_finish_reopens_lobby(self):
        self.game.forfeit(self.p2.player_id)
        self.game.leave(self.p2.player_id)
        # El resultado se conserva para el ganador...
        self.assertEqual(self.game.status, GameStatus.FINISHED)
        self.assertEqual(self.game.winner_id, self.p1.player_id)
        # ...pero no hay revancha sin rival...
        with self.assertRaises(GameError) as ctx:
            self.game.request_rematch(self.p1.player_id)
        self.assertEqual(ctx.exception.code, "rival_left")
        # ...y un jugador nuevo puede entrar y empezar otra partida.
        _, update = self.game.join("Nuevo")
        self.assertIn("game_started", types(update))

    def test_catalog_marker_mapping(self):
        cat = default_catalog()
        self.assertEqual(cat.from_marker(0).card_id, "dragon")
        self.assertEqual(cat.from_marker(2).card_id, "mage")
        self.assertIsNone(cat.from_marker(99))


if __name__ == "__main__":
    unittest.main()
