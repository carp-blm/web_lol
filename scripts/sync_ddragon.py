"""Fetch public, versioned ko_KR Data Dragon JSON, never a private Riot API."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from build_data import ROOT, read_json, write_json

BASE = "https://ddragon.leagueoflegends.com"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "NexusArchivePrototype/0.1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                if "json" not in r.headers.get("Content-Type", ""):
                    raise ValueError("Unexpected response content type")
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def tags(description):
    """Transparent heuristic tags, not Riot-supplied simulation mechanics."""
    rules = {"cc": ("기절", "속박", "둔화", "공중", "매혹", "도발", "밀쳐"),
             "mobility": ("돌진", "도약", "순간이동", "이동 속도"),
             "protect": ("보호막", "회복", "무적"),
             "aoe": ("주변", "범위", "모든 적", "광역"),
             "execute": ("잃은 체력", "처형")}
    return [tag for tag, words in rules.items() if any(w in description for w in words)] or ["damage"]


def sync(version=None):
    version = version or fetch(f"{BASE}/api/versions.json")[0]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid Data Dragon version")
    summary = fetch(f"{BASE}/cdn/{version}/data/ko_KR/champion.json")
    def one(cid):
        url = f"{BASE}/cdn/{version}/data/ko_KR/champion/{cid}.json"
        c = fetch(url)["data"][cid]
        spells = []
        for key, spell in [("P", c["passive"]), *zip("QWER", c["spells"])]:
            desc = re.sub("<[^>]+>", " ", spell["description"])
            spells.append({"key": key, "name": spell["name"], "tags": tags(desc),
                           "icon": f'{BASE}/cdn/{version}/img/{"passive" if key == "P" else "spell"}/{spell["image"]["full"]}'})
        return cid, {"id": cid, "name": c["name"], "tags": c["tags"], "skills": spells,
                     "portrait": f'{BASE}/cdn/{version}/img/champion/{c["image"]["full"]}',
                     "source": url}
    # Bounded concurrency; a partial fetch never replaces the last good snapshot.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        champions = dict(pool.map(one, sorted(summary["data"])))
    if len(champions) < 100 or any(len(c["skills"]) != 5 for c in champions.values()):
        raise ValueError("Incomplete Data Dragon response")
    write_json(ROOT / "web/data/champions.json", {"schema": 1, "version": version,
        "locale": "ko_KR", "champions": champions, "tag_method": "Korean description keyword heuristic v1",
        "permission": "Riot policy applies; game-use permission NOT established",
        "policy_url": "https://developer.riotgames.com/docs/lol#developer-api-policy"})
    print(f"Collected {len(champions)} champions, {len(champions)*5} passive/QWER names and icon URLs, patch {version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args()
    try:
        sync(args.version)
    except Exception as exc:
        print(f"Data Dragon update failed; existing snapshot preserved: {exc}", file=sys.stderr)
        if not (args.allow_stale and (ROOT / "web/data/champions.json").exists()):
            raise SystemExit(1)
