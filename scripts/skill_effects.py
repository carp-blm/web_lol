"""Conservative Korean tooltip classification plus explicit target/form overrides.

This is a simulation taxonomy, not a claim to implement every live-game condition.
Source text never runs as code. Unknown defensive targets grant no ally protection.
"""
import copy
import hashlib
import json
import re

CC_PATTERNS = {"blind": r"실명", "slow": r"둔화|느려", "root": r"속박",
               "polymorph": r"변이", "stun": r"기절", "airborne": r"공중(?:에|으로)\s*(?:띄|뜬|떠|뜨)|밀쳐|밀치|밀어|밀리(?:며|고|는)|밀려|끌어당|뒤로 던",
               "suppression": r"제압", "silence": r"침묵", "fear": r"공포|달아나|도망", "charm": r"매혹", "taunt": r"도발", "sleep": r"수면"}

# Every ally-capable defensive skill is opt-in; enemy healing reduction, mana
# restoration, pet HP, max-health scaling and shield breaking are not healing.
DEFENSE = {
    "Alistar:P": [("heal","team")], "Annie:E": [("shield","both")],
    "Bard:W": [("heal","both")], "Braum:E": [("shield","self")],
    "Fiora:R": [("heal","team")], "Galio:R": [("shield","ally")],
    "Ivern:E": [("shield","both")], "Janna:E": [("shield","both")], "Janna:R": [("heal","team")],
    "Karma:E": [("shield","both")], "Kayle:W": [("heal","both")], "Kayle:R": [("invulnerable","both")],
    "Kindred:R": [("invulnerable","team")], "KSante:E": [("shield","both")],
    "LeeSin:W": [("shield","both")], "Lulu:E": [("shield","both")], "Lulu:R": [("bonus_health","both")],
    "Lux:W": [("shield","team")], "Milio:W": [("heal","team")],
    "Milio:E": [("shield","both")], "Milio:R": [("heal","team")],
    "Morgana:E": [("magic_shield","both")], "Nami:W": [("heal","both")],
    "Nidalee:E": [("heal","both")], "Nilah:R": [("heal","team")],
    "Orianna:E": [("shield","both")], "Rakan:Q": [("heal","team")], "Rakan:E": [("shield","ally")],
    "Renata:W": [("revive","ally")], "Renata:E": [("shield","team")],
    "Senna:Q": [("heal","team")], "Senna:R": [("shield","team")],
    "Seraphine:W": [("shield","team"),("heal","team")], "Shen:R": [("shield","ally")],
    "Sona:W": [("heal","team"),("shield","team")], "Soraka:W": [("heal","ally")],
    "Soraka:R": [("heal","team")], "TahmKench:R": [("rescue","ally")],
    "Taric:Q": [("heal","team")], "Taric:W": [("shield","both")], "Taric:R": [("invulnerable","team")],
    "Thresh:W": [("shield","both")], "Yuumi:P": [("heal","both")],
    "Yuumi:W": [("heal","ally")], "Yuumi:E": [("shield","both")], "Yuumi:R": [("heal","team")],
    "Zilean:R": [("revive","both")], "Anivia:P": [("revive","self")], "Zac:P": [("revive","self")],
    "Zaahen:P": [("revive","self")],
}
SELF_HEAL = {
    "Aatrox":"PE", "Ahri":"P", "Ambessa":"R", "Aurora":"P", "Belveth":"R",
    "Briar":"PEW", "Camille":"W", "Cassiopeia":"E", "Chogath":"P", "Darius":"Q",
    "DrMundo":"PQWR", "Ekko":"R", "Elise":"P", "Evelynn":"P", "Fiddlesticks":"W",
    "Fiora":"P", "Gangplank":"W", "Garen":"P", "Gragas":"P", "Gwen":"P",
    "Hecarim":"W", "Illaoi":"P", "Irelia":"Q", "Kayn":"ER", "Khazix":"W",
    "Kindred":"W", "KSante":"R", "LeeSin":"W", "Lissandra":"R", "Locke":"W",
    "MasterYi":"W", "Maokai":"P", "Mordekaiser":"W", "Morgana":"P", "Naafiri":"QE",
    "Nasus":"P", "Nunu":"Q", "Olaf":"W", "RekSai":"P", "Renekton":"Q", "Rengar":"W",
    "Shyvana":"W", "Sivir":"E", "Smolder":"R", "Soraka":"Q", "Swain":"PR",
    "Sylas":"W", "TahmKench":"QE", "Talon":"Q", "Trundle":"PR", "Tryndamere":"Q",
    "Udyr":"W", "Viego":"PQ", "Vladimir":"QWR", "Volibear":"W", "Warwick":"PQR",
    "XinZhao":"P", "Yorick":"Q", "Zaahen":"QR", "Zac":"P",
}
SELF_SHIELD = {
    "Akshan":"P", "Ambessa":"W", "Azir":"E", "Blitzcrank":"P", "Camille":"P",
    "Diana":"W", "Ekko":"W", "Galio":"W", "Garen":"W", "JarvanIV":"W",
    "Kaisa":"R", "Kassadin":"Q", "Kled":"R", "Malphite":"P", "Mel":"W",
    "Mordekaiser":"W", "Naafiri":"R", "Nautilus":"W", "Nunu":"R", "Olaf":"W",
    "Rakan":"P", "Rell":"W", "Riven":"E", "Rumble":"W", "Sett":"W", "Shen":"P",
    "Shyvana":"W", "Sion":"W", "Skarner":"W", "TahmKench":"E", "Udyr":"W",
    "Urgot":"E", "Vex":"W", "Vi":"P", "Viktor":"Q", "Volibear":"E", "Yasuo":"P", "Yone":"W",
}
CC_OVERRIDES = {
    "Aatrox:R": [], "Alistar:P": [], "DrMundo:P": [], "Morgana:E": [],
    "Briar:W": [], "Olaf:R": [], "Yuumi:W": [], "Lulu:W": ["polymorph"],
    "TahmKench:R": ["suppression"], "Renata:R": ["taunt"],
    "Zilean:E": ["slow"], "Soraka:E": ["silence","root"], "Soraka:Q": ["slow"],
    "Gnar:mini:Q": ["slow"], "Gnar:mini:W": [], "Gnar:mini:E": ["slow"], "Gnar:mini:R": [],
    "Gnar:mega:Q": ["slow"], "Gnar:mega:W": ["stun"], "Gnar:mega:E": ["slow"], "Gnar:mega:R": ["airborne","stun"],
    "Nidalee:human:E": [], "Nidalee:cougar:E": [],
    "Elise:human:E": ["stun"], "Elise:spider:E": [],
    "Kled:mounted:Q": ["slow","airborne"], "Kled:unmounted:Q": [],
    "RekSai:burrowed:Q": [], "RekSai:burrowed:W": ["airborne"], "RekSai:surface:W": [],
    "Jayce:cannon:E": [], "Jayce:hammer:E": ["airborne"],
    "KSante:allout:W": [], "Rengar:normal:E": ["slow"], "Rengar:empowered:E": ["root"],
    "Hwei:QQ": [], "Hwei:QW": [], "Hwei:QE": ["slow"], "Hwei:WQ": [], "Hwei:WW": [], "Hwei:WE": [],
    "Hwei:EQ": ["fear"], "Hwei:EW": ["root"], "Hwei:EE": ["airborne","slow"],
    "Jayce:cannon:Q": [], "Jayce:hammer:Q": ["slow"],
    "Kayn:P": [], "Kayn:E": [], "Kayn:darkin:W": ["slow","airborne"],
    "Qiyana:base:Q": [], "Qiyana:brush:Q": [], "Qiyana:wall:Q": [],
    "Rell:mounted:W": ["airborne"], "Rell:dismounted:W": ["airborne"],
    "Aphelios:gravitum:Q": ["root"], "Aphelios:gravitum:R": ["slow"],
    "MasterYi:R": [], "Garen:Q": ["silence"], "Sejuani:P": [],
    "Vi:Q": ["airborne"], "Vi:R": ["airborne"], "XinZhao:R": ["airborne"],
    "Nautilus:Q": ["airborne"], "Nautilus:R": ["airborne"], "Leblanc:mimic:E": ["root"],
    "LeeSin:base:Q1": [], "LeeSin:base:Q2": [], "LeeSin:base:E1": [], "LeeSin:base:E2": ["slow"],
    # Tooltip references to the caster, a projectile, another skill or monsters
    # must not become crowd control against an enemy champion.
    "Draven:Q": [], "Aurora:Q": [], "Blitzcrank:W": [], "Jinx:Q": [],
    "Khazix:R": [], "Quinn:R": [], "Xayah:R": [], "Varus:Q": [], "Xerath:Q": [],
    "Urgot:W": [], "Viego:W": ["stun"], "Camille:E": ["stun"], "Galio:W": ["taunt"],
    "Kled:E": [], "Taliyah:Q": ["slow"], "Singed:E": ["airborne", "root"],
    "Kayn:base:W": ["slow"], "Kayn:shadow:W": ["slow"],
    "AurelionSol:normal:R": ["stun"], "AurelionSol:empowered:R": ["airborne", "slow"],
    "Leblanc:mimic:Q": [], "Leblanc:mimic:W": [],
    "Sylas:base:E1": [], "Sylas:base:E2": ["airborne"],
    "Fizz:base:E2": [], "Swain:base:R1": [],
    "Twitch:W": ["slow"],
}

# Combined slot descriptions are insufficient for these distinct casts.
DAMAGE_OVERRIDES = {
    "Jayce:cannon:E": False, "RekSai:burrowed:E": False,
    "Hwei:WQ": False, "Hwei:WW": False, "Sylas:base:E1": False,
    "Nidalee:human:E": False, "Nidalee:cougar:E": True,
    "Gangplank:base:Q": True,
}


def enrich_effects(snapshot, details):
    if snapshot["version"] != details["version"] or snapshot["version"] != "16.20.1":
        raise ValueError("Unreviewed effect taxonomy patch; keep the last good snapshot")
    output = copy.deepcopy(snapshot)
    classified = {"cc": 0, "defense": 0, "aoe": 0}
    for cid, champion in output["champions"].items():
        raw = details["champions"][cid]
        champion["attack_profile"] = "ranged_auto" if raw.get("stats", {}).get("attackrange", 0) >= 450 and "Marksman" in raw.get("tags", []) else "mixed"
        for spell in champion["variants"]:
            key, identity = spell["key"], f'{cid}:{spell["key"]}'
            source = raw["passive"] if key == "P" else raw["spells"]["QWER".index(key)]
            tooltip = source.get("tooltip", source["description"])
            description_fallback = not re.search(r"[가-힣]", tooltip)
            if description_fallback:
                tooltip = source["description"]
            # Skill names in cross-references (e.g. Quinn's Q or Kha'Zix's Q)
            # can contain CC words without applying that effect in this cast.
            text = re.sub(r"<spellName>.*?</spellName>", "", tooltip)
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", text))
            cc = [name for name, pattern in CC_PATTERNS.items() if re.search(pattern, text)]
            cc = CC_OVERRIDES.get(spell["id"], CC_OVERRIDES.get(identity, cc))
            if spell.get("stage") == 2 and "cc" not in spell["tags"]:
                cc = []
            defense = list(DEFENSE.get(identity, []))
            if key in SELF_HEAL.get(cid, ""):
                defense.append(("heal","self"))
            if key in SELF_SHIELD.get(cid, ""):
                defense.append(("shield","self"))
            form = spell["form"]
            if cid == "Kayn" and key == "R" and form != "darkin": defense = []
            if cid == "RekSai" and key == "P" and form != "burrowed": defense = []
            if cid == "Rell" and key == "W" and form != "mounted": defense = []
            if cid == "Aphelios" and form == "severum" and key in "QR": defense = [("heal","self")]
            if cid == "Nidalee" and form != "human": defense = []
            if cid == "Elise" and form != "spider": defense = []
            if cid == "Briar" and key == "W" and spell.get("stage") != 2: defense = []
            if cid == "Shyvana" and key == "W" and form != "dragon": defense = [("shield","self")]
            if cid == "LeeSin" and key == "W": defense = [("shield","both")] if spell.get("stage") == 1 else [("heal","self")]
            if cid == "Karma" and key == "W" and form == "empowered": defense = [("heal","self")]
            if cid == "Karma" and key == "E" and form == "empowered": defense = [("shield","team")]
            if cid == "Hwei": defense = [("shield","team")] if spell["display_key"] == "WW" else []
            if spell.get("control") or spell.get("unavailable"): cc, defense = [], []
            # Curated form tags are more specific than a combined base tooltip.
            aoe = "aoe" in spell["tags"] or (champion["kit"]["mode"] == "base" and bool(re.search(r"주변 적|범위 내|모든 적|일직선|충격파|주위의 적", text)))
            if identity in ("Ahri:E","Nautilus:Q","Blitzcrank:Q","Thresh:Q","Amumu:Q","Morgana:Q","Elise:E","Nidalee:Q","Jhin:W","Jhin:R","Kalista:Q","Teemo:Q","Malzahar:R","Warwick:R"):
                aoe = False
            if cid == "Lulu" and key == "R": aoe = True
            if cid == "Aphelios" and form == "gravitum": aoe = True
            if identity in ("Draven:E", "Draven:R", "Sylas:Q", "Lillia:R", "MonkeyKing:R", "Milio:Q", "Thresh:E", "Zac:R", "Ziggs:W", "Gragas:R", "Janna:R"):
                aoe = True
            # 'Damage absorbed/reduced' in shield text is not an attack.
            damage = bool(re.search(r"<(?:physicalDamage|magicDamage|trueDamage|damage)>", tooltip, re.I)) if "tooltip" in source and not description_fallback else "피해" in text
            damage = DAMAGE_OVERRIDES.get(spell["id"], damage)
            if (cid == "Aphelios" and key == "Q") or (cid == "Heimerdinger" and key == "Q"):
                damage = True
            if spell.get("control") or spell.get("unavailable"):
                damage = False
            defensive = [{"kind": kind, "target": target} for kind, target in defense]
            if identity == "Soraka:W": defensive[0]["health_cost"] = 10
            spell["effects"] = {"cc": cc, "defense": defensive, "aoe": aoe,
                                "damage": damage,
                                "classification": "curated" if identity in DEFENSE or identity in CC_OVERRIDES or spell["id"] in CC_OVERRIDES or spell["id"] in DAMAGE_OVERRIDES else "tooltip-and-curated-targets",
                                "damage_type": "magic" if "마법 피해" in text and "물리 피해" not in text else "physical" if "물리 피해" in text else "mixed",
                                "max_targets": 2 if identity in ("Lux:Q","Bard:Q") else 5,
                                "secondary_cc": ["slow"] if identity in ("Ashe:R","Leona:R","Milio:Q") or spell["id"] == "AurelionSol:empowered:R" else cc,
                                "source": champion["source"]}
            for name in classified:
                classified[name] += bool(spell["effects"][name])
    output["effects_audit"] = {"patch": snapshot["version"], "champions": len(output["champions"]),
                               "classified_variants": classified, "method": "ko_KR tooltip/status extraction; explicit defensive targets and form exceptions; uncertain defense disabled",
                               "limits": "Damage, conditional CC and resurrection timing are probabilistic MVP abstractions; not all live-game subconditions are reproduced."}
    output["effects_revision"] = hashlib.sha256(json.dumps({k:[s["effects"] for s in c["variants"]] for k,c in output["champions"].items()},sort_keys=True).encode()).hexdigest()[:16]
    return output
