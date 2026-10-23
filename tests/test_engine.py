import copy
import hashlib
import json
import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))
from engine import Bridge, Game, Match, ROLES

CATALOG = json.loads((ROOT / "web/data/cards.json").read_text(encoding="utf8"))
CHAMPIONS = json.loads((ROOT / "web/data/champions.json").read_text(encoding="utf8"))


def finish(game, option="commit"):
    for _ in range(1000):
        if game.match.s["winner"] is not None:
            return
        if game.match.s["event"]:
            game.apply({"type": "choose", "option": option})
        else:
            game.apply({"type": "tick", "steps": 10})
    raise AssertionError("Match did not finish")


class EngineTests(unittest.TestCase):
    def game(self, seed="test"):
        game = Game(CATALOG, CHAMPIONS, seed)
        for role in ROLES:
            game.apply({"type": "starter_open", "role": role})
        game.apply({"type": "starter_finish"})
        return game

    def test_starter_covers_roles_and_has_real_evidence(self):
        g = self.game()
        self.assertEqual(set(g.s["roster"]), set(ROLES))
        self.assertEqual(len({g.cards[i]["player_id"] for i in g.s["owned"]}), 5)
        for cid in g.s["owned"]:
            self.assertTrue(g.cards[cid]["evidence"]["first_game"])

    def test_seed_and_actions_reproduce_exact_state(self):
        a, b = self.game(), self.game()
        for g in (a, b):
            g.apply({"type": "pull", "role": "mid"})
            g.apply({"type": "start"})
            finish(g)
        self.assertEqual(a.view(), b.view())

    def test_pause_does_not_consume_rng_or_time(self):
        g = self.game(); g.apply({"type": "start"})
        while not g.match.s["event"]:
            g.match.step()
        snapshot, rng = copy.deepcopy(g.match.s), g.match.rng.state
        for _ in range(10):
            g.match.step()
        self.assertEqual(snapshot, g.match.s)
        self.assertEqual(rng, g.match.rng.state)
        self.assertTrue(2 <= len(snapshot["event"]["options"]) <= 4)

    def test_bad_choice_preserves_state(self):
        g = self.game();g.apply({"type": "start"})
        while not g.match.s["event"]:
            g.match.step()
        before, rng = copy.deepcopy(g.match.s), g.match.rng.state
        with self.assertRaises(ValueError): g.match.choose("invalid")
        self.assertEqual(before, g.match.s)
        self.assertEqual(rng, g.match.rng.state)

    def test_choices_change_future_state_and_followups(self):
        a = self.game();a.apply({"type": "start"})
        while not a.match.s["event"]: a.apply({"type":"tick","steps":1})
        b = Game.import_save(a.export_save(), CATALOG, CHAMPIONS)
        a.apply({"type":"choose","option":"commit"})
        b.apply({"type":"choose","option":"trade"})
        self.assertNotEqual(a.match.s, b.match.s)
        self.assertEqual(a.match.s["followup"], "countergank")
        self.assertIsNone(b.match.s["followup"])
        while not a.match.s["event"]: a.match.step()
        self.assertEqual(a.match.s["event"]["kind"], "followup")
        self.assertEqual(len(a.match.s["event"]["options"]), 4)

    def test_save_mid_event_restores_rng_and_result(self):
        a = self.game();a.apply({"type":"start"})
        while not a.match.s["event"]: a.apply({"type":"tick","steps":2})
        b = Game.import_save(a.export_save(), CATALOG, CHAMPIONS)
        self.assertEqual(a.view(), b.view())
        finish(a, "vision");finish(b, "vision")
        self.assertEqual(a.view(), b.view())

    def test_corrupt_and_incompatible_saves_are_rejected(self):
        g = self.game()
        for bad in ('{}', '[]', 'not json', '{"__reduce__":"evil"}'):
            with self.assertRaises(ValueError): Game.import_save(bad, CATALOG, CHAMPIONS)
        data = json.loads(g.export_save());data["seed"]="changed"
        with self.assertRaises(ValueError): Game.import_save(json.dumps(data), CATALOG, CHAMPIONS)
        wrong = {**CATALOG,"version":"different"}
        with self.assertRaisesRegex(ValueError, "데이터 버전"):
            Game.import_save(g.export_save(),wrong,CHAMPIONS)

    def test_bridge_import_is_transactional(self):
        bridge = Bridge(json.dumps(CATALOG),json.dumps(CHAMPIONS))
        before=bridge.game.export_save()
        result=json.loads(bridge.call(json.dumps({"type":"import","save":"bad"})))
        self.assertFalse(result["ok"])
        self.assertEqual(before,bridge.game.export_save())

    def test_roster_lock_during_match(self):
        g=self.game();g.apply({"type":"start"})
        before=g.view()
        for action in ({"type":"pull"},{"type":"equip","card":g.s["owned"][0]},
                       {"type":"draft","role":"mid","champion":"Ahri"},{"type":"start"}):
            with self.assertRaises(ValueError): g.apply(action)
        self.assertEqual(before,g.view())

    def test_draft_duplicate_rejected_and_unplayed_mastery(self):
        g=self.game()
        with self.assertRaises(ValueError): g.apply({"type":"draft","role":"top","champion":g.s["draft"]["mid"]})
        c=g.cards[g.s["roster"]["top"]]
        known={x["id"] for x in g.champion_pool(c)}
        pick=next(x for x in g.champions if x not in known and x not in g.s["draft"].values())
        g.apply({"type":"draft","role":"top","champion":pick})
        units=g.units([g.s["roster"][r] for r in ROLES],g.s["draft"])
        self.assertEqual(units[0]["mastery"],35)

    def test_free_currency_and_negative_balance_prevention(self):
        g=self.game()
        for _ in range(4): g.apply({"type":"pull"})
        while g.s["coins"]>=150: g.apply({"type":"pull"})
        before=g.export_save()
        with self.assertRaises(ValueError):g.apply({"type":"pull"})
        self.assertEqual(before,g.export_save())
        self.assertGreaterEqual(g.s["coins"],0)

    def test_no_premature_winner_and_reward_once(self):
        g=self.game();g.apply({"type":"start"})
        self.assertIsNone(g.match.s["winner"])
        finish(g)
        self.assertEqual(g.match.s["nexus"][1-g.match.s["winner"]],0)
        money=g.s["coins"];history=len(g.s["season"]["history"])
        g.apply({"type":"tick","steps":10});g.settle()
        self.assertEqual(money,g.s["coins"])
        self.assertEqual(history,len(g.s["season"]["history"]))

    def test_structures_protect_nexus(self):
        g=self.game();g.apply({"type":"start"});m=g.match
        m.push(0,"mid",100000)
        self.assertEqual(m.s["nexus"][1],4000)
        self.assertEqual(m.s["towers"][1]["mid"],2)

    def test_skill_cooldown_and_ultimate_unlock(self):
        g=self.game()
        role=next(r for r in ROLES if g.s["draft"][r]=="Ahri") if "Ahri" in g.s["draft"].values() else "mid"
        g.apply({"type":"draft","role":role,"champion":"Ahri"})
        g.apply({"type":"start"});m=g.match;u=m.unit(0,role)
        self.assertNotIn("R",[s["key"] for s in m.ready_skills(u)])
        m.s["time"]=400
        self.assertIn("R",[s["key"] for s in m.ready_skills(u)])
        u["cooldowns"]["R"]=500
        self.assertNotIn("R",[s["key"] for s in m.ready_skills(u)])

    def test_objective_spawn_and_respawn(self):
        g=self.game();g.apply({"type":"start"});m=g.match
        self.assertIsNone(m.available_objective())
        m.s["time"]=300;self.assertEqual(m.available_objective(),"dragon")
        m.objective(0,"dragon");self.assertEqual(m.s["next_dragon"],600)
        self.assertIsNone(m.available_objective())
        m.s["time"]=1200;self.assertEqual(m.available_objective(),"baron")

    def test_round_robin_unique_pairs_and_full_season(self):
        g=self.game("full-season")
        pairs=[tuple(sorted(p)) for r in g.s["season"]["schedule"] for p in r]
        self.assertEqual(len(set(pairs)),15)
        count=0
        while g.s["season"]["phase"]!="complete":
            g.apply({"type":"start"});finish(g);count+=1
            g.apply({"type":"reward_choice", "option":"credits"})
            self.assertLessEqual(count,11)
        self.assertEqual(g.s["season"]["round"],5)
        self.assertEqual(sum(t["wins"] for t in g.s["season"]["teams"]),15)
        self.assertTrue(all(t["wins"]+t["losses"]==5 for t in g.s["season"]["teams"]))
        old_owned=list(g.s["owned"]);coins=g.s["coins"]
        g.apply({"type":"next_season"})
        self.assertEqual(g.s["season_number"],2)
        self.assertEqual(g.s["owned"],old_owned)
        self.assertEqual(g.s["coins"],coins)

    def test_100_seed_simulations_invariants_and_variable_time(self):
        g=self.game();blue=g.units([g.s["roster"][r] for r in ROLES]);red=g.units(g.s["season"]["teams"][1]["roster"])
        durations=[];winners=set()
        for seed in range(1,101):
            m=Match(copy.deepcopy(blue),copy.deepcopy(red),seed,g.champions)
            winner=m.simulate();winners.add(winner);durations.append(m.s["time"])
            self.assertEqual(m.s["nexus"][1-winner],0)
            self.assertTrue(all(n>=0 for n in m.s["gold"]))
            self.assertTrue(all(0<=n<=3 for ts in m.s["towers"] for n in ts.values()))
            self.assertTrue(all(2<=len(c) for c in [m.s["decisions"]]))
        self.assertGreater(len(set(durations)),80)
        self.assertEqual(winners,{0,1})
        print(f"\n100 seeded matches: {min(durations)//60}-{max(durations)//60} minutes; median {statistics.median(durations)/60:.1f}; both sides can win")


if __name__=="__main__":unittest.main()
