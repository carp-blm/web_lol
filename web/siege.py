"""7.0 siege rules: a lead must convert into structures.

Earlier engines scaled structure damage only with match time and lane pressure, so a
team 30k gold ahead sieged no faster than an even one. These rules keep the same lane
contest (who pushes is still decided by the laners actually present) and scale the
damage by the pushing side's gold lead, living-player advantage and dragon lead.
Kept out of combat.py because the frozen 5.0/6.0 engines replay saves through it.
"""
from combat import bound

SIEGE_BASE = 1.35            # overall pace; even games should end in the low-to-mid 30s
GOLD_LEAD_STEP = 9000        # every 9k gold lead adds +100% structure damage
GOLD_LEAD_CAP = 2.0          # up to +200%
GOLD_DEFICIT_FLOOR = .6      # a trailing side still chips, at 60% at worst
ALIVE_BONUS = .18            # per extra living player on the pushing side
DRAGON_BONUS = .05           # per dragon of lead
OPEN_LANE = 1.8
BARON_FLAT = 140


class SiegeRules:
    def siege_multiplier(self, side):
        s = self.s
        lead = s["gold"][side]-s["gold"][1-side]
        gold = 1+bound(lead/GOLD_LEAD_STEP, GOLD_DEFICIT_FLOOR-1, GOLD_LEAD_CAP)
        alive = [sum(1 for u in team if u["status"] != "dead") for team in s["teams"]]
        numbers = 1+ALIVE_BONUS*max(0, alive[side]-alive[1-side])
        dragons = 1+DRAGON_BONUS*max(0, s["dragons"][side]-s["dragons"][1-side])
        return SIEGE_BASE*gold*numbers*dragons

    def siege(self, lane):
        s = self.s
        teams = [self.lane_members(side, lane) for side in (0, 1)]
        if not (teams[0] or teams[1]):
            return
        side = 0 if self.rng.random() < self.encounter_odds(*teams, lane) else 1
        if not teams[side]:
            return
        base = 35+s["time"]*.035+abs(s["pressure"][lane])*5
        damage = round(base*(OPEN_LANE if not teams[1-side] else 1)*self.siege_multiplier(side))
        if s["buff_until"][side] > s["time"]:
            damage += BARON_FLAT
        self.push(side, lane, damage)
