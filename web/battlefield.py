"""Continuous normalized-map movement and proximity-based encounters.

Distances are map units, not League world units. Timers schedule intentions;
only units physically near an encounter/objective can participate.
"""
import math
from combat import LANES, LABEL, bound

BASES = ((10, 90), (90, 10))
PITS = {"dragon": (66, 66), "herald": (35, 35), "baron": (35, 35)}
CAMP_POINTS = ({"top": (24, 36), "mid": (32, 63), "bot": (62, 78)},
               {"top": (38, 22), "mid": (68, 37), "bot": (76, 64)})
PATHS = {"top": ((10, 90), (12, 12), (90, 10)),
         "mid": ((10, 90), (90, 10)), "bot": ((10, 90), (88, 88), (90, 10))}


class BattlefieldRules:
    @staticmethod
    def distance(a, b):
        return math.hypot(a[0]-b[0], a[1]-b[1])

    def initialize_battlefield(self):
        self.s.update(rules="spatial-v5", next_contact=80, next_rotation=840,
                      first_blood=False, spatial_events=0, gold_history=[], objectives=PITS)
        for side, team in enumerate(self.s["teams"]):
            for u in team:
                u.update(pos=list(BASES[side]), destination=list(BASES[side]), route=[], intent="라인으로 이동",
                         moving=False, recent_casts=[], combo_ready_at=0, encounter_at=80, level=1)
                self.go_home(u)
        self.initialize_summoners()

    def physical_region(self, pos):
        if min(pos) < 20:
            return "top"
        if max(pos) > 80:
            return "bot"
        if abs(pos[0]+pos[1]-100) < 10:
            return "mid"
        if min(self.distance(pos, p) for p in PITS.values()) < 15:
            return "river"
        return "jungle"

    def ward_cycle(self):
        # Ward placement belongs to the current coordinates, never a remote destination.
        previous = [(u, u["location"]) for team in self.s["teams"] for u in team]
        for u, _ in previous:
            if self.present(u):
                u["location"] = self.physical_region(u["pos"])
        super().ward_cycle()
        for u, location in previous:
            u["location"] = location

    def lane_point(self, lane, side, role=None):
        path = PATHS[lane]
        lengths = [self.distance(a, b) for a, b in zip(path, path[1:])]
        progress = bound((.46 if side == 0 else .54) + self.s["pressure"][lane]*.012, .18, .82)
        distance = sum(lengths)*progress
        for a, b, length in zip(path, path[1:], lengths):
            if distance <= length:
                point = [round(a[i]+(b[i]-a[i])*distance/length, 2) for i in (0, 1)]
                if role == "sup":
                    point[0] -= 3 if side == 0 else -3
                    point[1] -= 3 if side == 0 else -3
                return point
            distance -= length
        return list(path[-1])

    def move_to(self, u, point, location, intent, duration=0, route=None):
        u.update(destination=list(point), location=location, intent=intent,
                 moving=self.distance(u["pos"], point) > 1, route=list(route or []),
                 roam_until=self.s["time"]+duration if duration else 0)

    def go_home(self, u):
        lane, side = self.home_lane(u), u["side"]
        if lane == "jungle":
            point = CAMP_POINTS[side]["bot" if side == 0 else "top"]
            route = []
        else:
            point = self.lane_point(lane, side, u["role"])
            route = []
            if self.distance(u["pos"], BASES[side]) < 3 and lane != "mid":
                route = [PATHS[lane][1]]
                # Do not walk past the lane front before returning to it.
                if self.distance(BASES[side], point) < self.distance(BASES[side], route[0]):
                    route = []
        self.move_to(u, point, lane, "정글 캠프 순환" if lane == "jungle" else f'{LABEL[lane]} 라인 복귀', route=route)

    def nearby(self, side, point, radius=22):
        return [u for u in self.s["teams"][side] if self.present(u) and self.distance(u["pos"], point) <= radius]

    def lane_members(self, side, lane):
        return [u for u in self.members(side, lane) if self.distance(u["pos"], self.lane_point(lane, side, u["role"])) < 18]

    def advance_positions(self):
        now = self.s["time"]
        for team in self.s["teams"]:
            for u in team:
                u["recent_casts"] = [c for c in u["recent_casts"] if now-c["time"] < 8]
                if not self.present(u):
                    if now >= u["return_at"]:
                        u.update(status="active", hp=100., pos=list(BASES[u["side"]]), cc_until=0, cc_strength=0)
                        self.go_home(u)
                        self.log("return", f'{u["name"]} · 기지 회복 완료, 담당 라인으로 이동합니다.', u["side"])
                    else:
                        continue
                if u["roam_until"] and now >= u["roam_until"]:
                    self.go_home(u)
                if not u["roam_until"] and u["role"] != "jng" and now % 10 == 0:
                    u["destination"] = self.lane_point(self.home_lane(u), u["side"], u["role"])
                target = u["route"][0] if u["route"] else u["destination"]
                dist = self.distance(u["pos"], target)
                speed = 1.05 if u["role"] == "jng" else .95
                if u["cc_until"] > now:
                    speed *= .25 if u["cc_strength"] >= 1.8 else .6
                if u["encounter_at"] > now and not u["moving"]:
                    speed = 0
                if dist <= speed:
                    u["pos"] = list(target)
                    if u["route"]:
                        u["route"].pop(0)
                elif dist:
                    u["pos"] = [round(u["pos"][i]+(target[i]-u["pos"][i])*speed/dist, 3) for i in (0, 1)]
                u["moving"] = self.distance(u["pos"], u["destination"]) > 1 or bool(u["route"])
                if not u["moving"] and not u["roam_until"] and u["role"] != "jng":
                    u["intent"] = "라인 압박" if u["hp"] > 50 else "안전하게 파밍"
                u["hp"] = round(min(100, u["hp"]+.065), 3)

    def encounter(self, kind, lane, blue, red, rounds=2, initiative=None, forced=None):
        pairs = [(a, b) for a in blue for b in red if self.present(a) and self.present(b)
                 and self.distance(a["pos"], b["pos"]) <= 22]
        if not pairs:
            return None
        a, b = min(pairs, key=lambda p:self.distance(p[0]["pos"], p[1]["pos"]))
        center = [(a["pos"][i]+b["pos"][i])/2 for i in (0, 1)]
        groups = [[u for u in team if self.present(u) and self.distance(u["pos"], center) <= 22] for team in (blue, red)]
        for u in groups[0]+groups[1]:
            u["encounter_at"] = self.s["time"]+25
        result = super().encounter(kind, lane, *groups, rounds, initiative, forced)
        if self.s["last_encounter"] and self.s["last_encounter"]["time"] == self.s["time"]:
            self.s["last_encounter"]["position"] = center
        if self.s["event"]:
            self.s["event"].setdefault("position", center)
        return result

    def detect_contacts(self):
        now = self.s["time"]
        pairs = sorted(((self.distance(a["pos"], b["pos"]), a, b)
                        for a in self.members(0) for b in self.members(1)
                        if a["encounter_at"] <= now and b["encounter_at"] <= now), key=lambda p:p[0])
        for dist, a, b in pairs:
            if dist > 18 or a["encounter_at"] > now or b["encounter_at"] > now:
                continue
            center = [(a["pos"][i]+b["pos"][i])/2 for i in (0, 1)]
            teams = [self.nearby(side, center) for side in (0, 1)]
            lane = a["location"] if a["location"] in LANES else "river"
            kind = "teamfight" if min(map(len, teams)) >= 3 else "gank" if any(u["role"] == "jng" for t in teams for u in t) and lane in LANES else "lane" if lane in LANES else "counterjungle" if any("침입" in u["intent"] for t in teams for u in t) else "jungle_duel"
            self.s["spatial_events"] += 1
            self.encounter(kind, lane, *teams, rounds=1)
            if self.s.get("reports") and self.s.get("interactive") or self.s["event"]:
                break

    def start_roam(self, side, lane="mid"):
        u = self.unit(side, "sup")
        if not self.present(u) or u["roam_until"] > self.s["time"]:
            return False
        self.move_to(u, self.lane_point(lane, side), lane, f'{LABEL[lane]} 로밍 합류', 80)
        self.log("roam", f'{u["name"]} · {LABEL[lane]}로 이동. 도착 전에는 교전에 합류할 수 없습니다.', side)
        return True

    def gank(self, side, lane):
        u = self.unit(side, "jng")
        if self.present(u):
            self.move_to(u, self.lane_point(lane, side), lane, f'{LABEL[lane]} 갱킹 접근', 75)
            self.log("gank", f'{u["name"]} · {LABEL[lane]} 갱킹 동선 진입.', side)

    def farm_camp(self, side, owner=None, lane=None):
        owner = side if owner is None else owner
        u = self.unit(side, "jng")
        if not self.present(u) or u["location"] != "jungle":
            return False
        ready = [l for l, at in self.s["camps"][owner].items() if self.s["time"] >= at
                 and (lane is None or lane == l) and self.distance(u["pos"], CAMP_POINTS[owner][l]) <= 9]
        if not ready:
            return False
        return super().farm_camp(side, owner, min(ready, key=lambda l:self.distance(u["pos"], CAMP_POINTS[owner][l])))

    def jungle_action(self, side):
        u = self.unit(side, "jng")
        if not self.present(u) or u["roam_until"] > self.s["time"]:
            return
        objective = self.available_objective()
        if objective and self.distance(u["pos"], PITS[objective]) < 32 and self.rng.random() < .38:
            self.move_to(u, PITS[objective], "river", "오브젝트 진입", 65)
            return
        candidates = [e for e in self.members(1-side) if e["location"] in LANES and self.distance(u["pos"], e["pos"]) < 40]
        if candidates and self.rng.random() < .52:
            target = min(candidates, key=lambda e:e["hp"]+self.distance(u["pos"],e["pos"]))
            self.gank(side, target["location"])
            return
        owner = 1-side if self.rng.random() < .18 else side
        ready = [l for l, at in self.s["camps"][owner].items() if at <= self.s["time"]+20]
        lane = min(ready or LANES, key=lambda l:self.distance(u["pos"], CAMP_POINTS[owner][l]))
        self.move_to(u, CAMP_POINTS[owner][lane], "jungle", "상대 정글 침입" if owner != side else "정글 캠프 사냥", 35)

    def start_objective(self, side, kind, solo=False):
        if kind not in PITS or self.s["objective_attempt"] or not self.objective_ready(kind):
            return False
        squad = [u for u in self.nearby(side, PITS[kind], 20) if u["hp"] >= 30]
        if len(squad) < (3 if kind == "baron" else 1) or not any(u["role"] == "jng" for u in squad):
            return False
        duration = 28 if len(squad) == 1 else 18
        for u in squad:
            self.move_to(u, PITS[kind], "river", f'{kind} 확보', duration+10)
        self.s["objective_attempt"] = {"side": side, "kind": kind, "roles": [u["role"] for u in squad],
            "finish_at": self.s["time"]+duration, "solo": len(squad) == 1, "position": list(PITS[kind])}
        self.log("objective", f'{"우리" if side == 0 else "상대"} 팀 · 근처 {len(squad)}명이 {kind} 사냥 시작.', side)
        return True

    def resolve_objective(self):
        attempt = self.s["objective_attempt"]
        if not attempt or self.s["time"] < attempt["finish_at"]:
            return
        self.s["objective_attempt"] = None
        kind, side, point = attempt["kind"], attempt["side"], PITS[attempt["kind"]]
        if not self.objective_ready(kind):
            return
        squads = [self.nearby(i, point, 22) for i in (0, 1)]
        if squads[0] and squads[1]:
            result = self.encounter("objective", "river", *squads, rounds=1)
            if result is not None:
                side = result
        squad = [u for u in squads[side] if self.present(u)]
        if not squad or kind == "baron" and len(squad) < 3:
            return
        smiter = next((u for u in squad if self.summoner_ready(u, "smite")), None)
        prepared = next((u for u in squad if side == attempt["side"] and u["role"] == attempt.get("prepared_smite")), None)
        if smiter and not prepared:
            self.spend_summoner(smiter, "smite", "오브젝트 마무리")
        if self.rng.random() < (.98 if smiter or prepared else .67):
            for u in squad:
                u["hp"] = max(1, u["hp"]-(22 if len(squad) == 1 else 9))
            self.objective(side, kind)
            self.add_highlight("objective", f'{ {"dragon":"드래곤", "herald":"전령", "baron":"바론"}[kind]} 확보',
                               f'{"우리" if side == 0 else "상대"} 팀 · {"강타 마무리" if smiter or prepared else "팀 집중 공격"}', side)

    def rotate_teams(self):
        objective = self.available_objective()
        for side in (0, 1):
            lane = min(LANES, key=lambda l:self.s["towers"][1-side][l])
            point = PITS[objective] if objective else self.lane_point(lane, side)
            for u in self.members(side):
                if u["role"] != "top" or self.s["time"] > 1500:
                    offset = (ROLES_INDEX[u["role"]]-2)*2
                    self.move_to(u, [point[0]+offset, point[1]-offset], "river" if objective else lane,
                                 "오브젝트 집결" if objective else "팀 공성 합류", 85)

    def make_event(self):
        s = self.s
        pairs = [(self.distance(a["pos"], b["pos"]), a, b) for a in self.members(0) for b in self.members(1)]
        objective = self.available_objective()
        squad = self.nearby(0, PITS[objective], 32) if objective else []
        if squad:
            actor = min(squad, key=lambda u:self.distance(u["pos"], PITS[objective]))
            point, lane, kind = list(PITS[objective]), "river", "objective"
            title = "오브젝트 앞, 결단의 순간"
        elif pairs and min(p[0] for p in pairs) <= 30:
            dist, actor, enemy = min(pairs, key=lambda p:p[0])
            point, lane, kind = list(actor["pos"]), actor["location"], "skirmish"
            objective = None
            title = "고립된 상대를 포착했습니다" if len(self.nearby(1, enemy["pos"], 20)) == 1 else "교전 거리 안으로 들어왔습니다"
        else:
            s["next_event"] = s["time"]+15
            return
        friends, enemies = self.nearby(0, point, 26), self.nearby(1, point, 26)
        p = round(bound(self.encounter_odds(friends, enemies, lane), .18, .88), 2)
        if s["followup"]:
            kind, title = "followup", "앞선 교전을 읽은 상대, 다음 선택은?"
            s["followup"] = None
        nearest = min((self.distance(actor["pos"], e["pos"]) for e in self.members(1)), default=100)
        s["event"] = {"id": f'spatial-{s["tick"]}', "kind": kind, "title": title,
            "context": f'{LABEL.get(lane, lane)} · 아군 {len(friends)} / 적군 {len(enemies)} · 최근접 적 {nearest:.1f} 거리',
            "story": f'{actor["name"]} 주변의 실제 위치와 시야를 바탕으로 판단합니다. 먼 선수는 이동 후 합류하며, 주문을 쓰면 선택 성공률이 상승합니다.',
            "lane": lane, "role": actor["role"], "position": point, "objective": objective,
            "skill": {"key": "AA", "name": "팀 콤보", "icon": "assets/skill-placeholder.svg", "tags": ["damage"]},
            "options": [
                {"id": "commit", "label": "콤보를 연결해 승부한다" if not objective else "주변 전력으로 오브젝트 확보", "chance": p, "detail": "선공 판정 · 근처 선수만 참여 · 실패 시 반격"},
                {"id": "vision", "label": "시야를 장악하고 기회를 만든다", "chance": min(.94, p+.17), "detail": "150G 사용 · 성공 시 주변 시야 +3"},
                {"id": "trade", "label": "라인 성장에 집중한다", "chance": .82, "detail": "성공 시 담당 선수 +120G · 오브젝트 견제 포기"},
                {"id": "disengage", "label": "전열을 지키며 후퇴한다", "chance": .90, "detail": "성공 시 안전하게 복귀 · 실패 시 추격 허용"}],
            "relic_bonus": round(sum(u.get("choice_bonus", 0) for u in s["teams"][0])/5, 4), "used_relics": []}
        self.refresh_relic_chances()

    def choose(self, option_id):
        s, event = self.s, self.s["event"]
        option = next((o for o in event["options"] if o["id"] == option_id), None) if event else None
        if not option or s["winner"] is not None:
            raise ValueError("현재 선택할 수 없는 전술입니다.")
        before = self.outcome_snapshot()
        success = self.rng.random() < option["chance"]
        lane, actor = event["lane"], self.unit(0, event["role"])
        point = event.get("position", actor["pos"])
        if option_id == "commit":
            s["followup"] = "countergank" if event["kind"] != "followup" else None
            self.encounter("lane_finish" if event["kind"] == "lane_kill" else "ambush", lane,
                           self.nearby(0, point, 26), self.nearby(1, point, 26), rounds=1, initiative=0 if success else 1)
            if event.get("objective"):
                self.start_objective(0 if success else 1, event["objective"])
        elif option_id == "vision":
            if event["kind"] != "lane_kill":
                s["gold"][0] = max(0, s["gold"][0]-150)
            if success:
                s["local_vision"][0][lane] = min(10, s["local_vision"][0].get(lane, 0)+(2 if event["kind"] == "lane_kill" else 3))
        elif option_id == "trade" and success:
            self.grant_gold(actor, 120)
            if lane in LANES:
                s["pressure"][lane] = min(8, s["pressure"][lane]+1)
        elif option_id == "disengage":
            if not success:
                self.encounter("ambush", lane, self.nearby(0, point), self.nearby(1, point), rounds=1, initiative=1)
            for u in self.nearby(0, point):
                if u["hp"] < 40:
                    self.recall(u, lane)
                else:
                    self.go_home(u)
        outcome = self.outcome_summary(before)
        s["decisions"].append({"event": event["id"], "kind": event["kind"], "choice": option_id,
                               "success": success, "chance": option["chance"], "time": s["time"], "outcome": outcome})
        self.log("decision", f'{option["label"]} · {"성공" if success else "실패"} ({round(option["chance"]*100)}%) · {outcome}', 0)
        self.add_report("전술 성공" if success else "전술 실패", outcome)
        self.add_highlight("decision", event["title"], outcome, 0)
        s["event"] = None
        s["next_event"] = s["time"]+self.rng.integer(150, 240)

    def kill_unit(self, attacker, victim, allies):
        if victim["status"] == "dead":
            return
        first = not self.s["first_blood"]
        bounty = min(400, max(0, victim.get("kill_streak", 0)-2)*100)
        super().kill_unit(attacker, victim, allies)
        if first:
            self.s["first_blood"] = True
            self.grant_gold(attacker, 100)
            self.add_highlight("first_blood", "FIRST BLOOD", f'{attacker["name"]} · 첫 처치 보너스 +100G', attacker["side"])
        if bounty:
            self.grant_gold(attacker, bounty)
            self.add_highlight("shutdown", "SHUTDOWN", f'{attacker["name"]} · 연속 처치 차단 +{bounty}G', attacker["side"])

    def step(self):
        s = self.s
        if s["winner"] is not None or s["event"] or s.get("interactive") and s["reports"]:
            return
        s["time"] += 1
        s["tick"] += 1
        now = s["time"]
        self.advance_forms(1)
        self.advance_summoners()
        self.advance_positions()
        if now >= 90 and now % 5 == 0:
            for team in s["teams"]:
                for u in team:
                    self.grant_gold(u, 10)
        if now >= 90 and now % 30 == 0:
            self.waves()
            s["gold_history"].append({"time": now, "delta": s["gold"][0]-s["gold"][1]})
        if now % 30 == 0:
            self.ward_cycle()
        if now % 8 == 0:
            for side in (0, 1):
                if not self.farm_camp(side):
                    self.farm_camp(side, 1-side)
        if now >= s["next_jungle"]:
            for side in (0, 1):
                self.jungle_action(side)
            s["next_jungle"] = now+35
        if now >= s["next_roam"]:
            for side in (0, 1):
                if self.rng.random() < .45:
                    self.start_roam(side)
            s["next_roam"] = now+100
        if now >= s["next_rotation"]:
            self.rotate_teams()
            s["next_rotation"] = now+150
        if now >= 80 and now % 5 == 0:
            self.detect_contacts()
            if s["event"] or s.get("interactive") and s["reports"]:
                return
        if now % 15 == 0 and self.available_objective():
            for side in (0, 1):
                self.start_objective(side, self.available_objective())
        self.resolve_objective()
        for lane in LANES:
            if now >= s["next_siege"][lane]:
                self.siege(lane)
                s["next_siege"][lane] = now+self.rng.integer(24, 36)
            if s["winner"] is not None:
                self.finish_awards()
                return
        if now >= s["next_event"] and not s["event"] and not (s.get("interactive") and s["reports"]):
            self.make_event()


ROLES_INDEX = {r: i for i, r in enumerate(("top", "jng", "mid", "bot", "sup"))}
