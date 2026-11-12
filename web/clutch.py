"""Engine 7 pressure and resolve: adversity can awaken a player to their career peak.

Inspired by stress systems in tactics games. Every player carries pressure (0-100) that
builds while their team or lane is losing and spikes on deaths and lost objectives. At 100
a resolve check happens: AWAKENED lifts every stat to the career peak for a while and
unlocks one clutch play (an outnumbered kill or an objective steal); SHAKEN costs 4 points
per stat, but never below the career floor. Both teams use the same rules and the seeded RNG.
"""
from battlefield import PITS
from combat import LANES, bound

STATS = ("lane", "combat", "vision", "farm")
PRESSURE_INTERVAL = 10
AWAKEN_SECONDS = 120
SHAKEN_SECONDS = 90
SHAKEN_PENALTY = 4
RESOLVE_COOLDOWN = 600
TEAM_RESOLVE_COOLDOWN = 360
DEATH_PRESSURE, NEARBY_DEATH_PRESSURE, KILL_RELIEF = 4, 1, -10
OUTNUMBERED_CLUTCH = .55
STEAL_CHANCE, STEAL_SMITE_BONUS, STEAL_RADIUS = .50, .15, 30
OBJECTIVE_NAMES = {"dragon": "드래곤", "herald": "전령", "baron": "바론"}


def resolve_chance(unit):
    """Base 30%; traits and match condition move it. Shown to the player as-is."""
    traits = set(unit.get("traits", []))
    condition = unit.get("condition", {}).get("modifier", 0)
    return round(bound(.30 + .15*("clutch" in traits) + .10*("big_game" in traits) + .05*("veteran" in traits)
                       + .02*condition, .10, .75), 2)


class ClutchRules:
    def initialize_clutch(self):
        self.s["clutch_rules"] = 1
        self.s["clutch_moments"] = []
        self.s["team_resolve_at"] = [0, 0]
        for team in self.s["teams"]:
            for u in team:
                u.setdefault("peak", dict(u["ratings"]))
                u.setdefault("floor", dict(u["ratings"]))
                u.update(pressure=0, resolve=None, awakenings=0, shaken=0, clutch_plays=0, next_resolve_at=0,
                         resolve_chance=resolve_chance(u))

    @staticmethod
    def awakened(u):
        return bool(u.get("resolve") and u["resolve"]["kind"] == "awakened")

    def side_name(self, side):
        return "우리" if side == 0 else "상대"

    # ---- pressure ---------------------------------------------------------------------------
    def add_pressure(self, u, amount):
        if amount > 0:
            traits = set(u.get("traits", []))
            amount *= (.7 if "clutch" in traits else 1) * (.85 if "veteran" in traits else 1)
        u["pressure"] = round(bound(u["pressure"] + amount, 0, 100), 1)

    def pressure_gain(self, u):
        s, side = self.s, u["side"]
        deficit = s["gold"][1-side] - s["gold"][side]
        team = bound(deficit/5000, 0, 1.2)
        lane = self.home_lane(u)
        lane_score = s["pressure"].get(lane, 0) if lane in LANES else 0
        mine = lane_score if side == 0 else -lane_score
        lane_loss = bound(-mine-2, 0, 2) * .5
        rival = self.unit(1-side, u["role"])
        personal = bound((rival["gold"]-u["gold"])/2000, 0, 1)
        gain = team + lane_loss + personal
        if gain <= 0:
            gain = -2 if deficit < -1000 else -1.5
        return gain

    def update_pressure(self):
        for team in self.s["teams"]:
            for u in team:
                if u["status"] != "dead":
                    self.add_pressure(u, self.pressure_gain(u))
        now = self.s["time"]
        for side, team in enumerate(self.s["teams"]):
            # One resolve check per team at a time: the most pressured eligible player.
            ready = [u for u in team if u["pressure"] >= 100 and not u["resolve"] and self.present(u) and now >= u["next_resolve_at"]]
            if ready and now >= self.s["team_resolve_at"][side]:
                self.s["team_resolve_at"][side] = now + TEAM_RESOLVE_COOLDOWN
                self.resolve_check(max(ready, key=lambda u: (u["pressure"], u["role"])))

    def resolve_check(self, u):
        now = self.s["time"]
        saved = dict(u["ratings"])
        if self.rng.random() < u["resolve_chance"]:
            u["ratings"] = {k: max(v, u["peak"][k]) for k, v in saved.items()}
            u["resolve"] = {"kind": "awakened", "until": now+AWAKEN_SECONDS, "saved": saved, "clutch_used": False}
            u["pressure"], u["awakenings"] = 0, u["awakenings"]+1
            title, detail = "각성 · 고점 도달", f'{self.unit_label(u)} · 위기 속 커리어 고점 경기력 {AWAKEN_SECONDS}초 · 클러치 플레이 가능'
            self.log("resolve", f'{u["name"]} 각성! 압박을 이겨내고 고점 경기력에 도달했습니다.', u["side"])
            self.add_highlight("awakened", title, detail, u["side"])
            if u["side"] == 0:
                self.add_report(title, detail)
        else:
            u["ratings"] = {k: max(u["floor"][k], v-SHAKEN_PENALTY) for k, v in saved.items()}
            u["resolve"] = {"kind": "shaken", "until": now+SHAKEN_SECONDS, "saved": saved, "clutch_used": True}
            u["pressure"], u["shaken"] = 30, u["shaken"]+1
            self.log("resolve", f'{u["name"]} 흔들림 · {SHAKEN_SECONDS}초간 능력치 −{SHAKEN_PENALTY} (저점 이하로는 떨어지지 않음)', u["side"])
            self.add_highlight("shaken", "흔들림", f'{self.unit_label(u)} · 압박에 위축', u["side"])
        self.s["clutch_moments"].append({"time": now, "side": u["side"], "role": u["role"], "kind": u["resolve"]["kind"]})

    def expire_resolve(self):
        now = self.s["time"]
        for team in self.s["teams"]:
            for u in team:
                r = u["resolve"]
                if r and now >= r["until"]:
                    u["ratings"], u["resolve"] = r["saved"], None
                    u["next_resolve_at"] = now + RESOLVE_COOLDOWN

    def clutch_moment(self, u, kind, title, detail):
        u["resolve"]["clutch_used"] = True
        u["clutch_plays"] += 1
        self.s["clutch_moments"].append({"time": self.s["time"], "side": u["side"], "role": u["role"], "kind": kind})
        self.log("clutch", f'CLUTCH · {detail}', u["side"])
        self.add_highlight("clutch", title, detail, u["side"])
        self.add_report(title, detail)

    # ---- hooks --------------------------------------------------------------------------------
    def kill_unit(self, attacker, victim, allies):
        alive = victim["status"] != "dead"
        super().kill_unit(attacker, victim, allies)
        if alive and victim["status"] == "dead":
            self.add_pressure(victim, DEATH_PRESSURE)
            for mate in self.s["teams"][victim["side"]]:
                if mate is not victim and self.present(mate) and self.distance(mate["pos"], victim["pos"]) <= 25:
                    self.add_pressure(mate, NEARBY_DEATH_PRESSURE)
            self.add_pressure(attacker, KILL_RELIEF)

    def objective(self, side, kind):
        super().objective(side, kind)
        for u in self.s["teams"][1-side]:
            self.add_pressure(u, 8 if kind == "baron" else 4)

    def encounter(self, kind, lane, blue, red, rounds=2, initiative=None, forced=None):
        now = self.s["time"]
        result = super().encounter(kind, lane, blue, red, rounds, initiative, forced)
        info = self.s.get("last_encounter")
        if result is None or not info or info["time"] != now or info.get("clutch_checked"):
            return result
        info["clutch_checked"] = True
        roles = info["sides"]
        for side in (0, 1):
            if len(roles[side]) >= len(roles[1-side]):
                continue
            allies = [u for u in self.s["teams"][side] if u["role"] in roles[side] and self.present(u)]
            heroes = [u for u in allies if self.awakened(u) and not u["resolve"]["clutch_used"]]
            victims = [u for u in self.s["teams"][1-side] if u["role"] in roles[1-side] and self.present(u)]
            if not heroes or not victims or self.rng.random() >= OUTNUMBERED_CLUTCH:
                continue
            hero = max(heroes, key=lambda u: (u["ratings"]["combat"], u["role"]))
            victim = min(victims, key=lambda u: (u["hp"], u["role"]))
            self.kill_unit(hero, victim, allies)
            n = len(roles[1-side])
            self.clutch_moment(hero, "outnumbered", f'CLUTCH · {len(roles[side])}대{n} 역전 처치',
                               f'{self.side_name(side)} {self.unit_label(hero)}이(가) 수적 열세에서 {self.unit_label(victim)} 처치')
        return result

    def resolve_objective(self):
        attempt = self.s["objective_attempt"]
        if attempt and self.s["time"] >= attempt["finish_at"] and self.objective_ready(attempt["kind"]):
            kind, thief_side = attempt["kind"], 1-attempt["side"]
            thieves = [u for u in self.nearby(thief_side, PITS[kind], STEAL_RADIUS)
                       if self.awakened(u) and not u["resolve"]["clutch_used"]]
            if thieves:
                thief = max(thieves, key=lambda u: (u["role"] == "jng", u["ratings"]["combat"], u["role"]))
                smite = self.summoner_ready(thief, "smite")
                if self.rng.random() < STEAL_CHANCE + (STEAL_SMITE_BONUS if smite else 0):
                    self.s["objective_attempt"] = None
                    if smite:
                        self.spend_summoner(thief, "smite", "오브젝트 스틸")
                    thief["hp"] = max(1, thief["hp"]-10)
                    self.objective(thief_side, kind)
                    self.clutch_moment(thief, "steal", f'CLUTCH · {OBJECTIVE_NAMES[kind]} 스틸',
                                       f'{self.side_name(thief_side)} {self.unit_label(thief)}이(가) 상대가 사냥하던 {OBJECTIVE_NAMES[kind]}를 가로챘습니다')
                    return
        super().resolve_objective()

    def step(self):
        before = self.s["time"]
        super().step()
        now = self.s["time"]
        if now == before or self.s["winner"] is not None:
            return
        self.expire_resolve()
        if now % PRESSURE_INTERVAL == 0:
            self.update_pressure()
