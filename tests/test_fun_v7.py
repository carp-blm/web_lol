"""0.7 fun layer: big-match pressure, lasting mental traits, clutch calls, former-teammate derbies."""
import unittest
from unittest import mock
from test_clutch import match
from test_choice_pressure import scene, POINT
from test_management import game
from engine import ROLES
import clutch
from clutch import (STAGE_PRESSURE, DECIDER_PRESSURE, CLUTCH_CALL_BONUS, CLUTCH_CALL_REACH, DERBY_START,
                    DERBY_KILL_PRESSURE, KILL_RELIEF, DERBY_KILL_RELIEF, DEATH_PRESSURE, EVENT_SCALE, resolve_chance)
import management
from management import BIG_STAGE_AWAKENINGS, FRAGILE_PLAYOFF_SHAKEN, FRAGILE_SEASON_SHAKEN, OVERCOME_AWAKENINGS


def calm(m):
    for team in m.s["teams"]:
        for u in team:
            u.update(pressure=0, traits=[])
    return m


class StageTests(unittest.TestCase):
    def test_regular_season_starts_calm(self):
        m = calm(match())
        m.set_stage("regular", [0, 0])
        self.assertNotIn("stage", m.s)
        self.assertTrue(all(u["pressure"] == 0 for t in m.s["teams"] for u in t))

    def test_final_decider_is_heavier_than_a_semifinal_opener(self):
        semi, final = calm(match()), calm(match())
        semi.set_stage("semifinal", [0, 0])
        final.set_stage("final", [1, 1])
        self.assertTrue(all(u["pressure"] == STAGE_PRESSURE["semifinal"] for t in semi.s["teams"] for u in t))
        self.assertTrue(all(u["pressure"] == STAGE_PRESSURE["final"]+DECIDER_PRESSURE for t in final.s["teams"] for u in t))
        self.assertTrue(final.s["stage"]["decider"])
        self.assertEqual(final.s["highlights"][-1]["title"], "결승 최종전")

    def test_composure_traits_soften_stage_pressure(self):
        m = calm(match())
        m.unit(0, "mid")["traits"] = ["clutch"]
        m.set_stage("final", [0, 0])
        self.assertLess(m.unit(0, "mid")["pressure"], m.unit(0, "top")["pressure"])


class MentalTraitTests(unittest.TestCase):
    def week(self, g, results, playoff=False):
        """Fake one match of resolve outcomes: {role: (awakenings, shaken)}."""
        teams = [[{"card_id": g.s["roster"][r], "role": r, "awakenings": results.get(r, (0, 0))[0],
                   "shaken": results.get(r, (0, 0))[1]} for r in ROLES]]
        return g.settle_mental({"teams": teams}, playoff)

    def test_three_awakenings_in_a_season_earn_big_stage(self):
        g = game("mental-big")
        cid = g.s["roster"]["mid"]
        self.week(g, {"mid": (2, 0)})
        self.assertNotIn("big_stage", g.mental_traits(cid))
        events = self.week(g, {"mid": (BIG_STAGE_AWAKENINGS-2, 0)})
        self.assertIn("big_stage", g.mental_traits(cid))
        self.assertEqual((events[0]["trait"], events[0]["change"]), ("big_stage", "gain"))
        self.assertIn("big_stage", g.management_view()["card_traits"][cid])

    def test_playoff_falters_earn_fragile_and_replace_big_stage(self):
        g = game("mental-fragile")
        cid = g.s["roster"]["top"]
        self.week(g, {"top": (BIG_STAGE_AWAKENINGS, 0)})
        events = self.week(g, {"top": (0, FRAGILE_PLAYOFF_SHAKEN)}, playoff=True)
        self.assertEqual(g.mental_traits(cid), ["fragile"])
        self.assertEqual([(e["trait"], e["change"]) for e in events], [("big_stage", "lose"), ("fragile", "gain")])

    def test_regular_season_falters_need_more(self):
        g = game("mental-regular")
        cid = g.s["roster"]["bot"]
        self.week(g, {"bot": (0, FRAGILE_SEASON_SHAKEN-1)})
        self.assertEqual(g.mental_traits(cid), [])
        self.week(g, {"bot": (0, 1)})
        self.assertEqual(g.mental_traits(cid), ["fragile"])

    def test_off_season_overcomes_fragile_after_enough_awakenings(self):
        g = game("mental-overcome")
        cid = g.s["roster"]["sup"]
        self.week(g, {"sup": (0, FRAGILE_SEASON_SHAKEN)})
        self.week(g, {"sup": (OVERCOME_AWAKENINGS, 0)})
        events = g.close_mental_season()
        self.assertEqual(g.mental_traits(cid), [])
        self.assertEqual((events[0]["trait"], events[0]["change"]), ("fragile", "lose"))
        record = g.ops["mental"][g.cards[cid]["player_id"]]
        self.assertEqual((record["awakened"], record["shaken"]), (0, 0))

    def test_mental_traits_follow_the_player_into_matches_on_our_side_only(self):
        g = game("mental-units")
        cid = g.s["roster"]["jng"]
        g.ops["mental"][g.cards[cid]["player_id"]] = {"traits": ["fragile"], "awakened": 0, "shaken": 0, "playoff_shaken": 0}
        ours = g.units([g.s["roster"][r] for r in ROLES], g.s["draft"])
        theirs = g.units([cid], campaign=False)
        self.assertIn("fragile", next(u for u in ours if u["card_id"] == cid)["traits"])
        self.assertNotIn("fragile", theirs[0]["traits"])

    def test_mental_trait_effects_in_match(self):
        base = {"traits": [], "condition": {"modifier": 0}}
        self.assertAlmostEqual(resolve_chance({**base, "traits": ["big_stage"]}) - resolve_chance(base), clutch.BIG_STAGE_CHANCE)
        self.assertAlmostEqual(resolve_chance(base) - resolve_chance({**base, "traits": ["fragile"]}), -clutch.FRAGILE_CHANCE)
        m = calm(match())
        m.unit(0, "mid")["traits"] = ["fragile"]
        for role in ("mid", "top"):
            m.add_pressure(m.unit(0, role), 10)
        self.assertEqual(m.unit(0, "mid")["pressure"], 10*clutch.FRAGILE_PRESSURE)

    def test_full_season_records_mental_report(self):
        g = game("mental-season")
        if g.s["reward_event"]:
            g.apply({"type": "reward_choice", "option": "credits"})
        g.apply({"type": "start"})
        while g.match.s["winner"] is None:
            if g.match.s["event"]:
                g.apply({"type": "choose", "option": g.match.s["event"]["options"][0]["id"]})
            else:
                g.apply({"type": "tick", "steps": 600})
        self.assertIn("mental_report", g.match.s)
        total = sum(u["awakenings"]+u["shaken"] for u in g.match.s["teams"][0])
        tally = sum(r["awakened"]+r["shaken"] for r in g.ops["mental"].values())
        self.assertEqual(total, tally)


class ClutchCallTests(unittest.TestCase):
    def awakened_scene(self, hero="mid", kind="skirmish"):
        m = scene(kind=kind)
        u = m.unit(0, hero)
        u["resolve_chance"], u["pressure"] = 1.0, 100
        m.resolve_check(u)
        m.s["event"]["options"] = [o for o in m.s["event"]["options"] if o["id"] != "clutch"]
        m.offer_clutch_call()
        return m, u

    def test_offered_with_better_odds_when_an_awakened_player_is_involved(self):
        m, u = self.awakened_scene()
        options = {o["id"]: o for o in m.s["event"]["options"]}
        self.assertIn("clutch", options)
        self.assertEqual(options["clutch"]["hero"], "mid")
        self.assertAlmostEqual(options["clutch"]["chance"], options["commit"]["chance"]+CLUTCH_CALL_BONUS)

    def test_not_offered_without_an_awakened_player_or_after_the_clutch_play(self):
        m = scene()
        m.offer_clutch_call()
        self.assertNotIn("clutch", [o["id"] for o in m.s["event"]["options"]])
        m, u = self.awakened_scene()
        u["resolve"]["clutch_used"] = True
        m.s["event"]["options"].pop()
        m.offer_clutch_call()
        self.assertNotIn("clutch", [o["id"] for o in m.s["event"]["options"]])

    def test_far_away_player_cannot_take_the_call(self):
        m, u = self.awakened_scene(hero="top")
        self.assertNotIn("clutch", [o["id"] for o in m.s["event"]["options"]])
        u["pos"] = [POINT[0]+CLUTCH_CALL_REACH-1, POINT[1]]
        m.offer_clutch_call()
        self.assertIn("clutch", [o["id"] for o in m.s["event"]["options"]])

    def test_success_lands_a_kill_and_spends_the_clutch_play(self):
        m, u = self.awakened_scene()
        m.rng.random = lambda: 0.0
        with mock.patch.object(type(m), "encounter", lambda self, *a, **k: None):
            m.choose("clutch")
        decision = m.s["decisions"][-1]
        self.assertEqual((decision["choice"], decision["hero"], decision["success"]), ("clutch", "mid", True))
        self.assertEqual(m.s["clutch_moments"][-1]["kind"], "call")
        self.assertEqual(u["clutch_plays"], 1)
        self.assertTrue(u["resolve"]["clutch_used"])
        self.assertEqual(sum(1 for e in m.s["teams"][1] if e["status"] == "dead"), 1)
        self.assertTrue(m.s["highlights"][-1]["title"].startswith("CLUTCH CALL"))

    def test_failure_spends_the_clutch_play_without_a_moment(self):
        m, u = self.awakened_scene()
        m.rng.random = lambda: 0.99
        with mock.patch.object(type(m), "encounter", lambda self, *a, **k: None):
            m.choose("clutch")
        self.assertFalse(m.s["decisions"][-1]["success"])
        self.assertTrue(u["resolve"]["clutch_used"])
        self.assertEqual(u["clutch_plays"], 0)
        self.assertNotIn("call", [x["kind"] for x in m.s["clutch_moments"]])

    def test_a_nearby_player_rushes_in(self):
        m, u = self.awakened_scene(hero="top")
        u["pos"] = [POINT[0]+30, POINT[1]]
        m.offer_clutch_call()
        m.rng.random = lambda: 0.0
        with mock.patch.object(type(m), "encounter", lambda self, *a, **k: None):
            m.choose("clutch")
        self.assertEqual(u["pos"], POINT)

    def test_awakening_brings_the_next_tactical_moment_forward(self):
        m = calm(match())
        m.s["time"], m.s["next_event"] = 900, 2000
        u = m.unit(0, "mid")
        u["resolve_chance"], u["pressure"] = 1.0, 100
        m.resolve_check(u)
        self.assertEqual(m.s["next_event"], 900+clutch.CALL_LOOKAHEAD)


class DerbyTests(unittest.TestCase):
    def teammates(self, g):
        by_stint = {}
        for cid, card in sorted(g.cards.items()):
            by_stint.setdefault((card["team_id"], card["year"]), {}).setdefault(card["player_id"], cid)
        for players in by_stint.values():
            if len(players) >= 2:
                return list(players.values())[:2]

    def test_pairs_need_a_shared_team_and_year(self):
        g = game("derby-pairs")
        a, b = self.teammates(g)
        pairs = g.derby_pairs([a], [b])
        self.assertEqual(len(pairs), 1)
        self.assertEqual((pairs[0]["ours"], pairs[0]["theirs"]), (g.cards[a]["role"], g.cards[b]["role"]))
        stranger = next(c for c, card in sorted(g.cards.items())
                        if not set(g.career_stints(c)) & set(g.career_stints(a)))
        self.assertEqual(g.derby_pairs([a], [stranger]), [])
        self.assertEqual(g.derby_pairs([a], [a]), [])

    def test_derby_starts_tense_and_kills_weigh_more(self):
        m = calm(match())
        pair = {"ours": "mid", "theirs": "jng", "ours_name": "A", "theirs_name": "B", "team": "T", "year": 2024}
        m.set_derby([pair])
        ours, theirs = m.unit(0, "mid"), m.unit(1, "jng")
        self.assertEqual((ours["pressure"], theirs["pressure"]), (DERBY_START, DERBY_START))
        self.assertEqual(m.unit(0, "top")["pressure"], 0)
        self.assertEqual(m.s["highlights"][-1]["kind"], "derby")
        m.s["time"] = 900
        m.kill_unit(ours, theirs, [ours])
        self.assertEqual(theirs["pressure"], DERBY_START+DEATH_PRESSURE*EVENT_SCALE+DERBY_KILL_PRESSURE)
        self.assertEqual(ours["pressure"], max(0, DERBY_START+KILL_RELIEF+DERBY_KILL_RELIEF))
        self.assertEqual(ours["derby_kills"], 1)

    def test_scouting_report_lists_derbies(self):
        g = game("derby-scout")
        report = g.scouting_report()
        self.assertIn("derbies", report)
        expected = g.derby_pairs([g.s["roster"][r] for r in ROLES], g.s["season"]["teams"][report["team"]]["roster"])
        self.assertEqual(report["derbies"], expected)


if __name__ == "__main__":
    unittest.main()
