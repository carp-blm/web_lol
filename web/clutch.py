"""Engine 7 pressure and resolve: adversity can awaken a player to their career peak.

Inspired by stress systems in tactics games. Every player carries pressure (0-100) that
builds while their team or lane is losing and spikes on deaths and lost objectives. At 100
a resolve check happens: AWAKENED lifts every stat to the career peak for a while, scales
fighting strength and unlocks one clutch play (an outnumbered kill or an objective steal);
SHAKEN costs points per stat (never below the career floor) and fighting strength. Each
awakening lowers that team's later chances. Both teams use the same rules and the seeded RNG.

The coach's tactical calls also move the pressure of the players involved. That effect is
deliberately never shown; see CHOICE_PRESSURE.
"""
from battlefield import PITS
from combat import LANES, bound
from josa import josa

STATS = ("lane", "combat", "vision", "farm")
PRESSURE_INTERVAL = 10
DRIFT_SCALE = 1.0            # scales the passive rise/fall
# Losing only builds tension up to this level. The last stretch to 100 has to come from deaths,
# lost objectives and the coach's calls; pressure above the ceiling eases off on its own.
DRIFT_CEILING, OVER_CEILING_DECAY = 80, .5
AWAKEN_SECONDS = 180
SHAKEN_SECONDS = 90
SHAKEN_PENALTY = 6
# A resolve check spreads to teammates within this distance: relief on awakening, doubt on faltering.
SPREAD_RADIUS, AWAKEN_RELIEF, SHAKEN_DOUBT = 25, -15, 6
# Rating points alone drown in gold and mastery, so resolve also scales fighting strength directly.
AWAKEN_POWER, SHAKEN_POWER = 1.5, .8
# Every awakening in a match lowers that team's later awakening chances (never below the 10% floor).
AWAKEN_DECAY, RESOLVE_FLOOR = .10, .10

# Hidden pressure from the coach's calls: (lead player, other allies involved, enemies involved).
# Never shown in option text, outcome summaries, the feed or highlights; the player infers it
# from who awakens and who falters later. Deterministic: no extra random draws.
CHOICE_PRESSURE = {
    "general": {
        ("commit", "success"): (-8, -4, 6),
        ("commit", "fail"): (10, 5, -4),
        ("vision", "success"): (-3, -3, 0),
        ("vision", "fail"): (2, 2, 0),
        ("trade", "success"): (-2, 0, 0),
        ("trade", "fail"): (3, 0, 0),
        ("disengage", "justified"): (-2, -2, 0),
        ("disengage", "avoidable"): (3, 3, -2),
        ("disengage", "fail"): (8, 4, -3),
    },
    "lane_kill": {
        ("commit", "kill"): (-10, -4, 8),
        ("commit", "success"): (2, 0, 2),
        ("commit", "fail"): (10, 4, -4),
        ("trade", "success"): (-2, 0, 0),
        ("trade", "fail"): (3, 0, 0),
        ("vision", "success"): (-2, 0, 0),
        ("vision", "fail"): (2, 0, 0),
    },
}
CHOICE_SCALE = 2.0           # multiplies every value in the table above
OUTNUMBERED_STAKES = 1.5     # committing while outnumbered: own-team changes are larger both ways
RETREAT_HP = 40              # a retreat is justified when outnumbered or someone is this low
PASSIVE_STEP, PASSIVE_CAP = 2, 6   # consecutive non-commit calls weigh on the lead player
INVOLVED_RADIUS = 26
RESOLVE_COOLDOWN = 600
TEAM_RESOLVE_COOLDOWN = 240
DEATH_PRESSURE, NEARBY_DEATH_PRESSURE, KILL_RELIEF = 4, 1, -10
EVENT_SCALE = 3.0            # scales pressure from deaths and lost objectives
OUTNUMBERED_CLUTCH = .55
STEAL_CHANCE, STEAL_SMITE_BONUS, STEAL_RADIUS = .50, .15, 30
OBJECTIVE_NAMES = {"dragon": "드래곤", "herald": "전령", "baron": "바론"}
# Mental traits earned over a season (management.py): 큰 무대 체질 and 새가슴.
BIG_STAGE_CHANCE, FRAGILE_CHANCE, FRAGILE_PRESSURE = .10, -.10, 1.2
# Big matches start tense for both teams; a deciding game (series 1:1) adds more.
STAGE_PRESSURE = {"semifinal": 15, "final": 30}
DECIDER_PRESSURE = 10
STAGE_NAMES = {"semifinal": "플레이오프 4강", "final": "결승"}
# Clutch call: while one of our players is awakened with the clutch play unused and is part of a
# tactical event, the coach may hand the moment to them. It rolls like the main commit at better
# odds; on success the player also lands a guaranteed kill. Either way the clutch play is spent.
CLUTCH_CALL_BONUS, CLUTCH_CALL_CAP = .20, .95
CLUTCH_CALL_REACH = 45       # an awakened player this close rushes in to take the call
# Former-teammate derby: both players start tense, and beating the old teammate weighs more.
DERBY_START, DERBY_KILL_PRESSURE, DERBY_KILL_RELIEF = 10, 8, -8
CALL_LOOKAHEAD = 20          # after one of our players awakens, the next tactical moment comes within this many seconds


def resolve_chance(unit):
    """Base 30%; traits and match condition move it. Shown to the player as-is."""
    traits = set(unit.get("traits", []))
    condition = unit.get("condition", {}).get("modifier", 0)
    return round(bound(.30 + .15*("clutch" in traits) + .10*("big_game" in traits) + .05*("veteran" in traits)
                       + BIG_STAGE_CHANCE*("big_stage" in traits) + FRAGILE_CHANCE*("fragile" in traits)
                       + .02*condition, .10, .75), 2)


class ClutchRules:
    def initialize_clutch(self):
        self.s["clutch_rules"] = 1
        self.s["clutch_moments"] = []
        self.s["team_resolve_at"] = [0, 0]
        self.s["passive_calls"] = 0
        for team in self.s["teams"]:
            for u in team:
                u.setdefault("peak", dict(u["ratings"]))
                u.setdefault("floor", dict(u["ratings"]))
                u.update(pressure=0, resolve=None, awakenings=0, shaken=0, clutch_plays=0, next_resolve_at=0,
                         resolve_chance=resolve_chance(u))

    def set_stage(self, phase, series):
        """Called by the campaign before kickoff. Both teams carry the weight of a big match."""
        base = STAGE_PRESSURE.get(phase, 0)
        if not base:
            return
        decider = list(series) == [1, 1]
        amount = base + (DECIDER_PRESSURE if decider else 0)
        for team in self.s["teams"]:
            for u in team:
                self.add_pressure(u, amount)
        self.s["stage"] = {"phase": phase, "decider": decider, "pressure": amount}
        title = f'{STAGE_NAMES[phase]}{" 최종전" if decider else ""}'
        self.log("resolve", f'{title} · 큰 경기의 무게로 양 팀 모두 긴장한 채 시작합니다.')
        self.add_highlight("stage", title, "큰 경기 · 양 팀 압박이 높은 상태로 시작")

    def set_derby(self, pairs):
        """pairs: [{"ours": role, "theirs": role, "ours_name", "theirs_name", "team", "year"}] from the campaign."""
        self.s["derbies"] = [dict(p) for p in pairs]
        tense = set()
        for p in pairs:
            ours, theirs = self.unit(0, p["ours"]), self.unit(1, p["theirs"])
            ours.setdefault("rivals", []).append(p["theirs"])
            theirs.setdefault("rivals", []).append(p["ours"])
            tense.update({(0, p["ours"]), (1, p["theirs"])})
            title = f'옛 동료 더비 · {p["ours_name"]} vs {p["theirs_name"]}'
            detail = f'{p["year"]} {p["team"]}에서 함께 뛴 두 선수가 적으로 만났습니다'
            self.log("resolve", f'{title} — {detail}.')
            self.add_highlight("derby", title, detail)
        for side, role in sorted(tense):
            self.add_pressure(self.unit(side, role), DERBY_START)

    @staticmethod
    def awakened(u):
        return bool(u.get("resolve") and u["resolve"]["kind"] == "awakened")

    def strength(self, unit, lane=None):
        base = super().strength(unit, lane)
        resolve = unit.get("resolve")
        if not resolve:
            return base
        return base*(AWAKEN_POWER if resolve["kind"] == "awakened" else SHAKEN_POWER)

    def side_name(self, side):
        return "우리" if side == 0 else "상대"

    # ---- pressure ---------------------------------------------------------------------------
    def add_pressure(self, u, amount):
        if amount > 0:
            traits = set(u.get("traits", []))
            amount *= ((.7 if "clutch" in traits else 1) * (.85 if "veteran" in traits else 1)
                       * (FRAGILE_PRESSURE if "fragile" in traits else 1))
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
                    gain = self.pressure_gain(u)*DRIFT_SCALE
                    if gain > 0 and DRIFT_CEILING < 100:
                        room = DRIFT_CEILING-u["pressure"]
                        # add_pressure applies trait relief to rises; the ceiling is the same for everyone.
                        # A player already at 100 is waiting for a check and does not ease off.
                        gain = min(gain, room) if room >= 0 else 0 if u["pressure"] >= 100 else -OVER_CEILING_DECAY
                    self.add_pressure(u, gain)
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
            for mate in self.s["teams"][u["side"]]:
                mate["resolve_chance"] = round(max(RESOLVE_FLOOR, mate["resolve_chance"]-AWAKEN_DECAY), 2)
            title, detail = "각성 · 고점 도달", f'{self.unit_label(u)} · 위기 속 커리어 고점 경기력 {AWAKEN_SECONDS}초 · 클러치 플레이 가능'
            self.log("resolve", f'{u["name"]} 각성! 압박을 이겨내고 고점 경기력에 도달했습니다.', u["side"])
            self.add_highlight("awakened", title, detail, u["side"])
            if u["side"] == 0:
                self.add_report(title, detail)
                # The team looks to the awakened player: the next tactical moment comes sooner.
                self.s["next_event"] = min(self.s["next_event"], now+CALL_LOOKAHEAD)
        else:
            u["ratings"] = {k: max(u["floor"][k], v-SHAKEN_PENALTY) for k, v in saved.items()}
            u["resolve"] = {"kind": "shaken", "until": now+SHAKEN_SECONDS, "saved": saved, "clutch_used": True}
            u["pressure"], u["shaken"] = 30, u["shaken"]+1
            self.log("resolve", f'{u["name"]} 흔들림 · {SHAKEN_SECONDS}초간 능력치 −{SHAKEN_PENALTY} (저점 이하로는 떨어지지 않음)', u["side"])
            self.add_highlight("shaken", "흔들림", f'{self.unit_label(u)} · 압박에 위축', u["side"])
        spread = AWAKEN_RELIEF if self.awakened(u) else SHAKEN_DOUBT
        for mate in self.s["teams"][u["side"]]:
            if mate is not u and self.present(mate) and self.distance(mate["pos"], u["pos"]) <= SPREAD_RADIUS:
                self.add_pressure(mate, spread)
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
            self.add_pressure(victim, DEATH_PRESSURE*EVENT_SCALE)
            for mate in self.s["teams"][victim["side"]]:
                if mate is not victim and self.present(mate) and self.distance(mate["pos"], victim["pos"]) <= 25:
                    self.add_pressure(mate, NEARBY_DEATH_PRESSURE*EVENT_SCALE)
            self.add_pressure(attacker, KILL_RELIEF)
            if victim["role"] in attacker.get("rivals", []) and attacker["side"] != victim["side"]:
                self.add_pressure(victim, DERBY_KILL_PRESSURE)
                self.add_pressure(attacker, DERBY_KILL_RELIEF)
                attacker["derby_kills"] = attacker.get("derby_kills", 0)+1
                self.log("resolve", f'더비 · {josa(attacker["name"], "이")} 옛 동료 {victim["name"]}에게 한 수 위를 보여줍니다.', attacker["side"])
                if attacker["derby_kills"] == 1:
                    self.add_highlight("derby", f'더비 · {attacker["name"]} 선제', f'{josa(self.unit_label(attacker), "이")} 옛 동료 {self.unit_label(victim)} 처치', attacker["side"])

    def objective(self, side, kind):
        super().objective(side, kind)
        for u in self.s["teams"][1-side]:
            self.add_pressure(u, (8 if kind == "baron" else 4)*EVENT_SCALE)

    def encounter(self, kind, lane, blue, red, rounds=2, initiative=None, forced=None):
        result = self.clutch_encounter(kind, lane, blue, red, rounds, initiative, forced)
        self.offer_clutch_call()
        return result

    def clutch_encounter(self, kind, lane, blue, red, rounds, initiative, forced):
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
                               f'{self.side_name(side)} {josa(self.unit_label(hero), "이")} 수적 열세에서 {self.unit_label(victim)} 처치')
        return result

    # ---- tactical calls ---------------------------------------------------------------------
    def involved(self, side, event):
        if event["kind"] == "lane_kill":
            return self.lane_members(side, event["lane"])
        return self.nearby(side, event.get("position", self.unit(0, event["role"])["pos"]), INVOLVED_RADIUS)

    def event_point(self, event):
        if event["kind"] == "lane_kill":
            return self.lane_point(event["lane"], 0)
        return event.get("position", self.unit(0, event["role"])["pos"])

    def clutch_hero(self, event):
        point, involved = self.event_point(event), self.involved(0, event)
        ready = [u for u in self.s["teams"][0] if self.awakened(u) and not u["resolve"]["clutch_used"] and self.present(u)
                 and (u in involved or self.distance(u["pos"], point) <= CLUTCH_CALL_REACH)]
        return max(ready, key=lambda u: (u["ratings"]["combat"], u["role"])) if ready else None

    def make_event(self):
        super().make_event()
        self.offer_clutch_call()

    def offer_clutch_call(self):
        event = self.s["event"]
        if not event or self.s["winner"] is not None or any(o["id"] == "clutch" for o in event["options"]):
            return
        commit = next((o for o in event["options"] if o["id"] == "commit"), None)
        hero = self.clutch_hero(event) if commit else None
        if not hero:
            return
        chance = round(min(CLUTCH_CALL_CAP, commit.get("base_chance", commit["chance"]) + CLUTCH_CALL_BONUS), 2)
        event["options"].append({"id": "clutch", "label": f'★ {hero["name"]}에게 맡긴다', "chance": chance,
                                 "base_chance": chance, "hero": hero["role"],
                                 "detail": "각성한 선수가 직접 승부 · 성공하면 처치 확정 · 성공·실패와 관계없이 클러치 기회 소모"})
        if "relic_bonus" in event:
            self.refresh_relic_chances()

    def choose(self, option_id):
        s, event = self.s, self.s["event"]
        if not event:
            return super().choose(option_id)
        hero = None
        if option_id == "clutch":
            call = next((o for o in event["options"] if o["id"] == "clutch"), None)
            if not call or s["winner"] is not None:
                raise ValueError("현재 선택할 수 없는 전술입니다.")
            hero = self.unit(0, call["hero"])
            # The call plays out as the commit at the call's odds; the player's clutch play is this call.
            next(o for o in event["options"] if o["id"] == "commit")["chance"] = call["chance"]
            hero["resolve"]["clutch_used"] = True
            if hero not in self.involved(0, event):
                # The player rushes in: they join the fight at the event spot.
                spot = list(self.event_point(event))
                hero.update(pos=spot, destination=spot, route=[], moving=False, intent="클러치 콜 합류",
                            location=event["lane"], roam_until=s["time"]+35)
            option_id = "commit"
        lane_kill = event["kind"] == "lane_kill"
        actor = hero or self.unit(0, event["role"])
        involved = [self.involved(side, event) for side in (0, 1)]
        crowd = len([u for u in involved[0] if u is not actor])+1
        outnumbered = crowd < len(involved[1])
        hurt = any(u["hp"] < RETREAT_HP for u in involved[0]+[actor])
        kills = s["kills"][0]
        super().choose(option_id)
        decision = s["decisions"][-1]
        choice, success = decision["choice"], decision["success"]
        if not success:
            outcome = "fail"
        elif lane_kill and choice == "commit":
            outcome = "kill" if s["kills"][0] > kills else "success"
        elif choice == "disengage":
            outcome = "justified" if outnumbered or hurt else "avoidable"
        else:
            outcome = "success"
        lead, allies, enemies = (v*CHOICE_SCALE for v in CHOICE_PRESSURE["lane_kill" if lane_kill else "general"][(choice, outcome)])
        if choice == "commit":
            s["passive_calls"] = 0
            if outnumbered:
                lead, allies = lead*OUTNUMBERED_STAKES, allies*OUTNUMBERED_STAKES
        else:
            s["passive_calls"] = s.get("passive_calls", 0)+1
            lead += min(PASSIVE_CAP, PASSIVE_STEP*(s["passive_calls"]-1))
        self.add_pressure(actor, lead)
        for u in involved[0]:
            if u is not actor:
                self.add_pressure(u, allies)
        for u in involved[1]:
            self.add_pressure(u, enemies)
        decision["pressure"] = {"outcome": outcome, "lead": lead, "allies": allies, "enemies": enemies,
                                "outnumbered": outnumbered, "passive_calls": s["passive_calls"]}
        if hero:
            decision.update(choice="clutch", hero=hero["role"])
            self.finish_clutch_call(hero, event, success)

    def finish_clutch_call(self, hero, event, success):
        label = self.unit_label(hero)
        if not success:
            self.log("clutch", f'{hero["name"]}에게 맡긴 승부가 막혔습니다 · 클러치 기회 소모', 0)
            return
        if not self.present(hero):
            self.log("clutch", f'{josa(hero["name"], "이")} 승부를 열었지만 끝까지 버티지 못했습니다 · 클러치 기회 소모', 0)
            return
        victims = self.involved(1, event)
        if victims:
            victim = min(victims, key=lambda u: (u["hp"], u["role"]))
            self.kill_unit(hero, victim, self.involved(0, event))
            detail = f'우리 {josa(label, "이")} 감독의 부름에 응답해 {self.unit_label(victim)} 처치'
        else:
            detail = f'우리 {josa(label, "이")} 감독의 부름에 응답해 교전을 정리했습니다'
        hero["resolve"]["clutch_used"] = False      # clutch_moment marks it spent and counts the play
        self.clutch_moment(hero, "call", f'CLUTCH CALL · {hero["name"]}', detail)

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
                                       f'{self.side_name(thief_side)} {josa(self.unit_label(thief), "이")} {self.side_name(1-thief_side)} 팀이 사냥하던 {josa(OBJECTIVE_NAMES[kind], "을")} 가로챘습니다')
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
