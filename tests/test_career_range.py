import collections
import unittest
from test_engine import CATALOG, CHAMPIONS, finish
from test_management import game, play
from engine import Game, ROLES
from legacy_engine_v6 import Game as GameV6
from management import EXHAUSTED

STATS = ("lane", "combat", "vision", "farm")


class CareerDataTests(unittest.TestCase):
    def test_every_player_has_range_containing_all_season_cards(self):
        players = CATALOG["players"]
        by_player = collections.defaultdict(list)
        for card in CATALOG["cards"]:
            by_player[card["player_id"]].append(card)
        self.assertEqual(set(players), set(by_player))
        for pid, cards in by_player.items():
            entry = players[pid]
            self.assertEqual(sorted(entry["cards"]), sorted(c["id"] for c in cards))
            for stat in STATS:
                self.assertLessEqual(entry["floor"][stat], entry["peak"][stat])
                self.assertTrue(1 <= entry["floor"][stat] and entry["peak"][stat] <= 99)
                # Season cards are points too: the highest/lowest season always lies inside.
                self.assertGreaterEqual(entry["peak"][stat], max(c["ratings"][stat] for c in cards))
                self.assertLessEqual(entry["floor"][stat], min(c["ratings"][stat] for c in cards))

    def test_season_cards_differ_but_share_one_career_range(self):
        multi = [p for p, e in CATALOG["players"].items() if len(e["cards"]) >= 2]
        self.assertGreater(len(multi), 1000)
        cards = {c["id"]: c for c in CATALOG["cards"]}
        differs = sum(len({tuple(sorted(cards[cid]["ratings"].items())) for cid in CATALOG["players"][p]["cards"]}) > 1 for p in multi)
        self.assertGreater(differs / len(multi), .9)


class CareerRuleTests(unittest.TestCase):
    def player_with_room(self, g):
        for role in ROLES:
            cid = g.s["roster"][role]
            peak = g.career_range(cid)["peak"]
            stat = next((s for s in STATS if peak[s] - g.cards[cid]["ratings"][s] >= 2), None)
            if stat:
                return role, cid, stat
        self.skipTest("no rostered player with growth room")

    def test_growth_reaches_peak_and_stops(self):
        g = game("career-peak")
        role, cid, stat = self.player_with_room(g)
        peak = g.career_range(cid)["peak"][stat]
        g.s["progression"][cid] = {"stats": {**dict.fromkeys(STATS, 0), stat: 500}, "mastery": {}, "games": 0, "wins": 0}
        self.assertEqual(g.permanent_ratings(cid)[stat], peak)
        g.s["progression"][cid]["stats"][stat] = peak - g.cards[cid]["ratings"][stat] - .2
        g.apply({"type": "set_training", "role": role, "focus": stat})
        play(g)
        row = next(r for r in g.s["management"]["last_week"] if r["card_id"] == cid)
        self.assertLessEqual(row["gain"], .2 + 1e-9)
        self.assertEqual(g.permanent_ratings(cid)[stat], peak)
        self.assertTrue(row["at_peak"])
        play(g)
        row = next(r for r in g.s["management"]["last_week"] if r["card_id"] == cid)
        self.assertEqual(row["gain"], 0)
        self.assertEqual(next(x for x in g.s["last_growth"] if x["card_id"] == cid)["stats"][stat], 0)

    def test_any_season_card_can_grow_to_the_same_peak(self):
        g = game("career-any-year")
        for entry in CATALOG["players"].values():
            if len(entry["cards"]) >= 2:
                break
        for cid in entry["cards"]:
            g.s["progression"][cid] = {"stats": dict.fromkeys(STATS, 200), "mastery": {}, "games": 0, "wins": 0}
            self.assertEqual(g.permanent_ratings(cid), {k: float(v) for k, v in entry["peak"].items()})

    def test_floor_holds_against_exhaustion_condition_and_nerfs(self):
        g = game("career-floor")
        for cid in g.s["roster"].values():
            g.s["management"]["stamina"][cid] = 0
        g.s["management"]["morale"] = -3
        meta = g.s["management"]["meta"]
        meta["nerfs"] = sorted(set(meta["nerfs"]) | set(g.s["draft"].values()))
        meta["buffs"] = [c for c in meta["buffs"] if c not in meta["nerfs"]]
        g.apply({"type": "set_plan", "plan": "aggressive"})
        g.apply({"type": "start"})
        clamped = 0
        for team in g.match.s["teams"]:
            for u in team:
                for stat in STATS:
                    self.assertGreaterEqual(u["ratings"][stat], u["floor"][stat])
                    clamped += u["ratings"][stat] == u["floor"][stat]
        self.assertTrue(all(u["exhausted"] for u in g.match.s["teams"][0]))
        self.assertGreater(clamped, 0)

    def test_temporary_buffs_may_exceed_peak_but_permanent_growth_does_not(self):
        g = game("career-buffs")
        cid = g.s["roster"]["mid"]
        g.s["progression"][cid] = {"stats": dict.fromkeys(STATS, 300), "mastery": {}, "games": 0, "wins": 0}
        g.s["coins"] = 5000
        g.apply({"type": "buy_relic", "relic": "3190"})
        unit = next(u for u in g.view()["lineup_preview"] if u["card_id"] == cid)
        peak = g.career_range(cid)["peak"]
        self.assertEqual(unit["permanent_ratings"], {k: float(v) for k, v in peak.items()})
        self.assertTrue(any(unit["ratings"][s] > peak[s] for s in STATS if peak[s] < 97))


class CareerSaveTests(unittest.TestCase):
    def test_v6_save_migrates_and_replays(self):
        old = game("v6-migration", cls=GameV6)
        play(old)
        old.apply({"type": "reward_choice", "option": "credits"})
        old.apply({"type": "start"})
        old.apply({"type": "tick", "steps": 20})
        migrated = Game.import_save(old.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(migrated.s["roster"], old.s["roster"])
        self.assertEqual(migrated.match.s["time"], old.match.s["time"])
        finish(migrated)
        again = Game.import_save(migrated.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(again.s, migrated.s)
        migrated.apply({"type": "reward_choice", "option": "credits"}) if migrated.s["reward_event"] else None
        migrated.apply({"type": "start"})
        self.assertTrue(all("floor" in u for u in migrated.match.s["teams"][0]))


if __name__ == "__main__":
    unittest.main()
