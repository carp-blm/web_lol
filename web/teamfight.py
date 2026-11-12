"""7.0 fight rules: who lands the kill, how big fights end, and when kills start.

In earlier engines every fight resolved its casters in roster order (top, jungle, mid,
bot, support). The support always acted last and collected the finishing blows; the top
laner always acted first and almost never did. Large fights also lasted as long as a
lane trade, so a 4v4 ended after a single kill.

These rules keep the damage model and the last-hit kill credit. They change only
- the acting order: engage and peel go first, damage dealers finish;
- the length of a fight when at least three players per side are in it;
- damage in the first minutes, when low-level champions lack kill pressure.
Kept out of combat.py because the frozen 5.0/6.0 engines replay saves through it.
"""

# Lower acts earlier. The random spread keeps the order from being fixed.
ACT_ORDER = {"sup": .3, "jng": 1.0, "top": 1.8, "mid": 1.9, "bot": 2.8}
ORDER_SPREAD = 1.6
TEAMFIGHT_SIZE = 3           # players per side
TEAMFIGHT_ROUNDS = 3          # exchanges in a teamfight; smaller fights stay one combo each
EARLY_UNTIL = 480            # seconds
EARLY_DAMAGE = .5            # damage scale at 0:00, rising linearly to 1 at EARLY_UNTIL


class TeamfightRules:
    def action_order(self, team):
        keyed = [(ACT_ORDER[u["role"]]+self.rng.random()*ORDER_SPREAD, index, u) for index, u in enumerate(team)]
        return [u for _, _, u in sorted(keyed, key=lambda k: k[:2])]

    def early_damage_scale(self):
        return min(1, EARLY_DAMAGE+(1-EARLY_DAMAGE)*self.s["time"]/EARLY_UNTIL)

    attacking = False

    def cast_attack(self, caster, enemies, allies, lane, preferred="damage", forced=None):
        self.attacking = True
        try:
            return super().cast_attack(caster, enemies, allies, lane, preferred, forced)
        finally:
            self.attacking = False

    def protect(self, victim, damage, allies, incoming=None):
        # Only attack damage is scaled; shields and saves keep their own values.
        return super().protect(victim, damage*self.early_damage_scale() if self.attacking else damage, allies, incoming)

    def encounter(self, kind, lane, blue, red, rounds=2, initiative=None, forced=None):
        blue, red = [u for u in blue if self.present(u)], [u for u in red if self.present(u)]
        if not blue or not red:
            return None
        blue, red = self.action_order(blue), self.action_order(red)
        if min(len(blue), len(red)) < TEAMFIGHT_SIZE:
            return super().encounter(kind, lane, blue, red, rounds, initiative, forced)
        self.sustained_fight = True
        try:
            return super().encounter(kind, lane, blue, red, TEAMFIGHT_ROUNDS, initiative, forced)
        finally:
            self.sustained_fight = False


class SustainedComboRules:
    """Sits ahead of ComboRules. A combo normally locks its caster for 8 seconds, which also
    silenced every later round of the same fight. In a teamfight the later rounds are real:
    the caster follows up with whatever is off cooldown, or basic attacks."""
    sustained_fight = False

    def execute_combo(self, caster, enemies, allies, lane, forced=None):
        if self.sustained_fight:
            caster["combo_ready_at"] = 0
        return super().execute_combo(caster, enemies, allies, lane, forced)
