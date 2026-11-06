import copy
import unittest
from test_engine import CATALOG, CHAMPIONS, finish
from engine import Game, ROLES
from legacy_engine_v5 import Game as GameV5
from management import (PLANS, TRAITS, TRAINING, SPONSORS, DIVISIONS, COUNTER_BONUS, EXHAUSTED, EXHAUSTED_PENALTY,
                        card_traits, plan_counter)


def game(seed="ops-tests", cls=Game):
    g = cls(CATALOG, CHAMPIONS, seed)
    for role in ROLES:
        g.apply({"type": "starter_open", "role": role})
    g.apply({"type": "starter_finish"})
    return g


def play(g):
    if g.s["reward_event"]:
        g.apply({"type": "reward_choice", "option": "credits"})
    g.apply({"type": "start"})
    finish(g)


class TraitTests(unittest.TestCase):
    def test_traits_are_deterministic_known_and_cover_every_card(self):
        seen = set()
        for card in CATALOG["cards"]:
            traits = card_traits(card)
            self.assertEqual(traits, card_traits(copy.deepcopy(card)))
            self.assertTrue(1 <= len(traits) <= 2)
            self.assertEqual(len(set(traits)), len(traits))
            self.assertTrue(set(traits) <= set(TRAITS))
            seen.update(traits)
        self.assertEqual(seen, set(TRAITS))

    def test_trait_stats_apply_to_both_teams(self):
        g = game()
        g.apply({"type": "start"})
        for team in g.match.s["teams"]:
            for u in team:
                self.assertEqual(u["traits"], card_traits(g.cards[u["card_id"]]))
                expected = sum(TRAITS[t].get("stats", {}).get("lane", 0) for t in u["traits"])
                meta = 2 if u["meta"] == "buff" else -2 if u["meta"] == "nerf" else 0
                self.assertEqual(u["ops_mods"]["lane"], expected + meta - (EXHAUSTED_PENALTY if u.get("exhausted") else 0))


class PlanTests(unittest.TestCase):
    def test_counter_cycle_is_closed_and_balanced_is_neutral(self):
        styles = [k for k in PLANS if k != "balanced"]
        for plan in styles:
            beaten = PLANS[plan]["beats"]
            self.assertIn(beaten, styles)
            self.assertEqual(plan_counter(plan, beaten), 1)
            self.assertEqual(plan_counter(beaten, plan), -1)
            self.assertEqual(plan_counter(plan, "balanced"), 0)
            self.assertEqual(plan_counter("balanced", plan), 0)
        self.assertEqual(sorted(PLANS[p]["beats"] for p in styles), sorted(styles))

    def test_counter_plan_boosts_our_team_and_preview_matches_match(self):
        g = game()
        scout = g.view()["ops_view"]["scouting"]
        g.apply({"type": "set_plan", "plan": scout["suggested"]})
        preview = {u["card_id"]: u for u in g.view()["lineup_preview"]}
        g.apply({"type": "start"})
        self.assertEqual(g.match.s["plans"], {"ours": scout["suggested"], "theirs": scout["style"], "counter": 1})
        for u in g.match.s["teams"][0]:
            self.assertEqual(u["plan"]["counter"], 1)
            p = preview[u["card_id"]]
            for stat, value in p["ratings"].items():
                self.assertEqual(u["ratings"][stat], round(max(1, min(99, value + u["condition"]["modifier"])), 2))
        for u in g.match.s["teams"][1]:
            self.assertEqual(u["plan"], {"id": scout["style"], "enemy": scout["suggested"], "counter": -1})

    def test_plan_bonus_value(self):
        g = game()
        style = g.view()["ops_view"]["scouting"]["style"]
        base = {u["card_id"]: u["ratings"] for u in g.view()["lineup_preview"]}
        g.apply({"type": "set_plan", "plan": next(k for k, v in PLANS.items() if v["beats"] == style)})
        for u in g.view()["lineup_preview"]:
            for stat in ("lane", "combat", "vision", "farm"):
                delta = PLANS[u["plan"]["id"]]["stats"].get(stat, 0) + COUNTER_BONUS
                self.assertEqual(u["ratings"][stat], round(max(1, min(99, base[u["card_id"]][stat] + delta)), 2))

    def test_plan_locked_during_match_and_bad_inputs_rejected(self):
        g = game()
        for bad in ({"type": "set_plan", "plan": "zerg"}, {"type": "set_training", "role": "mid", "focus": "nap"},
                    {"type": "set_training", "role": "coach", "focus": "rest"}, {"type": "sign_sponsor", "sponsor": "nope"}):
            snapshot = g.export_save()
            with self.assertRaises(ValueError):
                g.apply(bad)
            self.assertEqual(snapshot, g.export_save())
        g.apply({"type": "start"})
        with self.assertRaises(ValueError):
            g.apply({"type": "set_plan", "plan": "control"})


class WeekTests(unittest.TestCase):
    def test_training_fatigue_rest_and_growth_apply_once_per_match(self):
        g = game()
        g.apply({"type": "set_training", "role": "top", "focus": "combat"})
        g.apply({"type": "set_training", "role": "mid", "focus": "rest"})
        g.apply({"type": "set_training", "role": "sup", "focus": "champion", "champion": "Thresh"})
        top, mid, sup = (g.s["roster"][r] for r in ("top", "mid", "sup"))
        play(g)
        week = {row["role"]: row for row in g.s["management"]["last_week"]}
        self.assertEqual(len(week), 5)
        self.assertEqual(week["top"]["stat"], "combat")
        self.assertGreater(week["top"]["gain"], 0)
        self.assertLess(g.stamina(top), 100)
        self.assertEqual(g.stamina(mid), 100)
        self.assertEqual(week["sup"]["champion"], "Thresh")
        self.assertGreater(g.s["progression"][sup]["mastery"]["Thresh"], 0)
        snapshot = copy.deepcopy(g.s)
        g.apply({"type": "tick", "steps": 1}) if g.active() else None
        g.settle()
        self.assertEqual(snapshot, g.s)

    def test_exhaustion_lowers_condition_shift_and_ratings(self):
        g = game()
        fresh = {u["card_id"]: u for u in g.view()["lineup_preview"]}
        cid = g.s["roster"]["jng"]
        g.s["management"]["stamina"][cid] = EXHAUSTED - 5
        tired = next(u for u in g.view()["lineup_preview"] if u["card_id"] == cid)
        self.assertTrue(tired["exhausted"])
        self.assertLess(tired["condition_shift"], fresh[cid]["condition_shift"])
        self.assertEqual(tired["ratings"]["combat"], round(max(1, fresh[cid]["ratings"]["combat"] - EXHAUSTED_PENALTY), 2))

    def test_new_season_resets_stamina_and_keeps_morale(self):
        g = game()
        g.s["management"]["stamina"] = {g.s["roster"]["top"]: 20}
        g.s["management"]["morale"] = 2
        g.s["season"]["phase"] = "complete"
        g.apply({"type": "next_season"})
        self.assertEqual(g.s["management"]["stamina"], {})
        self.assertEqual(g.s["management"]["morale"], 2)

    def test_morale_follows_streaks_within_bounds(self):
        g = game()
        for _ in range(3):
            play(g)
            m = g.s["management"]
            self.assertTrue(-3 <= m["morale"] <= 3)
            self.assertEqual(m["morale"] > 0, m["streak"] > 0)


class SeasonOpsTests(unittest.TestCase):
    def test_sponsor_offers_sign_once_and_pay(self):
        g = game("sponsor-pay")
        offers = g.s["management"]["sponsor_offers"]
        self.assertEqual(len(set(offers)), 3)
        self.assertTrue(set(offers) <= set(SPONSORS))
        outside = next(k for k in SPONSORS if k not in offers)
        with self.assertRaises(ValueError):
            g.apply({"type": "sign_sponsor", "sponsor": outside})
        g.s["management"]["sponsor_offers"] = ["appearance", "win_bonus", "kill"]
        g.apply({"type": "sign_sponsor", "sponsor": "appearance"})
        with self.assertRaises(ValueError):
            g.apply({"type": "sign_sponsor", "sponsor": "win_bonus"})
        coins = g.s["coins"]
        play(g)
        won = g.match.s["winner"] == 0
        scale = DIVISIONS[0]["reward"]
        self.assertEqual(g.match.s["sponsor_income"], SPONSORS["appearance"]["match"])
        self.assertGreaterEqual(g.s["coins"] - coins, round((240 if won else 140)*scale) + 45)

    def test_patch_meta_touches_own_pool_and_adjusts_ratings(self):
        g = game()
        meta = g.s["management"]["meta"]
        self.assertEqual((len(meta["buffs"]), len(meta["nerfs"])), (4, 3))
        self.assertFalse(set(meta["buffs"]) & set(meta["nerfs"]))
        own = {p["id"] for cid in g.s["roster"].values() for p in g.champion_pool(g.cards[cid])[:4]}
        self.assertTrue(set(meta["buffs"][:2]) <= own)
        role = "mid"
        g.apply({"type": "draft", "role": role, "champion": meta["buffs"][2]}) if meta["buffs"][2] not in g.s["draft"].values() else None
        unit = next(u for u in g.view()["lineup_preview"] if u["role"] == role)
        if unit["champion"] in meta["buffs"]:
            self.assertEqual(unit["meta"], "buff")

    def test_promotion_relegation_and_reward_scaling(self):
        g = game()
        s = g.s["season"]
        s["phase"] = "complete"; s["standings"] = [1, 2, 3, 4, 5, 0]
        g.s["management"]["division"] = 1; s["division"] = 1
        g.close_season()
        self.assertEqual(g.s["management"]["season_result"]["outcome"], "relegate")
        self.assertEqual(g.s["management"]["division"], 0)
        g.close_season()  # idempotent
        self.assertEqual(g.s["management"]["division"], 0)
        g.apply({"type": "next_season"})
        names = [t["name"] for t in g.s["season"]["teams"]]
        self.assertEqual(names, DIVISIONS[0]["teams"])
        s = g.s["season"]
        s["phase"] = "complete"; s["standings"] = [0, 1, 2, 3, 4, 5]; s["champion"] = 0
        s["history"].append({"phase": "final", "won": True})
        g.close_season()
        self.assertEqual(g.s["management"]["season_result"]["outcome"], "promote")
        self.assertEqual(g.s["management"]["division"], 1)
        g.apply({"type": "next_season"})
        self.assertEqual(g.s["season"]["division"], 1)
        self.assertTrue(all(t["style"] for t in g.s["season"]["teams"][1:]))

    def test_full_season_replays_exactly(self):
        g = game("ops-replay")
        g.apply({"type": "sign_sponsor", "sponsor": g.s["management"]["sponsor_offers"][1]})
        g.apply({"type": "set_training", "role": "bot", "focus": "farm"})
        g.apply({"type": "set_plan", "plan": "aggressive"})
        for _ in range(2):
            play(g)
        replay = Game.import_save(g.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(replay.s, g.s)
        self.assertEqual(replay.view(), g.view())

    def test_v5_save_with_inflight_match_migrates(self):
        old = game("v5-migration", cls=GameV5)
        old.apply({"type": "start"})
        old.apply({"type": "tick", "steps": 30})
        migrated = Game.import_save(old.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(migrated.s["roster"], old.s["roster"])
        self.assertEqual(migrated.s["management"]["division"], 0)
        self.assertEqual(migrated.match.s["time"], old.match.s["time"])
        finish(migrated)
        self.assertEqual(migrated.s["management"]["last_week"], [])
        again = Game.import_save(migrated.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(again.s, migrated.s)
        play(migrated)
        self.assertEqual(len(migrated.s["management"]["last_week"]), 5)


if __name__ == "__main__":
    unittest.main()
