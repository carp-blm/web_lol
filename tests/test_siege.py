import copy
import statistics
import unittest
from test_clutch import match
from test_management import game
from engine import Match
from combat import CombatRules
from legacy_engine_v6 import Match as MatchV6
from siege import (SiegeRules, SIEGE_BASE, GOLD_LEAD_STEP, GOLD_LEAD_CAP, GOLD_DEFICIT_FLOOR, ALIVE_BONUS,
                   DRAGON_BONUS)


class SiegeMultiplierTests(unittest.TestCase):
    def test_even_game_uses_base_pace(self):
        m = match()
        m.s["gold"] = [20000, 20000]
        self.assertAlmostEqual(m.siege_multiplier(0), SIEGE_BASE)
        self.assertAlmostEqual(m.siege_multiplier(1), SIEGE_BASE)

    def test_gold_lead_speeds_up_and_deficit_slows_down_within_bounds(self):
        m = match()
        m.s["gold"] = [20000+GOLD_LEAD_STEP, 20000]
        self.assertAlmostEqual(m.siege_multiplier(0), SIEGE_BASE*2)
        self.assertLess(m.siege_multiplier(1), SIEGE_BASE)
        m.s["gold"] = [200000, 0]
        self.assertAlmostEqual(m.siege_multiplier(0), SIEGE_BASE*(1+GOLD_LEAD_CAP))
        self.assertAlmostEqual(m.siege_multiplier(1), SIEGE_BASE*GOLD_DEFICIT_FLOOR)

    def test_dead_enemies_and_dragon_lead_add_damage_for_the_leader_only(self):
        m = match()
        m.s["gold"] = [20000, 20000]
        m.s["teams"][1][0]["status"] = m.s["teams"][1][1]["status"] = "dead"
        self.assertAlmostEqual(m.siege_multiplier(0), SIEGE_BASE*(1+2*ALIVE_BONUS))
        self.assertAlmostEqual(m.siege_multiplier(1), SIEGE_BASE)
        m.s["teams"][1][0]["status"] = m.s["teams"][1][1]["status"] = "active"
        m.s["dragons"] = [3, 1]
        self.assertAlmostEqual(m.siege_multiplier(0), SIEGE_BASE*(1+2*DRAGON_BONUS))
        self.assertAlmostEqual(m.siege_multiplier(1), SIEGE_BASE)

    def test_lead_converts_into_structure_damage(self):
        def tower_damage(gold):
            m = match()
            m.s["time"] = 1200
            m.s["gold"] = list(gold)
            lane = "mid"
            for side in (0, 1):
                for u in m.s["teams"][side]:
                    if u["role"] == "mid":
                        u["location"], u["pos"] = lane, list(m.lane_point(lane, side, "mid"))
            m.encounter_odds = lambda *a, **k: 1
            before = m.s["tower_hp"][1][lane]
            m.siege(lane)
            return before-m.s["tower_hp"][1][lane]
        even, ahead = tower_damage((30000, 30000)), tower_damage((48000, 30000))
        self.assertGreater(even, 0)
        self.assertAlmostEqual(ahead/even, 3, delta=.05)


class SiegeScopeTests(unittest.TestCase):
    def test_only_the_current_engine_uses_lead_scaling(self):
        self.assertIs(Match.siege, SiegeRules.siege)
        self.assertIs(MatchV6.siege, CombatRules.siege)
        self.assertFalse(hasattr(MatchV6, "siege_multiplier"))

    def lengths(self, blue, red, champions):
        durations, stalled = [], 0
        for seed in range(1, 41):
            m = Match(copy.deepcopy(blue), copy.deepcopy(red), seed, champions)
            m.simulate()
            minutes = m.s["time"]/60
            durations.append(minutes)
            stalled += abs(m.s["gold"][0]-m.s["gold"][1]) > 15000 and minutes > 45
        return durations, stalled

    def test_match_length_distribution(self):
        g = game("clutch-tests")
        teams = g.s["season"]["teams"]
        even, stalled = self.lengths(g.units(teams[1]["roster"]), g.units(teams[2]["roster"]), g.champions)
        self.assertTrue(26 <= statistics.median(even) <= 40, statistics.median(even))
        self.assertLess(max(even), 75)
        self.assertEqual(stalled, 0)
        # The starter roster outclasses this opponent by about 7 OVR: a stomp must end sooner.
        base = match()
        stomp, stalled = self.lengths(*base.s["teams"], base.champions)
        self.assertLess(statistics.median(stomp), statistics.median(even)-3)
        self.assertLess(max(stomp), 45)
        self.assertEqual(stalled, 0)

if __name__ == "__main__":
    unittest.main()
