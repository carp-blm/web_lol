"""Stateful ability selection for the coarse, seeded match simulation.

Transitions are explicit; rendering and availability checks never consume RNG.
Timers/resources are MVP abstractions, not claims of patch-exact LoL simulation.
"""
import copy


class AbilityRules:
    def initialize_abilities(self):
        for team in self.s["teams"]:
            for unit in team:
                config = self.champions[unit["champion"]].get("kit", {})
                form = config.get("initial", "base")
                unit["ability_state"] = {
                    "form": form, "form_label": config.get("forms", {}).get(form, "기본"),
                    "resource": 0, "until": 0, "next_at": 90, "last_basic": None,
                    "chains": {}, "mount_hp": 100, "borrowed": None, "stolen": None,
                    "weapon_order": list(config["form_order"]), "ammo": {
                        f: 50 for f in config.get("forms", {})},
                }

    def set_form(self, unit, form, state=None, source_id=None):
        state = unit["ability_state"] if state is None else state
        source_id = source_id or unit["champion"]
        config = self.champions[source_id]["kit"]
        if state["form"] == form:
            return
        state["form"] = form
        state["form_label"] = config["forms"][form]
        self.log("form", f'{unit["name"]}의 {self.champions[source_id]["name"]} · {state["form_label"]} 전환.')

    def _candidates(self, unit):
        champion = self.champions[unit["champion"]]
        state = unit["ability_state"]
        borrowed = state["borrowed"]
        if borrowed and borrowed["until"] > self.s["time"]:
            source = self.champions[borrowed["champion"]]
            copy_label = "강탈" if unit["champion"] == "Sylas" else "빙의"
            pool = [dict(s, form_label=f'{copy_label} · {source["name"]} / {s["form_label"]}')
                    for s in source["variants"] if s["key"] in "QWE" and s["form"] == borrowed["state"]["form"]]
            pool += [s for s in champion["variants"] if s["key"] == "R" and s["form"] == state["form"]]
        else:
            pool = [s for s in champion.get("variants", champion["skills"])
                    if s.get("form", "base") == state["form"]]
        if state["stolen"]:
            stolen = state["stolen"]
            if not stolen.get("activated") or state["chains"].get("R", {}).get("until", 0) >= self.s["time"]:
                pool.append(stolen)
                pool.extend(stolen.get("recasts", []))
        return pool

    def ready_skills(self, unit):
        state, now = unit["ability_state"], self.s["time"]
        ready = []
        for spell in self._candidates(unit):
            if not spell.get("castable", spell["key"] != "P") or now < spell.get("min_time", 360 if spell["key"] == "R" else 0):
                continue
            used_state = self._spell_state(unit, spell)
            source_id = spell["source_champion"] if used_state is not state else unit["champion"]
            config = self.champions[source_id]["kit"]
            key = spell["key"]
            chain = used_state["chains"].get(key)
            chain = chain if chain and chain["until"] >= now else None
            if spell.get("stage", 1) != (2 if chain else 1):
                continue
            if spell.get("requires_last") and spell["requires_last"] != used_state["last_basic"]:
                continue
            if config["mode"] == "awaken" and used_state["form"] == "awakened" and key != used_state["last_basic"]:
                continue
            group = spell.get("cooldown_group", key)
            # Recast follows the first cast; it does not require the base cooldown to finish.
            if chain and spell.get("stage") == 2:
                if now < chain.get("next_at", 0):
                    continue
            elif unit["cooldowns"].get(group, 0) > now:
                continue
            ready.append(spell)
        return ready

    def _spell_state(self, unit, spell):
        state = unit["ability_state"]
        if (state["borrowed"] and state["borrowed"]["until"] > self.s["time"]
                and spell.get("source_champion") == state["borrowed"]["champion"] and spell["key"] in "QWE"):
            return state["borrowed"]["state"]
        return state

    def spend_skill(self, unit, spell):
        now, key = self.s["time"], spell["key"]
        if key == "AA":
            return
        state = unit["ability_state"]
        used_state = self._spell_state(unit, spell)
        source_id = spell["source_champion"] if used_state is not state else unit["champion"]
        config = self.champions[source_id]["kit"]
        def change_form(form):
            self.set_form(unit, form, used_state, source_id)
        group = spell.get("cooldown_group", key)
        cooldown = 100 if key == "R" and not config.get("basic_r") else 35
        if spell.get("stage") != 2:
            unit["cooldowns"][group] = now + cooldown
        if spell.get("stage") == 1:
            used_state["chains"][key] = {"until": now + 90}
        elif spell.get("stage") == 2:
            if spell.get("source_champion") == "Swain" and key == "R":
                used_state["chains"][key]["next_at"] = now + 35
            else:
                used_state["chains"].pop(key, None)
        if key in "QWE" or config.get("basic_r"):
            used_state["last_basic"] = key
        if spell.get("next_form") and spell.get("source_champion") == source_id:
            change_form(spell["next_form"])
        if source_id == "Briar" and key == "E":
            used_state["chains"].pop("W", None)
        if key == "R" and state["stolen"] and spell["id"].startswith("Sylas:stolen:"):
            if spell.get("stage") == 1:
                state["stolen"]["activated"] = True
            elif spell.get("stage") != 2 or spell.get("source_champion") != "Swain":
                state["stolen"] = None
        if key == "R" and state["borrowed"]:
            state["borrowed"] = None
        mode = config["mode"]
        if mode == "empower" and used_state["form"] == "empowered" and key in "QWE":
            change_form("normal")
            used_state["next_at"] = now + 100
            if used_state is state:
                unit["cooldowns"]["R"] = now + 100
        elif mode == "ferocity" and key in "QWE":
            if used_state["form"] == "empowered":
                used_state["resource"] = 0
                change_form("normal")
            else:
                used_state["resource"] += 1
                if used_state["resource"] >= 4:
                    change_form("empowered")
        elif mode == "awaken" and used_state["form"] == "awakened":
            change_form("normal")
            used_state["next_at"] = now + 120
        elif mode == "stardust" and key == "R" and used_state["form"] == "empowered":
            used_state["resource"] = 0
            change_form("normal")
        elif mode == "element" and key == "Q":
            change_form("base")
            used_state["next_at"] = now + 35
        elif mode == "weapon" and key == "Q":
            self.consume_ammo(unit, 10, used_state, source_id)
        elif mode == "mount" and used_state["form"] == "unmounted":
            used_state["resource"] = min(100, used_state["resource"] + 25)

    def use_skill(self, unit, preferred=None):
        ready = self.ready_skills(unit)
        if not ready:
            return {"key": "AA", "name": "기본 공격", "tags": ["damage"],
                    "form_label": unit["ability_state"]["form_label"], "icon": "assets/skill-placeholder.svg"}
        tagged = [s for s in ready if preferred in s["tags"]] if preferred else []
        spell = self.rng.pick(tagged or ready)
        self.spend_skill(unit, spell)
        return spell

    def consume_ammo(self, unit, amount, state=None, source_id=None):
        state = unit["ability_state"] if state is None else state
        order = state["weapon_order"]
        main = order[0]
        state["ammo"][main] = max(0, state["ammo"][main] - amount)
        if state["ammo"][main] == 0:
            order.append(order.pop(0))
            state["ammo"][main] = 50
            self.set_form(unit, order[0], state, source_id)
        state["offhand"] = order[1]

    def advance_forms(self, dt):
        now = self.s["time"]
        for side, team in enumerate(self.s["teams"]):
            for unit in team:
                state = unit["ability_state"]
                config = self.champions[unit["champion"]]["kit"]
                mode, forms = config["mode"], config["form_order"]
                if state["borrowed"] and now >= state["borrowed"]["until"]:
                    state["borrowed"] = None
                if state["stolen"] and state["stolen"].get("activated") and state["chains"].get("R", {}).get("until", 0) < now:
                    state["stolen"] = None
                    state["chains"].pop("R", None)
                if mode == "stance" and now >= state["next_at"]:
                    self.set_form(unit, forms[1 - forms.index(state["form"])])
                    state["next_at"] = now + 90
                elif mode in ("rage", "fury"):
                    if state["form"] == forms[0]:
                        if now >= state["next_at"]:
                            state["resource"] = min(100, state["resource"] + dt * .55)
                        if state["resource"] >= 100 and (mode == "rage" or now >= 360):
                            self.set_form(unit, forms[1])
                    else:
                        state["resource"] = max(0, state["resource"] - dt * 1.5)
                        if state["resource"] == 0:
                            self.set_form(unit, forms[0])
                            state["next_at"] = now + 45
                elif mode == "ultimate":
                    if state["form"] == forms[0] and now >= max(360, state["next_at"]):
                        self.set_form(unit, forms[1])
                        state["until"] = now + 90
                        unit["cooldowns"]["R"] = now + 180
                    elif state["form"] == forms[1] and now >= state["until"]:
                        self.set_form(unit, forms[0])
                        state["next_at"] = now + 90
                elif mode == "permanent" and state["form"] == forms[0] and now >= 600:
                    self.set_form(unit, self.rng.pick(forms[1:]))
                elif mode == "empower" and state["form"] == "normal" and now >= max(config["unlock"], state["next_at"]):
                    self.set_form(unit, "empowered")
                elif mode == "awaken" and state["form"] == "normal" and state["last_basic"] and now >= state["next_at"]:
                    self.set_form(unit, "awakened")
                    # Awakened recast is available even if the preceding stance is cooling down.
                    unit["cooldowns"][state["last_basic"]] = now
                elif mode == "stardust":
                    state["resource"] = min(100, state["resource"] + dt * .15)
                    if state["resource"] == 100:
                        self.set_form(unit, "empowered")
                elif mode == "element" and state["form"] == "base" and now >= state["next_at"]:
                    self.set_form(unit, self.rng.pick(forms[1:]))
                elif mode == "mount" and state["form"] == "unmounted":
                    state["resource"] = min(100, state["resource"] + dt * .25)
                    if state["resource"] == 100:
                        self.set_form(unit, "mounted")
                        state["mount_hp"], state["resource"] = 100, 0
                elif mode == "weapon":
                    if now >= state["next_at"]:
                        order = state["weapon_order"]
                        order[0], order[1] = order[1], order[0]
                        self.set_form(unit, order[0])
                        state["next_at"] = now + 90
                    state["offhand"] = state["weapon_order"][1]
                if config.get("copy") == "ultimate" and now >= 360 and unit["cooldowns"].get("R", 0) <= now and not state["stolen"] and not state["borrowed"]:
                    self.steal_ultimate(unit, self.rng.pick(self.s["teams"][1-side]))

    def steal_ultimate(self, unit, enemy):
        state = unit["ability_state"]
        source = self.champions[enemy["champion"]]
        if source["kit"]["mode"] == "stance" and "R" in source["kit"].get("controls", []):
            # A stolen transform borrows the alternate Q/W/E kit, not an imaginary damage R.
            borrowed = copy.deepcopy(enemy["ability_state"])
            forms = source["kit"]["form_order"]
            borrowed["form"] = forms[1 - forms.index(borrowed["form"])]
            borrowed["form_label"] = source["kit"]["forms"][borrowed["form"]]
            borrowed["chains"] = {}
            state["borrowed"] = {"champion": enemy["champion"], "state": borrowed, "until": self.s["time"] + 90}
            unit["cooldowns"]["R"] = self.s["time"] + 100
            self.log("form", f'{unit["name"]} 강탈 · {source["name"]}의 {borrowed["form_label"]} 기본 스킬로 전환.')
            return
        candidates = [s for s in source["variants"] if s["key"] == "R" and s.get("castable") and s.get("stage", 1) == 1]
        if not candidates:
            # Control-only ultimates are represented as a buff activation with their real name.
            original = next(s for s in source["skills"] if s["key"] == "R")
            selected = {**original, "id": f'{enemy["champion"]}:R', "tags": ["protect"], "source_champion": enemy["champion"]}
        else:
            selected = next((s for s in candidates if s["form"] == enemy["ability_state"]["form"]), candidates[0])
        stolen = {k: v for k, v in selected.items() if k not in ("next_form", "requires_last")}
        stolen.update(id=f'Sylas:stolen:{selected["id"]}', form_label=f'강탈 · {source["name"]}',
                      cooldown_group="R", min_time=360, castable=True)
        if selected.get("stage") == 1:
            stolen["recasts"] = [
                dict(s, id=f'Sylas:stolen:{s["id"]}', form_label=f'강탈 · {source["name"]}',
                     cooldown_group="R", min_time=360, castable=True)
                for s in source["variants"] if s["key"] == "R" and s.get("stage") == 2
                and s["form"] == selected["form"]]
        state["stolen"] = stolen
        self.log("form", f'{unit["name"]} 강탈 · {source["name"]}의 {selected["name"]} 확보.')

    def after_encounter(self, unit, enemy, kill):
        config = self.champions[unit["champion"]]["kit"]
        if config["mode"] == "weapon":
            self.consume_ammo(unit, 4)
        target = enemy["ability_state"]
        if enemy["champion"] == "Kled" and target["form"] == "mounted":
            target["mount_hp"] = max(0, target["mount_hp"] - (55 if kill else 30))
            if target["mount_hp"] == 0:
                self.set_form(enemy, "unmounted")
                target["resource"] = 0
        if config.get("copy") == "possession" and kill:
            borrowed = copy.deepcopy(target)
            borrowed["borrowed"], borrowed["stolen"] = None, None
            unit["ability_state"]["borrowed"] = {"champion": enemy["champion"], "state": borrowed,
                                                 "until": self.s["time"] + 90}
            self.log("form", f'{unit["name"]} 빙의 · {self.champions[enemy["champion"]]["name"]}의 {target["form_label"]} 기본 스킬 획득.')

    @staticmethod
    def skill_label(spell):
        form = spell.get("form_label", "기본")
        return spell["name"] + (f" [{form}]" if form != "기본" else "")
