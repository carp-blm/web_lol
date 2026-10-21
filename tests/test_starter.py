import copy
import json
import unittest
from test_engine import Game, Match, ROLES, CATALOG, CHAMPIONS, finish
from legacy_engine import Game as LegacyGame


class StarterTests(unittest.TestCase):
    def test_starts_with_five_unopened_packs_and_no_players(self):
        game = Game(CATALOG, CHAMPIONS, "starter")
        self.assertEqual(game.s["owned"], [])
        self.assertEqual(game.s["roster"], {})
        self.assertIsNone(game.s["season"])
        self.assertEqual(set(game.s["starter"]["packs"]), set(ROLES))
        self.assertEqual(game.s["coins"], 600)

    def test_each_pack_filters_league_year_and_is_free_once(self):
        game = Game(CATALOG, CHAMPIONS, "starter")
        for role in reversed(ROLES):
            game.apply({"type": "starter_filter", "role": role, "league": "LCK", "year": 2024})
            count = game.view()["starter_counts"][role]
            self.assertGreater(count, 0)
            game.apply({"type": "starter_open", "role": role})
            card = game.cards[game.s["roster"][role]]
            self.assertEqual((card["role"], card["league"], card["year"]), (role, "LCK", 2024))
            before = game.export_save()
            for action in ({"type": "starter_open", "role": role},
                           {"type": "starter_filter", "role": role, "year": 2023}):
                with self.assertRaises(ValueError):
                    game.apply(action)
                self.assertEqual(before, game.export_save())
        self.assertEqual(len(game.s["owned"]), 5)
        self.assertEqual(game.s["coins"], 600)
        game.apply({"type": "starter_finish"})
        self.assertEqual(game.s["season_number"], 1)
        self.assertEqual(len(set(game.s["draft"].values())), 5)
        with self.assertRaises(ValueError):
            game.apply({"type": "starter_finish"})

    def test_no_season_recruiting_or_equipping_before_finish(self):
        game = Game(CATALOG, CHAMPIONS)
        before = game.export_save()
        for kind in ("start", "pull", "equip", "draft", "next_season", "starter_finish"):
            with self.assertRaises(ValueError):
                game.apply({"type": kind})
            self.assertEqual(before, game.export_save())

    def test_invalid_filters_do_not_consume_rng_or_change_save(self):
        game = Game(CATALOG, CHAMPIONS)
        before, rng = game.export_save(), game.rng.state
        for action in ({"role": "unknown"}, {"role": "mid", "league": "unknown"},
                       {"role": "mid", "league": "LCK", "year": 2010}):
            with self.assertRaises(ValueError):
                game.apply({"type": "starter_filter", **action})
            self.assertEqual(game.export_save(), before)
            self.assertEqual(game.rng.state, rng)

    def test_empty_valid_combination_is_recoverable(self):
        catalog = copy.deepcopy(CATALOG)
        catalog["cards"] = [c for c in catalog["cards"] if not (c["role"] == "top" and c["league"] == "LCK" and c["year"] == 2024)]
        game = Game(catalog, CHAMPIONS)
        game.apply({"type": "starter_filter", "role": "top", "league": "LCK", "year": "2024"})
        self.assertEqual(game.view()["starter_counts"]["top"], 0)
        before = game.export_save()
        with self.assertRaises(ValueError):
            game.apply({"type": "starter_open", "role": "top"})
        self.assertEqual(game.export_save(), before)
        game.apply({"type": "starter_filter", "role": "top", "year": "2023"})
        game.apply({"type": "starter_open", "role": "top"})
        self.assertIsNotNone(game.s["starter"]["packs"]["top"]["card"])

    def test_partial_packs_restore_and_future_draws_reproduce(self):
        a = Game(CATALOG, CHAMPIONS, "partial")
        a.apply({"type": "starter_filter", "role": "sup", "league": "LCKC", "year": "2023"})
        a.apply({"type": "starter_open", "role": "sup"})
        a.apply({"type": "starter_filter", "role": "top", "league": "LPL", "year": "2024"})
        b = Game.import_save(a.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(a.view(), b.view())
        for g in (a, b):
            for role in ROLES[:-1]:
                g.apply({"type": "starter_open", "role": role})
            g.apply({"type": "starter_finish"})
        self.assertEqual(a.view(), b.view())

    def test_different_seeds_get_different_draws(self):
        outcomes = []
        for seed in ("one", "two", "three"):
            g = Game(CATALOG, CHAMPIONS, seed)
            g.apply({"type": "starter_open", "role": "mid"})
            outcomes.append(g.s["roster"]["mid"])
        self.assertGreater(len(set(outcomes)), 1)

    def test_v1_save_keeps_roster_coins_and_inflight_match(self):
        old = LegacyGame(CATALOG, CHAMPIONS, "old-player")
        old.apply({"type": "pull", "role": "mid"})
        old.apply({"type": "start"})
        while not old.match.s["event"]:
            old.apply({"type": "tick", "steps": 3})
        migrated = Game.import_save(old.export_save(), CATALOG, CHAMPIONS)
        for key in ("owned", "roster", "coins", "season", "draft"):
            self.assertEqual(old.s[key], migrated.s[key])
        self.assertTrue(migrated.s["starter"]["finished"])
        self.assertEqual(old.match.s, migrated.match.s)
        migrated.apply({"type": "choose", "option": "vision"})
        replayed = Game.import_save(migrated.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(migrated.view(), replayed.view())
        finish(migrated)
        migrated.apply({"type": "start"})
        self.assertIsInstance(migrated.match, Match)
        self.assertIn("ability_state", migrated.match.unit(0, "mid"))

    def test_mechanics_revision_mismatch_rejected(self):
        game = Game(CATALOG, CHAMPIONS)
        with self.assertRaisesRegex(ValueError, "데이터 버전"):
            Game.import_save(game.export_save(), CATALOG, {**CHAMPIONS, "revision": "changed"})
