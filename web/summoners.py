"""Pinned Riot 16.20.1 base spell timers, in simulation seconds (no haste).

Smite has two charges: 90s sequential recharge and 15s cast lockout.
Spell damage and choice bonuses are deliberately scaled for this simulator.
"""
SPELLS = {
    "flash": ("점멸", "SummonerFlash", 300, "거리 좁히기 · 추격 / 이탈", .28),
    "teleport": ("순간이동", "SummonerTeleport", 300, "먼 거리에서 전장 합류", .30),
    "ignite": ("점화", "SummonerDot", 180, "킬 마무리 · 회복 억제", .25),
    "heal": ("회복", "SummonerHeal", 240, "자신과 주변 아군 회복", .24),
    "barrier": ("방어막", "SummonerBarrier", 180, "치명적인 피해 방어", .24),
    "cleanse": ("정화", "SummonerBoost", 240, "군중 제어 해제", .28),
    "exhaust": ("탈진", "SummonerExhaust", 240, "적 딜러 약화", .26),
    "ghost": ("유체화", "SummonerHaste", 240, "추격과 안전한 후퇴", .24),
    "smite": ("강타", "SummonerSmite", 90, "오브젝트 확보 · 2충전 / 사용 간격 15초", .32),
}
DEFAULTS = {"top": ["flash", "teleport"], "jng": ["flash", "smite"],
            "mid": ["flash", "ignite"], "bot": ["flash", "barrier"], "sup": ["flash", "exhaust"]}
CATALOG = {key: {"id": key, "name": v[0], "icon": f"https://ddragon.leagueoflegends.com/cdn/16.20.1/img/spell/{v[1]}.png",
                 "cooldown": v[2], "description": v[3], "bonus": v[4]} for key, v in SPELLS.items()}


class SummonerRules:
    def initialize_summoners(self):
        for team in self.s["teams"]:
            for u in team:
                u["summoners"] = {key: {"ready_at": 0, "charges": 2 if key == "smite" else 1, "recharge_at": 0, "uses": 0}
                                  for key in u.get("summoner_loadout", DEFAULTS[u["role"]])}

    def advance_summoners(self):
        now = self.s["time"]
        for team in self.s["teams"]:
            for u in team:
                u["level"] = min(18, 1 + now // 100 + u["cs"] // 70)
                for key, spell in u["summoners"].items():
                    cap = 2 if key == "smite" else 1
                    if spell["charges"] < cap and now >= spell["recharge_at"]:
                        spell["charges"] += 1
                        spell["recharge_at"] = now + 90 if key == "smite" and spell["charges"] < cap else 0

    def summoner_ready(self, u, key):
        spell = u.get("summoners", {}).get(key)
        return bool(spell and self.present(u) and spell["charges"] > 0 and self.s["time"] >= spell["ready_at"])

    def summoner_cooldown(self, u, key):
        if key == "teleport" and self.s["time"] >= 600:
            return round(330 - 90 * (u.get("level", 1) - 1) / 17)
        return CATALOG[key]["cooldown"]

    def spend_summoner(self, u, key, reason):
        if not self.summoner_ready(u, key):
            raise ValueError("사용할 수 없는 소환사 주문입니다.")
        spell, now = u["summoners"][key], self.s["time"]
        spell["charges"] -= 1
        spell["uses"] += 1
        cooldown = self.summoner_cooldown(u, key)
        spell["ready_at"] = now + (15 if key == "smite" else cooldown)
        if not spell["recharge_at"]:
            spell["recharge_at"] = now + cooldown
        self.record_cast(u, {**CATALOG[key], "key": "D" if list(u["summoners"])[0] == key else "F"})
        self.log("summoner", f'{u["name"]} · {CATALOG[key]["name"]} 사용 — {reason}', u["side"], CATALOG[key])

    def summoner_options(self, event, option):
        result = []
        for u in self.s["teams"][0]:
            if not self.present(u):
                continue
            for key in u["summoners"]:
                if not self.summoner_ready(u, key):
                    continue
                near = self.distance(u["pos"], event.get("position", u["pos"])) <= 26
                allowed = (option["id"] == "commit" and (near or key == "teleport"))
                allowed |= option["id"] in ("roam", "trade") and key in ("teleport", "ghost")
                allowed |= option["id"] == "disengage" and near and key in ("flash", "heal", "barrier", "cleanse", "ghost", "exhaust")
                if key == "smite" and not event.get("objective"):
                    allowed = False
                if allowed:
                    chance = round(min(.98, option["chance"] + CATALOG[key]["bonus"]), 2)
                    result.append({**CATALOG[key], "role": u["role"], "player": u["name"], "chance": chance,
                                   "cooldown": self.summoner_cooldown(u, key)})
        return result

    def choose_with_summoner(self, option_id, role, key):
        event = self.s["event"]
        option = next((o for o in event["options"] if o["id"] == option_id), None) if event else None
        offer = next((s for s in self.summoner_options(event, option) if s["role"] == role and s["id"] == key), None) if option else None
        if not offer or self.s["winner"] is not None or self.s.get("interactive") and self.s.get("reports"):
            raise ValueError("이 선택에서 사용할 수 있는 주문을 고르세요.")
        actor = self.unit(0, role)
        self.spend_summoner(actor, key, option["label"])
        if key == "teleport":
            # Teleport is the only deliberate long-distance instant reposition in this model.
            actor.update(pos=list(event["position"]), destination=list(event["position"]),
                         route=[], moving=False, location=event["lane"], intent="순간이동 합류", roam_until=self.s["time"]+35)
        elif key == "heal":
            for ally in self.nearby(0, actor["pos"], 15)[:2]:
                ally["hp"] = min(100, ally["hp"] + 20)
        option["chance"] = offer["chance"]
        self.choose(option_id)
        attempt = self.s["objective_attempt"]
        if key == "smite" and attempt and attempt["side"] == 0 and role in attempt["roles"]:
            attempt["prepared_smite"] = role
        self.s["decisions"][-1]["summoner"] = {"role": role, "id": key}

    def protect(self, victim, damage, allies, incoming=None):
        if damage >= victim["hp"] or victim["hp"] < 30:
            for key in ("barrier", "heal", "flash", "exhaust"):
                if self.summoner_ready(victim, key) and self.rng.random() < .32:
                    self.spend_summoner(victim, key, "위기에서 생존 시도")
                    if key == "heal":
                        victim["hp"] = min(100, victim["hp"] + 20)
                    else:
                        damage *= .3 if key == "flash" else .45
                    break
        if victim["cc_until"] > self.s["time"] and victim["cc_strength"] < 3.3 and self.summoner_ready(victim, "cleanse"):
            self.spend_summoner(victim, "cleanse", "군중 제어 해제")
            victim.update(cc_until=0, cc_strength=0)
        return super().protect(victim, damage, allies, incoming)
