"""Build static cards from recorded appearances; stdlib only, deterministic output."""
import argparse
import bisect
import collections
import csv
import gzip
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("top", "jng", "mid", "bot", "sup")
FIELDS = "gameid league year date position playername playerid teamname teamid champion gamelength result kills deaths assists dpm cspm golddiffat15 vspm".split()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def num(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def eligible(row, rules):
    return (row.get("position") in ROLES and row.get("league") in rules["leagues"]
            and num(row.get("year")) in rules["years"]
            and all(row.get(k, "").strip() for k in ("gameid", "playerid", "playername", "teamid", "teamname", "champion"))
            and (num(row.get("gamelength")) or 0) > 0
            and row.get("result") in ("0", "1", "0.0", "1.0"))


def csv_rows(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not set(FIELDS[:11]).issubset(reader.fieldnames or []):
            raise ValueError(f"Invalid Oracle's Elixir CSV schema: {path}")
        yield from reader


def make_seed(raw_dir, rules):
    """Retain original field values, one row per real player appearance, no synthetic rows."""
    rows, seen, skipped, sources = [], set(), collections.Counter(), []
    registry = read_json(ROOT / "data/sources.json")
    for path in sorted(Path(raw_dir).glob("*.csv")):
        sources.append({"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        **registry["years"].get(path.stem, {})})
        for row in csv_rows(path):
            if not eligible(row, rules):
                skipped[row.get("league", "unknown")] += 1
                continue
            key = (row["gameid"], row["playerid"], row["position"])
            if key in seen:
                continue
            seen.add(key)
            rows.append({k: row.get(k, "") for k in FIELDS})
    if not rows:
        raise ValueError("No eligible real appearances; keep the last known good data.")
    rows.sort(key=lambda r: (r["year"], r["gameid"], r["playerid"], r["position"]))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    seed = ROOT / "data/seed/appearances.csv.gz"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_bytes(gzip.compress(stream.getvalue().encode("utf-8"), mtime=0))
    write_json(ROOT / "data/seed/provenance.json", {
        "attribution": registry["attribution"], "upstream": registry["upstream"],
        "permission_status": registry["permission_status"], "sources": sources,
        "snapshot_date": datetime.now(timezone.utc).date().isoformat(), "snapshot_kind": "preserved-appearance-extract",
        "original_mirror_equality_verified": False, "rows": len(rows),
        "excluded_rows_by_league": dict(skipped), "notes": registry["notes"]})
    return seed


def mean(rows, key, default=0):
    values = [num(r.get(key)) for r in rows]
    values = [n for n in values if n is not None]
    return sum(values) / len(values) if values else default


def media_record(key, year, team, kind, overrides):
    base = {"key": key, "year": year, "team": team, "kind": kind, "source_url": None,
            "rights_holder": None, "permission": "unknown", "permission_evidence": None,
            "verified": False, "uniform_year_verified": False, "checked_at": None,
            "display": "assets/player-placeholder.svg" if kind == "portrait" else "assets/team-placeholder.svg"}
    for entry in overrides:
        if entry.get("key") == key and entry.get("kind") == kind:
            base.update(entry)
            approved = (entry.get("verified") is True and entry.get("year") == year
                        and entry.get("team") == team and entry.get("source_url")
                        and entry.get("permission") in ("granted", "open-license")
                        and entry.get("permission_evidence") and entry.get("rights_holder")
                        and entry.get("checked_at")
                        and (kind != "portrait" or entry.get("uniform_year_verified") is True))
            local = str(entry.get("file", ""))
            resolved = (ROOT / "web" / local).resolve()
            approved_root = (ROOT / "web/assets/approved").resolve()
            if approved and resolved.is_relative_to(approved_root) and resolved.is_file():
                base["display"] = local
            # An unapproved entry can never override the fallback display.
            else:
                base["display"] = "assets/player-placeholder.svg" if kind == "portrait" else "assets/team-placeholder.svg"
    return base


def build(seed=None):
    rules = read_json(ROOT / "data/league_tiers.json")
    seed = Path(seed or ROOT / "data/seed/appearances.csv.gz")
    groups, seen = collections.defaultdict(list), set()
    for row in csv_rows(seed):
        if not eligible(row, rules):
            continue
        unique = (row["gameid"], row["playerid"], row["position"])
        if unique in seen:
            continue
        seen.add(unique)
        key = (int(float(row["year"])), row["playerid"], row["teamid"], row["position"])
        groups[key].append(row)
    if not groups:
        raise ValueError("No official appearances found. Existing JSON has not been changed.")
    cards, cohorts = [], collections.defaultdict(list)
    for key, rows in sorted(groups.items()):
        year, pid, tid, role = key
        rows.sort(key=lambda r: (r["date"], r["gameid"]))
        recent = rows[-1]
        raw = {"lane": mean(rows, "golddiffat15"),
               "combat": mean(rows, "dpm") + 50 * (mean(rows, "kills") + mean(rows, "assists")) / max(1, mean(rows, "deaths")),
               "vision": mean(rows, "vspm"), "farm": mean(rows, "cspm")}
        league = recent["league"]
        card = {"id": hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:20],
                "player_id": pid, "name": recent["playername"], "team": recent["teamname"],
                "team_id": tid, "year": year, "role": role, "league": league,
                **rules["leagues"][league], "games": len(rows), "raw_metrics": raw,
                "win_rate": round(mean(rows, "result"), 4),
                "evidence": {"first_game": rows[0]["gameid"], "last_game": recent["gameid"],
                             "first_date": rows[0]["date"], "last_date": recent["date"],
                             "source": "Oracle's Elixir", "identity_status": "source-playerid"}}
        champs = collections.defaultdict(list)
        for r in rows:
            champs[r["champion"]].append(r)
        card["mastery"] = [{"name": name, "games": len(rs),
                            "value": min(95, round(42 + 40 * len(rs) / (len(rs) + 8) + 14 * (sum(float(r["result"]) for r in rs) + 2) / (len(rs) + 4)))}
                           for name, rs in sorted(champs.items(), key=lambda p: (-len(p[1]), p[0]))]
        cards.append(card)
        cohorts[(year, role)].append(card)
    for cohort in cohorts.values():
        for metric in ("lane", "combat", "vision", "farm"):
            vals = sorted(c["raw_metrics"][metric] for c in cohort)
            for c in cohort:
                v = c["raw_metrics"][metric]
                percentile = (bisect.bisect_left(vals, v) + bisect.bisect_right(vals, v)) / (2 * len(vals))
                reliability = c["games"] / (c["games"] + 12)
                c.setdefault("ratings", {})[metric] = round(70 + (percentile - .5) * 44 * reliability)
        for c in cohort:
            c["overall"] = round(sum(c["ratings"].values()) / 4)
            c.pop("raw_metrics")
    if any(not any(c["role"] == r for c in cards) for r in ROLES):
        raise ValueError("Data must cover all five positions")
    version = hashlib.sha256((seed.read_bytes() + json.dumps(rules, sort_keys=True).encode())).hexdigest()[:16]
    supplement_path = ROOT / "data/seed/vision.json"
    supplement = read_json(supplement_path) if supplement_path.exists() else {}
    for card in cards:
        card["vision_stats"] = supplement.get("cards", {}).get(card["id"], {})
    overrides = read_json(ROOT / "data/media_overrides.json")["entries"]
    media = {}
    for c in cards:
        media[c["id"]] = media_record(c["id"], c["year"], c["team"], "portrait", overrides)
        team_key = f'{c["year"]}:{c["team_id"]}'
        c["team_media_key"] = team_key
        media[team_key] = media_record(team_key, c["year"], c["team"], "logo", overrides)
    provenance = read_json(ROOT / "data/seed/provenance.json")
    write_json(ROOT / "web/data/cards.json", {"schema": 1, "version": version, "cards": cards,
        "vision_revision": supplement.get("revision", "unavailable"),
        "coverage": {"years": sorted({c["year"] for c in cards}), "leagues": sorted({c["league"] for c in cards}),
                     "tiers": dict(collections.Counter(str(c["tier"]) for c in cards)), "cards": len(cards),
                     "appearances": len(seen)}, "provenance": provenance})
    write_json(ROOT / "web/data/media.json", {"schema": 1, "assets": media})
    print(f"Built {len(cards)} real cards from {len(seen)} appearances; dataset {version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, help="Replace compact seed with eligible rows from local yearly CSVs")
    args = parser.parse_args()
    if args.raw_dir:
        from build_vision import build as build_vision
        build_vision(args.raw_dir)
        make_seed(args.raw_dir, read_json(ROOT / "data/league_tiers.json"))
    build()
