"""Tournament draft: ABABAB / ABBAAB / BABA / BAAB (A = first pick)."""
from legacy_draft_v4 import DraftRules as LegacyDraftRules

ROLES = ("top", "jng", "mid", "bot", "sup")
ORDER = ([("ban", side, 1) for side in (0, 1, 0, 1, 0, 1)]
         + [("pick", side, 1) for side in (0, 1, 1, 0, 0, 1)]
         + [("ban", side, 2) for side in (1, 0, 1, 0)]
         + [("pick", side, 2) for side in (1, 0, 0, 1)])


class DraftRules(LegacyDraftRules):
    def draft_action(self, action):
        if action["type"] == "begin_draft":
            if self.s["season"]["phase"] == "complete":
                raise ValueError("새 시즌을 먼저 시작해주세요.")
            self.s["banpick"] = {"format": "tournament-v5", "phase": "ban", "round": 1,
                "cursor": 0, "turn": 0, "history": [], "bans": [[], []], "picks": [{}, {}],
                "role": "top", "opponent": self.s["season"]["teams"][self.opponent()]["name"]}
            return
        draft = self.s.get("banpick")
        if draft and draft.get("format") != "tournament-v5":
            return super().draft_action(action)
        champion = action.get("champion")
        if not draft or draft["phase"] == "ready" or champion not in self.champions or champion in self.draft_taken():
            raise ValueError("아직 밴/픽되지 않은 챔피언을 고르세요.")
        kind, side, _ = ORDER[draft["cursor"]]
        if side != 0 or action["type"] != f"{kind}_champion":
            raise ValueError("현재 밴/픽 순서에 맞는 행동을 선택하세요.")
        role = action.get("role", draft["role"]) if kind == "pick" else None
        if kind == "pick" and (role not in ROLES or role in draft["picks"][0]):
            raise ValueError("아직 선택하지 않은 포지션을 고르세요.")
        self.record_draft(champion, role)
        while draft["cursor"] < len(ORDER) and ORDER[draft["cursor"]][1] == 1:
            kind = ORDER[draft["cursor"]][0]
            role = next((r for r in ROLES if r not in draft["picks"][1]), None) if kind == "pick" else None
            self.record_draft(self.ai_draft_choice(role), role)
        if draft["cursor"] == len(ORDER):
            draft.update(phase="ready", turn=None)
            self.s["draft"] = dict(draft["picks"][0])
        else:
            kind, side, stage = ORDER[draft["cursor"]]
            draft.update(phase=kind, turn=side, round=stage,
                         role=next((r for r in ROLES if r not in draft["picks"][0]), "top"))

    def record_draft(self, champion, role):
        d = self.s["banpick"]
        kind, side, stage = ORDER[d["cursor"]]
        if kind == "ban":
            d["bans"][side].append(champion)
        else:
            d["picks"][side][role] = champion
        d["history"].append({"kind": kind, "side": side, "round": stage, "champion": champion, "role": role})
        d["cursor"] += 1
