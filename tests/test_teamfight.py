import collections
import re
import unittest
from test_clutch import match
from test_management import game
from engine import Match, ROLES
from legacy_engine_v6 import Match as MatchV6
from teamfight import TeamfightRules, SustainedComboRules, ACT_ORDER, EARLY_DAMAGE, EARLY_UNTIL, TEAMFIGHT_SIZE


def gather(m, roles, point=(50, 50)):
    """Put the given roles of both teams on one spot, healthy and ready to fight."""
    groups = []
    for side in (0, 1):
        group = [m.unit(side, role) for role in roles]
        for u in group:
            u.update(pos=list(point), location="river", status="active", hp=100, combo_ready_at=0, encounter_at=0)
        groups.append(group)
    m.s["time"] = 1500
    return groups


class ActingOrderTests(unittest.TestCase):
    def test_support_opens_and_carries_finish(self):
        m = match()
        team = m.s["teams"][0]
        first, last = collections.Counter(), collections.Counter()
        for _ in range(400):
            order = m.action_order(team)
            self.assertEqual(sorted(u["role"] for u in order), sorted(ROLES))
            first[order[0]["role"]] += 1
            last[order[-1]["role"]] += 1
        self.assertEqual(first.most_common(1)[0][0], "sup")
        self.assertEqual(last.most_common(1)[0][0], "bot")
        self.assertLess(last["sup"], 20)
        self.assertGreater(len(last), 2)
        self.assertEqual(min(ACT_ORDER, key=ACT_ORDER.get), "sup")

    def test_order_is_reproducible_from_the_seed(self):
        a, b = match(11), match(11)
        orders = [[[u["role"] for u in m.action_order(m.s["teams"][side])] for side in (0, 1, 0)] for m in (a, b)]
        self.assertEqual(orders[0], orders[1])


class SustainedFightTests(unittest.TestCase):
    def casts_per_player(self, roles):
        m = match()
        blue, red = gather(m, roles)
        m.encounter("teamfight", "river", blue, red, rounds=1)
        self.assertFalse(m.sustained_fight)
        casts = collections.Counter((c["side"], c["caster"]) for c in m.s["last_encounter"]["casts"])
        return m, casts

    def test_teamfight_runs_several_exchanges(self):
        roles = ROLES[:TEAMFIGHT_SIZE+1]
        m, casts = self.casts_per_player(roles)
        # More casts than a single four-step combo means a later exchange really happened.
        self.assertGreater(max(casts.values()), 4)

    def test_small_fight_stays_one_combo_each(self):
        m, casts = self.casts_per_player(("mid",))
        self.assertLessEqual(max(casts.values()), 4)
        self.assertGreater(m.unit(0, "mid")["combo_ready_at"], m.s["time"])

    def test_early_damage_ramps_to_full(self):
        m = match()
        m.s["time"] = 0
        self.assertAlmostEqual(m.early_damage_scale(), EARLY_DAMAGE)
        m.s["time"] = EARLY_UNTIL//2
        self.assertAlmostEqual(m.early_damage_scale(), (1+EARLY_DAMAGE)/2)
        m.s["time"] = EARLY_UNTIL*3
        self.assertEqual(m.early_damage_scale(), 1)

    def test_early_scale_applies_to_attacks_only(self):
        m = match()
        m.s["time"] = 0
        victim = m.unit(1, "mid")
        victim["protected_until"] = 0
        self.assertEqual(m.protect(victim, 40, []), 40)
        m.attacking = True
        self.assertAlmostEqual(m.protect(victim, 40, []), 40*EARLY_DAMAGE)


class FightScopeAndDistributionTests(unittest.TestCase):
    def test_only_the_current_engine_uses_fight_rules(self):
        self.assertIn(TeamfightRules, Match.__mro__)
        self.assertIn(SustainedComboRules, Match.__mro__)
        self.assertNotIn(TeamfightRules, MatchV6.__mro__)
        self.assertNotIn(SustainedComboRules, MatchV6.__mro__)

    def test_kill_distribution_by_role_and_fight_size(self):
        g = game("fight-distribution")
        kills, teamfights = collections.Counter(), collections.Counter()
        for i in range(30):
            m = Match(g.units(g.random_roster(68)), g.units(g.random_roster(68)), 4200+i, g.champions)
            m.simulate()
            for team in m.s["teams"]:
                for u in team:
                    kills[u["role"]] += u["kills"]
            for h in m.s["highlights"]:
                if h["kind"] == "teamfight":
                    teamfights[min(2, sum(int(n) for n in re.findall(r"(\d+)킬", h["detail"])))] += 1
        share = {role: kills[role]/sum(kills.values()) for role in ROLES}
        self.assertLess(share["sup"], .12, share)
        self.assertLess(share["sup"], share["bot"]/2, share)
        self.assertGreater(share["top"], .09, share)
        self.assertGreater(share["mid"]+share["bot"], .45, share)
        self.assertGreater(sum(teamfights.values()), 40)
        self.assertGreater(teamfights[2]/sum(teamfights.values()), .3, teamfights)


if __name__ == "__main__":
    unittest.main()
