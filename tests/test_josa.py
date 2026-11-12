import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))
from josa import josa, particle


class JosaTests(unittest.TestCase):
    def test_hangul_final_consonant(self):
        self.assertEqual(josa("드래곤", "를"), "드래곤을")
        self.assertEqual(josa("바텀", "을"), "바텀을")
        self.assertEqual(josa("미드", "을"), "미드를")
        self.assertEqual(josa("전령", "가"), "전령이")
        self.assertEqual(josa("아리", "이"), "아리가")
        self.assertEqual(josa("마스터즈", "은"), "마스터즈는")
        self.assertEqual(josa("네온 펄스 에너지", "과"), "네온 펄스 에너지와")
        self.assertEqual(josa("무한의 대검", "와"), "무한의 대검과")

    def test_euro_ro_treats_rieul_like_no_final(self):
        self.assertEqual(josa("탑", "로"), "탑으로")
        self.assertEqual(josa("미드", "으로"), "미드로")
        self.assertEqual(josa("정글", "으로"), "정글로")
        self.assertEqual(josa("챌린저스 리그", "로"), "챌린저스 리그로")

    def test_parenthetical_and_brackets_are_skipped(self):
        self.assertEqual(josa("Faker(아리)", "이"), "Faker(아리)가")
        self.assertEqual(josa("Canyon(바이)", "가"), "Canyon(바이)이")
        self.assertEqual(josa("질풍검 [강화]", "로"), "질풍검 [강화]으로")

    def test_latin_and_digits(self):
        for name, expected in (("Faker", "가"), ("Scout", "가"), ("Canyon", "이"), ("Aiming", "이"), ("Kael", "이")):
            self.assertEqual(particle(name, "이"), expected, name)
        self.assertEqual(particle("Kael", "로"), "로")
        self.assertEqual(particle("3", "로"), "으로")
        self.assertEqual(particle("7", "로"), "로")
        self.assertEqual(particle("", "을"), "를")

    def test_no_placeholder_particles_left_in_current_engine(self):
        frozen = re.compile(r"legacy_")
        for path in (ROOT / "web").glob("*.py"):
            if frozen.match(path.name):
                continue
            text = path.read_text(encoding="utf-8-sig")
            self.assertNotIn("이(가)", text, path.name)
            self.assertNotIn("을(를)", text, path.name)

    def test_js_helper_mirrors_python_rules(self):
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("const DIGIT_FINAL={0:21,1:8,2:0,3:16,4:0,5:0,6:1,7:8,8:8,9:0};", js)
        self.assertIn("(m|n|ng)$", js)


if __name__ == "__main__":
    unittest.main()
