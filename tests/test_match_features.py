import copy
import unittest
from test_progression import game, lineup
from test_engine import CATALOG, CHAMPIONS
from engine import Game


def draft(g):
    g.apply({"type":"begin_draft"})
    while g.s["banpick"]["phase"] != "ready":
        phase=g.s["banpick"]["phase"]
        champion=next(c for c in sorted(g.champions) if c not in g.draft_taken())
        g.apply({"type":"ban_champion" if phase=="ban" else "pick_champion","champion":champion})


def finish_interactive(g):
    for _ in range(1500):
        if g.match.s["reports"]:
            g.apply({"type":"ack_report","report":g.match.s["reports"][0]["id"]})
        elif g.match.s["winner"] is not None:
            return
        elif g.match.s["event"]:
            g.apply({"type":"choose","option":"commit"})
        else:
            g.apply({"type":"tick","steps":12})
    raise AssertionError("interactive match did not complete")


class MatchFeatureTests(unittest.TestCase):
    def match(self):
        g=game();g.apply({"type":"start"});return g.match

    def test_single_and_area_attacks_log_actual_names_without_single_hit_count(self):
        m=self.match();caster=m.unit(0,"mid");target=m.unit(1,"mid")
        m.hit_chance=lambda *args:1
        m.protect=lambda victim,damage,*args:damage
        attack={"key":"AA","name":"기본 공격","tags":["damage"],"effects":{"damage":True}}
        result=m.cast_attack(caster,[target],[caster],"mid",forced=attack)
        self.assertEqual([t["name"] for t in result["targets"]],[target["name"]])
        log=m.s["log"][-1]["text"]
        self.assertIn(target["name"],log);self.assertNotIn("1명",log)
        for u in m.s["teams"][1]:u["frontline"]=False
        aoe={**attack,"name":"광역 테스트","effects":{"damage":True,"aoe":True,"max_targets":3}}
        result=m.cast_attack(caster,m.s["teams"][1],[caster],"river",forced=aoe)
        self.assertEqual(len(result["targets"]),3)
        for t in result["targets"]:self.assertIn(t["name"],m.s["log"][-1]["text"])

    def test_enemy_carry_focus_requires_breach_and_cannot_aoe_through_blockers(self):
        m=self.match();caster=m.unit(1,"mid");front=m.unit(0,"top");carry=m.unit(0,"bot")
        front.update(frontline=True,hp=100,cc_strength=0);carry.update(frontline=False,gold=20000)
        spell={"key":"AA","tags":["damage"],"effects":{"aoe":True}}
        m.rng.random=lambda: .99
        primary,reachable,note=m.select_combat_target(caster,[front,carry],spell,"mid")
        self.assertIs(primary,front);self.assertNotIn(carry,reachable);self.assertIn("차단",note)
        m.rng.random=lambda:0
        primary,reachable,note=m.select_combat_target(caster,[front,carry],spell,"mid")
        self.assertIs(primary,carry);self.assertIn(carry,reachable);self.assertEqual(note,"전열 돌파")
        front["hp"]=20
        m.rng.random=lambda:.99
        self.assertIs(m.select_combat_target(caster,[front,carry],spell,"mid")[0],carry)

    def test_player_front_rear_strategy_changes_targets(self):
        m=self.match();caster=m.unit(0,"mid");front=m.unit(1,"top");rear=m.unit(1,"bot")
        front.update(frontline=True,hp=100);rear.update(frontline=False,gold=20000)
        spell={"key":"AA","tags":[]}
        m.rng.random=lambda:0
        self.assertIs(m.select_combat_target(caster,[front,rear],spell,"mid")[0],front)
        m.s["target_focus"]="rear"
        self.assertIs(m.select_combat_target(caster,[front,rear],spell,"mid")[0],rear)

    def test_three_v_three_report_names_participants_and_stops_interactive_clock(self):
        m=self.match();m.s["interactive"]=True
        m.encounter("teamfight","river",m.s["teams"][0][:3],m.s["teams"][1][:3],rounds=1)
        report=m.s["reports"][0]
        self.assertIn("3대3",report["title"])
        self.assertEqual(len(report["fight"]["participants"][0]),3)
        before=copy.deepcopy(m.s);rng=m.rng.state
        m.step();self.assertEqual(m.s,before);self.assertEqual(m.rng.state,rng)

    def test_streak_resets_on_death_keeps_peak_and_awards_use_actual_metrics(self):
        m=self.match();attacker=m.unit(0,"bot");victim=m.unit(1,"mid")
        for _ in range(5):
            victim.update(status="active",hp=10)
            m.kill_unit(attacker,victim,[attacker])
        self.assertEqual(attacker["kill_streak"],5)
        m.kill_unit(m.unit(1,"bot"),attacker,m.s["teams"][1])
        self.assertEqual(attacker["kill_streak"],0);self.assertEqual(attacker["peak_streak"],5)
        self.assertIn("5연속 킬 종료",m.s["highlights"][-1]["detail"])
        m.s["winner"]=0;m.finish_awards();award=copy.deepcopy(m.s["player_of_match"])
        self.assertEqual(award["card_id"],attacker["card_id"])
        m.finish_awards();self.assertEqual(m.s["player_of_match"],award)

    def test_lane_kill_choice_is_real_encounter_and_alternative_has_exact_reward(self):
        m=self.match();m.s["time"]=350;m.s["tick"]=350
        a,b=m.unit(0,"top"),m.unit(1,"top")
        a.update(hp=100,location="top",status="active");b.update(hp=50,location="top",status="active")
        m.encounter("lane","top",[a],[b],rounds=0)
        self.assertEqual(m.s["event"]["kind"],"lane_kill")
        before=a["gold"];m.rng.random=lambda:0
        m.choose("trade")
        self.assertEqual(a["gold"]-before,120)
        self.assertIn("+120G",m.s["decisions"][-1]["outcome"])
        self.assertNotIn("반영됩니다",m.s["reports"][-1]["detail"])
        # A separate pursuit actually attacks, so the result can be kills or escapes.
        m.s.update(time=650,tick=650);b.update(hp=50,status="active",location="top")
        m.encounter("lane","top",[a],[b],rounds=0)
        m.choose("commit")
        self.assertEqual(m.s["last_encounter"]["kind"],"lane_finish")
        self.assertTrue(m.s["last_encounter"]["casts"])

    def test_draft_six_bans_ten_unique_picks_and_opponent_uses_its_picks(self):
        g=game();draft(g);d=copy.deepcopy(g.s["banpick"])
        self.assertEqual([len(b) for b in d["bans"]],[3,3])
        self.assertEqual(len(g.draft_taken()),16)
        self.assertEqual(g.view(),Game.import_save(g.export_save(),CATALOG,CHAMPIONS).view())
        g.apply({"type":"start"})
        for side in (0,1):
            self.assertEqual({u["role"]:u["champion"] for u in g.match.s["teams"][side]},d["picks"][side])
        self.assertTrue(g.match.s["interactive"])

    def test_partial_draft_replay_invalid_bans_and_roster_locks_are_atomic(self):
        g=game();g.apply({"type":"begin_draft"});g.apply({"type":"ban_champion","champion":"Ahri"})
        before=g.view();save=g.export_save()
        for action in ({"type":"ban_champion","champion":"Ahri"},{"type":"pick_champion","champion":"Jinx"},
                       {"type":"equip","card":g.s["owned"][0]},{"type":"start"},{"type":"begin_draft"}):
            with self.assertRaises(ValueError):g.apply(action)
            self.assertEqual(g.view(),before);self.assertEqual(g.export_save(),save)
        replay=Game.import_save(save,CATALOG,CHAMPIONS)
        self.assertEqual(g.view(),replay.view())

    def test_popup_ack_and_full_interactive_match_save_replay(self):
        g=game("interactive-save");draft(g);g.apply({"type":"start"})
        for _ in range(60):
            if g.match.s["reports"]:break
            if g.match.s["event"]:g.apply({"type":"choose","option":"commit"})
            else:g.apply({"type":"tick","steps":12})
        self.assertTrue(g.match.s["reports"])
        before=g.view()
        with self.assertRaises(ValueError):g.apply({"type":"ack_report","report":-1})
        self.assertEqual(g.view(),before)
        g.apply({"type":"target_focus","focus":"rear"})
        self.assertEqual(g.view(),Game.import_save(g.export_save(),CATALOG,CHAMPIONS).view())
        finish_interactive(g)
        self.assertIsNotNone(g.match.s["player_of_match"])
        self.assertTrue(g.match.s["highlights"])
        self.assertTrue(g.s["last_growth"])
        self.assertEqual(g.view(),Game.import_save(g.export_save(),CATALOG,CHAMPIONS).view())

    def test_interactive_slow_and_fast_ticks_replay_same_result(self):
        results=[]
        for speed in (1,12):
            g=game("interactive-speeds");draft(g);g.apply({"type":"start"})
            for _ in range(6000):
                if g.match.s["reports"]:g.apply({"type":"ack_report","report":g.match.s["reports"][0]["id"]})
                elif g.match.s["winner"] is not None:break
                elif g.match.s["event"]:g.apply({"type":"choose","option":"vision"})
                else:g.apply({"type":"tick","steps":speed})
            self.assertIsNotNone(g.match.s["winner"])
            self.assertLess(len(g.actions),600)
            self.assertEqual(g.view(),Game.import_save(g.export_save(),CATALOG,CHAMPIONS).view())
            results.append(g.match.s)
        self.assertEqual(*results)

    def test_outcome_does_not_claim_an_existing_objective_attempt_as_new(self):
        m=self.match();m.s["time"]=500
        m.s["objective_attempt"]={"side":0,"kind":"dragon","finish_at":510}
        before=m.outcome_snapshot()
        self.assertNotIn("사냥 개시",m.outcome_summary(before))
        m.s["objective_attempt"]={"side":1,"kind":"herald","finish_at":520}
        self.assertIn("상대 전령 사냥 개시",m.outcome_summary(before))


if __name__ == "__main__":unittest.main()
