"""Campaign-only growth and relics; all randomness uses the existing seeded RNG.

Names/icons are the pinned Riot 16.20.1 ko_KR snapshot in data/item_snapshot.json.
Relic effects are Nexus Archive rules, independent of League item balance.
"""
from collections import Counter
from copy import deepcopy

STATS = ("lane", "combat", "vision", "farm")
CONDITIONS = (("부진", -6), ("저조", -3), ("보통", 0), ("좋음", 3), ("절정", 6))
PATCH = "16.20.1"
RELICS = {
    "3190": {"name": "강철의 솔라리 펜던트", "kind": "team", "price": 360,
             "description": "팀 전원 모든 능력치 +2", "stats": dict.fromkeys(STATS, 2)},
    "2065": {"name": "슈렐리아의 군가", "kind": "team", "price": 320,
             "description": "팀 전원 시야 +3 · 모든 전술 선택 성공률 +4%p", "stats": {"vision": 3}, "choice": .04},
    "3031": {"name": "무한의 대검", "kind": "player", "price": 300,
             "description": "지정 선수 전투 +7 · 라인전 +3", "stats": {"combat": 7, "lane": 3}},
    "3083": {"name": "워모그의 갑옷", "kind": "player", "price": 280,
             "description": "지정 선수 모든 능력치 +3 · 부진/저조 컨디션을 보통으로 보정", "stats": dict.fromkeys(STATS, 3), "condition_floor": 0},
    "3089": {"name": "라바돈의 죽음모자", "kind": "mastery", "price": 340, "exclusive": "마법 유물",
             "description": "지정 선수의 선택 챔피언 숙련도 +8 · 경기 후 숙련도 성장 25% 증가", "mastery": 8, "growth": .25},
    "3157": {"name": "존야의 모래시계", "kind": "team", "price": 300, "exclusive": "마법 유물",
             "description": "모든 전술 선택 성공률 +7%p · 죽음모자와 동시 소유 불가", "choice": .07},
    "1052": {"name": "증폭의 고서", "kind": "mastery", "price": 180,
             "description": "지정 선수의 선택 챔피언 숙련도 +4 · 경기 후 숙련도 성장 15% 증가", "mastery": 4, "growth": .15},
    "2055": {"name": "제어 와드", "kind": "consumable", "price": 70,
             "description": "전술 선택 대기 중 사용 · 현재 선택 성공률 +12%p · 선택당 1회", "choice": .12, "timing": "event"},
    "2140": {"name": "분노의 영약", "kind": "consumable", "price": 120, "exclusive": "영약",
             "description": "사용 후 다음 한 경기 팀 전원 전투 +6", "stats": {"combat": 6}, "timing": "next_match"},
    "2139": {"name": "마법의 영약", "kind": "consumable", "price": 120, "exclusive": "영약",
             "description": "사용 후 다음 한 경기 팀 숙련도 +6 · 숙련도 성장 30% 증가", "mastery": 6, "growth": .30, "timing": "next_match"},
}
for relic_id, relic in RELICS.items():
    relic["id"] = relic_id
    relic["icon"] = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/img/item/{relic_id}.png"


def bound(value, low, high):
    return max(low, min(high, value))


def synergy_groups(units):
    counts = Counter(u["team_id"] for u in units)
    groups = []
    for team_id, count in counts.items():
        if count < 2:
            continue
        members = [u for u in units if u["team_id"] == team_id]
        # Same source team across years; matching year adds one extra point.
        same_year = len({u["year"] for u in members}) == 1
        groups.append({"team_id": team_id, "team": members[0]["team"], "count": count,
                       "same_year": same_year, "bonus": (count-1)*2 + int(same_year),
                       "members": [u["card_id"] for u in members]})
    return groups


class ProgressionMatchRules:
    def initialize_progression(self):
        self.s["progression_rules"] = 1
        self.s["synergies"] = []
        for team in self.s["teams"]:
            self.s["synergies"].append(synergy_groups(team))
            for unit in team:
                # 10 / 20 / 40 / 20 / 10 percent; fixed once per match.
                roll = self.rng.integer(1, 100)
                index = 0 if roll <= 10 else 1 if roll <= 30 else 2 if roll <= 70 else 3 if roll <= 90 else 4
                label, delta = CONDITIONS[index]
                applied = max(delta, unit.get("condition_floor", -6))
                unit["condition"] = {"label": label, "rolled": delta, "modifier": applied}
                unit["ratings"] = {k: round(bound(v+applied, 1, 99), 2) for k, v in unit["ratings"].items()}
                unit["overall"] = round(sum(unit["ratings"].values()) / 4, 2)

    def make_event(self):
        super().make_event()
        if self.s["event"]:
            bonus = sum(u.get("choice_bonus", 0) for u in self.s["teams"][0]) / 5
            self.s["event"].update(relic_bonus=round(bonus, 4), used_relics=[])
            self.refresh_relic_chances()

    def refresh_relic_chances(self):
        event = self.s["event"]
        for option in event["options"]:
            base = option.setdefault("base_chance", option["chance"])
            option["chance"] = round(bound(base + event["relic_bonus"], .05, .98), 2)
            option["relic_bonus"] = round(option["chance"] - base, 2)


class CampaignRules:
    def initialize_campaign(self):
        defaults = {"progression": {}, "relics": {}, "prepared_relics": [],
                    "reward_event": None, "last_growth": []}
        for key, value in defaults.items():
            self.s.setdefault(key, value)

    def permanent_ratings(self, cid):
        growth = self.s["progression"].get(cid, {}).get("stats", {})
        return {k: round(bound(v+growth.get(k, 0), 1, 99), 2) for k, v in self.cards[cid]["ratings"].items()}

    def prepare_units(self, units, campaign=False):
        groups = synergy_groups(units)
        for unit in units:
            cid = unit["card_id"]
            unit["synergy"] = next((g for g in groups if cid in g["members"]), None)
            bonus = unit["synergy"]["bonus"] if unit["synergy"] else 0
            unit["relic_effects"] = []
            unit["choice_bonus"] = 0
            unit["mastery_growth_bonus"] = 0
            if campaign:
                unit["ratings"] = self.permanent_ratings(cid)
                growth = self.s["progression"].get(cid, {}).get("mastery", {}).get(unit["champion"], 0)
                unit["mastery"] = round(min(100, unit["mastery"]+growth), 2)
            unit["permanent_ratings"] = dict(unit["ratings"])
            unit["permanent_mastery"] = unit["mastery"]
            # Linked teammates coordinate better, in addition to their own growth.
            for stat in ("combat", "vision"):
                unit["ratings"][stat] += bonus
            if campaign:
                effects = [(rid, item["target"]) for rid, item in self.s["relics"].items()
                           if RELICS[rid]["kind"] != "consumable"]
                effects += [(rid, None) for rid in self.s["prepared_relics"]]
                for rid, target in effects:
                    relic = RELICS[rid]
                    if relic["kind"] in ("player", "mastery") and target != cid:
                        continue
                    unit["relic_effects"].append(rid)
                    for stat, amount in relic.get("stats", {}).items():
                        unit["ratings"][stat] += amount
                    unit["mastery"] += relic.get("mastery", 0)
                    unit["mastery_growth_bonus"] += relic.get("growth", 0)
                    unit["choice_bonus"] += relic.get("choice", 0)
                    if "condition_floor" in relic:
                        unit["condition_floor"] = relic["condition_floor"]
            unit["ratings"] = {k: round(bound(v, 1, 99), 2) for k, v in unit["ratings"].items()}
            unit["mastery"] = round(min(100, unit["mastery"]), 2)
            unit["overall"] = round(sum(unit["ratings"].values()) / 4, 2)
        return units

    def relic_block(self, rid):
        relic = RELICS[rid]
        owned = self.s["relics"]
        if rid in owned and (relic["kind"] != "consumable" or owned[rid]["count"] >= 3):
            return "이미 보유한 유물입니다." if relic["kind"] != "consumable" else "소비성 유물은 종류별 3개까지 보관합니다."
        group = relic.get("exclusive")
        for other in (*owned, *self.s["prepared_relics"]):
            if other != rid and group and RELICS[other].get("exclusive") == group:
                return f'{RELICS[other]["name"]}와 동시 소유할 수 없습니다. ({group})'
        return None

    def acquire_relic(self, rid):
        error = self.relic_block(rid)
        if error:
            raise ValueError(error)
        target = self.s["roster"].get("mid") if RELICS[rid]["kind"] in ("player", "mastery") else None
        item = self.s["relics"].setdefault(rid, {"count": 0, "target": target})
        item["count"] += 1

    def campaign_action(self, action):
        kind, rid = action["type"], action.get("relic")
        if not self.s["starter"]["finished"]:
            raise ValueError("구단 창단을 먼저 완료해주세요.")
        if self.active() and kind != "use_relic":
            raise ValueError("경기 종료 후 변경할 수 있습니다.")
        if kind == "reward_choice":
            event = self.s["reward_event"]
            if not event or action.get("option") not in (*event["relics"], "credits"):
                raise ValueError("현재 선택할 수 없는 보상입니다.")
            choice = action["option"]
            if choice == "credits":
                self.s["coins"] += 100
                self.s["notice"] = "유물 대신 연구 지원금 +100 CR을 받았습니다."
            else:
                self.acquire_relic(choice)
                self.s["notice"] = f'{RELICS[choice]["name"]} 획득! 지정 유물은 미드 선수에게 배정되며 유물 보관함에서 변경할 수 있습니다.'
            self.s["reward_event"] = None
            return
        if not isinstance(rid, str) or rid not in RELICS:
            raise ValueError("존재하지 않는 유물입니다.")
        relic = RELICS[rid]
        if kind == "buy_relic":
            if self.s["coins"] < relic["price"]:
                raise ValueError("크레딧이 부족합니다.")
            self.acquire_relic(rid)
            self.s["coins"] -= relic["price"]
            self.s["notice"] = f'{relic["name"]} 구매 완료'
        elif kind == "assign_relic":
            target = action.get("card")
            if rid not in self.s["relics"] or relic["kind"] not in ("player", "mastery") or target not in self.s["owned"]:
                raise ValueError("보유 유물과 보유 선수를 선택해주세요.")
            self.s["relics"][rid]["target"] = target
            self.s["notice"] = f'{relic["name"]} → {self.cards[target]["name"]}'
        elif kind == "use_relic":
            if rid not in self.s["relics"] or relic["kind"] != "consumable":
                raise ValueError("보유 중인 소비성 유물만 사용할 수 있습니다.")
            if relic["timing"] == "event":
                if not self.active() or not self.match.s.get("progression_rules") or not self.match.s["event"]:
                    raise ValueError("새 규칙 경기의 전술 선택 대기 중에 사용하세요.")
                event = self.match.s["event"]
                if rid in event["used_relics"]:
                    raise ValueError("이번 선택에서는 이미 사용했습니다.")
                event["used_relics"].append(rid)
                event["relic_bonus"] += relic["choice"]
                self.match.refresh_relic_chances()
                self.match.log("relic", f'{relic["name"]} 사용 · 이번 전술 성공률 +12%p (최대 98%)', 0)
            else:
                if self.active() or rid in self.s["prepared_relics"]:
                    raise ValueError("경기 전에 한 번만 준비할 수 있습니다.")
                self.s["prepared_relics"].append(rid)
            self.s["relics"][rid]["count"] -= 1
            if not self.s["relics"][rid]["count"]:
                del self.s["relics"][rid]
            self.s["notice"] = f'{relic["name"]} 사용 완료'

    def settle_progression(self, won):
        match = self.match.s
        report = []
        minutes = max(1, match["time"] / 60)
        for unit in match["teams"][0]:
            cid, champion = unit["card_id"], unit["champion"]
            progress = self.s["progression"].setdefault(cid, {"stats": dict.fromkeys(STATS, 0), "mastery": {}, "games": 0, "wins": 0})
            # Support is scored by participation and saves, not solo farm/kills.
            involvement = (unit["kills"] + unit["assists"]*.8) / max(1, unit["deaths"])
            farm = unit["cs"] / minutes / (2 if unit["role"] == "sup" else 7)
            score = round(bound(involvement*.45 + min(1.5, farm)*.6 + unit["saves"]*.15, 0, 5), 2)
            base = .12 + .10*won + score*.045
            deltas = {}
            for stat in STATS:
                extra = min(.20, unit["saves"]*.04 + unit["assists"]*.005) if stat == "vision" else min(.20, farm*.08) if stat == "farm" else min(.20, involvement*.025) if stat == "combat" else 0
                before = self.permanent_ratings(cid)[stat]
                delta = round(min(99-before, base+extra), 2)
                progress["stats"][stat] = round(progress["stats"][stat]+delta, 2)
                deltas[stat] = delta
            raw_mastery = next((p["mastery"] for p in self.champion_pool(self.cards[cid]) if p["id"] == champion), 35)
            before = min(100, raw_mastery + progress["mastery"].get(champion, 0))
            mastery_delta = round(min(100-before, (.50 + .35*won + score*.25)*(1+unit.get("mastery_growth_bonus", 0))), 2)
            progress["mastery"][champion] = round(progress["mastery"].get(champion, 0)+mastery_delta, 2)
            progress["games"] += 1
            progress["wins"] += int(won)
            report.append({"card_id": cid, "name": unit["name"], "role": unit["role"], "champion": champion,
                           "score": score, "kda": f'{unit["kills"]}/{unit["deaths"]}/{unit["assists"]}',
                           "stats": deltas, "mastery": mastery_delta, "mastery_after": round(before+mastery_delta, 2)})
        self.s["last_growth"] = report
        match["growth_report"] = deepcopy(report)
        # A new opportunity after every match. Do not reroll on viewing or loading.
        pool = [rid for rid in RELICS if not self.relic_block(rid)]
        offers = []
        for _ in range(min(3, len(pool))):
            pick = self.rng.pick(pool)
            offers.append(pick)
            pool.remove(pick)
        self.s["reward_event"] = {"title": "경기 후 발견한 전리품", "relics": offers}
