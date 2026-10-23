"""Target access, concrete fight reports, streaks, lane kill choices and awards."""
from copy import deepcopy


def clamp(n, low, high):
    return max(low, min(high, n))


class MatchFeatures:
    def initialize_match_features(self):
        self.s.update(target_focus="front", reports=[], highlights=[], report_sequence=0,
                      next_lane_choice=300, player_of_match=None)
        for team in self.s["teams"]:
            for unit in team:
                tags = self.champions[unit["champion"]].get("tags", [])
                unit.update(frontline=bool(set(tags) & {"Tank", "Fighter"}), damage_dealt=0,
                            damage_taken=0, kill_streak=0, peak_streak=0)

    def unit_label(self, unit):
        return f'{unit["name"]}({self.champions[unit["champion"]]["name"]})'

    def threat(self, unit):
        return unit["ratings"]["combat"]*.45 + unit["mastery"]*.25 + unit["gold"]/300 + unit.get("damage_dealt",0)/100 + (10 if unit["role"] == "bot" else 0)

    def select_combat_target(self, caster, living, spell, lane):
        front = [u for u in living if u.get("frontline") and u["hp"] >= 25
                 and not (u["cc_until"] > self.s["time"] and u["cc_strength"] >= 1.8)]
        focus = self.s["target_focus"] if caster["side"] == 0 else "carry"
        if focus == "front":
            target = min(front or living, key=lambda u: (u["hp"], -self.threat(u)))
            return target, front or living, "전열 집중"
        rear = [u for u in living if not u.get("frontline")]
        # Enemy focus always ranks the highest damage threat; access still applies.
        target = max(living if focus == "carry" else rear or living, key=self.threat)
        if not front or target in front:
            return target, living, "딜러 포착" if focus == "carry" else "후열 노출"
        mobile = "mobility" in spell.get("tags", [])
        assassin = "Assassin" in self.champions[caster["champion"]].get("tags", [])
        breach = clamp(.08 + .30*mobile + .22*assassin + caster["mastery"]*.002
                       + self.vision_delta(caster["side"], lane)*.025 - .10*(len(front)-1), .03, .75)
        if self.rng.random() < breach:
            return target, living, "전열 돌파"
        blocker = min(front, key=lambda u: (u["hp"], -self.threat(u)))
        return blocker, front, f'{self.unit_label(blocker)}이(가) 후열 접근 차단'

    def add_highlight(self, kind, title, detail, side=None):
        entry = {"time": self.s["time"], "kind": kind, "title": title, "detail": detail, "side": side}
        self.s["highlights"].append(entry)
        self.s["highlights"] = self.s["highlights"][-80:]
        return entry

    def add_report(self, title, detail, fight=None):
        self.s["report_sequence"] += 1
        report = {"id": self.s["report_sequence"], "time": self.s["time"], "title": title, "detail": detail}
        if fight:
            report["fight"] = deepcopy(fight)
        self.s["reports"].append(report)
        self.s["reports"] = self.s["reports"][-12:]

    def outcome_snapshot(self):
        return {"gold": self.s["gold"][:], "kills": self.s["kills"][:],
                "pressure": dict(self.s["pressure"]), "vision": deepcopy(self.s["local_vision"]),
                "objective_attempt": deepcopy(self.s["objective_attempt"]),
                "hp": {f'{side}:{u["role"]}':u["hp"] for side,t in enumerate(self.s["teams"]) for u in t}}

    def outcome_summary(self, before):
        parts = []
        for side, label in ((0,"우리"),(1,"상대")):
            kills = self.s["kills"][side]-before["kills"][side]
            gold = self.s["gold"][side]-before["gold"][side]
            if kills: parts.append(f"{label} {kills}킬")
            if gold: parts.append(f"{label} 골드 {gold:+,}G")
        for lane, label in (("top","탑"),("mid","미드"),("bot","바텀")):
            change = self.s["pressure"][lane]-before["pressure"][lane]
            if change: parts.append(f"{label} 우리 주도권 {change:+d}")
        for side, label in ((0,"우리"),(1,"상대")):
            for lane, value in self.s["local_vision"][side].items():
                delta = value-before["vision"][side][lane]
                if delta: parts.append(f'{label} { {"top":"탑","mid":"미드","bot":"바텀","river":"강가","jungle":"정글"}[lane]} 시야 {delta:+.1f}')
            lost = sum(max(0,before["hp"][f'{side}:{u["role"]}']-u["hp"]) for u in self.s["teams"][side])
            if lost: parts.append(f"{label} 체력 합계 −{lost:.1f}%p")
        attempt = self.s["objective_attempt"]
        if attempt and attempt != before["objective_attempt"]:
            name = {"dragon":"드래곤", "herald":"전령", "baron":"바론"}[attempt["kind"]]
            parts.append(f'{"우리" if attempt["side"] == 0 else "상대"} {name} 사냥 개시 · 완료까지 {attempt["finish_at"]-self.s["time"]}초')
        return " · ".join(parts) or "처치·골드·시야 변화 없음 · 현재 전열 유지"

    def kill_unit(self, attacker, victim, allies):
        if victim["status"] == "dead": return
        previous = victim.get("kill_streak", 0)
        super().kill_unit(attacker, victim, allies)
        attacker["kill_streak"] += 1
        attacker["peak_streak"] = max(attacker["peak_streak"], attacker["kill_streak"])
        victim["kill_streak"] = 0
        streak = attacker["kill_streak"]
        detail = f'{self.unit_label(attacker)} +300G · {streak}연속 킬' + (f' · {victim["name"]}의 {previous}연속 킬 종료' if previous >= 2 else '')
        self.add_highlight("kill", f'{self.unit_label(attacker)} → {self.unit_label(victim)} 처치', detail, attacker["side"])

    def encounter(self, kind, lane, blue, red, rounds=2, initiative=None, forced=None):
        before = self.outcome_snapshot()
        groups = [[self.unit_label(u) for u in team if self.present(u)] for team in (blue,red)]
        previous = self.s["last_encounter"]
        result = super().encounter(kind,lane,blue,red,rounds,initiative,forced)
        info = self.s["last_encounter"]
        if info is previous: return result
        info.update(participants=groups, summary=self.outcome_summary(before),
                    kills=[self.s["kills"][i]-before["kills"][i] for i in (0,1)])
        large = all(len(t)>=3 for t in groups)
        if large or any(info["kills"]):
            title = f'{len(groups[0])}대{len(groups[1])} ' + ("대규모 교전" if large else "킬 발생")
            self.add_report(title, info["summary"], info)
            self.add_highlight("teamfight" if large else "skirmish",title,info["summary"],result)
        # A low-health opponent creates an actual player-controlled lane kill chance.
        if kind == "lane" and self.s["time"] >= self.s["next_lane_choice"] and not self.s["event"] and self.s["time"] < 1100:
            allies = [u for u in blue if self.present(u)]
            enemies = [u for u in red if self.present(u) and u["hp"] <= 60]
            if allies and enemies:
                actor, target = max(allies,key=self.threat), min(enemies,key=lambda u:u["hp"])
                chance = round(clamp(self.encounter_odds(allies,enemies,lane)+.1,.15,.90),2)
                self.s["event"] = {"id": f'kill-{self.s["tick"]}', "kind":"lane_kill", "title": "라인 킬 기회! 끝까지 추격할까요?",
                    "context": f'{self.unit_label(target)} 체력 {target["hp"]:.1f}%', "story":f'{self.unit_label(actor)}이(가) 킬 각을 포착했습니다. 성공하면 선공, 실패하면 상대가 먼저 반격합니다. 처치는 실제 교전으로 결정됩니다.',
                    "lane":lane,"role":actor["role"],"objective":None,
                    "skill":{"key":"AA","name":"기본 공격","tags":["damage"],"icon":"assets/skill-placeholder.svg"},
                    "options":[{"id":"commit","label":"추격하여 킬을 노린다","chance":chance,"detail":"3턴 교전 · 처치 시 300G · 역습 위험"},
                               {"id":"trade","label":"추격 대신 미니언 확보","chance":.9,"detail":"성공 시 담당 선수 +120G · 해당 라인 주도권 +1"},
                               {"id":"vision","label":"시야를 확보하고 물러난다","chance":.95,"detail":"성공 시 해당 라인 시야 +2 · 교전 중단"}],
                    "relic_bonus":round(sum(u.get("choice_bonus",0) for u in self.s["teams"][0])/5,4),"used_relics":[]}
                self.refresh_relic_chances()
                self.s["next_lane_choice"] = self.s["time"]+240
        return result

    def choose(self, option_id):
        event = self.s["event"]
        before = self.outcome_snapshot()
        if event and event["kind"] == "lane_kill":
            option = next((o for o in event["options"] if o["id"] == option_id),None)
            if not option or self.s["winner"] is not None: raise ValueError("현재 선택할 수 없는 전술입니다.")
            success = self.rng.random() < option["chance"]
            lane = event["lane"]
            if option_id == "commit":
                self.encounter("lane_finish",lane,self.lane_members(0,lane),self.lane_members(1,lane),rounds=3,initiative=0 if success else 1)
                self.s["followup"] = "countergank"
            elif option_id == "trade" and success:
                self.grant_gold(self.unit(0,event["role"]),120)
                self.s["pressure"][lane] = min(8,self.s["pressure"][lane]+1)
            elif option_id == "vision" and success:
                self.s["local_vision"][0][lane] = min(10,self.s["local_vision"][0][lane]+2)
            self.s["decisions"].append({"event":event["id"],"kind":event["kind"],"choice":option_id,"success":success,"chance":option["chance"],"time":self.s["time"]})
            self.s["event"] = None
            self.s["next_event"] = self.s["time"]+self.rng.integer(210,330)
        else:
            super().choose(option_id)
        outcome = self.outcome_summary(before)
        self.s["decisions"][-1]["outcome"] = outcome
        self.log("decision_result",outcome,0)
        self.add_report("선택 결과",outcome)
        self.add_highlight("decision",event["title"],outcome,0)

    def finish_awards(self):
        if self.s["winner"] is None or self.s["player_of_match"]: return
        candidates = []
        for side,team in enumerate(self.s["teams"]):
            for u in team:
                score = round(u["kills"]*3 + u["assists"]*1.5 - u["deaths"]*2 + u["saves"]*3
                              + u["damage_dealt"]/80 + u["peak_streak"] + (4 if side == self.s["winner"] else 0),2)
                candidates.append({"card_id":u["card_id"],"name":u["name"],"champion":u["champion"],"role":u["role"],"side":side,
                    "score":score,"kills":u["kills"],"deaths":u["deaths"],"assists":u["assists"],"damage":round(u["damage_dealt"],1),"saves":u["saves"],"peak_streak":u["peak_streak"]})
        self.s["player_of_match"] = max(candidates,key=lambda u:(u["score"],-u["side"],u["card_id"]))

    def step(self):
        if self.s.get("interactive") and self.s["reports"]:
            return
        super().step()
        self.finish_awards()
