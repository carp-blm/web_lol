"""Engine 6/7 team operations: the manager's week between matches.

Engine 7 adds career ranges: growth stops at the player's peak; match ratings never go below the floor.

Weekly training, stamina and morale, deterministic player traits, game plans with a
counter cycle, AI team identities and scouting, a seasonal patch meta, sponsor
contracts and a four-division promotion ladder. Every draw uses the saved seed RNG.
These are Nexus Archive campaign rules, not a model of real teams or real patches.
"""
import hashlib
from copy import deepcopy
from josa import josa

STATS = ("lane", "combat", "vision", "farm")
ROLES = ("top", "jng", "mid", "bot", "sup")
STAT_NAMES = {"lane": "라인전", "combat": "전투", "vision": "시야", "farm": "성장"}

DIVISIONS = (
    {"id": "challengers", "name": "챌린저스 리그", "short": "CL", "ai_base": 60.5, "ai_step": 1.3, "reward": 1.0,
     "teams": ["NEXUS CLUB", "ROOKIE RAVENS", "HARBOR KITES", "IRON MOTHS", "DUNE RUNNERS", "NORTH LANTERNS"]},
    {"id": "pro", "name": "프로 리그", "short": "PRO", "ai_base": 66.5, "ai_step": 1.4, "reward": 1.25,
     "teams": ["NEXUS CLUB", "SEOUL COMETS", "PACIFIC FOXES", "BERLIN ECHO", "SHANGHAI NOVA", "ATLANTIC WAVE"]},
    {"id": "masters", "name": "마스터즈", "short": "MST", "ai_base": 71.5, "ai_step": 1.4, "reward": 1.5,
     "teams": ["NEXUS CLUB", "CRIMSON CROWN", "AURORA PACT", "OBSIDIAN TIDE", "SILVER VANGUARD", "STORM SIGIL"]},
    {"id": "worlds", "name": "월드 아레나", "short": "WLD", "ai_base": 77.0, "ai_step": 1.2, "reward": 2.0,
     "teams": ["NEXUS CLUB", "ETERNAL MONARCHS", "APEX ORACLE", "ZENITH LEGION", "HALCYON SIX", "INFINITY CORE"]},
)

# Rock-paper-scissors around four styles; "balanced" neither counters nor is countered.
PLANS = {
    "balanced": {"name": "균형 운영", "desc": "능력치 보정 없음 · 상성 영향 없음", "stats": {}, "beats": None,
                 "why": "어떤 상대에게도 무난합니다."},
    "aggressive": {"name": "난전 지향", "desc": "전투 +3 · 시야 −2", "stats": {"combat": 3, "vision": -2}, "beats": "scaling",
                   "why": "상대가 성장하기 전에 교전으로 무너뜨립니다."},
    "scaling": {"name": "후반 지향", "desc": "성장 +3 · 라인전 −2", "stats": {"farm": 3, "lane": -2}, "beats": "control",
                "why": "느린 운영이 준 시간을 후반 한타로 돌려받습니다."},
    "control": {"name": "시야 장악", "desc": "시야 +3 · 전투 −1", "stats": {"vision": 3, "combat": -1}, "beats": "lane",
                "why": "깊게 밀어붙인 라인을 시야와 갱킹으로 응징합니다."},
    "lane": {"name": "라인 압박", "desc": "라인전 +3 · 성장 −1", "stats": {"lane": 3, "farm": -1}, "beats": "aggressive",
             "why": "라인 주도권으로 난전의 진입로를 먼저 막습니다."},
}
COUNTER_BONUS = 2
AI_STYLES = ("aggressive", "scaling", "control", "lane")

TRAINING = {
    "lane": {"name": "라인전 훈련", "desc": "라인전 +0.45 · 피로 9", "stat": "lane", "fatigue": 9},
    "combat": {"name": "교전 훈련", "desc": "전투 +0.45 · 피로 10", "stat": "combat", "fatigue": 10},
    "vision": {"name": "시야·운영 훈련", "desc": "시야 +0.45 · 피로 6", "stat": "vision", "fatigue": 6},
    "farm": {"name": "성장 훈련", "desc": "성장 +0.45 · 피로 8", "stat": "farm", "fatigue": 8},
    "champion": {"name": "챔피언 연습", "desc": "지정 챔피언 숙련 +1.6 · 피로 7", "fatigue": 7, "mastery": 1.6},
    "rest": {"name": "휴식", "desc": "훈련 없음 · 체력 +30", "fatigue": -30},
}
TRAINING_GAIN = .45
MATCH_LOAD = 8
WEEKLY_RECOVERY = 5
EXHAUSTED = 25
EXHAUSTED_PENALTY = 4
BENCH_RECOVERY = 25

TRAITS = {
    "lane_king": {"name": "라인 지배자", "desc": "라인전 +3", "stats": {"lane": 3}},
    "teamfighter": {"name": "한타 장인", "desc": "전투 +3", "stats": {"combat": 3}},
    "architect": {"name": "시야 설계자", "desc": "시야 +3 · 전술 성공률 +1%p", "stats": {"vision": 3}, "choice": .01},
    "farmer": {"name": "성장 괴물", "desc": "성장 +3", "stats": {"farm": 3}},
    "prospect": {"name": "원석", "desc": "훈련·경기 성장 +50%", "growth": .5},
    "veteran": {"name": "베테랑", "desc": "컨디션 판정 +8", "condition": 8},
    "big_game": {"name": "승부사", "desc": "플레이오프 경기 모든 능력치 +3", "playoff": 3},
    "flex": {"name": "챔피언 폭", "desc": "챔피언 연습 효율 +60%", "practice": .6},
    "iron": {"name": "철인", "desc": "훈련·경기 피로 −40%", "fatigue": .4},
    "clutch": {"name": "강심장", "desc": "컨디션 최저 '저조'(−3)", "floor": -3},
    # Engine 7 mental traits: earned in matches from resolve checks, our club only (see MENTAL_*).
    "big_stage": {"name": "큰 무대 체질", "desc": "각성 확률 +10%p · 한 시즌 각성 3회로 획득", "mental": True},
    "fragile": {"name": "새가슴", "desc": "압박 증가 +20% · 각성 확률 −10%p · 한 시즌 각성 2회면 휴식기에 극복", "mental": True},
}

# Lasting marks of resolve checks, per player (not per card) and for our club only.
MENTAL_TRAITS = ("big_stage", "fragile")
BIG_STAGE_AWAKENINGS = 3          # awakenings in one season → 큰 무대 체질
FRAGILE_PLAYOFF_SHAKEN = 3        # falters in one season's playoff matches → 새가슴
FRAGILE_SEASON_SHAKEN = 5         # or falters in one season overall
OVERCOME_AWAKENINGS = 2           # a 새가슴 player who awakens this often in a season overcomes it in the off-season
LOSE_BIG_STAGE_SHAKEN = 3         # a 큰 무대 체질 player who falters this often without awakening loses it

SPONSORS = {
    "win_bonus": {"name": "네온 펄스 에너지", "desc": "승리할 때마다 +70 CR", "win": 70},
    "appearance": {"name": "하이퍼 기어", "desc": "경기마다 승패 무관 +45 CR", "match": 45},
    "title": {"name": "오로라 캐피털", "desc": "결승 진출 +350 CR · 우승 +900 CR", "final": 350, "title": 900},
    "highlight": {"name": "스트림박스", "desc": "우리 팀 처치 1회당 +6 CR", "kill": 6},
    "academy": {"name": "퓨처랩 아카데미", "desc": "주간 훈련 효과 +40%", "training": .4},
    "wellness": {"name": "그린필드 웰니스", "desc": "매주 체력 +10 · 피로 −20%", "stamina": 10, "fatigue": .2},
}

META_TAGS = {"Fighter": "전사", "Tank": "탱커", "Mage": "마법사", "Assassin": "암살자", "Marksman": "원거리 딜러", "Support": "서포터"}
META_BUFF = {"combat": 3, "lane": 2}
META_TAG_BONUS = 2


def bound(value, low, high):
    return max(low, min(high, value))


def card_hash(card_id):
    return int(hashlib.sha256(card_id.encode()).hexdigest()[:8], 16)


def card_traits(card):
    """Deterministic: one signature trait from the card profile plus an optional second."""
    ratings = card["ratings"]
    if card.get("tier") == 2 or card["overall"] < 64:
        first = "prospect"
    else:
        top = max(STATS, key=lambda k: (ratings[k], -STATS.index(k)))
        first = {"lane": "lane_king", "combat": "teamfighter", "vision": "architect", "farm": "farmer"}[top]
    candidates = []
    if card.get("games", 0) >= 60:
        candidates.append("veteran")
    if card.get("win_rate", 0) >= .65:
        candidates.append("big_game")
    if sum(1 for m in card.get("mastery", []) if m.get("games", 0) >= 3) >= 6:
        candidates.append("flex")
    candidates += ["iron", "clutch"]
    h = card_hash(card["id"])
    out = [first]
    if h % 5:
        second = candidates[(h // 5) % len(candidates)]
        if second != first:
            out.append(second)
    return out


def plan_counter(plan, enemy):
    """+1 when plan beats enemy, -1 when enemy beats plan, 0 otherwise."""
    if PLANS.get(plan, {}).get("beats") == enemy:
        return 1
    if PLANS.get(enemy, {}).get("beats") == plan:
        return -1
    return 0


class ManagementRules:
    # ---- state -------------------------------------------------------------------------
    def initialize_management(self):
        m = self.s.setdefault("management", {})
        m.setdefault("division", 0)
        m.setdefault("plan", "balanced")
        m.setdefault("training", {})
        m.setdefault("stamina", {})
        m.setdefault("morale", 0)
        m.setdefault("streak", 0)
        m.setdefault("sponsor", None)
        m.setdefault("sponsor_offers", [])
        m.setdefault("meta", None)
        m.setdefault("last_week", [])
        m.setdefault("season_result", None)
        m.setdefault("closed_season", 0)
        m.setdefault("division_history", [])
        m.setdefault("sponsor_income", 0)
        m.setdefault("mental", {})
        return m

    @property
    def ops(self):
        return self.s["management"]

    def division(self):
        return DIVISIONS[self.ops["division"]]

    # ---- career range (engine 7) ------------------------------------------------------------
    def career_range(self, cid):
        """Peak and floor per stat from every season card and form window of this player."""
        card = self.cards[cid]
        entry = self.catalog.get("players", {}).get(card["player_id"])
        if not entry:
            return {"peak": dict.fromkeys(STATS, 99), "floor": dict.fromkeys(STATS, 1)}
        return entry

    def stat_cap(self, cid, stat):
        # Development can lift any season's card to the player's career peak, never beyond it.
        return max(self.cards[cid]["ratings"][stat], self.career_range(cid)["peak"][stat])

    def stamina(self, cid):
        return self.ops["stamina"].get(cid, 100)

    def traits(self, cid):
        return card_traits(self.cards[cid])

    # ---- mental traits (engine 7) ------------------------------------------------------------
    def mental_record(self, cid):
        return self.ops.setdefault("mental", {}).setdefault(self.cards[cid]["player_id"],
                                             {"traits": [], "awakened": 0, "shaken": 0, "playoff_shaken": 0})

    def mental_traits(self, cid):
        entry = self.ops.get("mental", {}).get(self.cards[cid]["player_id"])
        return list(entry["traits"]) if entry else []

    def set_mental(self, cid, trait, events, reason):
        record = self.mental_record(cid)
        if trait in record["traits"]:
            return
        for other in MENTAL_TRAITS:
            if other in record["traits"]:
                record["traits"].remove(other)
                events.append({"card_id": cid, "name": self.cards[cid]["name"], "trait": other, "change": "lose", "reason": reason})
        record["traits"].append(trait)
        events.append({"card_id": cid, "name": self.cards[cid]["name"], "trait": trait, "change": "gain", "reason": reason})

    def settle_mental(self, match, playoff):
        """After each of our matches: count resolve outcomes; earn a mental trait at a threshold."""
        events = []
        for u in match["teams"][0]:
            awakened, shaken = u.get("awakenings", 0), u.get("shaken", 0)
            if not (awakened or shaken):
                continue
            cid = u["card_id"]
            record = self.mental_record(cid)
            record["awakened"] += awakened
            record["shaken"] += shaken
            record["playoff_shaken"] += shaken if playoff else 0
            if awakened and record["awakened"] >= BIG_STAGE_AWAKENINGS:
                self.set_mental(cid, "big_stage", events, f'이번 시즌 각성 {record["awakened"]}회')
            elif shaken and (record["playoff_shaken"] >= FRAGILE_PLAYOFF_SHAKEN or record["shaken"] >= FRAGILE_SEASON_SHAKEN):
                self.set_mental(cid, "fragile", events, f'플레이오프 흔들림 {record["playoff_shaken"]}회' if playoff and record["playoff_shaken"] >= FRAGILE_PLAYOFF_SHAKEN else f'이번 시즌 흔들림 {record["shaken"]}회')
        match["mental_report"] = events
        return events

    def close_mental_season(self):
        """Off-season: a 새가슴 player who still awakened enough overcomes it; tallies reset."""
        events = []
        for pid, record in sorted(self.ops["mental"].items()):
            cid = next((c for c in self.s["owned"] if self.cards[c]["player_id"] == pid), None)
            name = self.cards[cid]["name"] if cid else pid
            if "fragile" in record["traits"] and record["awakened"] >= OVERCOME_AWAKENINGS:
                record["traits"].remove("fragile")
                events.append({"card_id": cid, "name": name, "trait": "fragile", "change": "lose", "reason": f'시즌 각성 {record["awakened"]}회로 극복'})
            elif "big_stage" in record["traits"] and record["awakened"] == 0 and record["shaken"] >= LOSE_BIG_STAGE_SHAKEN:
                record["traits"].remove("big_stage")
                events.append({"card_id": cid, "name": name, "trait": "big_stage", "change": "lose", "reason": f'각성 없이 흔들림 {record["shaken"]}회'})
            record.update(awakened=0, shaken=0, playoff_shaken=0)
        return events

    # ---- former-teammate derby (engine 7) ----------------------------------------------------
    def career_stints(self, cid):
        """(team_id, year) -> card for every season this player has in the archive."""
        card = self.cards[cid]
        ids = self.catalog.get("players", {}).get(card["player_id"], {}).get("cards", [cid])
        return {(self.cards[i]["team_id"], self.cards[i]["year"]): self.cards[i] for i in ids if i in self.cards}

    def derby_pairs(self, ours, theirs):
        """Players on opposite sides who played on the same team in the same year."""
        pairs = []
        for a in ours:
            mine = self.career_stints(a)
            for b in theirs:
                if self.cards[a]["player_id"] == self.cards[b]["player_id"]:
                    continue
                shared = sorted(set(mine) & set(self.career_stints(b)), key=lambda k: (k[1], k[0]))
                if shared:
                    stint = mine[shared[-1]]
                    pairs.append({"ours": self.cards[a]["role"], "theirs": self.cards[b]["role"],
                                  "ours_name": self.cards[a]["name"], "theirs_name": self.cards[b]["name"],
                                  "team": stint["team"], "year": stint["year"]})
        return pairs

    def trait_sum(self, cid, key):
        return sum(TRAITS[t].get(key, 0) for t in self.traits(cid))

    def sponsor_value(self, key):
        sponsor = self.ops.get("sponsor")
        return SPONSORS[sponsor].get(key, 0) if sponsor else 0

    def condition_shift(self, cid):
        """Stamina 100 → +10, 60 → 0, 20 → −10; morale ±2 per step; veteran trait."""
        return int(round((self.stamina(cid)-60)/4)) + self.ops["morale"]*2 + self.trait_sum(cid, "condition")

    # ---- patch meta ----------------------------------------------------------------------
    def roll_meta(self):
        pools = sorted({p["id"] for cid in self.s["roster"].values() for p in self.champion_pool(self.cards[cid])[:4]})
        everyone = sorted(self.champions)
        buffs, nerfs = [], []

        def draw(source, out, count):
            options = [c for c in source if c not in buffs and c not in nerfs]
            for _ in range(min(count, len(options))):
                pick = self.rng.pick(options)
                out.append(pick)
                options.remove(pick)
        # Keep it relevant: some changes always touch the manager's own champion pools.
        draw(pools, buffs, 2)
        draw(pools, nerfs, 1)
        draw(everyone, buffs, 2)
        draw(everyone, nerfs, 2)
        tag = self.rng.pick(sorted(META_TAGS))
        number = self.s["season_number"]
        return {"patch": f"N{number}.{self.rng.integer(1, 9)}", "buffs": buffs, "nerfs": nerfs, "tag": tag}

    def meta_value(self, champion):
        meta = self.ops.get("meta")
        if not meta:
            return 0
        value = 8 if champion in meta["buffs"] else -8 if champion in meta["nerfs"] else 0
        return value + (3 if meta["tag"] in self.champions.get(champion, {}).get("tags", []) else 0)

    # ---- unit preparation (both teams) --------------------------------------------------
    def prepare_units(self, units, campaign=False):
        units = super().prepare_units(units, campaign=campaign)
        meta = self.ops.get("meta") if "management" in self.s else None
        season = self.s.get("season")
        playoff = bool(season and season["phase"] in ("semifinal", "final"))
        for unit in units:
            cid = unit["card_id"]
            unit["traits"] = self.traits(cid) + (self.mental_traits(cid) if campaign and "management" in self.s else [])
            career = self.career_range(cid)
            unit["peak"], unit["floor"] = dict(career["peak"]), dict(career["floor"])
            unit["meta"] = None
            ratings = unit["ratings"]
            start = dict(ratings)
            for trait in unit["traits"]:
                info = TRAITS[trait]
                for stat, amount in info.get("stats", {}).items():
                    ratings[stat] += amount
                if playoff and info.get("playoff"):
                    for stat in STATS:
                        ratings[stat] += info["playoff"]
                unit["choice_bonus"] = unit.get("choice_bonus", 0) + info.get("choice", 0)
                if "floor" in info:
                    unit["condition_floor"] = max(unit.get("condition_floor", -6), info["floor"])
            unit["growth_bonus"] = self.trait_sum(cid, "growth") if campaign else 0
            if meta:
                champion = unit["champion"]
                if champion in meta["buffs"] or champion in meta["nerfs"]:
                    sign = 1 if champion in meta["buffs"] else -1
                    unit["meta"] = "buff" if sign > 0 else "nerf"
                    for stat, amount in META_BUFF.items():
                        ratings[stat] += sign*amount
                if meta["tag"] in self.champions.get(champion, {}).get("tags", []):
                    ratings["combat"] += META_TAG_BONUS
                    unit["meta_tag"] = True
            if campaign and "management" in self.s:
                unit["stamina"] = self.stamina(cid)
                unit["condition_shift"] = self.condition_shift(cid)
                unit["exhausted"] = unit["stamina"] < EXHAUSTED
                if unit["exhausted"]:
                    for stat in STATS:
                        ratings[stat] -= EXHAUSTED_PENALTY
            else:
                unit["condition_shift"] = self.trait_sum(cid, "condition")
            # Unbounded per-stat total of traits, patch and exhaustion, for display and tests.
            unit["ops_mods"] = {k: round(ratings[k]-start[k], 2) for k in STATS}
            unit["ratings"] = {k: round(bound(v, 1, 99), 2) for k, v in ratings.items()}
            unit["overall"] = round(sum(unit["ratings"].values()) / 4, 2)
        if campaign and season and "management" in self.s:
            opponent = self.current_opponent()
            enemy = season["teams"][opponent].get("style", "balanced") if opponent is not None else "balanced"
            self.apply_plan(units, self.ops["plan"], enemy)
        return units

    def apply_plan(self, units, plan, enemy):
        counter = plan_counter(plan, enemy)
        for unit in units:
            for stat, amount in PLANS[plan]["stats"].items():
                unit["ratings"][stat] += amount
            if counter > 0:
                for stat in STATS:
                    unit["ratings"][stat] += COUNTER_BONUS
            unit["plan"] = {"id": plan, "enemy": enemy, "counter": counter}
            unit["ratings"] = {k: round(bound(v, 1, 99), 2) for k, v in unit["ratings"].items()}
            unit["overall"] = round(sum(unit["ratings"].values()) / 4, 2)
        return units

    def current_opponent(self):
        season = self.s.get("season")
        if not season or season["phase"] == "complete":
            return None
        try:
            return self.opponent()
        except (StopIteration, IndexError, KeyError):
            return None

    # ---- AI draft respects the patch ----------------------------------------------------
    def ai_draft_choice(self, role=None):
        if not self.ops.get("meta"):
            return super().ai_draft_choice(role)
        taken = self.draft_taken()
        if role:
            ids = self.s["season"]["teams"][self.opponent()]["roster"]
            card = next(self.cards[cid] for cid in ids if self.cards[cid]["role"] == role)
            pool = [(p["id"], p["mastery"]) for p in self.champion_pool(card) if p["id"] not in taken]
            pool += [(c, 35) for c in self.ops["meta"]["buffs"] if c not in taken and c not in {x for x, _ in pool}]
            margin = 5
        else:
            pool = [(p["id"], p["mastery"]) for cid in self.s["roster"].values()
                    for p in self.champion_pool(self.cards[cid]) if p["id"] not in taken]
            margin = 3
        if pool:
            scored = [(c, m + self.meta_value(c)) for c, m in pool]
            best = max(s for _, s in scored)
            return self.rng.pick(sorted({c for c, s in scored if s >= best-margin}))
        return self.rng.pick([cid for cid in sorted(self.champions) if cid not in taken])

    # ---- season hooks ---------------------------------------------------------------------
    def setup_season_management(self):
        ops = self.ops
        ops["meta"] = self.roll_meta()
        pool = sorted(SPONSORS)
        offers = []
        for _ in range(3):
            pick = self.rng.pick(pool)
            offers.append(pick)
            pool.remove(pick)
        ops["sponsor"], ops["sponsor_offers"], ops["sponsor_income"] = None, offers, 0
        ops["season_result"] = None
        # Off-season: everyone returns rested; morale carries over.
        ops["stamina"] = {}
        ops["streak"] = 0

    def ai_team_target(self, index):
        d = self.division()
        return d["ai_base"] + index*d["ai_step"]

    def settle_week(self, won, match):
        """One week passes after each of our matches: fatigue, training, morale, sponsor."""
        ops = self.ops
        ops["streak"] = max(1, ops["streak"]+1) if won else min(-1, ops["streak"]-1)
        ops["morale"] = min(3, max(0, ops["morale"])+1) if won else max(-3, min(0, ops["morale"])-1)
        starters = {self.s["roster"][r]: r for r in self.s["roster"]}
        played = {u["card_id"]: u for u in match["teams"][0]}
        training_bonus = self.sponsor_value("training")
        relief = self.sponsor_value("fatigue")
        if match.get("clutch_rules"):
            self.settle_mental(match, self.s["season"]["phase"] in ("semifinal", "final"))
        report = []
        for cid in list(dict.fromkeys([*starters, *self.s["owned"]])):
            before = self.stamina(cid)
            if cid not in starters:
                if before < 100:
                    ops["stamina"][cid] = min(100, before + BENCH_RECOVERY)
                continue
            role = starters[cid]
            plan = ops["training"].get(role, {"focus": "lane"})
            focus = plan["focus"] if plan.get("focus") in TRAINING else "lane"
            info = TRAINING[focus]
            fatigue_mult = max(0, 1 - self.trait_sum(cid, "fatigue") - relief)
            load = (MATCH_LOAD if cid in played else 0) * fatigue_mult
            cost = info["fatigue"]*fatigue_mult if info["fatigue"] > 0 else info["fatigue"]
            after = round(bound(before - load - cost + WEEKLY_RECOVERY + self.sponsor_value("stamina"), 0, 100), 1)
            ops["stamina"][cid] = after
            progress = self.s["progression"].setdefault(cid, {"stats": dict.fromkeys(STATS, 0), "mastery": {}, "games": 0, "wins": 0})
            # Exhausted players learn less: below 30 stamina, training is half as effective.
            efficiency = (1 + self.trait_sum(cid, "growth") + training_bonus) * (.5 if before < 30 else 1)
            row = {"card_id": cid, "name": self.cards[cid]["name"], "role": role, "focus": focus,
                   "stamina_before": before, "stamina_after": after, "stat": None, "gain": 0, "champion": None}
            if info.get("stat"):
                stat = info["stat"]
                current = self.permanent_ratings(cid)[stat]
                cap = self.stat_cap(cid, stat)
                gain = round(max(0, min(cap-current, TRAINING_GAIN*efficiency)), 2)
                progress["stats"][stat] = round(progress["stats"][stat]+gain, 2)
                row.update(stat=stat, gain=gain, peak=cap, at_peak=current+gain >= cap)
            elif focus == "champion":
                champion = plan.get("champion") if plan.get("champion") in self.champions else self.default_practice(cid)
                raw = next((p["mastery"] for p in self.champion_pool(self.cards[cid]) if p["id"] == champion), 35)
                current = min(100, raw + progress["mastery"].get(champion, 0))
                gain = round(min(100-current, info["mastery"]*efficiency*(1+self.trait_sum(cid, "practice"))), 2)
                progress["mastery"][champion] = round(progress["mastery"].get(champion, 0)+gain, 2)
                row.update(champion=champion, gain=gain)
            report.append(row)
        ops["last_week"] = report
        match["week_report"] = deepcopy(report)
        # Sponsor per-match income.
        sponsor = ops.get("sponsor")
        if sponsor:
            info = SPONSORS[sponsor]
            kills = sum(u["kills"] for u in match["teams"][0])
            income = info.get("match", 0) + (info.get("win", 0) if won else 0) + info.get("kill", 0)*kills
            if income:
                self.s["coins"] += income
                ops["sponsor_income"] += income
                match["sponsor_income"] = income

    def close_season(self):
        """Called once when our season phase becomes complete: promotion or relegation."""
        ops, season = self.ops, self.s["season"]
        if ops["closed_season"] == self.s["season_number"]:
            return
        ops["closed_season"] = self.s["season_number"]
        before = ops["division"]
        standing = season["standings"].index(0) + 1
        reached_final = any(h["phase"] == "final" for h in season["history"])
        champion = season["champion"] == 0
        sponsor = ops.get("sponsor")
        bonus = 0
        if sponsor:
            info = SPONSORS[sponsor]
            bonus = (info.get("final", 0) if reached_final else 0) + (info.get("title", 0) if champion else 0)
            if bonus:
                self.s["coins"] += bonus
                ops["sponsor_income"] += bonus
        if reached_final and before < len(DIVISIONS)-1:
            outcome = "promote"
        elif standing == 6 and before > 0:
            outcome = "relegate"
        else:
            outcome = "stay"
        after = before + (1 if outcome == "promote" else -1 if outcome == "relegate" else 0)
        ops["division"] = after
        ops["season_result"] = {"season": self.s["season_number"], "outcome": outcome, "standing": standing,
                                "champion": champion, "final": reached_final, "from": before, "to": after,
                                "sponsor_bonus": bonus, "mental": self.close_mental_season()}
        ops["division_history"].append({"season": self.s["season_number"], "division": before,
                                        "standing": standing, "champion": champion, "outcome": outcome})
        label = {"promote": f'{DIVISIONS[after]["name"]} 승격!', "relegate": f'{josa(DIVISIONS[after]["name"], "로")} 강등',
                 "stay": f'{DIVISIONS[after]["name"]} 잔류'}[outcome]
        self.s["notice"] = f'시즌 종료 · {label}'

    def default_practice(self, cid):
        champion = self.s["draft"].get(self.cards[cid]["role"])
        if champion:
            return champion
        pool = self.champion_pool(self.cards[cid])
        return pool[0]["id"] if pool else sorted(self.champions)[0]

    # ---- actions --------------------------------------------------------------------------
    def management_action(self, action):
        kind, ops = action["type"], self.ops
        if not self.s["starter"]["finished"]:
            raise ValueError("구단 창단을 먼저 완료해주세요.")
        if kind == "set_training":
            role, focus = action.get("role"), action.get("focus")
            if role not in ("top", "jng", "mid", "bot", "sup") or focus not in TRAINING:
                raise ValueError("훈련 포지션과 종류를 확인해주세요.")
            plan = {"focus": focus}
            if focus == "champion":
                champion = action.get("champion")
                if champion is not None and champion not in self.champions:
                    raise ValueError("존재하지 않는 챔피언입니다.")
                plan["champion"] = champion or self.default_practice(self.s["roster"][role])
            ops["training"][role] = plan
        elif kind == "set_plan":
            if self.active():
                raise ValueError("경기 중에는 전략을 바꿀 수 없습니다.")
            if action.get("plan") not in PLANS:
                raise ValueError("존재하지 않는 전략입니다.")
            ops["plan"] = action["plan"]
        elif kind == "sign_sponsor":
            if ops.get("sponsor"):
                raise ValueError("이번 시즌 스폰서 계약을 이미 맺었습니다.")
            if action.get("sponsor") not in ops.get("sponsor_offers", []):
                raise ValueError("이번 시즌 제안받은 스폰서만 계약할 수 있습니다.")
            ops["sponsor"] = action["sponsor"]
            self.s["notice"] = f'{josa(SPONSORS[ops["sponsor"]]["name"], "와")} 시즌 계약 체결'
        else:
            raise ValueError("지원하지 않는 운영 명령입니다.")

    # ---- views ------------------------------------------------------------------------------
    def scouting_report(self):
        opponent = self.current_opponent()
        if opponent is None:
            return None
        team = self.s["season"]["teams"][opponent]
        style = team.get("style", "balanced")
        players = []
        for cid in team["roster"]:
            card = self.cards[cid]
            pool = sorted(self.champion_pool(card), key=lambda p: -(p["mastery"] + self.meta_value(p["id"])))[:3]
            players.append({"card_id": cid, "name": card["name"], "role": card["role"], "overall": card["overall"],
                            "team": card["team"], "year": card["year"], "traits": card_traits(card),
                            "champions": [{"id": p["id"], "mastery": p["mastery"], "meta": self.meta_value(p["id"])} for p in pool]})
        threats = sorted({p["id"] for cid in self.s["roster"].values() for p in self.champion_pool(self.cards[cid])[:3]},
                         key=lambda c: -self.meta_value(c))[:5]
        plan = self.ops["plan"]
        return {"team": opponent, "name": team["name"], "style": style, "record": [team["wins"], team["losses"]],
                "overall": round(sum(self.cards[c]["overall"] for c in team["roster"]) / 5, 1),
                "players": players, "likely_bans": threats,
                "derbies": self.derby_pairs([self.s["roster"][r] for r in ROLES if r in self.s["roster"]], team["roster"]),
                "counter": plan_counter(plan, style),
                "suggested": next((k for k, v in PLANS.items() if v["beats"] == style), "balanced")}

    def management_view(self):
        owned = set(self.s["owned"])
        return {"plans": deepcopy(PLANS), "training_catalog": deepcopy(TRAINING), "traits_catalog": deepcopy(TRAITS),
                "sponsor_catalog": deepcopy(SPONSORS), "divisions": deepcopy(DIVISIONS), "meta_tags": dict(META_TAGS),
                "card_traits": {cid: card_traits(self.cards[cid]) + self.mental_traits(cid) for cid in owned},
                "condition_shift": {cid: self.condition_shift(cid) for cid in self.s["roster"].values()},
                "scouting": self.scouting_report() if self.s.get("season") else None}
