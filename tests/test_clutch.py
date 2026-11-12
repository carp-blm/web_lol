import unittest
from test_engine import CATALOG, CHAMPIONS
from test_management import game
from engine import Match, ROLES
from legacy_engine_v6 import Game as GameV6
from battlefield import PITS
import clutch
from clutch import AWAKEN_SECONDS, SHAKEN_PENALTY, TEAM_RESOLVE_COOLDOWN, resolve_chance

STATS = ("lane", "combat", "vision", "farm")


def match(seed=7):
    g = game("clutch-tests")
    teams = g.s["season"]["teams"]
    blue = g.units([g.s["roster"][r] for r in ROLES], g.s["draft"])
    red = g.units(teams[1]["roster"])
    return Match(blue, red, seed, g.champions)


def behind(m):
    """Team 0 is losing, so pressure keeps rising instead of easing."""
    m.s["gold"] = [0, 20000]
    return m


class ResolveTests(unittest.TestCase):
    def test_initial_state_and_chance_bounds(self):
        m = match()
        for team in m.s["teams"]:
            for u in team:
                self.assertEqual((u["pressure"], u["resolve"]), (0, None))
                self.assertTrue(.10 <= u["resolve_chance"] <= .75)
                self.assertEqual(u["resolve_chance"], resolve_chance(u))
        base = {"traits": [], "condition": {"modifier": 0}}
        self.assertGreater(resolve_chance({**base, "traits": ["clutch"]}), resolve_chance(base))

    def test_pressure_builds_only_for_the_trailing_team(self):
        m = match()
        m.s["time"] = 900
        m.s["gold"] = [10000, 16000]
        m.update_pressure()
        self.assertTrue(all(u["pressure"] > 0 for u in m.s["teams"][0]))
        self.assertTrue(all(u["pressure"] == 0 for u in m.s["teams"][1]))

    def test_awakening_reaches_peak_and_expires(self):
        m = behind(match())
        u = m.unit(0, "mid")
        u["peak"] = {k: max(v, 90) for k, v in u["ratings"].items()}
        saved = dict(u["ratings"])
        u["resolve_chance"], u["pressure"] = 1.0, 100
        m.update_pressure()
        self.assertTrue(m.awakened(u))
        self.assertEqual(u["ratings"], {k: max(saved[k], u["peak"][k]) for k in STATS})
        self.assertEqual(u["pressure"], 0)
        m.s["time"] += AWAKEN_SECONDS
        m.expire_resolve()
        self.assertIsNone(u["resolve"])
        self.assertEqual(u["ratings"], saved)

    def test_shaken_never_drops_below_floor(self):
        m = behind(match())
        u = m.unit(0, "top")
        u["floor"] = {k: v - 1 for k, v in u["ratings"].items()}
        saved = dict(u["ratings"])
        u["resolve_chance"], u["pressure"] = 0.0, 100
        m.update_pressure()
        self.assertEqual(u["resolve"]["kind"], "shaken")
        self.assertEqual(u["ratings"], {k: max(u["floor"][k], saved[k] - SHAKEN_PENALTY) for k in STATS})
        self.assertTrue(all(u["ratings"][k] >= u["floor"][k] for k in STATS))

    def test_one_resolve_check_per_team_window(self):
        m = behind(match())
        for u in m.s["teams"][0]:
            u["pressure"] = 100
        m.update_pressure()
        self.assertEqual(sum(1 for u in m.s["teams"][0] if u["resolve"]), 1)
        m.s["time"] += TEAM_RESOLVE_COOLDOWN - 1
        m.update_pressure()
        self.assertEqual(sum(1 for u in m.s["teams"][0] if u["resolve"]), 1)
        m.s["time"] += 1
        m.update_pressure()
        self.assertEqual(sum(1 for u in m.s["teams"][0] if u["resolve"]), 2)

    def test_death_and_lost_objective_add_pressure(self):
        m = match()
        victim, killer = m.unit(0, "mid"), m.unit(1, "mid")
        m.kill_unit(killer, victim, [killer])
        self.assertGreater(victim["pressure"], 0)
        before = [u["pressure"] for u in m.s["teams"][0]]
        m.objective(1, "dragon")
        self.assertTrue(all(u["pressure"] > b for u, b in zip(m.s["teams"][0], before)))


class ClutchPlayTests(unittest.TestCase):
    def awaken(self, m, u):
        u["resolve_chance"], u["pressure"] = 1.0, 100
        m.resolve_check(u)
        self.assertTrue(m.awakened(u))

    def test_objective_steal_by_awakened_player(self):
        m = match()
        m.s["time"] = 600
        m.s["next_dragon"] = 0
        thief = m.unit(0, "jng")
        self.awaken(m, thief)
        for u in m.s["teams"][0]:
            u["pos"] = [5, 95]
        thief["pos"] = list(PITS["dragon"])
        m.s["objective_attempt"] = {"side": 1, "kind": "dragon", "roles": ["jng"], "finish_at": 600,
                                    "solo": True, "position": list(PITS["dragon"])}
        m.rng.random = lambda: 0.0
        dragons = list(m.s["dragons"])
        m.resolve_objective()
        self.assertEqual(m.s["dragons"], [dragons[0] + 1, dragons[1]])
        self.assertEqual(m.s["clutch_moments"][-1]["kind"], "steal")
        self.assertTrue(thief["resolve"]["clutch_used"])
        self.assertEqual(thief["clutch_plays"], 1)

    def test_outnumbered_awakened_player_can_win_1v3(self):
        m = match()
        m.s["time"] = 900
        hero = m.unit(0, "mid")
        self.awaken(m, hero)
        for u in m.s["teams"][0]:
            u["pos"] = [5, 95]
        hero["pos"] = [50, 50]
        enemies = [m.unit(1, r) for r in ("mid", "top", "jng")]
        for u in m.s["teams"][1]:
            u["pos"] = [95, 5]
        for e in enemies:
            e["pos"] = [51, 50]
        m.rng.random = lambda: 0.0
        kills = m.s["kills"][0]
        m.encounter("lane", "mid", [hero], enemies, rounds=1)
        moments = [x for x in m.s["clutch_moments"] if x["kind"] == "outnumbered"]
        self.assertEqual(len(moments), 1)
        self.assertGreater(m.s["kills"][0], kills)
        self.assertTrue(hero["resolve"]["clutch_used"])
        self.assertEqual(m.s["highlights"][-1]["title"], "CLUTCH · 1대3 역전 처치")

    def test_clutch_rules_only_in_engine_7_matches(self):
        old = GameV6(CATALOG, CHAMPIONS, "no-clutch")
        for role in ROLES:
            old.apply({"type": "starter_open", "role": role})
        old.apply({"type": "starter_finish"})
        old.apply({"type": "start"})
        self.assertNotIn("clutch_rules", old.match.s)
        self.assertIn("clutch_rules", match().s)

    def test_full_match_replays_with_clutch_moments(self):
        a, b = match(31), match(31)
        a.simulate(), b.simulate()
        self.assertEqual(a.s, b.s)


if __name__ == "__main__":
    unittest.main()
