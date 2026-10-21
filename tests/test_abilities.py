import copy
import gzip
import json
import sys
import unittest
from test_engine import Game, Match, ROLES, ROOT, CATALOG, CHAMPIONS
sys.path.insert(0, str(ROOT / "scripts"))
from skill_variants import REGISTRY, enrich


def match_for(cid, opponent="Ahri"):
    g = Game(CATALOG, CHAMPIONS, "abilities")
    for role in ROLES:
        g.apply({"type": "starter_open", "role": role})
    g.apply({"type": "starter_finish"})
    blue = g.units([g.s["roster"][r] for r in ROLES])
    red = g.units(g.s["season"]["teams"][1]["roster"])
    blue[2]["champion"], red[2]["champion"] = cid, opponent
    m = Match(blue, red, 124, g.champions)
    return m, m.unit(0, "mid")


class AbilityTests(unittest.TestCase):
    def test_all_173_reviewed_and_no_combined_names_remain(self):
        self.assertEqual(CHAMPIONS["variant_audit"]["reviewed_champions"], 173)
        self.assertEqual(len(REGISTRY), 29)
        raw = json.loads(gzip.decompress((ROOT / "data/champion_details.json.gz").read_bytes()))
        for cid, c in CHAMPIONS["champions"].items():
            self.assertEqual([s["name"] for s in c["skills"][1:]], [s["name"] for s in raw["champions"][cid]["spells"]])
            self.assertEqual(len({s["id"] for s in c["variants"]}), len(c["variants"]))
            for s in c["variants"]:
                self.assertNotRegex(s["name"], r"[/|]")
                self.assertEqual(s["source_champion"], cid)
                self.assertTrue(s["source"].startswith("https://ddragon.leagueoflegends.com/"))

    def test_enrichment_is_deterministic_and_rejects_unreviewed_patch(self):
        a = enrich(CHAMPIONS)
        self.assertEqual(a, enrich(a))
        with self.assertRaises(ValueError):
            enrich({**CHAMPIONS, "version": "99.1.1"})

    def test_every_family_respects_form_and_never_casts_passive_or_selector(self):
        for cid in REGISTRY:
            m, unit = match_for(cid)
            m.s["time"] = 700
            for form in REGISTRY[cid]["forms"]:
                m.set_form(unit, form)
                before = copy.deepcopy(m.s), m.rng.state
                ready = m.ready_skills(unit)
                self.assertEqual(before, (m.s, m.rng.state))
                for spell in ready:
                    self.assertTrue(spell["castable"], (cid, form, spell))
                    self.assertNotEqual(spell["key"], "P")
                    self.assertEqual(spell["form"], form)

    def test_nidalee_forms_and_independent_cooldowns(self):
        m, u = match_for("Nidalee")
        q = next(s for s in m.ready_skills(u) if s["key"] == "Q")
        self.assertEqual(q["name"], "창 투척")
        m.spend_skill(u, q)
        m.set_form(u, "cougar")
        self.assertEqual(next(s for s in m.ready_skills(u) if s["key"] == "Q")["name"], "숨통 끊기")
        self.assertNotIn("R", [s["key"] for s in m.ready_skills(u)])

    def test_gnar_mega_r_only_and_mini_w_passive(self):
        m, u = match_for("Gnar");m.s["time"] = 600
        self.assertEqual({s["key"] for s in m.ready_skills(u)}, {"Q", "E"})
        m.set_form(u, "mega")
        self.assertEqual({s["name"] for s in m.ready_skills(u)}, {"돌덩이 던지기", "쿵쾅", "우지끈", "나르!"})

    def test_kled_dismount_and_remount(self):
        m, u = match_for("Kled");m.s["time"] = 600
        foe = m.unit(1, "mid")
        m.after_encounter(foe, u, True);m.after_encounter(foe, u, True)
        self.assertEqual(u["ability_state"]["form"], "unmounted")
        self.assertEqual([(s["key"], s["name"]) for s in m.ready_skills(u)], [("Q", "빵야!")])
        u["ability_state"]["resource"] = 99
        m.advance_forms(10)
        self.assertEqual(u["ability_state"]["form"], "mounted")

    def test_rell_w_changes_form_then_shares_cooldown(self):
        m, u = match_for("Rell")
        w = next(s for s in m.ready_skills(u) if s["key"] == "W")
        self.assertEqual(w["name"], "철마술: 붕괴")
        m.spend_skill(u, w)
        self.assertEqual(u["ability_state"]["form"], "dismounted")
        self.assertNotIn("W", [s["key"] for s in m.ready_skills(u)])
        m.s["time"] = 40
        w = next(s for s in m.ready_skills(u) if s["key"] == "W")
        self.assertEqual(w["name"], "철마술: 탑승")
        m.spend_skill(u, w)
        self.assertEqual(u["ability_state"]["form"], "mounted")

    def test_hwei_nine_spells_share_topic_cooldown(self):
        m, u = match_for("Hwei")
        ready = m.ready_skills(u)
        self.assertEqual(len(ready), 9)
        self.assertEqual({s["display_key"] for s in ready}, {"QQ","QW","QE","WQ","WW","WE","EQ","EW","EE"})
        m.spend_skill(u, next(s for s in ready if s["display_key"] == "QE"))
        self.assertNotIn("Q", [s["key"] for s in m.ready_skills(u)])
        self.assertEqual(len(m.ready_skills(u)), 6)

    def test_aphelios_weapon_q_and_no_castable_e(self):
        m, u = match_for("Aphelios");m.s["time"] = 600
        names = []
        for _ in range(5):
            ready = m.ready_skills(u)
            names.append(next(s for s in ready if s["key"] == "Q")["name"])
            self.assertNotIn("E", [s["key"] for s in ready])
            m.consume_ammo(u, 50)
        self.assertEqual(set(names), {"달빛탄", "맹공", "속박의 월식", "황혼파", "파수탑"})

    def test_named_recasts_require_first_cast(self):
        for cid, key in (("LeeSin","Q"),("LeeSin","W"),("LeeSin","E"),("Ambessa","Q"),
                         ("Briar","W"),("Fizz","E"),("Skarner","Q"),("Sylas","E"),("Riven","R"),("Swain","R")):
            m,u=match_for(cid);m.s["time"]=600
            first=next(s for s in m.ready_skills(u) if s["key"]==key)
            self.assertEqual(first["stage"],1)
            m.spend_skill(u,first)
            second=next(s for s in m.ready_skills(u) if s["key"]==key)
            self.assertEqual(second["stage"],2)
            self.assertNotEqual(first["name"],second["name"])
            m.spend_skill(u,second)
            if cid!="Swain":
                self.assertNotIn(key,[s["key"] for s in m.ready_skills(u)])
            m.s["time"]=800
            self.assertEqual(next(s for s in m.ready_skills(u) if s["key"]==key)["stage"],1)

    def test_briar_e_clears_w_recast(self):
        m,u=match_for("Briar")
        m.spend_skill(u,next(s for s in m.ready_skills(u) if s["key"]=="W"))
        m.spend_skill(u,next(s for s in m.ready_skills(u) if s["key"]=="E"))
        self.assertNotIn("W",[s["key"] for s in m.ready_skills(u)])

    def test_empowerment_is_consumed_once(self):
        for cid in ("Karma","Heimerdinger"):
            m,u=match_for(cid);m.s["time"]=400;m.advance_forms(30)
            self.assertEqual(u["ability_state"]["form"],"empowered")
            q=next(s for s in m.ready_skills(u) if s["key"]=="Q")
            m.spend_skill(u,q)
            self.assertEqual(u["ability_state"]["form"],"normal")
            self.assertGreater(u["cooldowns"]["R"],m.s["time"])

    def test_udyr_r_is_basic_and_awakens_current_stance(self):
        m,u=match_for("Udyr")
        r=next(s for s in m.ready_skills(u) if s["key"]=="R")
        m.spend_skill(u,r);m.s["time"]=100;m.advance_forms(30)
        self.assertEqual(u["ability_state"]["form"],"awakened")
        self.assertEqual([s["key"] for s in m.ready_skills(u)],["R"])
        m.spend_skill(u,m.ready_skills(u)[0])
        self.assertEqual(u["ability_state"]["form"],"normal")

    def test_kayn_transformation_permanent_and_ksante_w_no_cc(self):
        m,u=match_for("Kayn");m.s["time"]=600;m.advance_forms(30)
        form=u["ability_state"]["form"];self.assertIn(form,("shadow","darkin"))
        m.s["time"]=1800;m.advance_forms(1200)
        self.assertEqual(u["ability_state"]["form"],form)
        m,u=match_for("KSante");m.set_form(u,"allout")
        self.assertNotIn("cc",next(s for s in m.ready_skills(u) if s["key"]=="W")["tags"])

    def test_leblanc_mimics_last_basic(self):
        m,u=match_for("Leblanc");m.s["time"]=400
        self.assertNotIn("R",[s["key"] for s in m.ready_skills(u)])
        m.spend_skill(u,next(s for s in m.ready_skills(u) if s["key"]=="E"))
        r=next(s for s in m.ready_skills(u) if s["key"]=="R")
        self.assertEqual((r["name"],r["display_key"]),("환영 사슬","RE"))

    def test_viego_copies_victim_form_basics_but_own_r(self):
        m,u=match_for("Viego","Nidalee");m.s["time"]=500
        foe=m.unit(1,"mid");m.set_form(foe,"cougar")
        m.after_encounter(u,foe,True)
        ready=m.ready_skills(u)
        self.assertEqual(next(s["name"] for s in ready if s["key"]=="Q"),"숨통 끊기")
        r=next(s for s in ready if s["key"]=="R")
        self.assertEqual(r["name"],"심장 파괴자")
        m.spend_skill(u,r);self.assertIsNone(u["ability_state"]["borrowed"])

    def test_sylas_steals_enemy_r_and_transform_kit(self):
        m,u=match_for("Sylas","Ahri");m.s["time"]=500
        m.steal_ultimate(u,m.unit(1,"mid"))
        r=next(s for s in m.ready_skills(u) if s["key"]=="R")
        self.assertEqual((r["name"],r["source_champion"]),("혼령 질주","Ahri"))
        m.spend_skill(u,r)
        self.assertIsNone(u["ability_state"]["stolen"])
        m,u=match_for("Sylas","Nidalee");m.s["time"]=500
        m.steal_ultimate(u,m.unit(1,"mid"))
        self.assertEqual(next(s["name"] for s in m.ready_skills(u) if s["key"]=="Q"),"숨통 끊기")
        self.assertNotIn("R",[s["key"] for s in m.ready_skills(u)])

    def test_each_exception_family_can_finish_a_seeded_match(self):
        for cid in REGISTRY:
            m,u=match_for(cid)
            winner=m.simulate()
            self.assertEqual(m.s["nexus"][1-winner],0,cid)

    def test_borrowed_skills_change_and_consume_the_borrowed_state(self):
        for cid, form, key, expected in [
            ("Rell", "mounted", "W", "dismounted"),
            ("Karma", "empowered", "Q", "normal"),
            ("Heimerdinger", "empowered", "Q", "normal"),
            ("Qiyana", "river", "Q", "base"),
            ("Rengar", "empowered", "Q", "normal"),
            ("Udyr", "awakened", "Q", "normal"),
        ]:
            m, u = match_for("Viego", cid)
            m.s["time"] = 500
            foe = m.unit(1, "mid")
            m.set_form(foe, form)
            foe["ability_state"]["last_basic"] = key
            m.after_encounter(u, foe, True)
            ready = m.ready_skills(u)
            if cid == "Udyr":
                self.assertEqual({s["key"] for s in ready}, {"Q", "R"})
            m.spend_skill(u, next(s for s in ready if s["key"] == key))
            self.assertEqual(u["ability_state"]["borrowed"]["state"]["form"], expected, cid)
            self.assertEqual(u["ability_state"]["form"], "base")
            self.assertIn("R", [s["key"] for s in m.ready_skills(u)], cid)
            self.assertEqual(foe["ability_state"]["form"], form)

    def test_sylas_keeps_stolen_ultimate_recasts_until_used_or_expired(self):
        for cid, second_name in [("Riven", "바람 가르기"), ("Swain", "악의 불길")]:
            m, u = match_for("Sylas", cid)
            m.s["time"] = 500
            m.steal_ultimate(u, m.unit(1, "mid"))
            first = next(s for s in m.ready_skills(u) if s["key"] == "R")
            self.assertEqual(first["stage"], 1)
            m.spend_skill(u, first)
            second = next(s for s in m.ready_skills(u) if s["key"] == "R")
            self.assertEqual(second["name"], second_name)
            m.spend_skill(u, second)
            self.assertNotIn("R", [s["key"] for s in m.ready_skills(u)])
            m.s["time"] = 540
            if cid == "Swain":
                self.assertEqual(next(s for s in m.ready_skills(u) if s["key"] == "R")["name"], second_name)
            else:
                self.assertIsNone(u["ability_state"]["stolen"])
            m.s["time"] = 595
            m.advance_forms(1)
            self.assertIsNone(u["ability_state"]["stolen"])

    def test_recast_and_weapon_ultimate_tags_are_specific(self):
        m, u = match_for("LeeSin")
        q1 = next(s for s in m.ready_skills(u) if s["key"] == "Q")
        self.assertNotIn("mobility", q1["tags"])
        m.spend_skill(u, q1)
        self.assertIn("mobility", next(s for s in m.ready_skills(u) if s["key"] == "Q")["tags"])
        m, u = match_for("Aphelios")
        m.s["time"] = 600
        for form in REGISTRY["Aphelios"]["forms"]:
            m.set_form(u, form)
            tags = next(s for s in m.ready_skills(u) if s["key"] == "R")["tags"]
            self.assertNotIn("mobility", tags)
            self.assertNotIn("vision", tags)

    def test_serialized_form_order_drives_natural_transitions(self):
        for cid, form in [("Gnar", "mega"), ("Shyvana", "dragon"),
                          ("Yunara", "transcendent"), ("KSante", "allout")]:
            m, u = match_for(cid)
            m.s["time"] = 600
            m.advance_forms(300)
            self.assertEqual(u["ability_state"]["form"], form, cid)
        m, u = match_for("Kayn")
        m.s["time"] = 600
        m.advance_forms(30)
        self.assertIn(u["ability_state"]["form"], ("shadow", "darkin"))
        m, u = match_for("Aphelios")
        self.assertEqual(u["ability_state"]["weapon_order"],
                         ["calibrum", "severum", "gravitum", "infernum", "crescendum"])
