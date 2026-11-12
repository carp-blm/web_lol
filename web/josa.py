"""Korean particles that follow a name: 을/를, 이/가, 은/는, 과/와, 으로/로.

Names in this game are Hangul (champions, lanes, leagues) or Latin (player handles), so the
choice is made from how the last word is read aloud:
- Hangul: the final syllable's consonant (받침). For 으로/로 a ㄹ final takes 로.
- A trailing parenthetical is ignored: "Faker(아리)" follows "Faker".
- Digits use their Korean reading (1 일, 3 삼, 6 육, 7 칠, 8 팔, 0 영 end in a consonant).
- Latin words: an approximation from the spelling. Endings in m, n, ng read with a final
  consonant (Canyon 캐니언, Aiming 에이밍), l with ㄹ (Kael 케일); everything else is read
  with a trailing vowel (Faker 페이커, Scout 스카우트). Unusual readings can still be wrong.
"""
import re

PAIRS = {"을": ("을", "를"), "를": ("을", "를"), "이": ("이", "가"), "가": ("이", "가"),
         "은": ("은", "는"), "는": ("은", "는"), "과": ("과", "와"), "와": ("과", "와"),
         "으로": ("으로", "로"), "로": ("으로", "로")}
RIEUL = 8
DIGIT_FINAL = {"0": 21, "1": RIEUL, "2": 0, "3": 16, "4": 0, "5": 0, "6": 1, "7": RIEUL, "8": RIEUL, "9": 0}


def final_consonant(word):
    """Index of the last syllable's final consonant (0 = none, 8 = ㄹ), as read aloud."""
    text = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*$", "", str(word))
    text = re.sub(r"[^0-9A-Za-z가-힣]+$", "", text)
    if not text:
        return 0
    last = text[-1]
    if "가" <= last <= "힣":
        return (ord(last)-0xAC00) % 28
    if last.isdigit():
        return DIGIT_FINAL[last]
    lower = text.lower()
    if lower.endswith(("m", "n", "ng")):
        return 4
    if lower.endswith("l"):
        return RIEUL
    return 0


def particle(word, kind):
    """The particle alone. kind is either form of the pair, e.g. "을" or "를"."""
    with_final, without = PAIRS[kind]
    final = final_consonant(word)
    if with_final == "으로":
        return "으로" if final and final != RIEUL else "로"
    return with_final if final else without


def josa(word, kind):
    """The word followed by its particle: josa("드래곤", "를") -> "드래곤을"."""
    return f"{word}{particle(word, kind)}"
