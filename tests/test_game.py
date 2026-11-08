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
from game.player import STARTING_LIFE  # noqa: E402
from game.rules import DEFAULT_RULES, GameRules, starter_deck  # noqa: E402

ONE_OF_EACH = ["dragon", "warrior", "mage"]
# Reglas "clásicas" para tests de combate: mazo de 3 cartas, todo en la mano
# y nada que robar => partidas deterministas sin azar.
CLASSIC = GameRules(initial_hand=3, deck_min=3)


def types(update):
    return [e["type"] for e in update.events]


class GameTestCase(unittest.TestCase):
    def setUp(self):
        self.game = Game(rules=CLASSIC, seed=1)
        self.p1, _ = self.game.join("Ana", deck=ONE_OF_EACH)
        self.p2, self.start_update = self.game.join("Luis", deck=ONE_OF_EACH)

    def turn(self):
        return self.game.turn_number


class LobbyTests(GameTestCase):
    def test_starts_when_two_players_join(self):
        self.assertIn("game_started", types(self.start_update))
        self.assertEqual(self.game.status, GameStatus.IN_PROGRESS)
        self.assertIs(self.game.current_player, self.p1)
        self.assertEqual(sorted(self.p1.hand), sorted(ONE_OF_EACH))

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
        self.assertEqual(rival["deck_count"], 0)
        self.assertNotIn("deck", rival)
        self.assertNotIn("session_token", str(view))


class CombatTests(GameTestCase):
    def test_direct_attack_and_turn_change(self):
        update = self.game.play_card(self.p1.player_id, "mage")
        self.assertEqual(types(update), ["card_played", "player_damaged", "turn_changed"])
        self.assertEqual(self.p2.life, STARTING_LIFE - 40)
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
        self.game.play_card(self.p1.player_id, "dragon")       # p2: -30
        self.p1.creature.hp = 10
        update = self.game.play_card(self.p2.player_id, "mage")  # 10 a criatura, 30 a p1
        self.assertEqual(types(update), ["card_played", "creature_damaged",
                                         "creature_destroyed", "player_damaged",
                                         "turn_changed"])
        self.assertEqual(self.p1.life, STARTING_LIFE - 30)
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
        for i in range(200):
            g = Game(seed=i)              # reglas por defecto: mazos barajados y robos
            a, _ = g.join("A")
            g.join("B")
            for _turn in range(500):
                if g.status == GameStatus.FINISHED:
                    break
                p = g.current_player
                if p.creature:
                    g.attack(p.player_id)
                else:
                    g.play_card(p.player_id, rng.choice(p.hand))
            self.assertEqual(g.status, GameStatus.FINISHED)


class DeckTests(unittest.TestCase):
    """Mazos, barajado, robo e información oculta (reglas por defecto)."""

    def new_game(self, seed=1, rules=DEFAULT_RULES, decks=(None, None)):
        g = Game(rules=rules, seed=seed)
        a, _ = g.join("A", deck=decks[0])
        b, start = g.join("B", deck=decks[1])
        return g, a, b, start

    def test_default_deck_is_dealt(self):
        g, a, b, _ = self.new_game()
        for p in (a, b):
            self.assertEqual(len(p.hand), DEFAULT_RULES.initial_hand)
            self.assertEqual(len(p.deck), len(starter_deck()) - DEFAULT_RULES.initial_hand)
            self.assertEqual(sorted(p.hand + p.deck), sorted(starter_deck()))

    def test_shuffle_is_deterministic_with_seed_and_varies_without(self):
        hands = lambda seed: [p.hand for p in self.new_game(seed)[1:3]]  # noqa: E731
        self.assertEqual(hands(5), hands(5))
        self.assertGreater(len({str(hands(s)) for s in range(20)}), 5)

    def test_draw_at_start_of_turn_is_private(self):
        g, a, b, _ = self.new_game()
        before = (len(b.hand), len(b.deck))
        update = g.play_card(a.player_id, a.hand[0])
        drawn = [e for e in update.events if e["type"] == "card_drawn"]
        self.assertEqual(len(drawn), 1)
        self.assertEqual((len(b.hand), len(b.deck)), (before[0] + 1, before[1] - 1))
        mine = Game.events_for(update.events, b.player_id)
        theirs = Game.events_for(update.events, a.player_id)
        card_b = next(e for e in mine if e["type"] == "card_drawn")["payload"]["card"]
        card_a = next(e for e in theirs if e["type"] == "card_drawn")["payload"]["card"]
        self.assertEqual(card_b["card_id"], b.hand[-1])
        self.assertIsNone(card_a)                      # el rival no ve qué robaste
        for ev in mine + theirs:
            self.assertNotIn("_private_to", ev)        # la marca interna no sale

    def test_first_player_does_not_draw_on_turn_one(self):
        g, a, _, start = self.new_game()
        self.assertNotIn("card_drawn", types(start))
        self.assertEqual(len(a.hand), DEFAULT_RULES.initial_hand)

    def test_first_turn_attack_can_be_disabled(self):
        rules = GameRules(first_turn_attack=False)
        g, a, b, _ = self.new_game(rules=rules)
        update = g.play_card(a.player_id, a.hand[0])
        self.assertNotIn("player_damaged", types(update))
        self.assertEqual(b.life, rules.starting_life)

    def test_custom_deck_and_validation(self):
        deck = ["mage", "mage", "dragon", "dragon", "warrior", "warrior"]
        g, a, _, _ = self.new_game(decks=(deck, None))
        self.assertEqual(sorted(a.hand + a.deck), sorted(deck))
        bad = {
            "pequeño": ["mage", "dragon"],
            "copias": ["mage", "mage", "mage", "dragon", "dragon", "warrior"],
            "desconocida": ["mage", "mage", "dragon", "dragon", "warrior", "unicornio"],
        }
        for label, deck in bad.items():
            with self.subTest(label), self.assertRaises(GameError) as ctx:
                Game().join("X", deck=deck)
            self.assertEqual(ctx.exception.code, "invalid_deck")

    def test_lose_when_hand_and_deck_are_empty(self):
        g, a, b, _ = self.new_game()
        b.hand.clear()
        b.deck.clear()
        update = g.play_card(a.player_id, a.hand[0])
        self.assertEqual(types(update)[-2:], ["player_eliminated", "game_over"])

    def test_empty_hand_but_cards_in_deck_keeps_playing(self):
        g, a, b, _ = self.new_game()
        b.hand.clear()                                 # le queda mazo: roba y sigue
        update = g.play_card(a.player_id, a.hand[0])
        self.assertIn("turn_changed", types(update))
        self.assertEqual(len(b.hand), 1)

    def test_rematch_reshuffles_full_deck(self):
        g, a, b, _ = self.new_game()
        g.forfeit(b.player_id)
        g.request_rematch(a.player_id)
        g.request_rematch(b.player_id)
        for p in (a, b):
            self.assertEqual(sorted(p.hand + p.deck), sorted(starter_deck()))
            self.assertEqual(p.discard, [])


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
        self.assertEqual((self.p1.life, self.p2.life), (STARTING_LIFE, STARTING_LIFE))
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
