import copy
import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from build_data import eligible,read_json,media_record,num
from fetch_sources import validate_csv,validate_url
from build_site import validate


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules=read_json(ROOT/"data/league_tiers.json")
        cls.data=read_json(ROOT/"web/data/cards.json")
        with gzip.open(ROOT/"data/seed/appearances.csv.gz","rt",encoding="utf8",newline="") as f:
            cls.rows=list(csv.DictReader(f))

    def test_every_card_matches_actual_appearance_identity(self):
        keys={(int(float(r["year"])),r["playerid"],r["teamid"],r["position"]) for r in self.rows}
        for c in self.data["cards"]:
            self.assertIn((c["year"],c["player_id"],c["team_id"],c["role"]),keys)
            self.assertGreater(c["games"],0)
            self.assertIn(c["tier"],(1,2))

    def test_no_unknown_or_unplayed_or_team_cards(self):
        row=copy.deepcopy(self.rows[0]);self.assertTrue(eligible(row,self.rules))
        for field,value in (("league","UNKNOWN"),("position","team"),("playerid",""),("gameid",""),("gamelength","0"),("result",""),("year","2012")):
            self.assertFalse(eligible({**row,field:value},self.rules))

    def test_dual_year_global_and_second_tier_coverage(self):
        self.assertEqual(self.data["coverage"]["years"],[2023,2024])
        self.assertGreater(self.data["coverage"]["cards"],3000)
        self.assertIn("LCKC",self.data["coverage"]["leagues"])
        self.assertIn("LDL",self.data["coverage"]["leagues"])
        self.assertIn("CBLOL",self.data["coverage"]["leagues"])
        self.assertGreaterEqual(len(self.data["coverage"]["leagues"]),15)

    def test_stats_and_mastery_are_bounded(self):
        for c in self.data["cards"]:
            self.assertTrue(40<=c["overall"]<=99)
            self.assertTrue(all(40<=v<=99 for v in c["ratings"].values()))
            self.assertTrue(all(35<=m["value"]<=95 and m["games"]>0 for m in c["mastery"]))

    def test_no_nonfinite_numeric_data(self):
        self.assertIsNone(num("nan"));self.assertIsNone(num("inf"));self.assertIsNone(num(""))
        self.assertEqual(num("3.5"),3.5)

    def test_ddragon_complete_passive_qwer_and_korean(self):
        data=read_json(ROOT/"web/data/champions.json")
        self.assertEqual(data["locale"],"ko_KR")
        self.assertGreaterEqual(len(data["champions"]),170)
        for c in data["champions"].values():
            self.assertEqual([s["key"] for s in c["skills"]],list("PQWER"))
            self.assertTrue(c["source"].startswith("https://ddragon.leagueoflegends.com/"))
            self.assertTrue(all(s["name"] and s["tags"] and s["icon"].startswith("https://ddragon.leagueoflegends.com/") for s in c["skills"]))

    def test_unapproved_image_uses_placeholder_even_if_override_supplied(self):
        entry={"key":"test","kind":"portrait","display":"https://evil/image.jpg","file":"assets/approved/test.png","verified":True,"year":2024,"team":"T1","permission":"unknown"}
        m=media_record("test",2024,"T1","portrait",[entry])
        self.assertEqual(m["display"],"assets/player-placeholder.svg")

    def test_default_media_tracks_rights_without_claiming_verification(self):
        data=read_json(ROOT/"web/data/media.json")
        for c in self.data["cards"]:
            m=data["assets"][c["id"]]
            self.assertEqual(m["year"],c["year"])
            self.assertEqual(m["team"],c["team"])
            self.assertIn("permission_evidence",m)
            if not m["verified"]:self.assertEqual(m["display"],"assets/player-placeholder.svg")

    def test_download_guard_blocks_quota_html_and_untrusted_hosts(self):
        for data in (b'<!DOCTYPE html>Google Drive quota exceeded',b'<html>login</html>',b'foo,bar\n1,2'):
            with self.assertRaises(ValueError):validate_csv(data)
        for url in ('http://drive.google.com/test','https://example.com/data.csv','file:///etc/passwd','https://127.0.0.1/x'):
            with self.assertRaises(ValueError):validate_url(url)
        validate_url('https://drive.google.com/uc?id=test')

    def test_static_package_input_valid(self):
        self.assertGreater(len(validate()["cards"]),3000)

if __name__=="__main__":unittest.main()
