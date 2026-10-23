"""Nexus Archive: deterministic Python simulation and campaign, CPython/Pyodide.

No clock, network, pickle, eval or hidden preselected winner. Every random draw uses
the serialized seed/action history. A match ends only when a nexus reaches zero.
"""
import copy
import hashlib
import json
import re
from abilities import AbilityRules
from combat import CombatRules
from progression import CampaignRules, ProgressionMatchRules, RELICS
from match_features import MatchFeatures
from draft import DraftRules
from legacy_engine_v2 import Match as PreviousMatch

ENGINE_VERSION = "4.0.0"
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


class Match(MatchFeatures, ProgressionMatchRules, CombatRules, AbilityRules, PreviousMatch):
    def __init__(self, blue, red, seed, champions):
        super().__init__(blue, red, seed, champions)
        self.initialize_combat()
        self.initialize_progression()
        self.initialize_match_features()



class Game(DraftRules, CampaignRules):
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
        self.initialize_campaign()
        self.s["banpick"] = None

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

    def units(self, ids, draft=None, campaign=None):
        units, used = [], set()
        for cid in ids:
            c = self.cards[cid]
            pool = self.champion_pool(c)
            chosen = draft[c["role"]] if draft else next((p["id"] for p in pool if p["id"] not in used), None)
            chosen = chosen or next(x for x in sorted(self.champions) if x not in used)
            mastery = next((p["mastery"] for p in pool if p["id"] == chosen), 35)
            units.append({"card_id": cid, "name": c["name"], "role": c["role"], "overall": c["overall"],
                          "team_id": c["team_id"], "team": c["team"], "year": c["year"],
                          "ratings": dict(c["ratings"]), "vision_stats": c.get("vision_stats", {}), "champion": chosen, "mastery": mastery, "cooldowns": {}})
            used.add(chosen)
        return self.prepare_units(units, campaign=draft is not None if campaign is None else campaign)

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
        if m.get("progression_rules"):
            self.match.finish_awards()
            self.settle_progression(won)
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
        campaign_actions = ("buy_relic", "assign_relic", "use_relic", "reward_choice")
        starter = self.s["starter"]
        if kind.startswith("starter_") and starter["finished"]:
            raise ValueError("시작 팩은 이미 모두 사용했습니다.")
        if kind in ("pull", "equip", "draft", "start", "next_season", "begin_draft", "ban_champion", "pick_champion") and not starter["finished"]:
            raise ValueError("포지션별 팩 5개를 열고 구단 창단을 완료해주세요.")
        if kind in ("pull", "equip", "draft", "start", "next_season", "begin_draft", "ban_champion", "pick_champion") and self.active():
            raise ValueError("경기 종료 후 변경할 수 있습니다.")
        if kind in ("start", "next_season", "begin_draft") and self.s["reward_event"]:
            raise ValueError("경기 후 발견한 유물 보상을 먼저 선택해주세요.")
        if self.s.get("banpick") and kind in ("pull", "equip", "draft", "next_season", "begin_draft"):
            raise ValueError("진행 중인 밴픽을 먼저 완료해주세요.")
        if kind in ("begin_draft", "ban_champion", "pick_champion"):
            self.draft_action(action)
        elif kind == "target_focus":
            if not self.active() or not self.match.s.get("progression_rules") or action.get("focus") not in ("front", "rear"):
                raise ValueError("진행 중인 경기에서 전열 또는 후열을 선택하세요.")
            self.match.s["target_focus"] = action["focus"]
        elif kind == "ack_report":
            if not self.match or not self.match.s.get("reports") or action.get("report") != self.match.s["reports"][0]["id"]:
                raise ValueError("현재 교전 보고서를 확인해주세요.")
            self.match.s["reports"].pop(0)
        elif kind in campaign_actions:
            self.campaign_action(action)
        elif kind in ("starter_filter", "starter_open"):
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
            banpick = self.s.get("banpick")
            if banpick and banpick["phase"] != "ready":
                raise ValueError("밴픽을 먼저 완료해주세요.")
            ids = [self.s["roster"][r] for r in ROLES]
            red = self.units(self.s["season"]["teams"][opponent]["roster"], banpick["picks"][1] if banpick else None, campaign=False)
            self.match = Match(self.units(ids, self.s["draft"]), red, self.rng.next(), self.champions)
            self.match.s["banpick"] = copy.deepcopy(banpick)
            self.match.s["interactive"] = bool(banpick)
            self.s["banpick"] = None
            self.match.s["opponent_name"] = self.s["season"]["teams"][opponent]["name"]
            self.match.s["prepared_relics"] = self.s["prepared_relics"][:]
            self.s["prepared_relics"] = []
        elif kind == "tick":
            steps = action.get("steps", 1)
            if type(steps) is not int or not 1 <= steps <= 3600 or not self.match:
                raise ValueError("잘못된 경기 진행 요청입니다.")
            if record and sum(a.get("steps", 1) for a in self.actions if a["type"] == "tick") + steps > 300000:
                raise ValueError("기록 가능한 경기 시간이 가득 찼습니다. 세이브를 내보낸 후 새 게임을 시작하세요.")
            for _ in range(steps):
                self.match.step()
                if self.match.s.get("interactive") and self.match.s.get("reports"):
                    break
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
            if kind == "tick" and (not self.match.s.get("interactive") or not (self.match.s.get("reports") or self.match.s["event"])) and self.actions and self.actions[-1]["type"] == "tick" and self.actions[-1].get("steps", 1) + action.get("steps", 1) <= 3600:
                self.actions[-1]["steps"] = self.actions[-1].get("steps", 1) + action.get("steps", 1)
            else:
                self.actions.append(copy.deepcopy(action))
        return None

    def view(self):
        match = copy.deepcopy(self.match.s) if self.match else None
        if match and hasattr(self.match, "ready_skills"):
            for side, team in enumerate(match["teams"]):
                for index, unit in enumerate(team):
                    unit["available_skills"] = self.match.ready_skills(self.match.s["teams"][side][index])
        return {**copy.deepcopy(self.s), "match": match,
                "engine": ENGINE_VERSION, "dataset": self.catalog["version"],
                "relic_catalog": copy.deepcopy(RELICS),
                "relic_availability": {rid: self.relic_block(rid) for rid in RELICS},
                "lineup_preview": self.units([self.s["roster"][r] for r in ROLES], self.s["draft"])
                if self.s["starter"]["finished"] else [],
                "starter_counts": {r: len(self.starter_pool(r)) for r in ROLES}
                if not self.s["starter"]["finished"] else {},
                "save_actions": len(self.actions)}

    def export_save(self):
        payload = {"schema": 4, "engine": ENGINE_VERSION, "dataset": self.catalog["version"],
                   "champions": self.champion_data["version"],
                   "mechanics": self.champion_data.get("revision", self.champion_data["version"]),
                   "effects": self.champion_data.get("effects_revision"), "vision": self.catalog.get("vision_revision"),
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
            if (data["schema"], data["engine"]) in ((1, "1.0.0"), (2, "2.0.0"), (3, "3.0.0")):
                return cls.migrate_legacy(text, catalog, champions)
            if data["schema"] != 4 or data["engine"] != ENGINE_VERSION:
                raise ValueError("다른 버전의 세이브입니다.")
            if (data["dataset"] != catalog["version"] or data["champions"] != champions["version"]
                    or data.get("mechanics") != champions.get("revision", champions["version"])
                    or data.get("effects") != champions.get("effects_revision")
                    or data.get("vision") != catalog.get("vision_revision")):
                raise ValueError("데이터 버전이 다릅니다. 저장 당시 버전의 게임에서 불러오세요. 기존 세이브는 보존됩니다.")
            actions = data["actions"]
            if not isinstance(actions, list) or len(actions) > 12000:
                raise ValueError("세이브 동작 수가 허용 범위를 초과했습니다.")
            if sum(a.get("steps", 1) for a in actions if isinstance(a, dict) and a.get("type") == "tick" and type(a.get("steps", 1)) is int) > 300000:
                raise ValueError("세이브 재생 시간이 허용 범위를 초과했습니다.")
            candidate = (cls.migrate_legacy(data["legacy"], catalog, champions)
                         if data.get("legacy") else cls(catalog, champions, data["seed"]))
            if candidate.seed != data["seed"]:
                raise ValueError("세이브의 시작 시드가 일치하지 않습니다.")
            for action in actions:
                candidate.apply(action)
            return candidate
        except (KeyError, TypeError, RecursionError, json.JSONDecodeError) as exc:
            raise ValueError("올바른 Nexus Archive 세이브가 아닙니다.") from exc

    @classmethod
    def migrate_legacy(cls, text, catalog, champions):
        # Replay with the unchanged v1 rules first. Never replace a user's earned roster.
        version = json.loads(text).get("engine")
        if version == "3.0.0":
            from legacy_engine_v3 import Game as LegacyGame
        elif version == "2.0.0":
            from legacy_engine_v2 import Game as LegacyGame
        elif version == "1.0.0":
            from legacy_engine import Game as LegacyGame
        else:
            raise ValueError("지원하지 않는 이전 세이브입니다.")
        old = LegacyGame.import_save(text, catalog, champions)
        candidate = cls(catalog, champions, old.seed)
        candidate.s = copy.deepcopy(old.s)
        candidate.initialize_campaign()
        candidate.s.setdefault("banpick", None)
        if "starter" not in candidate.s:
            candidate.s["starter"] = {"finished": True, "packs": {
                r: {"league": "any", "year": "any", "card": old.s["roster"][r]} for r in ROLES}}
        candidate.s["notice"] = "기존 선수·재화·시즌을 보존했습니다. 다음 경기부터 성장·컨디션·유물·시너지를 적용합니다."
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
