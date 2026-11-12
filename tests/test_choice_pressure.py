import unittest
from unittest import mock
from test_clutch import match, behind
from legacy_engine_v6 import Match as MatchV6
import clutch
from clutch import (ClutchRules, CHOICE_PRESSURE, CHOICE_SCALE, OUTNUMBERED_STAKES, PASSIVE_STEP, PASSIVE_CAP,
                    AWAKEN_POWER, SHAKEN_POWER, AWAKEN_DECAY, RESOLVE_FLOOR, AWAKEN_RELIEF, SHAKEN_DOUBT)

POINT = [50, 50]


def scene(blue=("mid", "jng"), red=("mid", "jng"), kind="skirmish", lead="mid", seed=7):
    """A paused decision at one spot. Everyone starts at pressure 50 with no trait modifiers."""
    m = match(seed)
    m.s["time"] = 900
    for team in m.s["teams"]:
        for u in team:
            u.update(pos=[5, 5] if u["side"] == 0 else [95, 95], pressure=50, traits=[], hp=100, status="active")
    for side, roles in ((0, blue), (1, red)):
        for role in roles:
            m.unit(side, role).update(pos=list(POINT), location="mid")
    m.s["event"] = {"id": "test", "kind": kind, "title": "테스트", "lane": "mid", "role": lead, "position": list(POINT),
                    "objective": None, "relic_bonus": 0, "used_relics": [],
                    "options": [{"id": i, "label": i, "chance": .5, "detail": ""} for i in
                                (("commit", "trade", "vision") if kind == "lane_kill" else ("commit", "vision", "trade", "disengage"))]}
    return m


def call(m, option, success):
    for o in m.s["event"]["options"]:
        o["chance"] = 1 if success else 0
    # The follow-up fight has its own pressure effects (deaths, kills); keep the call's effect isolated.
    with mock.patch.object(type(m), "encounter", lambda self, *a, **k: None):
        m.choose(option)
    return m.s["decisions"][-1]["pressure"]


def change(m, side, role):
    return round(m.unit(side, role)["pressure"]-50, 1)


class ChoicePressureTests(unittest.TestCase):
    def table(self, group, choice, outcome):
        return tuple(v*CHOICE_SCALE for v in CHOICE_PRESSURE[group][(choice, outcome)])

    def test_commit_success_and_failure_move_lead_allies_and_enemies(self):
        for success, outcome in ((True, "success"), (False, "fail")):
            m = scene()
            record = call(m, "commit", success)
            lead, allies, enemies = self.table("general", "commit", outcome)
            self.assertEqual(record["outcome"], outcome)
            self.assertEqual(change(m, 0, "mid"), lead)
            self.assertEqual(change(m, 0, "jng"), allies)
            self.assertEqual(change(m, 1, "mid"), enemies)
            self.assertEqual(change(m, 1, "jng"), enemies)
            # Players away from the call are untouched.
            self.assertEqual(change(m, 0, "top"), 0)
            self.assertEqual(change(m, 1, "bot"), 0)

    def test_outnumbered_commit_raises_the_stakes_for_our_side_only(self):
        m = scene(blue=("mid",), red=("mid", "jng", "sup"))
        record = call(m, "commit", False)
        lead, _, enemies = self.table("general", "commit", "fail")
        self.assertTrue(record["outnumbered"])
        self.assertEqual(change(m, 0, "mid"), lead*OUTNUMBERED_STAKES)
        self.assertEqual(change(m, 1, "sup"), enemies)

    def test_retreat_is_judged_by_whether_there_was_a_reason(self):
        even = scene()
        self.assertEqual(call(even, "disengage", True)["outcome"], "avoidable")
        self.assertEqual(change(even, 0, "mid"), self.table("general", "disengage", "avoidable")[0])
        hurt = scene()
        hurt.unit(0, "jng")["hp"] = 30
        self.assertEqual(call(hurt, "disengage", True)["outcome"], "justified")
        outnumbered = scene(blue=("mid",), red=("mid", "jng"))
        self.assertEqual(call(outnumbered, "disengage", True)["outcome"], "justified")
        self.assertEqual(change(outnumbered, 0, "mid"), self.table("general", "disengage", "justified")[0])

    def test_passive_calls_accumulate_on_the_lead_and_reset_on_commit(self):
        m = scene()
        base = self.table("general", "vision", "success")[0]
        extras = []
        for _ in range(5):
            m.unit(0, "mid")["pressure"] = 50
            m.s["event"] = scene().s["event"]
            call(m, "vision", True)
            extras.append(round(change(m, 0, "mid")-base, 1))
        self.assertEqual(extras, [min(PASSIVE_CAP, PASSIVE_STEP*i) for i in range(5)])
        m.s["event"] = scene().s["event"]
        call(m, "commit", True)
        self.assertEqual(m.s["passive_calls"], 0)

    def test_lane_kill_distinguishes_a_kill_from_a_chase_that_came_up_empty(self):
        m = scene(kind="lane_kill")
        for u in m.s["teams"][0]+m.s["teams"][1]:
            if u["role"] == "mid":
                u["pos"] = list(m.lane_point("mid", u["side"], "mid"))
        self.assertEqual(call(m, "commit", True)["outcome"], "success")
        m2 = scene(kind="lane_kill")
        with mock.patch.object(type(m2), "encounter", lambda self, *a, **k: self.s["kills"].__setitem__(0, self.s["kills"][0]+1)):
            for o in m2.s["event"]["options"]:
                o["chance"] = 1
            m2.choose("commit")
        self.assertEqual(m2.s["decisions"][-1]["pressure"]["outcome"], "kill")

    def test_trait_modifiers_apply_to_rises_only(self):
        m = scene()
        m.unit(0, "mid")["traits"] = ["clutch"]
        call(m, "commit", False)
        self.assertEqual(change(m, 0, "mid"), round(self.table("general", "commit", "fail")[0]*.7, 1))
        m = scene()
        m.unit(0, "mid")["traits"] = ["clutch"]
        call(m, "commit", True)
        self.assertEqual(change(m, 0, "mid"), self.table("general", "commit", "success")[0])

    def test_effect_is_hidden_and_draws_no_random_numbers(self):
        a, b = scene(), scene()
        with mock.patch.object(clutch, "CHOICE_SCALE", 0), mock.patch.object(clutch, "PASSIVE_STEP", 0):
            call(b, "commit", False)
        call(a, "commit", False)
        self.assertEqual(a.rng.state, b.rng.state)
        strip = lambda m: [{k: v for k, v in u.items() if k != "pressure"} for t in m.s["teams"] for u in t]
        self.assertEqual(strip(a), strip(b))
        self.assertNotEqual(change(a, 0, "mid"), change(b, 0, "mid"))
        shown = [l["text"] for l in a.s["log"]]+[r["title"]+r["detail"] for r in a.s["reports"]]
        shown += [h["title"]+h["detail"] for h in a.s["highlights"]]+[a.s["decisions"][-1]["outcome"]]
        self.assertFalse([text for text in shown if "압박" in text])

    def test_only_the_current_engine_has_choice_pressure(self):
        self.assertIs(type(match()).choose, ClutchRules.choose)
        self.assertNotIn(ClutchRules, MatchV6.__mro__)


class ResolveImpactTests(unittest.TestCase):
    def force(self, awaken):
        m = behind(match())
        u = m.unit(0, "mid")
        for mate in m.s["teams"][0]:
            mate.update(pos=list(POINT), pressure=40, traits=[], status="active", hp=100, resolve_chance=.5)
        u["resolve_chance"], u["pressure"] = (1.0 if awaken else 0.0), 100
        before = super(ClutchRules, m).strength(u)
        m.resolve_check(u)
        return m, u, before

    def test_resolve_scales_fighting_strength(self):
        m, u, before = self.force(True)
        self.assertGreater(m.strength(u), before*AWAKEN_POWER*.99)
        m, u, before = self.force(False)
        self.assertLess(m.strength(u), before*SHAKEN_POWER*1.01)
        self.assertGreater(m.strength(u), 0)

    def test_resolve_spreads_to_nearby_teammates(self):
        m, u, _ = self.force(True)
        self.assertEqual({mate["pressure"] for mate in m.s["teams"][0] if mate is not u}, {40+AWAKEN_RELIEF})
        m, u, _ = self.force(False)
        self.assertEqual({mate["pressure"] for mate in m.s["teams"][0] if mate is not u}, {40+SHAKEN_DOUBT})

    def test_each_awakening_lowers_the_teams_next_chance(self):
        m, u, _ = self.force(True)
        self.assertEqual(u["resolve_chance"], round(1.0-AWAKEN_DECAY, 2))
        self.assertEqual({mate["resolve_chance"] for mate in m.s["teams"][0] if mate is not u}, {round(.5-AWAKEN_DECAY, 2)})
        self.assertEqual({mate["resolve_chance"] for mate in m.s["teams"][1]},
                         {clutch.resolve_chance(mate) for mate in m.s["teams"][1]})
        for _ in range(10):
            other = m.unit(0, "top")
            other["resolve"], other["pressure"] = None, 100
            with mock.patch.object(m.rng, "random", lambda: 0):
                m.resolve_check(other)
        self.assertEqual({mate["resolve_chance"] for mate in m.s["teams"][0]}, {RESOLVE_FLOOR})

    def test_faltering_does_not_change_the_chance(self):
        m, u, _ = self.force(False)
        self.assertEqual({mate["resolve_chance"] for mate in m.s["teams"][0] if mate is not u}, {.5})


class DriftCeilingTests(unittest.TestCase):
    def losing(self):
        m = behind(match())
        m.s["time"] = 900
        for u in m.s["teams"][0]:
            u.update(traits=[], status="active", hp=100, pressure=0)
        return m

    def test_losing_alone_never_triggers_a_check(self):
        m = self.losing()
        for _ in range(200):
            m.update_pressure()
        self.assertEqual({u["pressure"] for u in m.s["teams"][0]}, {clutch.DRIFT_CEILING})
        self.assertFalse([c for c in m.s["clutch_moments"] if c["side"] == 0])

    def test_pressure_above_the_ceiling_eases_unless_a_check_is_pending(self):
        m = self.losing()
        m.s["team_resolve_at"][0] = 10**9
        over, pending = m.unit(0, "top"), m.unit(0, "mid")
        over["pressure"], pending["pressure"] = clutch.DRIFT_CEILING+10, 100
        m.update_pressure()
        self.assertEqual(over["pressure"], clutch.DRIFT_CEILING+10-clutch.OVER_CEILING_DECAY)
        self.assertEqual(pending["pressure"], 100)

    def test_a_death_or_a_failed_call_carries_a_player_over_the_ceiling(self):
        m = self.losing()
        victim = m.unit(0, "mid")
        victim["pressure"] = clutch.DRIFT_CEILING
        m.kill_unit(m.unit(1, "mid"), victim, [m.unit(1, "mid")])
        self.assertEqual(victim["pressure"], clutch.DRIFT_CEILING+clutch.DEATH_PRESSURE*clutch.EVENT_SCALE)
        s = scene()
        s.unit(0, "mid")["pressure"] = clutch.DRIFT_CEILING
        call(s, "commit", False)
        self.assertEqual(s.unit(0, "mid")["pressure"], 100)


if __name__ == "__main__":
    unittest.main()
