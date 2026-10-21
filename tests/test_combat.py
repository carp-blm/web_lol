import copy
import gzip
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "web"), str(ROOT / "scripts")]
from engine import Game, Match, ROLES, RNG
from combat import CC
from build_site import runtime_archive, PYTHON_FILES
from skill_effects import enrich_effects
from legacy_engine_v2 import Game as GameV2

CARDS = json.loads((ROOT / "web/data/cards.json").read_text(encoding="utf8"))
CHAMPS = json.loads((ROOT / "web/data/champions.json").read_text(encoding="utf8"))


def game(cls=Game):
    g = cls(CARDS, CHAMPS, "persistent-tests")
    for role in ROLES:
        g.apply({"type": "starter_open", "role": role})
    g.apply({"type": "starter_finish"})
    return g


BASE = game()
BLUE = BASE.units([BASE.s["roster"][r] for r in ROLES], BASE.s["draft"])
RED = BASE.units(BASE.s["season"]["teams"][1]["roster"])


def match(seed=17):
    return Match(copy.deepcopy(BLUE), copy.deepcopy(RED), seed, CHAMPS["champions"])


def champion(m, side, role, cid):
    u = m.unit(side, role)
    u["champion"] = cid
    u["mastery"] = 90
    m.initialize_abilities()
    return u


class CombatTests(unittest.TestCase):
    def test_one_second_ticks_and_most_incidents_are_automatic(self):
        m = match()
        m.step()
        self.assertEqual(m.s["time"], 1)
        for _ in range(238): m.step()
        self.assertIsNone(m.s["event"])
        self.assertGreater(sum(m.s["encounter_counts"].values()), 5)
        self.assertTrue(any(l["kind"] in ("dodge", "recall", "fight") for l in m.s["log"]))
        m.step()
        self.assertIsNotNone(m.s["event"])
        before = copy.deepcopy(m.s), m.rng.state
        m.step()
        self.assertEqual(before, (m.s, m.rng.state))

    def test_bot_is_2v2_then_1v2_then_1v1_after_roams(self):
        m = match()
        self.assertEqual([len(m.lane_members(i, "bot")) for i in (0,1)], [2,2])
        m.start_roam(0)
        self.assertEqual([len(m.lane_members(i, "bot")) for i in (0,1)], [1,2])
        self.assertEqual([u["role"] for u in m.lane_members(0,"mid")], ["mid","sup"])
        m.start_roam(1)
        self.assertEqual([len(m.lane_members(i, "bot")) for i in (0,1)], [1,1])
        m.encounter("lane", "bot", m.lane_members(0,"bot"), m.lane_members(1,"bot"))
        self.assertEqual(m.s["last_encounter"]["sides"], [["bot"],["bot"]])

    def test_support_duels_are_extremely_rare(self):
        m = match(); occurrences = 0
        for _ in range(1000):
            if m.encounter("lane", "bot", [m.unit(0,"sup")], [m.unit(1,"sup")], rounds=0) is not None:
                occurrences += 1
        self.assertLess(occurrences, 15)

    def test_kill_and_recall_concede_growth_and_change_future_odds(self):
        m = match(); a,b=m.unit(0,"mid"),m.unit(1,"mid")
        before=m.encounter_odds([a],[b],"mid"); old_gold=a["gold"]
        m.kill_unit(a,b,[a]);m.waves()
        self.assertGreater(a["gold"], old_gold+300)
        self.assertEqual(b["cs"],0)
        self.assertEqual(b["status"],"dead")
        self.assertEqual(m.s["pressure"]["mid"],1)
        self.assertGreater(m.encounter_odds([a],[b],"mid"),before)
        a["hp"]=18;m.recall(a,"mid")
        self.assertEqual(m.lane_members(0,"mid"),[])
        self.assertGreater(a["return_at"],m.s["time"])

    def test_jungle_camp_spawn_steal_and_respawn(self):
        m=match()
        self.assertFalse(m.farm_camp(0,1,"top"))
        m.s["time"]=90
        self.assertTrue(m.farm_camp(0,1,"top"))
        self.assertEqual(m.s["camps"][1]["top"],210)
        self.assertFalse(m.farm_camp(1,1,"top"))
        m.s["time"]=210
        self.assertTrue(m.farm_camp(1,1,"top"))

    def test_all_jungle_encounters_occur_and_ganks_reach_all_lanes(self):
        kinds=set();lanes=set()
        for seed in range(1,12):
            m=match(seed)
            for _ in range(1500):
                if m.s["event"]:m.choose("trade")
                m.step()
                kinds.update(m.s["encounter_counts"])
                e=m.s["last_encounter"]
                if e and e["kind"]=="gank":lanes.add(e["lane"])
        self.assertTrue({"jungle_duel","counterjungle","gank","invade"}.issubset(kinds), kinds)
        self.assertEqual(lanes,{"top","mid","bot"})

    def test_solo_objective_has_duration_and_cannot_start_early(self):
        m=match()
        self.assertFalse(m.start_objective(0,"dragon",solo=True))
        m.s["time"]=300
        self.assertTrue(m.start_objective(0,"dragon",solo=True))
        self.assertEqual(m.s["objective_attempt"]["roles"],["jng"])
        m.resolve_objective();self.assertEqual(m.s["dragons"],[0,0])
        m.s["time"]=328
        rolls=iter([.99,0]);m.rng.random=lambda:next(rolls)
        m.resolve_objective()
        self.assertEqual(m.s["dragons"],[1,0])
        self.assertEqual(m.s["next_dragon"],628)
        self.assertLess(m.unit(0,"jng")["hp"],100)
        m.s["time"]=1200
        self.assertFalse(m.start_objective(0,"baron",solo=True))

    def test_measured_ward_rates_and_missing_fallback(self):
        covered=sum(bool(c["vision_stats"].get("wardsplaced",{}).get("samples")) for c in CARDS["cards"])
        self.assertGreater(covered,3000)
        self.assertTrue(CARDS["vision_revision"])
        high,low=match(),match()
        for m,value in ((high,4),(low,0)):
            for u in m.s["teams"][0]:
                u["vision_stats"]={k:{"per_minute":value}for k in ("wardsplaced","wardskilled","controlwardsbought")}
            for _ in range(10):m.ward_cycle()
        self.assertGreater(high.s["vision_actions"][0]["placed"],low.s["vision_actions"][0]["placed"])
        self.assertEqual(low.s["vision_actions"][0]["placed"],0)
        self.assertGreater(high.vision_at(0,"river"),low.vision_at(0,"river"))

    def test_vision_mastery_health_affect_hit_and_decision_odds(self):
        m=match();a,b=m.unit(0,"mid"),m.unit(1,"mid")
        before=m.hit_chance(a,b,"mid")
        m.s["local_vision"][0]["mid"]=8;a["mastery"]=95
        self.assertGreater(m.hit_chance(a,b,"mid"),before)
        m.make_event();p=m.s["event"]["options"][0]["chance"]
        for u in m.s["teams"][1]:u["hp"]=10
        m.make_event();self.assertGreater(m.s["event"]["options"][0]["chance"],p)

    def test_cc_order_blind_adc_and_cc_reduces_fighting_power(self):
        self.assertTrue(CC["blind"]<CC["slow"]<CC["root"]<CC["polymorph"]<=CC["stun"]<CC["airborne"]==CC["suppression"])
        m=match();adc=champion(m,1,"bot","Ashe");melee=champion(m,1,"top","Garen")
        blind={"effects":{"cc":["blind"]}}
        self.assertGreater(m.cc_value(blind,adc),m.cc_value(blind,melee))
        before=m.strength(adc);adc.update(cc_until=10,cc_strength=CC["stun"])
        self.assertLess(m.strength(adc),before*.8)

    def test_defense_targeting_and_form_specific_effects(self):
        m=match();s=champion(m,0,"sup","Soraka");ally=m.unit(0,"bot")
        self.assertTrue(any(sp["key"]=="W" for sp,_ in m.protective_spells(s,ally)))
        self.assertFalse(any(sp["key"]=="W" for sp,_ in m.protective_spells(s,s)))
        selfish=champion(m,0,"top","Riven")
        self.assertFalse(list(m.protective_spells(selfish,ally)))
        nid=champion(m,0,"jng","Nidalee")
        self.assertTrue(any(sp["key"]=="E" for sp,_ in m.protective_spells(nid,ally)))
        m.set_form(nid,"cougar")
        self.assertFalse(list(m.protective_spells(nid,ally)))
        self.assertEqual(next(s for s in CHAMPS["champions"]["Morgana"]["variants"] if s["key"]=="E")["effects"]["cc"],[])

    def test_form_specific_cc_and_first_target_projectiles(self):
        def effects(cid, sid):
            return next(s["effects"] for s in CHAMPS["champions"][cid]["variants"] if s["id"]==sid)
        self.assertEqual(effects("KSante","KSante:allout:W")["cc"],[])
        self.assertEqual(effects("Vi","Vi:base:Q")["cc"],["airborne"])
        self.assertEqual(effects("XinZhao","XinZhao:base:R")["cc"],["airborne"])
        self.assertEqual(effects("Jayce","Jayce:cannon:Q")["cc"],[])
        self.assertEqual(effects("Qiyana","Qiyana:wall:Q")["cc"],[])
        self.assertIn("root",effects("Qiyana","Qiyana:river:Q")["cc"])
        self.assertEqual(effects("Aphelios","Aphelios:gravitum:Q")["cc"],["root"])
        self.assertFalse(effects("Ahri","Ahri:base:E")["aoe"])
        self.assertEqual(effects("Lux","Lux:base:Q")["max_targets"],2)

    def test_rare_ally_lifesave_requires_available_correct_skill(self):
        m=match();u=champion(m,0,"sup","Zilean");victim=m.unit(0,"bot")
        m.s["time"]=400;victim["hp"]=5;m.rng.random=lambda:0
        self.assertEqual(m.protect(victim,100,[u,victim]),0)
        self.assertEqual(u["saves"],1)
        self.assertGreater(u["cooldowns"]["R"],400)
        m.s["time"]=404;victim["hp"]=5
        self.assertEqual(m.protect(victim,100,[u]),100)
        self.assertEqual(u["saves"],1)

    def test_aoe_hits_vary_and_cc_hits_every_target_actually_hit(self):
        counts=set()
        for seed in range(1,31):
            m=match(seed);u=champion(m,0,"top","Gnar");m.s["time"]=700;m.set_form(u,"mega")
            spell=next(s for s in m.ready_skills(u) if s["key"]=="R")
            result=m.cast_attack(u,m.s["teams"][1],[u],"river",forced=spell)
            counts.add(result["hits"])
            self.assertEqual(sum(t["cc_until"]>700 for t in m.s["teams"][1]),result["hits"])
        self.assertGreater(len(counts),2)
        self.assertTrue(all(0<=n<=5 for n in counts))

    def test_slow_ticks_coalesce_without_changing_replay(self):
        g=game();g.apply({"type":"start"})
        for _ in range(120):g.apply({"type":"tick"})
        self.assertEqual(g.actions[-1],{"type":"tick","steps":120})
        self.assertEqual(g.view(),Game.import_save(g.export_save(),CARDS,CHAMPS).view())

    def test_v2_partial_starter_and_inflight_match_migrate_exactly(self):
        g=GameV2(CARDS,CHAMPS,"old-packs");g.apply({"type":"starter_open","role":"top"})
        upgraded=Game.import_save(g.export_save(),CARDS,CHAMPS)
        self.assertEqual(upgraded.s["starter"],g.s["starter"])
        old=game(GameV2);old.apply({"type":"start"});old.apply({"type":"tick","steps":3})
        upgraded=Game.import_save(old.export_save(),CARDS,CHAMPS)
        self.assertEqual(upgraded.match.s,old.match.s)
        upgraded.apply({"type":"tick","steps":2});old.apply({"type":"tick","steps":2})
        self.assertEqual(upgraded.match.s,old.match.s)
        self.assertEqual(upgraded.view(),Game.import_save(upgraded.export_save(),CARDS,CHAMPS).view())

    def test_effect_build_and_minimized_runtime_are_reproducible(self):
        details=json.loads(gzip.decompress((ROOT/"data/champion_details.json.gz").read_bytes()))
        self.assertEqual(CHAMPS,enrich_effects(CHAMPS,details))
        first=runtime_archive();self.assertEqual(first,runtime_archive())
        with zipfile.ZipFile(io.BytesIO(first)) as z:
            self.assertEqual(set(z.namelist()),set(PYTHON_FILES))
            for name in z.namelist():compile(z.read(name),name,"exec")
        self.assertLess(len(first),sum((ROOT/"web"/p).stat().st_size for p in PYTHON_FILES)/3)


if __name__ == "__main__":unittest.main()
