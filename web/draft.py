"""Three bans per side and ten unique picks, with deterministic opponent drafting."""
ROLES = ("top", "jng", "mid", "bot", "sup")


class DraftRules:
    def draft_taken(self):
        draft = self.s["banpick"]
        return {*draft["bans"][0], *draft["bans"][1], *draft["picks"][0].values(), *draft["picks"][1].values()}

    def ai_draft_choice(self, role=None):
        taken = self.draft_taken()
        if role:
            ids = self.s["season"]["teams"][self.opponent()]["roster"]
            card = next(self.cards[cid] for cid in ids if self.cards[cid]["role"] == role)
            pool = [p for p in self.champion_pool(card) if p["id"] not in taken]
            if pool:
                best = max(p["mastery"] for p in pool)
                return self.rng.pick([p["id"] for p in pool if p["mastery"] >= best-5])
        else:
            pool = [p for cid in self.s["roster"].values() for p in self.champion_pool(self.cards[cid]) if p["id"] not in taken]
            if pool:
                best = max(p["mastery"] for p in pool)
                return self.rng.pick([p["id"] for p in pool if p["mastery"] >= best-3])
        return self.rng.pick([cid for cid in sorted(self.champions) if cid not in taken])

    def draft_action(self, action):
        kind = action["type"]
        if kind == "begin_draft":
            if self.s["season"]["phase"] == "complete":
                raise ValueError("새 시즌을 먼저 시작해주세요.")
            self.s["banpick"] = {"phase":"ban", "bans":[[],[]], "picks":[{},{}],
                                 "role":"top", "opponent":self.s["season"]["teams"][self.opponent()]["name"]}
            return
        draft, champion = self.s.get("banpick"), action.get("champion")
        if not draft or champion not in self.champions or champion in self.draft_taken():
            raise ValueError("밴 또는 선택되지 않은 챔피언을 고르세요.")
        if kind == "ban_champion":
            if draft["phase"] != "ban": raise ValueError("현재는 밴 단계가 아닙니다.")
            draft["bans"][0].append(champion)
            draft["bans"][1].append(self.ai_draft_choice())
            if len(draft["bans"][0]) == 3: draft["phase"] = "pick"
        elif kind == "pick_champion":
            if draft["phase"] != "pick": raise ValueError("밴을 먼저 완료해주세요.")
            role = draft["role"]
            draft["picks"][0][role] = champion
            draft["picks"][1][role] = self.ai_draft_choice(role)
            index = len(draft["picks"][0])
            if index == 5:
                draft["phase"] = "ready"
                self.s["draft"] = dict(draft["picks"][0])
            else:
                draft["role"] = ROLES[index]
