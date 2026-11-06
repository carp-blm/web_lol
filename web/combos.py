"""Mechanic-driven, state-aware combos. Re-evaluate availability after every cast."""
PROFILES = {
    "Ahri": ("매혹 연계", "EQWR"), "LeeSin": ("음파 추격", "QQER"),
    "Leona": ("천공의 검 진입", "EQWR"), "Nautilus": ("닻 견인 연계", "QEAR"),
    "Alistar": ("박치기 · 분쇄", "WQER"), "JarvanIV": ("깃창 진입", "EQRW"),
    "Lux": ("속박 폭발", "QER"), "Renekton": ("진입 · 기절 · 이탈", "EWQE"),
    "Syndra": ("구체 기절", "QEWR"), "Orianna": ("공 배치 · 충격파", "QRW"),
    "Yasuo": ("강철 폭풍 연계", "EQR"), "Riven": ("기동 연계", "EQWQ"),
    "Elise": ("고치 · 형태 전환", "EQWR"), "Nidalee": ("창 적중 · 추격", "QWR"),
}


class ComboRules:
    def record_cast(self, unit, spell):
        now = self.s["time"]
        unit["recent_casts"] = [s for s in unit.get("recent_casts", []) if now - s["time"] < 8][-3:]
        unit["recent_casts"].append({"name": spell["name"], "key": spell["key"],
                                     "icon": spell.get("icon", "assets/skill-placeholder.svg"), "time": now})

    def spend_skill(self, unit, spell):
        super().spend_skill(unit, spell)
        self.record_cast(unit, spell)

    def execute_combo(self, caster, enemies, allies, lane, forced=None):
        if not self.present(caster) or caster.get("combo_ready_at", 0) > self.s["time"]:
            return []
        if caster["cc_until"] > self.s["time"] and caster["cc_strength"] >= 1.8:
            return []
        living = [u for u in enemies if self.present(u)]
        if not living:
            return []
        name, order = PROFILES.get(caster["champion"], ("제어 · 집중 사격", ""))
        casts, used, missed = [], set(), set()
        for index in range(4):
            living = [u for u in living if self.present(u)]
            if not living:
                break
            pool = [s for s in self.ready_skills(caster) if s.get("id", s["key"]) not in used
                    and (self.offensive(s) or "mobility" in s["tags"] or s.get("next_form"))]
            pool = [s for s in pool if not (s.get("stage") == 2 and s["key"] in missed)]
            # Yasuo's ultimate requires an actual knock-up, not simply any CC.
            pool = [s for s in pool if not (caster["champion"] == "Yasuo" and s["key"] == "R"
                    and not any(u.get("airborne_until", 0) > self.s["time"] for u in living))]
            spell = None
            if forced and index == 0:
                spell = next((s for s in pool if s.get("id") == forced.get("id") and s["key"] == forced["key"]), None)
            if not spell and pool:
                def rank(s):
                    e = s.get("effects", {})
                    if order:
                        return (order.find(s["key"]) if s["key"] in order else 10, s.get("stage", 1))
                    return (0 if index == 0 and e.get("cc") else 1 if index == 0 and "mobility" in s["tags"]
                            else 2 if s["key"] != "R" and e.get("damage") else 3, s["key"])
                spell = min(pool, key=rank)
            if not spell:
                if casts:
                    break
                spell = {"key": "AA", "name": "기본 공격", "tags": ["damage"], "icon": "assets/skill-placeholder.svg"}
            used.add(spell.get("id", spell["key"]))
            caster["combo_scale"] = .62 if spell["key"] != "AA" else 1
            targets = living
            if caster["champion"] == "Yasuo" and spell["key"] == "R":
                targets = [u for u in living if u.get("airborne_until", 0) > self.s["time"]]
            result = self.cast_attack(caster, targets, allies, lane, forced=spell)
            caster.pop("combo_scale", None)
            if not result:
                break
            result.update(combo=name, combo_step=index+1, skill_icon=spell.get("icon"), aoe=bool(spell.get("effects", {}).get("aoe")))
            casts.append(result)
            if not result["hits"] and self.offensive(spell):
                missed.add(spell["key"])
                if (caster["champion"], spell["key"]) in {("LeeSin", "Q"), ("Akali", "E"), ("Vex", "R")}:
                    self._spell_state(caster, spell)["chains"].pop(spell["key"], None)
            if "airborne" in spell.get("effects", {}).get("cc", []) and result["hits"]:
                ids = {t["card_id"] for t in result.get("targets", [])}
                for u in living:
                    if u["card_id"] in ids:
                        u["airborne_until"] = self.s["time"]+4
            if spell["key"] == "AA":
                break
        caster["combo_ready_at"] = self.s["time"]+8
        if casts:
            caster["last_combo"] = {"name": name, "time": self.s["time"],
                                    "steps": [{"key": s["skill"].split(":")[-1], "name": s.get("skill_name", "준비"), "icon": s.get("skill_icon"), "hit": bool(s["hits"])} for s in casts]}
        return casts
