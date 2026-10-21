"""Reviewed 16.20.1 ability families, using Riot's Korean descriptions/tooltips.

Names stay official. Form labels are separate simulation annotations, not invented
ability names. Time/resource values in engine.py are coarse game rules, not LoL
cooldowns. The original P/Q/W/E/R snapshot stays intact for v1 save replay.
"""
import copy
import hashlib
import json
import re

REVIEWED_PATCH = "16.20.1"
REGISTRY = {}


def profile(cid, mode, forms, **kwargs):
    REGISTRY[cid] = {"mode": mode, "forms": forms, "form_order": list(forms), "initial": next(iter(forms)), **kwargs}
    return REGISTRY[cid]


def variant(name=None, tags=None, **kwargs):
    return {**({"name": name} if name else {}), **({"tags": tags} if tags else {}), **kwargs}


def dual(cid, forms, keys="QWE", mode="stance", **kwargs):
    return profile(cid, mode, forms, split={k: list(forms) for k in keys}, **kwargs)


dual("Gnar", {"mini": "미니 나르", "mega": "메가 나르"}, mode="rage",
     inactive={"mini": ["W", "R"]}, overrides={
         "mini": {"Q": variant(tags=["damage", "cc"]), "W": variant(tags=["damage", "mobility"]), "E": variant(tags=["mobility"])},
         "mega": {"Q": variant(tags=["damage", "cc"]), "W": variant(tags=["cc", "aoe"]),
                  "E": variant(tags=["mobility", "aoe"]), "R": variant(tags=["cc", "aoe"])}},
     condition="분노가 차면 메가 나르, 분노 소진 후 미니 나르. R은 메가에서만 능동 사용.")
dual("Nidalee", {"human": "인간", "cougar": "쿠거"}, controls=["R"],
     overrides={"human": {"Q": variant(tags=["damage"]), "W": variant(tags=["vision"]), "E": variant(tags=["protect"])},
                "cougar": {"Q": variant(tags=["damage", "execute"]), "W": variant(tags=["mobility"]), "E": variant(tags=["aoe"])}},
     condition="쿠거의 상으로 전환. 인간과 쿠거의 Q/W/E 재사용 대기시간은 분리.")
dual("Elise", {"human": "인간", "spider": "거미"}, controls=["R"],
     overrides={"human": {"Q": variant(tags=["damage"]), "W": variant(tags=["aoe"]), "E": variant(tags=["cc"])},
                "spider": {"Q": variant(tags=["execute", "mobility"]), "W": variant(tags=["damage"]), "E": variant(tags=["mobility", "protect"])}},
     condition="거미 형태로 전환. 고치는 인간, 줄타기는 거미에서 사용.")
dual("Jayce", {"hammer": "머큐리 해머", "cannon": "머큐리 캐논"}, keys="QWER", controls=["R"],
     overrides={"hammer": {"Q": variant(tags=["mobility", "aoe"]), "W": variant(tags=["aoe"]), "E": variant(tags=["cc"])},
                "cannon": {"Q": variant(tags=["damage", "aoe"]), "W": variant(tags=["damage"]), "E": variant(tags=["mobility"])}},
     condition="R 이름은 전환할 무기. 해머 R=머큐리 캐논, 캐논 R=머큐리 해머.")
dual("RekSai", {"surface": "지상", "burrowed": "매복"}, controls=["W"],
     overrides={"surface": {"Q": variant(tags=["damage"]), "E": variant(tags=["execute"])},
                "burrowed": {"Q": variant(tags=["damage", "vision"]), "E": variant(tags=["mobility"])}},
     condition="W 매복/돌출로 상태 전환. 지상 Q/E와 매복 Q/E를 구분.")
profile("Kled", "mount", {"mounted": "스칼 탑승", "unmounted": "스칼 미탑승"},
        inactive={"unmounted": ["E", "R"]}, passive_keys=["W"],
        overrides={"unmounted": {"Q": variant("빵야!", ["damage", "mobility"])}},
        condition="스칼 체력 소진 시 하차, 용기 충전 시 재탑승. 하차 상태 E/R 불가.")
profile("Rell", "on_cast", {"mounted": "탑승", "dismounted": "중갑"},
        overrides={"mounted": {"W": variant("철마술: 붕괴", ["mobility", "cc", "protect"], next_form="dismounted")},
                   "dismounted": {"W": variant("철마술: 탑승", ["mobility", "cc"], next_form="mounted")}},
        condition="붕괴를 쓰면 중갑, 탑승을 쓰면 탑승 상태.")
profile("Shyvana", "fury", {"human": "인간", "dragon": "용 형상"}, controls=["R"],
        overrides={"human": {"Q": variant(tags=["damage", "aoe"]), "W": variant(tags=["protect", "aoe", "mobility"]),
                             "E": variant(tags=["damage", "cc"])},
                   "dragon": {"Q": variant(tags=["damage", "execute", "aoe"]), "W": variant(tags=["protect", "aoe", "mobility"]),
                              "E": variant(tags=["aoe", "cc"])}},
        condition="16.20.1 리워크 스킬. 분노와 R로 용 형상, 분노 소진 시 인간으로 복귀.")
dual("Yunara", {"normal": "일반", "transcendent": "자기 초월"}, keys="WE", mode="ultimate", controls=["R"],
     overrides={"normal": {"W": variant(tags=["damage", "cc"]), "E": variant(tags=["mobility"])},
                "transcendent": {"W": variant(tags=["aoe", "cc"]), "E": variant(tags=["mobility"])}},
     condition="R 자기 초월 동안 W/E 교체. Q 영혼 단련은 같은 이름의 강화 상태.")
profile("Kayn", "permanent", {"base": "기본", "shadow": "그림자 암살자", "darkin": "다르킨 학살자"},
        overrides={"shadow": {"W": variant(tags=["aoe", "mobility"]), "E": variant(tags=["mobility", "protect"])},
                   "darkin": {"Q": variant(tags=["damage", "protect"]), "W": variant(tags=["cc", "aoe"]),
                              "R": variant(tags=["execute", "protect"])}},
        condition="교전 후 그림자 암살자/다르킨 중 하나로 영구 변신. 왕복하지 않음.")
profile("KSante", "ultimate", {"normal": "일반", "allout": "총공세"}, controls=["R"],
        overrides={"normal": {"W": variant(tags=["cc", "protect", "mobility"])},
                   "allout": {"W": variant(tags=["damage", "mobility"]), "E": variant(tags=["mobility", "protect"])}},
        condition="총공세 동안 기본기 변형. 현행 총공세 W는 밀치기/기절 없음.")
profile("Aphelios", "weapon", {"calibrum": "만월총", "severum": "절단검", "gravitum": "중력포",
                              "infernum": "화염포", "crescendum": "반월검"},
        controls=["W"], passive_keys=["E"],
        overrides={form: {"Q": variant(name, tags), "R": variant(tags=r_tags)}
                   for form, name, tags, r_tags in [
                       ("calibrum", "달빛탄", ["damage", "vision"], ["damage"]),
                       ("severum", "맹공", ["damage", "protect", "mobility"], ["damage", "protect"]),
                       ("gravitum", "속박의 월식", ["cc"], ["damage", "cc"]),
                       ("infernum", "황혼파", ["aoe"], ["aoe"]),
                       ("crescendum", "파수탑", ["damage", "vision"], ["damage"])]},
        extra_sources=["https://www.leagueoflegends.com/ko-kr/news/game-updates/patch-10-8-notes/",
                       "https://www.leagueoflegends.com/ko-kr/news/game-updates/league-of-legends-patch-26-19-notes/"],
        condition="주/보조 무기와 탄약을 관리. 주 무기 Q/R만 사용, E는 안내용이며 시전 불가.")
profile("Hwei", "spellbook", {"base": "흐웨이의 주문"}, selectors=["Q", "W", "E"],
        spells=[("QQ", "파멸의 화염", ["aoe"]), ("QW", "절단의 번개", ["execute", "aoe"]),
                ("QE", "녹아내린 균열", ["aoe", "cc"]), ("WQ", "쏜살같은 물살", ["mobility"]),
                ("WW", "반사의 웅덩이", ["protect"]), ("WE", "요동치는 빛", ["damage"]),
                ("EQ", "암울한 형상", ["cc"]), ("EW", "심연의 응시", ["cc", "vision"]),
                ("EE", "파괴의 아귀", ["cc", "aoe"])],
        condition="주제 선택 Q/W/E 대신 실제 QQ~EE 주문. 같은 주제의 세 주문은 쿨다운 공유.")
profile("Karma", "empower", {"normal": "일반", "empowered": "만트라"}, controls=["R"], unlock=0,
        overrides={"normal": {"Q": variant(tags=["damage", "cc"]), "W": variant(tags=["cc"]), "E": variant(tags=["protect", "mobility"])},
                   "empowered": {"Q": variant("영혼의 불꽃", ["aoe", "cc"]), "W": variant(tags=["cc", "protect"]),
                                 "E": variant("저항", ["protect", "mobility", "aoe"])}},
        extra_sources=["https://www.leagueoflegends.com/ko-kr/news/game-updates/patch-13-16-notes/",
                       "https://www.leagueoflegends.com/ko-kr/news/game-updates/patch-14-12-notes/"],
        condition="만트라를 다음 기본 스킬 한 번에 소비. W는 공식 기본 이름+만트라 상태 표시.")
profile("Heimerdinger", "empower", {"normal": "일반", "empowered": "업그레이드"}, controls=["R"], unlock=360,
        overrides={"empowered": {"Q": variant("H-28Q 최첨단 포탑", ["damage", "aoe"]),
                                 "W": variant("마법공학 로켓 연사", ["aoe"]),
                                 "E": variant("CH-3X 전격 수류탄", ["aoe", "cc"])}},
        condition="업그레이드!!!를 다음 기본 스킬 한 번에 소비.")
profile("Rengar", "ferocity", {"normal": "일반", "empowered": "최대 야성"},
        overrides={"normal": {"Q": variant(tags=["damage"]), "W": variant(tags=["protect"]), "E": variant(tags=["damage", "cc"])},
                   "empowered": {"Q": variant(tags=["damage"]), "W": variant(tags=["protect"]), "E": variant(tags=["cc"])}},
        condition="기본 스킬 4회로 야성 충전, 다음 강화 기본 스킬에 소비.")
profile("Udyr", "awaken", {"normal": "일반 태세", "awakened": "각성"}, basic_r=True,
        overrides={"awakened": {"Q": variant(tags=["damage", "aoe"]), "W": variant(tags=["protect"]),
                               "E": variant(tags=["mobility", "protect"]), "R": variant(tags=["aoe", "cc"])}},
        condition="현재 태세를 재사용해 각성. R도 일반 태세여서 6분 궁극기 잠금 대상 아님.")
dual("AurelionSol", {"normal": "유성", "empowered": "별가루 강화"}, keys="R", mode="stardust",
     overrides={"normal": {"R": variant(tags=["cc", "aoe"])}, "empowered": {"R": variant(tags=["cc", "aoe"])}},
     condition="별가루를 모은 뒤 다음 R만 천상 강림으로 강화.")
profile("Qiyana", "element", {"base": "원소 없음", "river": "강 원소", "brush": "수풀 원소", "wall": "벽 원소"}, controls=["W"],
        overrides={"base": {"Q": variant("이쉬탈의 칼날", ["damage"])},
                   "river": {"Q": variant("원소의 분노", ["cc"])},
                   "brush": {"Q": variant("원소의 분노", ["protect", "damage"])},
                   "wall": {"Q": variant("원소의 분노", ["execute", "damage"])}},
        condition="W로 얻은 강/수풀/벽 원소별 Q. Q 사용 시 원소 소비.")

for cid, keys in [("Ambessa", "Q"), ("Briar", "W"), ("Fizz", "E"),
                  ("LeeSin", "QWE"), ("Skarner", "Q"), ("Sylas", "E")]:
    profile(cid, "chain", {"base": "기본"}, chains={k: None for k in keys},
            condition="첫 스킬 사용/적중 후에만 같은 슬롯의 두 번째 스킬을 사용.")
REGISTRY["Sylas"]["copy"] = "ultimate"
REGISTRY["Sylas"]["controls"] = ["R"]
REGISTRY["Briar"]["condition"] = "W 핏빛 광분 후 식욕 폭발. E 사용 시 광분을 해제."
profile("Riven", "chain", {"base": "기본"}, chains={"R": ["추방자의 검", "바람 가르기"]},
        condition="R 추방자의 검 이후 강화 지속 중 바람 가르기 한 번.")
profile("Swain", "chain", {"base": "기본"}, chains={"R": ["악의 승천", "악의 불길"]},
        condition="악의 승천 상태에서만 악의 불길. 재시전만으로 변신이 종료되지는 않음.")
profile("Leblanc", "mimic", {"base": "기본"}, controls=["R"],
        condition="마지막 기본 스킬을 R로 모방. 모방할 스킬이 없으면 모방 불가.")
profile("Viego", "possession", {"base": "기본"}, copy="possession",
        condition="처치한 상대의 현재 형태 Q/W/E를 빌림. 궁극기는 자신의 심장 파괴자이며 사용 시 빙의 해제.")

for cid, tags in {
    "Ambessa": {"Q": [["aoe"], ["aoe"]]},
    "Briar": {"W": [["mobility", "damage"], ["execute", "protect"]]},
    "Fizz": {"E": [["mobility", "protect"], ["aoe", "cc"]]},
    "LeeSin": {"Q": [["damage", "vision"], ["damage", "mobility", "execute"]],
               "W": [["protect", "mobility"], ["protect"]],
               "E": [["damage", "vision"], ["cc"]]},
    "Skarner": {"Q": [["damage", "cc"], ["damage", "cc"]]},
    "Sylas": {"E": [["mobility"], ["damage", "mobility", "cc"]]},
    "Riven": {"R": [["damage"], ["aoe", "execute"]]},
    "Swain": {"R": [["aoe", "protect"], ["aoe", "cc"]]},
}.items():
    REGISTRY[cid]["chain_tags"] = tags

EXCLUDED = {
    "evolution": ["Khazix", "Kaisa", "Viktor"],
    "same_name_buffs": ["Aatrox", "Belveth", "Nasus", "Renekton", "Pantheon", "Annie", "Seraphine"],
    "disguise_only": ["Neeko"],
    "same_name_recast_or_target_variation": ["Ahri", "Akali", "Riven", "Zed", "Gragas", "Samira", "Talon", "Lulu"],
}


def enrich(snapshot):
    if snapshot["version"] != REVIEWED_PATCH:
        raise ValueError(f"Skill variants are reviewed for {REVIEWED_PATCH}; review the new patch before replacing the snapshot")
    output = copy.deepcopy(snapshot)
    for cid, champion in output["champions"].items():
        config = REGISTRY.get(cid, {"mode": "base", "forms": {"base": "기본"}, "form_order": ["base"], "initial": "base"})
        config = copy.deepcopy(config)
        champion["kit"] = config
        variants = []
        for form, label in config["forms"].items():
            for original in champion["skills"]:
                key = original["key"]
                spell = copy.deepcopy(original)
                if key in config.get("split", {}):
                    names = re.split(r"\s*[/|]\s*", original["name"])
                    spell["name"] = names[config["split"][key].index(form)]
                spell.update(config.get("overrides", {}).get(form, {}).get(key, {}))
                spell.update(id=f"{cid}:{form}:{key}", form=form, form_label=label,
                             display_key=key, source_champion=cid, source=champion["source"],
                             icon_status="base-slot-icon", castable=key != "P",
                             cooldown_group=key, min_time=360 if key == "R" and not config.get("basic_r") else 0)
                if config["mode"] in ("stance", "weapon") and key in "QWE":
                    spell["cooldown_group"] = f"{form}:{key}"
                if config["mode"] == "ferocity" and form == "empowered" and key in "QWE":
                    spell["cooldown_group"] = f"{form}:{key}"
                if key in config.get("inactive", {}).get(form, []) + config.get("passive_keys", []):
                    spell["castable"] = False
                if key in config.get("inactive", {}).get(form, []) and not (cid == "Gnar" and key == "W"):
                    spell["unavailable"] = True
                if key in config.get("controls", []) + config.get("selectors", []):
                    spell["castable"] = False
                    spell["control"] = True
                chain = config.get("chains", {}).get(key, "missing")
                if chain != "missing":
                    names = chain or re.split(r"\s*[/|]\s*", original["name"])
                    if len(names) != 2:
                        raise ValueError(f"Unreviewed recast names: {cid} {key}")
                    for index, name in enumerate(names, 1):
                        part = {**spell, "id": f"{cid}:{form}:{key}{index}", "name": name,
                                "display_key": f"{key}{index}", "stage": index,
                                "tags": config["chain_tags"][key][index - 1]}
                        variants.append(part)
                    continue
                variants.append(spell)
        for display_key, name, tags in config.get("spells", []):
            original = next(s for s in champion["skills"] if s["key"] == display_key[0])
            variants.append({**original, "id": f"{cid}:{display_key}", "key": display_key[0],
                             "display_key": display_key, "name": name, "tags": tags, "form": "base",
                             "form_label": config["forms"]["base"], "source_champion": cid,
                             "source": champion["source"], "icon_status": "base-slot-icon", "castable": True,
                             "cooldown_group": display_key[0], "min_time": 0})
        if cid == "Leblanc":
            for slot in "QWE":
                original = next(s for s in champion["skills"] if s["key"] == slot)
                variants.append({**original, "id": f"Leblanc:mimic:{slot}", "key": "R",
                                 "display_key": f"R{slot}", "form": "base", "form_label": "모방",
                                 "source_champion": cid, "source": champion["source"],
                                 "icon_status": "base-slot-icon", "castable": True, "requires_last": slot,
                                 "cooldown_group": "R", "min_time": 360})
        for spell in variants:
            if "/" in spell["name"] or "|" in spell["name"]:
                raise ValueError(f"Combined skill remains: {cid} {spell['name']}")
        champion["variants"] = variants
    output["variant_audit"] = {
        "reviewed_patch": REVIEWED_PATCH, "reviewed_champions": len(output["champions"]),
        "families": sorted(REGISTRY), "excluded_categories": EXCLUDED,
        "scope": "Form, weapon, spellbook, separately named recast, empowerment and copied abilities; identical-name numeric buffs are not separate official spells.",
        "icon_note": "Data Dragon exposes base-slot icons; variants share that verified icon unless a separate verified icon is supplied.",
    }
    revision = hashlib.sha256(json.dumps({"kits": REGISTRY, "variants": {
        cid: c["variants"] for cid, c in output["champions"].items()}}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    output["revision"] = f"{REVIEWED_PATCH}-{revision}"
    return output
