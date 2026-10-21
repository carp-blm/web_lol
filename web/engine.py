"""Nexus Archive: deterministic Python simulation and campaign, CPython/Pyodide.

No clock, network, pickle, eval or hidden preselected winner. Every random draw uses
the serialized seed/action history. A match ends only when a nexus reaches zero.
"""
import copy
import hashlib
import json
import re
from abilities import AbilityRules

ENGINE_VERSION = "2.0.0"
ROLES = ("top", "jng", "mid", "bot", "sup")
LANES = ("top", "mid", "bot")
ROLE_NAMES = {"top": "탑", "jng": "정글", "mid": "미드", "bot": "바텀", "sup": "서포터"}
TEAM_NAMES = ["NEXUS CLUB", "SEOUL COMETS", "PACIFIC FOXES", "BERLIN ECHO", "SHANGHAI NOVA", "ATLANTIC WAVE"]


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class RNG:
    """Xorshift32. Stable across Python releases and WebAssembly."""
    def __init__(self, seed):
        self.state = int(seed) & 0xFFFFFFFF or 0x9E3779B9

    def next(self):
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state

    def random(self):
        return self.next() / 4294967296

    def pick(self, items):
        if not items:
            raise ValueError("선택할 항목이 없습니다.")
        return items[self.next() % len(items)]

    def integer(self, low, high):
        return low + self.next() % (high - low + 1)


def normalize(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


class Match(AbilityRules):
    def __init__(self, blue, red, seed, champions):
        self.rng = RNG(seed)
        self.champions = champions
        self.s = {"seed": seed, "time": 0, "tick": 0, "winner": None,
                  "teams": [blue, red], "gold": [2500, 2500], "kills": [0, 0],
                  "nexus": [4000, 4000], "towers": [{l: 3 for l in LANES} for _ in range(2)],
                  "tower_hp": [{l: 1500 for l in LANES} for _ in range(2)],
                  "inhibitors": [{l: 1800 for l in LANES} for _ in range(2)],
                  "pressure": {l: 0 for l in LANES}, "vision": [0, 0], "momentum": [0, 0],
                  "dragons": [0, 0], "barons": [0, 0], "heralds": [0, 0],
                  "buff_until": [0, 0], "next_dragon": 300, "next_baron": 1200,
                  "herald_available": True, "event": None, "next_event": 150,
                  "followup": None, "log": [], "decisions": [], "claimed": False}
        self.initialize_abilities()
        self.log("system", "경기 시작. 모든 연도 카드에 동일한 경기 규칙이 적용됩니다.")

    def log(self, kind, text, side=None, skill=None):
        self.s["log"].append({"time": self.s["time"], "kind": kind, "text": text,
                              "side": side, "skill": skill})
        self.s["log"] = self.s["log"][-160:]

    def unit(self, side, role):
        return next(u for u in self.s["teams"][side] if u["role"] == role)

    def power(self, side, role=None):
        units = [self.unit(side, role)] if role else self.s["teams"][side]
        base = sum(u["overall"] + (u["mastery"] - 60) * .17 for u in units) / len(units)
        return base + (self.s["gold"][side] - self.s["gold"][1-side]) / 1800 + self.s["momentum"][side] * 1.5 + self.s["dragons"][side] * 1.2

    def odds(self, role=None):
        return clamp(.5 + (self.power(0, role) - self.power(1, role)) / 110
                     + (self.s["vision"][0] - self.s["vision"][1]) * .008, .16, .84)

    def push(self, side, lane, damage):
        s, target = self.s, 1-side
        if s["towers"][target][lane] > 0:
            s["tower_hp"][target][lane] -= damage
            if s["tower_hp"][target][lane] <= 0:
                s["towers"][target][lane] -= 1
                s["tower_hp"][target][lane] = 1500 if s["towers"][target][lane] else 0
                s["gold"][side] += 500
                self.log("tower", f'{"우리" if side == 0 else "상대"} 팀이 {ROLE_NAMES[lane]} 포탑을 파괴했습니다.', side)
        elif s["inhibitors"][target][lane] > 0:
            s["inhibitors"][target][lane] = max(0, s["inhibitors"][target][lane] - damage)
            if s["inhibitors"][target][lane] == 0:
                self.log("tower", f'{ROLE_NAMES[lane]} 억제기 파괴! 넥서스 진격로가 열립니다.', side)
        else:
            s["nexus"][target] = max(0, s["nexus"][target] - damage)
            self.log("nexus", f'{"상대" if side == 0 else "우리"} 넥서스에 {damage} 피해.', side)
            if s["nexus"][target] == 0:
                s["winner"] = side
                s["event"] = None
                self.log("end", f'{"우리" if side == 0 else "상대"} 팀 승리 — 넥서스가 파괴되었습니다.', side)

    def objective(self, side, kind):
        s = self.s
        if kind == "dragon":
            s["dragons"][side] += 1
            s["next_dragon"] = s["time"] + 300
            label = "드래곤"
        elif kind == "baron":
            s["barons"][side] += 1
            s["next_baron"] = s["time"] + 360
            s["buff_until"][side] = s["time"] + 180
            label = "바론"
        else:
            s["heralds"][side] += 1
            s["herald_available"] = False
            label = "전령"
        s["gold"][side] += 650 if kind == "baron" else 350
        self.log("objective", f'{"우리" if side == 0 else "상대"} 팀이 {label}을 확보했습니다.', side)

    def available_objective(self):
        s = self.s
        if s["time"] >= s["next_baron"]:
            return "baron"
        if s["time"] >= s["next_dragon"]:
            return "dragon"
        if 480 <= s["time"] < 1200 and s["herald_available"]:
            return "herald"
        return None

    def make_event(self):
        s = self.s
        lane = min(LANES, key=lambda l: s["pressure"][l]) if self.rng.random() < .5 else self.rng.pick(LANES)
        obj = self.available_objective()
        follow = s["followup"]
        s["followup"] = None
        kind = "followup" if follow else "objective" if obj else self.rng.pick(["gank", "vision", "lane"] if s["time"] < 900 else ["teamfight", "vision", "siege"])
        role = "jng" if kind in ("objective", "gank") else "sup" if kind == "vision" else lane
        unit = self.unit(0, role)
        ready = self.ready_skills(unit)
        preferred = {"gank": "cc", "objective": "execute", "vision": "protect", "teamfight": "aoe", "siege": "damage", "lane": "mobility", "followup": "cc"}[kind]
        skill = next((x for x in ready if preferred in x["tags"]), ready[-1] if ready else {"key": "AA", "name": "기본 공격", "tags": ["damage"], "icon": "assets/skill-placeholder.svg"})
        p = round(clamp(self.odds(role) + (unit["mastery"] - 60) / 400 + (.06 if preferred in skill["tags"] else 0), .18, .88), 2)
        label = {"dragon": "드래곤", "baron": "바론", "herald": "전령"}.get(obj, "라인 주도권")
        titles = {"lane": f'{ROLE_NAMES[lane]}의 작은 틈', "gank": f'{ROLE_NAMES[lane]} 갱킹 타이밍',
                  "vision": "강가의 사라진 시야", "objective": f'{label}, 지금 승부를 볼까?',
                  "teamfight": "한 번의 이니시에이팅", "siege": "포위망을 좁혀라",
                  "followup": "상대의 역갱" if follow == "countergank" else "심어 둔 와드의 보상"}
        context = f'{s["time"]//60}:{s["time"]%60:02d} · 골드 격차 {s["gold"][0]-s["gold"][1]:+,} · {ROLE_NAMES[lane]} 압박 {s["pressure"][lane]:+d}'
        story = (f'{unit["name"]}의 {self.champions[unit["champion"]]["name"]}, {self.skill_label(skill)} 사용 가능. '
                 f'숙련도 {unit["mastery"]}. ' +
                 ("앞선 공격적인 선택을 읽은 상대가 측면으로 들어옵니다." if follow == "countergank" else
                  "앞서 확보한 시야에서 상대의 동선이 드러났습니다." if follow else
                  f'{label}을 두고 상대와 동선이 겹칩니다.'))
        options = [
            {"id": "commit", "label": f'{self.skill_label(skill)}로 승부', "chance": p,
             "detail": "+650G · 라인 압박 / 실패 시 상대 +500G · 역갱 위험", "effect": "commit"},
            {"id": "vision", "label": "시야를 먼저 확보", "chance": round(clamp(p+.16, .3, .96), 2),
             "detail": "150G 사용 · 성공 시 시야 +3 · 후속 기회", "effect": "vision"},
            {"id": "trade", "label": "반대편에서 교환", "chance": round(clamp(.72 + (s["gold"][0]-s["gold"][1])/100000, .5, .9), 2),
             "detail": "+300G · 반대 라인 압박 / 오브젝트는 상대에게", "effect": "trade"}]
        if s["gold"][0] < 150:
            options = [o for o in options if o["id"] != "vision"]
        if kind == "followup":
            options.append({"id": "disengage", "label": "전열을 지키며 후퇴", "chance": .95,
                            "detail": "성공 시 사기 +1 / 라인 압박 양보", "effect": "disengage"})
        s["event"] = {"id": f'e-{s["tick"]}', "kind": kind, "title": titles[kind], "context": context,
                      "story": story, "lane": lane, "role": role, "objective": obj,
                      "skill": skill, "options": options}

    def choose(self, option_id):
        s = self.s
        event = s["event"]
        if not event or s["winner"] is not None:
            raise ValueError("현재 선택할 이벤트가 없습니다.")
        option = next((o for o in event["options"] if o["id"] == option_id), None)
        if option is None:
            raise ValueError("유효하지 않은 이벤트 선택입니다.")
        success = self.rng.random() < option["chance"]
        lane, kind = event["lane"], option["effect"]
        if kind == "commit":
            unit = self.unit(0, event["role"])
            self.spend_skill(unit, event["skill"])
            side = 0 if success else 1
            s["gold"][side] += 650 if success else 500
            s["kills"][side] += 1
            self.after_encounter(self.unit(side, event["role"]), self.unit(1-side, event["role"]), True)
            s["momentum"][side] = min(6, s["momentum"][side]+1)
            s["pressure"][lane] = int(clamp(s["pressure"][lane] + (2 if success else -2), -8, 8))
            self.push(side, lane, 350 + s["time"]//8)
            if event["objective"]:
                self.objective(side, event["objective"])
            s["followup"] = "countergank" if event["kind"] != "followup" else None
        elif kind == "vision":
            s["gold"][0] -= 150
            s["vision"][0] = min(10, s["vision"][0]+3) if success else max(0, s["vision"][0]-1)
            if success:
                s["followup"] = "vision_pick" if event["kind"] != "followup" else None
        elif kind == "trade":
            opposite = "bot" if lane != "bot" else "top"
            if success:
                s["gold"][0] += 300
                s["pressure"][opposite] = min(8, s["pressure"][opposite]+2)
                self.push(0, opposite, 300 + s["time"]//10)
            else:
                s["gold"][1] += 250
            if event["objective"]:
                self.objective(1, event["objective"])
        else:
            s["pressure"][lane] = max(-8, s["pressure"][lane]-1)
            if success:
                s["momentum"][0] = min(6, s["momentum"][0]+1)
            else:
                s["gold"][1] += 200
        s["decisions"].append({"event": event["id"], "kind": event["kind"], "choice": option_id,
                                "success": success, "chance": option["chance"], "time": s["time"]})
        self.log("decision", f'{option["label"]} — {"성공" if success else "실패"} ({round(option["chance"]*100)}%).', 0, event["skill"])
        s["event"] = None
        s["next_event"] = s["time"] + self.rng.integer(120, 240)

    def step(self):
        s = self.s
        if s["winner"] is not None or s["event"]:
            return
        dt = self.rng.integer(24, 38)
        s["time"] += dt
        s["tick"] += 1
        self.advance_forms(dt)
        for side in (0, 1):
            farm = sum(u["ratings"]["farm"] for u in s["teams"][side])/5
            s["gold"][side] += round(dt*(25 + farm/12))
        lane = self.rng.pick(LANES)
        role = "jng" if self.rng.random() < .18 else lane
        side = 0 if self.rng.random() < self.odds(role) else 1
        unit = self.unit(side, role)
        skill = self.use_skill(unit, "aoe" if s["time"] > 900 else "cc")
        tag_bonus = 70 if "aoe" in skill["tags"] and s["time"] > 900 else 45 if "cc" in skill["tags"] else 0
        kill = self.rng.random() < (.34 if s["time"] < 900 else .56)
        self.after_encounter(unit, self.unit(1-side, role), kill)
        if kill:
            count = self.rng.integer(1, 3) if s["time"] > 900 else 1
            s["kills"][side] += count
            s["gold"][side] += 300*count
        s["pressure"][lane] = int(clamp(s["pressure"][lane] + (1 if side == 0 else -1), -8, 8))
        phase = "한타" if s["time"] >= 900 else "갱킹" if role == "jng" else "라인전"
        self.log("fight" if kill else "lane", f'{ROLE_NAMES[lane]} {phase} · {unit["name"]}의 {self.champions[unit["champion"]]["name"]} '
                 f'{self.skill_label(skill)}! {"킬을 만들었습니다." if kill else "주도권을 가져옵니다."}', side, skill)
        if s["time"] > 480:
            # Scaling siege pressure avoids endless stalemates but never assigns a timer winner.
            damage = round(180 + s["time"]*.13 + tag_bonus + (220 if s["buff_until"][side] > s["time"] else 0))
            if s["time"] > 1800 and self.rng.random() < .65:
                lane = min(LANES, key=lambda l: s["towers"][1-side][l]*1500 + s["inhibitors"][1-side][l])
            self.push(side, lane, damage)
        if s["winner"] is not None:
            return
        if s["time"] >= s["next_event"]:
            self.make_event()
        elif self.available_objective() and self.rng.random() < .4:
            self.objective(0 if self.rng.random() < self.odds() else 1, self.available_objective())
        if s["tick"] % 12 == 0:
            s["vision"] = [max(0, v-1) for v in s["vision"]]
            s["momentum"] = [max(0, v-1) for v in s["momentum"]]

    def simulate(self):
        # Only a safety assertion, never a substitute win condition.
        for _ in range(2000):
            if self.s["winner"] is not None:
                return self.s["winner"]
            if self.s["event"]:
                self.choose(self.rng.pick(self.s["event"]["options"])["id"])
            else:
                self.step()
        raise RuntimeError("Simulation invariant failed: no nexus destroyed")


class Game:
    def __init__(self, catalog, champion_data, seed="NEXUS-2026"):
        if not isinstance(seed, str) or not 1 <= len(seed) <= 80:
            raise ValueError("시드는 1~80자 문자열이어야 합니다.")
        self.catalog, self.champion_data = catalog, champion_data
        self.cards = {c["id"]: c for c in catalog["cards"]}
        self.champions = champion_data["champions"]
        self.aliases = {normalize(k): k for k in self.champions}
        self.aliases["monkeyking"] = "MonkeyKing"
        self.aliases["wukong"] = "MonkeyKing"
        self.seed = seed
        self.rng = RNG(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))
        self.actions = []
        self.legacy_save = None
        self.match = None
        self.s = {"schema": 1, "seed": seed, "coins": 600, "owned": [], "roster": {},
                  "draft": {}, "season": None, "season_number": 0, "last_pull": None,
                  "notice": "리그와 연도를 골라 포지션별 무료 팩 5개를 열어주세요.", "trophies": 0,
                  "starter": {"finished": False, "packs": {
                      r: {"league": "any", "year": "any", "card": None} for r in ROLES}}}

    def starter_pool(self, role, filters=None):
        pack = filters or self.s["starter"]["packs"][role]
        people = {self.cards[cid]["player_id"] for cid in self.s["owned"]}
        return [c for c in self.catalog["cards"] if c["role"] == role
                and (pack["league"] == "any" or c["league"] == pack["league"])
                and (pack["year"] == "any" or str(c["year"]) == pack["year"])
                and c["player_id"] not in people]

    def champion_pool(self, card):
        out = []
        for m in card["mastery"]:
            cid = self.aliases.get(normalize(m["name"]))
            if cid and cid in self.champions:
                out.append({"id": cid, "mastery": m["value"], "games": m["games"]})
        return out

    def reset_draft(self):
        used = set()
        for role in ROLES:
            pool = self.champion_pool(self.cards[self.s["roster"][role]])
            pick = next((p["id"] for p in pool if p["id"] not in used), None)
            if not pick:
                pick = next(c for c in sorted(self.champions) if c not in used)
            self.s["draft"][role] = pick
            used.add(pick)

    def units(self, ids, draft=None):
        units, used = [], set()
        for cid in ids:
            c = self.cards[cid]
            pool = self.champion_pool(c)
            chosen = draft[c["role"]] if draft else next((p["id"] for p in pool if p["id"] not in used), None)
            chosen = chosen or next(x for x in sorted(self.champions) if x not in used)
            mastery = next((p["mastery"] for p in pool if p["id"] == chosen), 35)
            units.append({"card_id": cid, "name": c["name"], "role": c["role"], "overall": c["overall"],
                          "ratings": c["ratings"], "champion": chosen, "mastery": mastery, "cooldowns": {}})
            used.add(chosen)
        return units

    def random_roster(self, target):
        roster, people = [], set()
        for role in ROLES:
            pool = [c for c in self.catalog["cards"] if c["role"] == role and c["player_id"] not in people and abs(c["overall"]-target) < 9]
            c = self.rng.pick(pool)
            roster.append(c["id"])
            people.add(c["player_id"])
        return roster

    def new_season(self):
        self.s["season_number"] += 1
        teams = [{"name": TEAM_NAMES[0], "roster": [], "wins": 0, "losses": 0}]
        for i in range(1, 6):
            teams.append({"name": TEAM_NAMES[i], "roster": self.random_roster(68+i*2), "wins": 0, "losses": 0})
        rotation, schedule = list(range(6)), []
        for _ in range(5):
            schedule.append([[rotation[i], rotation[5-i]] for i in range(3)])
            rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
        self.s["season"] = {"phase": "regular", "round": 0, "teams": teams, "schedule": schedule,
                            "history": [], "series": [0, 0], "opponent": None, "finalist": None,
                            "champion": None, "standings": list(range(6))}

    def simulate_ai(self, a, b):
        teams = self.s["season"]["teams"]
        match = Match(self.units(teams[a]["roster"]), self.units(teams[b]["roster"]), self.rng.next(), self.champions)
        winner = a if match.simulate() == 0 else b
        return winner

    def simulate_series(self, a, b):
        wins = {a: 0, b: 0}
        while max(wins.values()) < 2:
            wins[self.simulate_ai(a, b)] += 1
        return max(wins, key=wins.get)

    def opponent(self):
        season = self.s["season"]
        if season["phase"] == "regular":
            pair = next(p for p in season["schedule"][season["round"]] if 0 in p)
            return next(x for x in pair if x != 0)
        return season["opponent"]

    def settle(self):
        m = self.match.s
        if m["winner"] is None or m["claimed"]:
            return
        m["claimed"] = True
        season = self.s["season"]
        won = m["winner"] == 0
        reward = 240 if won else 140
        self.s["coins"] += reward
        opp = self.opponent()
        season["history"].append({"opponent": opp, "won": won, "phase": season["phase"], "duration": m["time"], "seed": m["seed"], "reward": reward})
        self.s["notice"] = f'{"승리" if won else "패배"} 보상 +{reward} 크레딧'
        if season["phase"] == "regular":
            for a, b in season["schedule"][season["round"]]:
                winner = (0 if won else opp) if 0 in (a, b) else self.simulate_ai(a, b)
                loser = b if winner == a else a
                season["teams"][winner]["wins"] += 1
                season["teams"][loser]["losses"] += 1
            season["round"] += 1
            # Transparent deterministic tie-break: wins, direct result for human is not privileged, team index.
            season["standings"] = sorted(range(6), key=lambda i: (-season["teams"][i]["wins"], i))
            if season["round"] == 5:
                top = season["standings"][:4]
                if 0 not in top:
                    season["phase"] = "complete"
                    a = self.simulate_series(top[0], top[3])
                    b = self.simulate_series(top[1], top[2])
                    season["champion"] = self.simulate_series(a, b)
                else:
                    pairs = [[top[0], top[3]], [top[1], top[2]]]
                    mine = next(p for p in pairs if 0 in p)
                    other = next(p for p in pairs if 0 not in p)
                    season["opponent"] = next(i for i in mine if i != 0)
                    season["finalist"] = self.simulate_series(*other)
                    season["phase"] = "semifinal"
                    self.s["coins"] += 200
        else:
            season["series"][0 if won else 1] += 1
            if max(season["series"]) == 2:
                if season["series"][1] == 2:
                    season["champion"] = (self.simulate_series(opp, season["finalist"])
                                            if season["phase"] == "semifinal" else opp)
                    season["phase"] = "complete"
                elif season["phase"] == "semifinal":
                    season["phase"] = "final"
                    season["opponent"] = season["finalist"]
                    season["series"] = [0, 0]
                    self.s["coins"] += 300
                else:
                    season["phase"] = "complete"
                    season["champion"] = 0
                    self.s["trophies"] += 1
                    self.s["coins"] += 600

    def active(self):
        return self.match is not None and self.match.s["winner"] is None

    def apply(self, action, record=True):
        if not isinstance(action, dict) or not isinstance(action.get("type"), str):
            raise ValueError("잘못된 명령입니다.")
        if record and len(self.actions) >= 12000:
            raise ValueError("세이브 기록이 가득 찼습니다. 내보낸 뒤 새 게임을 시작하세요.")
        kind = action["type"]
        starter = self.s["starter"]
        if kind.startswith("starter_") and starter["finished"]:
            raise ValueError("시작 팩은 이미 모두 사용했습니다.")
        if kind in ("pull", "equip", "draft", "start", "next_season") and not starter["finished"]:
            raise ValueError("포지션별 팩 5개를 열고 구단 창단을 완료해주세요.")
        if kind in ("pull", "equip", "draft", "start", "next_season") and self.active():
            raise ValueError("경기 종료 후 변경할 수 있습니다.")
        if kind in ("starter_filter", "starter_open"):
            role = action.get("role")
            if role not in ROLES:
                raise ValueError("잘못된 포지션입니다.")
            pack = starter["packs"][role]
            if pack["card"]:
                raise ValueError("이 포지션 팩은 이미 열었습니다.")
            if kind == "starter_filter":
                league, year = action.get("league", pack["league"]), str(action.get("year", pack["year"]))
                if league not in {"any", *(c["league"] for c in self.catalog["cards"])}:
                    raise ValueError("지원하지 않는 리그입니다.")
                if year not in {"any", *(str(c["year"]) for c in self.catalog["cards"])}:
                    raise ValueError("지원하지 않는 연도입니다.")
                pack.update(league=league, year=year)
            else:
                pool = self.starter_pool(role)
                if not pool:
                    raise ValueError("이 조건에서 뽑을 선수가 없습니다. 리그나 연도를 바꿔주세요.")
                card = self.rng.pick(pool)
                pack["card"] = card["id"]
                self.s["owned"].append(card["id"])
                self.s["roster"][role] = card["id"]
                self.s["notice"] = f'{ROLE_NAMES[role]} 팩 · {card["year"]} {card["name"]} 영입!'
        elif kind == "starter_finish":
            if any(not p["card"] for p in starter["packs"].values()):
                raise ValueError("포지션별 팩 5개를 먼저 열어주세요.")
            starter["finished"] = True
            self.reset_draft()
            self.new_season()
            self.s["notice"] = "드림팀 창단 완료! 무료 크레딧 600으로 다음 선수를 만나보세요."
        elif kind == "pull":
            role = action.get("role", "any")
            if role not in (*ROLES, "any"):
                raise ValueError("잘못된 포지션입니다.")
            cost = 150 if role == "any" else 200
            if self.s["coins"] < cost:
                raise ValueError("크레딧이 부족합니다. 경기를 마치면 보상을 받습니다.")
            pool = [c for c in self.catalog["cards"] if role == "any" or c["role"] == role]
            card = self.rng.pick(pool)
            self.s["coins"] -= cost
            duplicate = card["id"] in self.s["owned"]
            if duplicate:
                self.s["coins"] += 90
            else:
                self.s["owned"].append(card["id"])
            self.s["last_pull"] = {"id": card["id"], "duplicate": duplicate}
            self.s["notice"] = f'{card["year"]} {card["name"]} 영입' + (" · 중복 90 크레딧 환급" if duplicate else "!")
        elif kind == "equip":
            cid = action.get("card")
            if cid not in self.s["owned"]:
                raise ValueError("보유 카드만 편성할 수 있습니다.")
            c = self.cards[cid]
            if any(self.cards[i]["player_id"] == c["player_id"] for role, i in self.s["roster"].items() if role != c["role"]):
                raise ValueError("동일 선수를 다른 연도 카드로 중복 출전시킬 수 없습니다.")
            self.s["roster"][c["role"]] = cid
            self.reset_draft()
        elif kind == "draft":
            role, champion = action.get("role"), action.get("champion")
            if role not in ROLES or champion not in self.champions:
                raise ValueError("잘못된 챔피언 선택입니다.")
            if any(c == champion for r, c in self.s["draft"].items() if r != role):
                raise ValueError("팀 내 같은 챔피언을 중복 선택할 수 없습니다.")
            self.s["draft"][role] = champion
        elif kind == "start":
            if self.s["season"]["phase"] == "complete":
                raise ValueError("시즌이 끝났습니다. 새 시즌을 시작하세요.")
            opponent = self.opponent()
            ids = [self.s["roster"][r] for r in ROLES]
            self.match = Match(self.units(ids, self.s["draft"]), self.units(self.s["season"]["teams"][opponent]["roster"]), self.rng.next(), self.champions)
            self.match.s["opponent_name"] = self.s["season"]["teams"][opponent]["name"]
        elif kind == "tick":
            steps = action.get("steps", 1)
            if type(steps) is not int or not 1 <= steps <= 10 or not self.match:
                raise ValueError("잘못된 경기 진행 요청입니다.")
            for _ in range(steps):
                self.match.step()
            self.settle()
        elif kind == "choose":
            if not self.match:
                raise ValueError("진행 중인 경기가 없습니다.")
            self.match.choose(action.get("option"))
            self.settle()
        elif kind == "next_season":
            if self.s["season"]["phase"] != "complete":
                raise ValueError("현재 시즌을 먼저 마쳐주세요.")
            self.match = None
            self.new_season()
        else:
            raise ValueError("지원하지 않는 명령입니다.")
        if record:
            self.actions.append(copy.deepcopy(action))
        return None

    def view(self):
        match = copy.deepcopy(self.match.s) if self.match else None
        if match and isinstance(self.match, Match):
            for side, team in enumerate(match["teams"]):
                for index, unit in enumerate(team):
                    unit["available_skills"] = self.match.ready_skills(self.match.s["teams"][side][index])
        return {**copy.deepcopy(self.s), "match": match,
                "engine": ENGINE_VERSION, "dataset": self.catalog["version"],
                "starter_counts": {r: len(self.starter_pool(r)) for r in ROLES}
                if not self.s["starter"]["finished"] else {},
                "save_actions": len(self.actions)}

    def export_save(self):
        payload = {"schema": 2, "engine": ENGINE_VERSION, "dataset": self.catalog["version"],
                   "champions": self.champion_data["version"],
                   "mechanics": self.champion_data.get("revision", self.champion_data["version"]),
                   "seed": self.seed, "actions": self.actions, "legacy": self.legacy_save}
        payload["checksum"] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def import_save(cls, text, catalog, champions):
        if not isinstance(text, str) or len(text.encode()) > 4_000_000:
            raise ValueError("세이브는 4MB 이하의 JSON 파일이어야 합니다.")
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError()
            checksum = data.pop("checksum")
            expected = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if checksum != expected:
                raise ValueError("세이브 무결성 검사에 실패했습니다.")
            if data["schema"] == 1 and data["engine"] == "1.0.0":
                return cls.migrate_legacy(text, catalog, champions)
            if data["schema"] != 2 or data["engine"] != ENGINE_VERSION:
                raise ValueError("다른 버전의 세이브입니다.")
            if (data["dataset"] != catalog["version"] or data["champions"] != champions["version"]
                    or data.get("mechanics") != champions.get("revision", champions["version"])):
                raise ValueError("데이터 버전이 다릅니다. 저장 당시 버전의 게임에서 불러오세요. 기존 세이브는 보존됩니다.")
            actions = data["actions"]
            if not isinstance(actions, list) or len(actions) > 12000:
                raise ValueError("세이브 동작 수가 허용 범위를 초과했습니다.")
            candidate = (cls.migrate_legacy(data["legacy"], catalog, champions)
                         if data.get("legacy") else cls(catalog, champions, data["seed"]))
            if candidate.seed != data["seed"]:
                raise ValueError("세이브의 시작 시드가 일치하지 않습니다.")
            for action in actions:
                candidate.apply(action)
            return candidate
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("올바른 Nexus Archive 세이브가 아닙니다.") from exc

    @classmethod
    def migrate_legacy(cls, text, catalog, champions):
        # Replay with the unchanged v1 rules first. Never replace a user's earned roster.
        from legacy_engine import Game as LegacyGame
        old = LegacyGame.import_save(text, catalog, champions)
        candidate = cls(catalog, champions, old.seed)
        candidate.s = copy.deepcopy(old.s)
        candidate.s["starter"] = {"finished": True, "packs": {
            r: {"league": "any", "year": "any", "card": old.s["roster"][r]} for r in ROLES}}
        candidate.s["notice"] = "기존 선수·재화·시즌을 보존했습니다. 다음 경기부터 새 스킬 규칙을 적용합니다."
        candidate.rng.state = old.rng.state
        candidate.legacy_save = text
        # In-flight v1 matches finish under v1 rules; future matches use the new engine.
        candidate.match = old.match
        return candidate


class Bridge:
    def __init__(self, catalog_json, champions_json):
        self.catalog = json.loads(catalog_json)
        self.champions = json.loads(champions_json)
        self.game = Game(self.catalog, self.champions)

    def call(self, request_json):
        try:
            req = json.loads(request_json)
            kind = req.get("type")
            if kind == "new":
                self.game = Game(self.catalog, self.champions, req.get("seed", "NEXUS-2026"))
            elif kind == "import":
                candidate = Game.import_save(req["save"], self.catalog, self.champions)
                self.game = candidate
            elif kind not in ("view", "export"):
                self.game.apply(req)
            return json.dumps({"ok": True, "state": self.game.view(), "save": self.game.export_save()}, ensure_ascii=False)
        except (ValueError, KeyError, TypeError) as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
