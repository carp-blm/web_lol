import copy
import json
import unittest
from test_engine import CATALOG, CHAMPIONS, ROOT, finish
from engine import Game, Match, ROLES, Bridge
from legacy_engine_v3 import Game as GameV3
from progression import RELICS, synergy_groups


def game(seed="growth-tests", cls=Game):
    g = cls(CATALOG, CHAMPIONS, seed)
    for role in ROLES:
        g.apply({"type": "starter_open", "role": role})
    g.apply({"type": "starter_finish"})
    return g


def lineup(g):
    return g.units([g.s["roster"][r] for r in ROLES], g.s["draft"])


def event(g):
    while not g.match.s["event"]:
        g.apply({"type": "tick", "steps": 12})


class ProgressionTests(unittest.TestCase):
    def test_official_item_names_and_icons_match_pinned_snapshot(self):
        snapshot = json.loads((ROOT / "data/item_snapshot.json").read_text(encoding="utf8"))
        self.assertEqual(set(RELICS), set(snapshot["items"]))
        for rid, relic in RELICS.items():
            self.assertEqual(relic["name"], snapshot["items"][rid]["name"])
            self.assertTrue(relic["icon"].endswith(f'/{snapshot["version"]}/img/item/{snapshot["items"][rid]["image"]}'))

    def test_conditions_are_seeded_fixed_and_change_power_without_mutating_cards(self):
        g = game(); before = copy.deepcopy(CATALOG)
        g.apply({"type": "start"})
        replay = Game.import_save(g.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(g.view(), replay.view())
        conditions = [u["condition"] for t in g.match.s["teams"] for u in t]
        self.assertGreater(len({c["modifier"] for c in conditions}), 1)
        for u, preview in zip(g.match.s["teams"][0], lineup(g)):
            expected = min(99, max(1, preview["ratings"]["combat"]+u["condition"]["modifier"]))
            self.assertEqual(u["ratings"]["combat"], expected)
        for _ in range(3): g.view()
        g.apply({"type": "tick", "steps": 10})
        self.assertEqual(conditions, [u["condition"] for t in g.match.s["teams"] for u in t])
        self.assertEqual(CATALOG, before)

    def test_growth_depends_on_win_performance_and_caps(self):
        reports = []
        for won, kills in ((False, 0), (True, 0), (True, 15)):
            g = game(); g.apply({"type": "start"}); g.match.s["time"] = 1800
            for u in g.match.s["teams"][0]:
                u.update(kills=kills, deaths=3, assists=kills, cs=160, saves=0)
            g.settle_progression(won)
            reports.append(g.s["last_growth"][0])
        for previous, current in zip(reports, reports[1:]):
            self.assertGreater(current["mastery"], previous["mastery"])
            self.assertGreater(current["stats"]["combat"], previous["stats"]["combat"])
        cid = g.s["roster"]["top"]; champion = g.s["draft"]["top"]
        g.s["progression"][cid]["stats"] = {k: 99-v for k, v in g.cards[cid]["ratings"].items()}
        raw = next((p["mastery"] for p in g.champion_pool(g.cards[cid]) if p["id"] == champion), 35)
        g.s["progression"][cid]["mastery"][champion] = 100-raw
        g.settle_progression(True)
        self.assertTrue(all(v == 0 for v in g.s["last_growth"][0]["stats"].values()))
        self.assertEqual(g.s["last_growth"][0]["mastery"], 0)

    def test_match_settlement_growth_and_reward_are_once_only_and_replayable(self):
        g = game(); g.apply({"type": "start"}); finish(g)
        self.assertEqual(len(g.s["last_growth"]), 5)
        self.assertEqual(len(g.s["reward_event"]["relics"]), 3)
        self.assertTrue(all(p["games"] == 1 for p in g.s["progression"].values()))
        before = copy.deepcopy(g.s); rng = g.rng.state
        g.settle(); g.apply({"type": "tick", "steps": 12})
        self.assertEqual(g.s, before); self.assertEqual(g.rng.state, rng)
        replay = Game.import_save(g.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(g.view(), replay.view())
        for unit in lineup(g):
            self.assertGreater(unit["permanent_mastery"], unit["mastery"]-1)
            self.assertEqual(unit["permanent_ratings"], g.permanent_ratings(unit["card_id"]))

    def test_growth_only_changes_played_card_and_champion(self):
        g = game(); g.apply({"type": "pull"})
        g.apply({"type": "start"}); finish(g)
        self.assertEqual(set(g.s["progression"]), set(g.s["roster"].values()))
        for role, cid in g.s["roster"].items():
            self.assertEqual(set(g.s["progression"][cid]["mastery"]), {g.s["draft"][role]})
        # AI teams never borrow the human's progression, even for the same card ID.
        cid = g.s["roster"]["top"]
        self.assertEqual(g.units([cid])[0]["permanent_ratings"], g.cards[cid]["ratings"])

    def test_team_and_assigned_buffs_affect_correct_units(self):
        g = game(); original = lineup(g)
        g.apply({"type": "buy_relic", "relic": "3190"})
        for old, new in zip(original, lineup(g)):
            self.assertEqual(new["ratings"]["combat"], min(99, old["ratings"]["combat"]+2))
        g.s["coins"] += 300
        g.apply({"type": "buy_relic", "relic": "3031"})
        g.apply({"type": "assign_relic", "relic": "3031", "card": g.s["roster"]["bot"]})
        for unit in lineup(g):
            self.assertEqual("3031" in unit["relic_effects"], unit["role"] == "bot")
        g.apply({"type": "start"})
        self.assertIn("3031", g.match.unit(0,"bot")["relic_effects"])

    def test_mastery_relic_changes_effective_mastery_and_growth_only_for_target(self):
        base, buffed = game(), game()
        buffed.apply({"type": "buy_relic", "relic": "3089"})
        for g in (base, buffed):
            g.apply({"type": "start"}); g.match.s["time"] = 1800
            for u in g.match.s["teams"][0]: u.update(kills=2,deaths=2,assists=3,cs=120,saves=0)
            g.settle_progression(True)
        a, b = base.match.unit(0,"mid"), buffed.match.unit(0,"mid")
        self.assertEqual(b["mastery"], min(100, a["mastery"]+8))
        self.assertGreater(buffed.s["last_growth"][2]["mastery"], base.s["last_growth"][2]["mastery"])
        self.assertEqual(buffed.s["last_growth"][0], base.s["last_growth"][0])

    def test_consumable_applies_one_match_and_is_preserved_through_save(self):
        g = game(); g.apply({"type":"buy_relic","relic":"2140"})
        g.apply({"type":"use_relic","relic":"2140"})
        self.assertNotIn("2140", g.s["relics"])
        replay = Game.import_save(g.export_save(),CATALOG,CHAMPIONS)
        self.assertEqual(g.view(), replay.view())
        g.apply({"type":"start"})
        self.assertFalse(g.s["prepared_relics"])
        self.assertTrue(all("2140" in u["relic_effects"] for u in g.match.s["teams"][0]))
        finish(g); g.apply({"type":"reward_choice","option":"credits"}); g.apply({"type":"start"})
        self.assertTrue(all("2140" not in u["relic_effects"] for u in g.match.s["teams"][0]))
        self.assertEqual(g.view(), Game.import_save(g.export_save(),CATALOG,CHAMPIONS).view())

    def test_passive_and_ward_odds_are_visible_consumed_once_and_replayed(self):
        g = game(); g.apply({"type":"buy_relic","relic":"2065"})
        for _ in range(2):g.apply({"type":"buy_relic","relic":"2055"})
        g.apply({"type":"start"});event(g)
        before = copy.deepcopy(g.match.s["event"])
        self.assertEqual(before["relic_bonus"], .04)
        for o in before["options"]: self.assertEqual(o["chance"], round(min(.98,o["base_chance"]+.04),2))
        time, rng = g.match.s["time"], g.match.rng.state
        g.apply({"type":"use_relic","relic":"2055"})
        after = g.match.s["event"]
        for o in after["options"]: self.assertEqual(o["chance"], round(min(.98,o["base_chance"]+.16),2))
        self.assertEqual(g.s["relics"]["2055"]["count"],1)
        snapshot = g.export_save()
        with self.assertRaises(ValueError):g.apply({"type":"use_relic","relic":"2055"})
        self.assertEqual(snapshot,g.export_save());self.assertEqual((time,rng),(g.match.s["time"],g.match.rng.state))
        self.assertEqual(g.view(),Game.import_save(snapshot,CATALOG,CHAMPIONS).view())
        g.apply({"type":"choose","option":"vision"});event(g)
        self.assertEqual(g.match.s["event"]["relic_bonus"],.04)

    def test_exclusive_relics_reject_purchase_reward_and_pending_elixir(self):
        for first, second in (("3089","3157"),("3157","3089"),("2140","2139"),("2139","2140")):
            g=game();g.s["coins"]=2000
            g.apply({"type":"buy_relic","relic":first})
            if first in ("2140","2139"):g.apply({"type":"use_relic","relic":first})
            before=copy.deepcopy(g.s)
            with self.assertRaisesRegex(ValueError,"동시 소유"):g.apply({"type":"buy_relic","relic":second})
            self.assertEqual(g.s,before)
            g.s["reward_event"]={"relics":[second]}
            before=copy.deepcopy(g.s)
            with self.assertRaisesRegex(ValueError,"동시 소유"):g.apply({"type":"reward_choice","option":second})
            self.assertEqual(g.s,before)

    def test_invalid_purchase_assignment_and_midmatch_actions_are_atomic(self):
        g=game();g.apply({"type":"buy_relic","relic":"3031"});g.apply({"type":"buy_relic","relic":"2055"})
        actions=[{"type":"buy_relic","relic":"bad"},{"type":"buy_relic","relic":"3031"},
                 {"type":"buy_relic","relic":"3190"},{"type":"assign_relic","relic":"3031","card":"bad"},
                 {"type":"use_relic","relic":"2055"}]
        for action in actions:
            before=copy.deepcopy(g.s);save=g.export_save()
            with self.assertRaises(ValueError):g.apply(action)
            self.assertEqual(g.s,before);self.assertEqual(g.export_save(),save)
        g.apply({"type":"start"})
        for action in actions[:4]:
            before=g.view()
            with self.assertRaises(ValueError):g.apply(action)
            self.assertEqual(g.view(),before)

    def test_synergy_counts_exact_team_id_year_and_only_members(self):
        g=game(); units=lineup(g)
        for i,u in enumerate(units):u.update(team_id=f"other-{i}",team="Same display name",year=2024)
        self.assertFalse(synergy_groups(units))
        for count in range(2,6):
            test=copy.deepcopy(units)
            for u in test[:count]:u["team_id"]="linked"
            group=synergy_groups(test)[0]
            self.assertEqual(group["bonus"],(count-1)*2+1)
            test[0]["year"]=2023
            self.assertEqual(synergy_groups(test)[0]["bonus"],(count-1)*2)
            prepared=g.prepare_units(test)
            for i,u in enumerate(prepared):
                self.assertEqual(bool(u["synergy"]),i<count)
                self.assertEqual(u["ratings"]["combat"],min(99,u["permanent_ratings"]["combat"]+((count-1)*2 if i<count else 0)))

    def test_ward_stack_limit_and_no_double_reward(self):
        g=game()
        for _ in range(3):g.apply({"type":"buy_relic","relic":"2055"})
        before=g.view()
        with self.assertRaises(ValueError):g.apply({"type":"buy_relic","relic":"2055"})
        self.assertEqual(g.view(),before)
        g.apply({"type":"start"});finish(g)
        with self.assertRaises(ValueError):g.apply({"type":"start"})
        rid=g.s["reward_event"]["relics"][0]
        g.apply({"type":"reward_choice","option":rid});before=g.view()
        with self.assertRaises(ValueError):g.apply({"type":"reward_choice","option":rid})
        self.assertEqual(g.view(),before)

    def test_warmog_prevents_negative_condition(self):
        for seed in range(12):
            g=game(str(seed));g.apply({"type":"buy_relic","relic":"3083"});g.apply({"type":"start"})
            self.assertGreaterEqual(g.match.unit(0,"mid")["condition"]["modifier"],0)

    def test_tick_batch_sizes_have_identical_events_rng_and_match_result(self):
        results=[]
        for speed in (1,2,3,6,12):
            g=game();g.apply({"type":"start"})
            while g.match.s["winner"] is None:
                g.apply({"type":"choose","option":"vision"} if g.match.s["event"] else {"type":"tick","steps":speed})
            results.append((g.match.s,g.rng.state,g.s["progression"]))
        self.assertTrue(all(result==results[0] for result in results[1:]))

    def test_v3_partial_starter_and_inflight_save_remain_exact(self):
        partial=GameV3(CATALOG,CHAMPIONS,"v3-starter")
        partial.apply({"type":"starter_open","role":"top"})
        migrated=Game.import_save(partial.export_save(),CATALOG,CHAMPIONS)
        self.assertEqual(partial.s["starter"],migrated.s["starter"])
        old=game(cls=GameV3);old.apply({"type":"start"});event(old)
        migrated=Game.import_save(old.export_save(),CATALOG,CHAMPIONS)
        self.assertEqual(old.match.s,migrated.match.s)
        migrated.apply({"type":"choose","option":"vision"})
        self.assertEqual(migrated.view(),Game.import_save(migrated.export_save(),CATALOG,CHAMPIONS).view())
        finish(migrated)
        self.assertFalse(migrated.s["progression"])
        migrated.apply({"type":"start"})
        self.assertTrue(migrated.match.s["progression_rules"])
        self.assertEqual(migrated.view(),Game.import_save(migrated.export_save(),CATALOG,CHAMPIONS).view())


if __name__ == "__main__":
    unittest.main()
