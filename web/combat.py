"""Persistent one-second simulation. All timing, targeting and rolls use match RNG.

Values are common MVP balance rules, not patch-exact damage or spawn rules.
No function selects a match winner: the inherited structure path destroys a nexus.
"""
import math

LANES = ("top", "mid", "bot")
LABEL = {"top": "탑", "mid": "미드", "bot": "바텀", "jungle": "정글", "river": "강가"}
CC = {"blind": .6, "slow": 1.0, "root": 1.8, "polymorph": 2.3,
      "stun": 2.5, "airborne": 3.3, "suppression": 3.3,
      "silence": 1.2, "fear": 2.3, "charm": 2.3, "taunt": 2.3}
CC_KO = {"blind": "실명", "slow": "감속", "root": "속박", "polymorph": "변이",
         "stun": "기절", "airborne": "공중에 뜸", "suppression": "제압",
         "silence": "침묵", "fear": "공포", "charm": "매혹", "taunt": "도발"}


def bound(n, low, high):
    return max(low, min(high, n))


class CombatRules:
    def initialize_combat(self):
        s = self.s
        s.update(next_event=240, next_lane=95, next_jungle=120, next_roam=180,
                 next_vision=60, next_fight=920, invade_done=False,
                 local_vision=[{l: 0.0 for l in (*LANES, "jungle", "river")} for _ in range(2)],
                 camps=[{l: 90 for l in LANES} for _ in range(2)],
                 vision_actions=[{"placed": 0, "cleared": 0, "control": 0} for _ in range(2)],
                 encounter_counts={}, last_encounter=None, objective_attempt=None,
                 announced=[], next_siege={l: 480+self.rng.integer(0,20) for l in LANES}, rules="persistent-v3")
        for side, team in enumerate(s["teams"]):
            for unit in team:
                unit.update(side=side, hp=100.0, max_hp=100.0, gold=500, cs=0, kills=0, deaths=0,
                            assists=0, status="active", return_at=0, roam_until=0,
                            location=self.home_lane(unit), cc_until=0, cc_strength=0,
                            protected_until=0, saves=0)

    @staticmethod
    def home_lane(unit):
        return "bot" if unit["role"] == "sup" else "jungle" if unit["role"] == "jng" else unit["role"]

    def present(self, unit):
        return unit["status"] == "active" and unit["hp"] > 0

    def members(self, side, location=None):
        return [u for u in self.s["teams"][side] if self.present(u)
                and (location is None or u["location"] == location)]

    def vision_at(self, side, lane):
        return self.s["local_vision"][side].get(lane, 0)

    def vision_delta(self, side, lane):
        return self.vision_at(side, lane) - self.vision_at(1-side, lane)

    def grant_gold(self, unit, amount):
        amount = max(0, int(amount))
        unit["gold"] += amount
        self.s["gold"][unit["side"]] += amount

    def strength(self, unit, lane=None):
        if not self.present(unit):
            return 0
        stats = unit["ratings"]
        base = stats["combat"] * .45 + stats["lane"] * .25 + unit["mastery"] * .30
        items = 1 + min(2.5, max(0, unit["gold"]-500)/9500)
        health = .3 + .7 * unit["hp"]/100
        cc = 1 - min(.55, unit["cc_strength"]*.12) if unit["cc_until"] > self.s["time"] else 1
        return base * items * health * cc * (1 + self.s["dragons"][unit["side"]]*.018)

    def encounter_odds(self, blue, red, lane, bonus=0):
        a, b = sum(self.strength(u, lane) for u in blue), sum(self.strength(u, lane) for u in red)
        pressure = self.s["pressure"].get(lane, 0)
        return bound(a/max(1, a+b) + self.vision_delta(0, lane)*.012 + pressure*.007 + bonus, .05, .95)

    def power(self, side, role=None):
        units = [self.unit(side, role)] if role else self.s["teams"][side]
        return sum(self.strength(u) for u in units)/len(units)

    def odds(self, role=None):
        a = [self.unit(0, role)] if role else self.members(0)
        b = [self.unit(1, role)] if role else self.members(1)
        return self.encounter_odds(a, b, "bot" if role == "sup" else role or "river")

    def cc_value(self, spell, target):
        values = []
        for effect in spell.get("effects", {}).get("cc", []):
            value = CC.get(effect, 0)
            if effect == "blind" and self.champions[target["champion"]].get("attack_profile") == "ranged_auto":
                value *= 2.7
            values.append(value)
        return max(values, default=0)

    def hit_chance(self, caster, target, lane, skill=None):
        chance = .72 + (caster["mastery"]-target["mastery"])*.003
        chance += (caster["ratings"]["combat"]-target["ratings"]["combat"])*.0015
        chance += self.vision_delta(caster["side"], lane)*.018
        if target["cc_until"] > self.s["time"]:
            chance += target["cc_strength"]*.045
        if any("mobility" in s["tags"] for s in self.ready_skills(target)):
            chance -= .06
        return bound(chance, .22, .95)

    def protective_spells(self, caster, target):
        spells = list(self.ready_skills(caster))
        spells += [s for s in self._candidates(caster) if s["key"] == "P"
                   and caster["cooldowns"].get("protect:P", 0) <= self.s["time"]]
        for spell in spells:
            for effect in spell.get("effects", {}).get("defense", []):
                allowed = effect["target"] in ("both", "team") or (caster is target and effect["target"] == "self") or (caster is not target and effect["target"] == "ally")
                if allowed:
                    yield spell, effect

    def protect(self, victim, damage, allies, incoming=None):
        if victim["protected_until"] > self.s["time"]:
            return 0
        # Only participating, living allies can intervene. Self-only skills never save another unit.
        for caster in sorted(allies, key=lambda u: (u is victim, -u["mastery"])):
            if not self.present(caster) or (caster["cc_until"] > self.s["time"] and caster["cc_strength"] >= 1.8):
                continue
            for spell, effect in self.protective_spells(caster, victim):
                if effect["kind"] == "magic_shield" and (not incoming or incoming.get("effects", {}).get("damage_type") != "magic"):
                    continue
                if effect.get("health_cost", 0) >= caster["hp"]:
                    continue
                lethal = damage >= victim["hp"]
                chance = (.025 + caster["mastery"]*.0012) if lethal else (.08 + caster["mastery"]*.003)
                if effect["kind"] in ("revive", "invulnerable", "rescue") and not lethal:
                    continue
                if self.rng.random() >= chance:
                    continue
                if spell["key"] == "P":
                    caster["cooldowns"]["protect:P"] = self.s["time"] + 55
                else:
                    self.spend_skill(caster, spell)
                amount = 11 + caster["mastery"]*.16
                kind = effect["kind"]
                if kind == "heal":
                    victim["hp"] = min(100, victim["hp"]+amount)
                    if effect.get("health_cost"):
                        caster["hp"] = max(1, caster["hp"]-effect["health_cost"])
                elif kind in ("revive", "invulnerable", "rescue"):
                    damage = 0
                    victim["hp"] = max(victim["hp"], 18)
                    victim["protected_until"] = self.s["time"] + 3
                else:
                    damage = max(0, damage-amount)
                saved = lethal and damage < victim["hp"]
                if saved:
                    caster["saves"] += 1
                label = "죽음 직전 아군을 구했습니다!" if saved and caster is not victim else "치명상을 버텼습니다!" if saved else "피해를 완화했습니다."
                self.log("save" if saved else "protect", f'{caster["name"]} · {self.skill_label(spell)} → {victim["name"]}, {label}', caster["side"], spell)
                return damage
        return damage

    def kill_unit(self, attacker, victim, allies):
        if victim["status"] == "dead":
            return
        victim.update(hp=0, status="dead", location="base", roam_until=0,
                      return_at=self.s["time"] + min(65, 10 + self.s["time"]//80) + 10)
        victim["deaths"] += 1
        attacker["kills"] += 1
        side = attacker["side"]
        self.s["kills"][side] += 1
        self.grant_gold(attacker, 300)
        for ally in allies:
            if ally is not attacker and self.present(ally):
                ally["assists"] += 1
                self.grant_gold(ally, 75)
        self.s["momentum"][side] = min(6, self.s["momentum"][side]+1)
        self.after_encounter(attacker, victim, True)
        self.log("fight", f'{attacker["name"]} → {victim["name"]} 처치! {victim["return_at"]-self.s["time"]}초 뒤 복귀 · 성장과 인원 우위 확보.', side)

    def cast_attack(self, caster, enemies, allies, lane, preferred="damage", forced=None):
        living = [u for u in enemies if self.present(u)]
        if not living or not self.present(caster):
            return None
        candidates = [s for s in self.ready_skills(caster) if s.get("effects", {}).get("damage", "damage" in s["tags"]) or s.get("effects", {}).get("cc")]
        spell = forced if forced else self.rng.pick([s for s in candidates if preferred in s["tags"]] or candidates) if candidates else None
        spell = spell or {"key": "AA", "name": "기본 공격", "tags": ["damage"], "icon": "assets/skill-placeholder.svg"}
        self.spend_skill(caster, spell)
        effects = spell.get("effects", {})
        primary = self.rng.pick(living)
        targets = [primary] + [u for u in living if u is not primary] if effects.get("aoe") else [primary]
        targets = targets[:effects.get("max_targets", 5)]
        hits = 0
        for victim in targets:
            if self.rng.random() >= self.hit_chance(caster, victim, lane, spell):
                if victim is primary:
                    self.log("dodge", f'{victim["name"]}이(가) {caster["name"]}의 {spell["name"]}을 피했습니다.', victim["side"], spell)
                continue
            hits += 1
            hit_spell = spell if victim is primary else dict(spell, effects={**effects, "cc": effects.get("secondary_cc", effects.get("cc", []))})
            cc = self.cc_value(hit_spell, victim)
            if cc:
                victim["cc_strength"] = max(victim["cc_strength"] if victim["cc_until"] > self.s["time"] else 0, cc)
                victim["cc_until"] = self.s["time"] + 2 + math.ceil(cc*2)
            advantage = bound(self.strength(caster)/max(20, self.strength(victim)), .55, 1.8)
            damage = self.rng.integer(7, 13) * advantage * (1 + cc*.12)
            if spell["key"] != "AA":
                damage += self.rng.integer(5, 10) + caster["mastery"]*.04
            if caster["cc_until"] > self.s["time"]:
                damage *= 1 - min(.6, caster["cc_strength"]*.15)
            damage *= .72 if caster["role"] == "sup" else 1
            damage = self.protect(victim, damage, enemies, spell)
            victim["hp"] = round(max(0, victim["hp"]-damage), 2)
            if victim["hp"] <= 0:
                self.kill_unit(caster, victim, allies)
            else:
                self.after_encounter(caster, victim, False)
        if hits:
            names = "/".join(CC_KO.get(x, x) for x in effects.get("cc", []))
            self.log("skill", f'{caster["name"]} · {self.skill_label(spell)} {hits}명 적중' + (f' · {names}, 후속 공격 기회!' if names else '.'), caster["side"], spell)
        return {"caster": caster["role"], "skill": spell.get("id", spell["key"]), "hits": hits, "cc": effects.get("cc", [])}

    def recall(self, unit, lane):
        unit.update(status="recall", location="base", return_at=self.s["time"]+self.rng.integer(24, 36), roam_until=0)
        self.log("recall", f'{unit["name"]} 체력 {round(unit["hp"])}% · 귀환합니다. {LABEL.get(lane, lane)} 인원과 미니언을 내줍니다.', unit["side"])

    def encounter(self, kind, lane, blue, red, rounds=2, initiative=None, forced=None):
        blue, red = [u for u in blue if self.present(u)], [u for u in red if self.present(u)]
        if not blue or not red:
            return None
        # No ordinary support-only duel. Two isolated supports normally avoid fighting.
        if all(u["role"] == "sup" for u in blue+red) and self.rng.random() >= .005:
            return None
        s = self.s
        counts = s["encounter_counts"]
        counts[kind] = counts.get(kind, 0)+1
        odds = self.encounter_odds(blue, red, lane)
        info = {"time": s["time"], "kind": kind, "lane": lane, "sides": [[u["role"] for u in blue], [u["role"] for u in red]], "odds": round(odds, 3), "casts": []}
        labels = {"lane": "라인 교전", "gank": "갱킹", "counterjungle": "카운터 정글 조우", "jungle_duel": "정글 1대1", "invade": "초반 인베이드", "teamfight": "한타", "ambush": "시야 밖 기습", "objective": "오브젝트 교전", "roam": "로밍 합류"}
        self.log("encounter", f'{LABEL[lane]} · {labels.get(kind, kind)} {len(blue)}대{len(red)} · 체력·성장·시야가 교전에 반영됩니다.')
        for turn in range(rounds):
            first = initiative if turn == 0 and initiative is not None else 0 if self.rng.random() < odds else 1
            for side in (first, 1-first):
                friends, enemies = (blue, red) if side == 0 else (red, blue)
                for u in friends:
                    spell = forced if turn == 0 and forced and u["side"] == 0 and u["role"] == forced.get("actor_role") else None
                    cast = self.cast_attack(u, enemies, friends, lane, "aoe" if len(enemies)>2 else "cc", spell)
                    if cast:
                        info["casts"].append(cast)
        a, b = sum(self.strength(u) for u in blue), sum(self.strength(u) for u in red)
        side = 0 if a > b else 1
        info["advantage"] = side
        if lane in LANES:
            delta = 1 if side == 0 else -1
            s["pressure"][lane] = int(bound(s["pressure"][lane]+delta, -8, 8))
        for u in blue+red:
            if self.present(u) and u["hp"] < 27 and self.rng.random() < .83:
                self.recall(u, lane)
        s["last_encounter"] = info
        return side

    def start_roam(self, side, lane="mid"):
        u = self.unit(side, "sup")
        if not self.present(u) or u["roam_until"] > self.s["time"]:
            return False
        u.update(location=lane, roam_until=self.s["time"]+self.rng.integer(42, 66))
        self.log("roam", f'{u["name"]} 서포터가 {LABEL[lane]}로 로밍합니다. 바텀은 남은 인원으로 버텨야 합니다.', side)
        return True

    def lane_members(self, side, lane):
        return [u for u in self.members(side, lane) if u["role"] != "jng"]

    def gank(self, side, lane):
        jungler = self.unit(side, "jng")
        if not self.present(jungler):
            return
        jungler.update(location=lane, roam_until=self.s["time"]+18)
        detected = self.rng.random() < bound(.18 + self.vision_delta(1-side, lane)*.055, .05, .85)
        if detected:
            self.log("vision", f'{LABEL[lane]} 와드가 {jungler["name"]}의 갱 동선을 포착했습니다. 수비가 뒤로 빠집니다.', 1-side)
            self.s["pressure"][lane] = int(bound(self.s["pressure"][lane]+(1 if side == 0 else -1), -8, 8))
            return
        teams = [self.lane_members(i, lane) for i in (0, 1)]
        teams[side].append(jungler)
        enemy = self.unit(1-side, "jng")
        if self.present(enemy) and self.rng.random() < .12 + max(0, self.vision_delta(1-side, lane))*.025:
            enemy.update(location=lane, roam_until=self.s["time"]+18)
            teams[1-side].append(enemy)
            self.log("gank", f'{enemy["name"]}이(가) 동선을 읽고 역갱에 합류했습니다.', 1-side)
        self.encounter("gank", lane, *teams, rounds=2, initiative=side)

    def farm_camp(self, side, owner=None, lane=None):
        owner = side if owner is None else owner
        u = self.unit(side, "jng")
        if not self.present(u) or u["location"] != "jungle":
            return False
        ready = [l for l, at in self.s["camps"][owner].items() if self.s["time"] >= at]
        if lane:
            ready = [l for l in ready if l == lane]
        if not ready:
            return False
        lane = self.rng.pick(ready)
        self.s["camps"][owner][lane] = self.s["time"]+120
        self.grant_gold(u, 95 + u["ratings"]["farm"]//5)
        u["cs"] += 4
        u["hp"] = min(100, max(1, u["hp"]-3) + u["mastery"]*.05)
        self.log("jungle", f'{u["name"]} · {"상대 " if owner != side else ""}{LABEL[lane]} 쪽 캠프 정리. 120초 뒤 재생성.', side)
        return True

    def jungle_action(self, side):
        u, enemy = self.unit(side, "jng"), self.unit(1-side, "jng")
        if not self.present(u) or u["location"] != "jungle":
            return
        roll = self.rng.random()
        if self.available_objective() and roll < .18:
            self.start_objective(side, self.available_objective(), solo=True)
        elif roll < .47:
            weights = [max(1, 4 + self.s["pressure"][l]*(1 if side == 0 else -1)) for l in LANES]
            pool = [l for l, weight in zip(LANES, weights) for _ in range(weight)]
            self.gank(side, self.rng.pick(pool))
        elif roll < .72:
            detected = self.rng.random() < bound(.25+self.vision_delta(1-side, "jungle")*.05, .08, .8)
            if self.present(enemy) and enemy["location"] == "jungle" and self.rng.random() < (.8 if detected else .32):
                self.encounter("counterjungle", "jungle", [self.unit(0, "jng")], [self.unit(1, "jng")], rounds=2, initiative=1-side if detected else side)
            if self.present(u):
                self.farm_camp(side, 1-side)
        elif roll < .84 and self.present(enemy) and enemy["location"] == "jungle":
            self.encounter("jungle_duel", "river", [self.unit(0, "jng")], [self.unit(1, "jng")], rounds=2)
        else:
            self.farm_camp(side)

    def objective_ready(self, kind):
        s = self.s
        return (kind == "dragon" and s["time"] >= s["next_dragon"]) or (kind == "baron" and s["time"] >= s["next_baron"]) or (kind == "herald" and 480 <= s["time"] < 1200 and s["herald_available"])

    def start_objective(self, side, kind, solo=False):
        if self.s["objective_attempt"] or not self.objective_ready(kind):
            return False
        squad = [self.unit(side, "jng")] if solo else self.members(side)
        squad = [u for u in squad if self.present(u) and u["hp"] >= 40]
        if not squad or (kind == "baron" and len(squad) < 3):
            return False
        for u in squad:
            u.update(location="river", roam_until=self.s["time"]+(32 if solo else 22))
        self.s["objective_attempt"] = {"side": side, "kind": kind, "roles": [u["role"] for u in squad],
                                       "finish_at": self.s["time"]+(28 if solo else 18), "solo": solo}
        self.log("objective", f'{"우리" if side == 0 else "상대"} 팀 · {"정글 단독" if solo else "팀 합류"} {kind} 사냥 시작. 시야에 따라 발각될 수 있습니다.', side)
        return True

    def resolve_objective(self):
        attempt = self.s["objective_attempt"]
        if not attempt or self.s["time"] < attempt["finish_at"]:
            return
        self.s["objective_attempt"] = None
        side = attempt["side"]
        squad = [self.unit(side, r) for r in attempt["roles"] if self.present(self.unit(side, r)) and self.unit(side, r)["location"] == "river"]
        if not squad or not self.objective_ready(attempt["kind"]):
            return
        detected = self.rng.random() < bound(.32+self.vision_delta(1-side, "river")*.065, .05, .9)
        opponents = self.members(1-side)
        if detected and opponents:
            if attempt["solo"]:
                opponents = [u for u in opponents if u["role"] in ("jng", "mid", "sup")][:2]
            self.log("vision", "오브젝트 사냥이 발각됐습니다. 상대가 견제하러 합류합니다.", 1-side)
            groups = [squad, opponents] if side == 0 else [opponents, squad]
            winner = self.encounter("objective", "river", *groups, rounds=3)
            if winner is not None:
                side = winner
                squad = [u for u in groups[side] if self.present(u)]
        if squad:
            # Monster damage and time are paid even for an unseen attempt.
            for u in squad:
                u["hp"] = max(1, u["hp"]-(22 if attempt["solo"] else 9))
            if self.rng.random() < bound(.65+sum(u["mastery"] for u in squad)/len(squad)*.003, .7, .96):
                self.objective(side, attempt["kind"])

    def ward_cycle(self):
        s = self.s
        for side in (0, 1):
            for loc in s["local_vision"][side]:
                s["local_vision"][side][loc] = max(0, s["local_vision"][side][loc]-.45)
            for u in self.members(side):
                stats = u.get("vision_stats", {})
                values = []
                for key, fallback in (("wardsplaced", .3), ("wardskilled", .12), ("controlwardsbought", .12)):
                    value = stats.get(key, {}).get("per_minute")
                    values.append(fallback * u["ratings"]["vision"]/70 if value is None else value)
                loc = u["location"]
                if loc not in s["local_vision"][side]:
                    continue
                for value, action in zip(values, ("placed", "cleared", "control")):
                    if self.rng.random() < bound(value/2, 0, .95):
                        s["vision_actions"][side][action] += 1
                        if action == "cleared":
                            s["local_vision"][1-side][loc] = max(0, s["local_vision"][1-side][loc]-1.4)
                        else:
                            gain = 1.6 if action == "control" else 1.0
                            if action == "control":
                                if u["gold"] < 75:
                                    continue
                                u["gold"] -= 75
                                s["gold"][side] = max(0, s["gold"][side]-75)
                            s["local_vision"][side][loc] = min(10, s["local_vision"][side][loc]+gain)
                            if u["role"] in ("sup", "jng"):
                                s["local_vision"][side]["river"] = min(10, s["local_vision"][side]["river"]+gain*.8)
            s["vision"][side] = round(sum(s["local_vision"][side].values())/5, 2)

    def waves(self):
        s = self.s
        for lane in LANES:
            teams = [self.lane_members(side, lane) for side in (0, 1)]
            for side in (0, 1):
                farmers = [u for u in teams[side] if u["role"] != "sup"]
                for u in farmers:
                    advantage = s["pressure"][lane]*(1 if side == 0 else -1)
                    count = int(bound(3 + u["ratings"]["farm"]//25 + advantage//3, 1, 6))
                    u["cs"] += count
                    self.grant_gold(u, count*19)
                # Missing laners concede waves, XP-equivalent growth, and structure pressure.
            diff = len(teams[0])-len(teams[1])
            if diff:
                s["pressure"][lane] = int(bound(s["pressure"][lane]+(1 if diff>0 else -1), -8, 8))

    def siege(self, lane):
        s = self.s
        teams = [self.lane_members(side, lane) for side in (0, 1)]
        if teams[0] or teams[1]:
            p = self.encounter_odds(*teams, lane)
            side = 0 if self.rng.random() < p else 1
            if not teams[side]:
                return
            open_lane = not teams[1-side]
            pressure = abs(s["pressure"][lane])
            damage = round((35+s["time"]*.035+pressure*5)*(1.8 if open_lane else 1))
            if s["buff_until"][side] > s["time"]:
                damage += 140
            self.push(side, lane, damage)
            if s["winner"] is not None:
                return

    def make_event(self):
        s = self.s
        lane = min(LANES, key=lambda l: s["pressure"][l])
        active = self.members(0)
        if not active:
            s["next_event"] = s["time"]+30
            return
        obj, follow = self.available_objective(), s["followup"]
        kind = "followup" if follow else "objective" if obj else "roam" if self.present(self.unit(0, "sup")) and not self.unit(0, "sup")["roam_until"] > s["time"] else "gank"
        role = "sup" if kind == "roam" else "jng"
        unit = self.unit(0, role)
        if unit not in active:
            unit = active[0]
            role = unit["role"]
        ready = self.ready_skills(unit)
        spell = max(ready, key=lambda x: max((CC.get(c, 0) for c in x.get("effects", {}).get("cc", [])), default=0), default={"key": "AA", "name": "기본 공격", "tags": ["damage"], "icon": "assets/skill-placeholder.svg"})
        cc = max((CC.get(c, 0) for c in spell.get("effects", {}).get("cc", [])), default=0)
        p = round(bound(self.encounter_odds(self.members(0), self.members(1), lane)+(unit["mastery"]-60)*.002+cc*.025, .12, .90), 2)
        options = [
            {"id": "commit", "label": f'{self.skill_label(spell)}로 교전 개시', "chance": p,
             "detail": f'선공 기회 · CC 영향 {cc:.1f} · 실패 시 역습과 귀환 위험', "effect": "commit"},
            {"id": "vision", "label": "시야 확보 후 기회를 기다린다", "chance": round(bound(p+.18,.3,.95),2),
             "detail": "150G · 주변 시야 +3 · 후속 기습 탐지", "effect": "vision"},
            {"id": "trade", "label": "반대편 라인에서 성장한다", "chance": round(bound(.7+s["pressure"][lane]*.01,.45,.9),2),
             "detail": "교전 회피 · 반대쪽 미니언 확보 · 오브젝트 견제 포기", "effect": "trade"}]
        if kind == "roam":
            options.append({"id": "roam", "label": "서포터를 미드로 로밍", "chance": round(bound(p+self.vision_delta(0,"mid")*.015,.15,.9),2),
                            "detail": "42~66초 합류 · 바텀 원딜이 홀로 남을 수 있음", "effect": "roam"})
        elif follow:
            options.append({"id": "disengage", "label": "전열을 지키며 후퇴", "chance": .95,
                            "detail": "체력 보존 · 라인 주도권 양보", "effect": "disengage"})
        s["event"] = {"id": f'e-{s["tick"]}', "kind": kind, "title": "앞선 선택이 만든 다음 기회" if follow else "잠깐, 팀의 방향을 정해주세요",
                      "context": f'{s["time"]//60}:{s["time"]%60:02d} · {LABEL[lane]} 주도권 {s["pressure"][lane]:+d} · 시야 {self.vision_delta(0,lane):+.1f}',
                      "story": f'{unit["name"]} 체력 {round(unit["hp"])}% · 숙련도 {unit["mastery"]}. 자동 교전은 계속되며, 지금은 중요한 전술만 결정합니다. ' + ("앞선 공격을 읽은 역갱 위험입니다." if follow == "countergank" else ""),
                      "lane": lane, "role": role, "objective": obj, "skill": spell, "options": options}
        s["followup"] = None

    def choose(self, option_id):
        s, event = self.s, self.s["event"]
        option = next((o for o in event["options"] if o["id"] == option_id), None) if event else None
        if option is None or s["winner"] is not None:
            raise ValueError("현재 선택할 수 없는 전술입니다.")
        success = self.rng.random() < option["chance"]
        lane = event["lane"]
        if option_id == "commit":
            squad = [self.lane_members(i, lane) for i in (0, 1)]
            for i in (0, 1):
                j = self.unit(i, "jng")
                if self.present(j):
                    j.update(location=lane, roam_until=s["time"]+20)
                    squad[i].append(j)
            actor = self.unit(0, event["role"])
            if self.present(actor) and actor not in squad[0]:
                actor.update(location=lane, roam_until=s["time"]+20)
                squad[0].append(actor)
            forced = dict(event["skill"], actor_role=actor["role"])
            self.encounter("gank", lane, *squad, rounds=3, initiative=0 if success else 1, forced=forced)
            s["pressure"][lane] = int(bound(s["pressure"][lane]+(2 if success else -2), -8, 8))
            if event["objective"]:
                self.start_objective(0 if success else 1, event["objective"])
            s["followup"] = "countergank" if event["kind"] != "followup" else None
        elif option_id == "vision":
            s["gold"][0] = max(0, s["gold"][0]-150)
            for loc in (lane, "river"):
                s["local_vision"][0][loc] = bound(s["local_vision"][0][loc]+(3 if success else -1),0,10)
            if success and event["kind"] != "followup":
                s["followup"] = "vision_pick"
        elif option_id == "roam":
            self.start_roam(0)
            if success:
                self.encounter("roam", "mid", self.lane_members(0,"mid"), self.lane_members(1,"mid"), initiative=0)
            else:
                self.gank(1, "bot")
        elif option_id == "trade":
            opposite = "bot" if lane != "bot" else "top"
            if success:
                self.grant_gold(self.unit(0, opposite), 180)
                s["pressure"][opposite] = min(8, s["pressure"][opposite]+2)
            if event["objective"]:
                self.start_objective(1, event["objective"])
        else:
            s["pressure"][lane] = max(-8, s["pressure"][lane]-1)
            for u in self.lane_members(0, lane):
                if u["hp"] < 45:
                    self.recall(u, lane)
        s["decisions"].append({"event": event["id"], "kind": event["kind"], "choice": option_id, "success": success, "chance": option["chance"], "time": s["time"]})
        self.log("decision", f'{option["label"]} · 전술 {"성공" if success else "실패"} ({round(option["chance"]*100)}%). 이후 교전·성장에 반영됩니다.', 0, event["skill"])
        s["event"] = None
        s["next_event"] = s["time"] + self.rng.integer(210, 330)

    def step(self):
        s = self.s
        if s["winner"] is not None or s["event"]:
            return
        s["time"] += 1
        s["tick"] += 1
        now = s["time"]
        self.advance_forms(1)
        for team in s["teams"]:
            for u in team:
                if u["status"] != "active" and now >= u["return_at"]:
                    u.update(status="active", hp=100.0, location=self.home_lane(u), cc_until=0, cc_strength=0)
                    self.log("return", f'{u["name"]} 전장 복귀 · 체력을 회복했습니다.', u["side"])
                if u["roam_until"] and now >= u["roam_until"]:
                    u.update(roam_until=0, location=self.home_lane(u))
                if self.present(u):
                    u["hp"] = round(min(100, u["hp"]+.065), 3)
                if now >= 90 and now % 5 == 0:
                    self.grant_gold(u, 10)
        if not s["invade_done"] and now >= 45:
            s["invade_done"] = True
            if self.rng.random() < .35:
                teams = [[self.unit(i,r) for r in ("jng","mid","sup")] for i in (0,1)]
                self.encounter("invade", "jungle", *teams, rounds=2)
        if now >= 90 and now % 30 == 0:
            self.waves()
        for lane in LANES:
            if now >= s["next_siege"][lane]:
                self.siege(lane)
                s["next_siege"][lane] = now + self.rng.integer(24, 36)
            if s["winner"] is not None:
                return
        if now >= s["next_vision"]:
            self.ward_cycle()
            s["next_vision"] = now+30
        if now >= 90 and now % 32 == 0:
            for side in (0,1):
                self.farm_camp(side)
        if now >= s["next_lane"]:
            lane = self.rng.pick(LANES)
            self.encounter("lane", lane, self.lane_members(0,lane), self.lane_members(1,lane), rounds=2)
            s["next_lane"] = now+self.rng.integer(17, 29)
        if now >= s["next_jungle"]:
            self.jungle_action(self.rng.integer(0,1))
            s["next_jungle"] = now+self.rng.integer(24, 38)
        if now >= s["next_roam"]:
            for side in (0,1):
                support = self.unit(side,"sup")
                chance = .23+(support["ratings"]["vision"]-60)*.004+self.vision_delta(side,"mid")*.015
                if self.rng.random() < chance:
                    self.start_roam(side, "mid" if self.rng.random()<.8 else "top")
            s["next_roam"] = now+self.rng.integer(75,120)
        if now >= s["next_fight"]:
            kind = "ambush" if abs(self.vision_delta(0,"river"))>2 else "teamfight"
            side = self.encounter(kind, "river", self.members(0), self.members(1), rounds=3)
            if side is not None:
                lane = min(LANES,key=lambda l:s["towers"][1-side][l]*1500+s["inhibitors"][1-side][l])
                self.push(side, lane, 150+now//4)
                self.start_objective(side, self.available_objective()) if self.available_objective() else None
            s["next_fight"] = now+self.rng.integer(65,110)
        self.resolve_objective()
        for key, label in (("next_dragon","드래곤"),("next_baron","바론")):
            token = f'{key}:{s[key]}'
            if now >= s[key] and token not in s["announced"]:
                s["announced"].append(token)
                self.log("objective", f'{label} 출현 · 시야와 합류 인원을 확인하세요.')
        if now >= s["next_event"] and s["winner"] is None:
            self.make_event()

    def simulate(self):
        for _ in range(14400):
            if self.s["winner"] is not None:
                return self.s["winner"]
            if self.s["event"]:
                self.choose(self.rng.pick(self.s["event"]["options"])["id"])
            else:
                self.step()
        raise RuntimeError("Simulation invariant failed: no nexus destroyed")
