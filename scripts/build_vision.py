"""Aggregate measured ward counts from eligible Oracle's Elixir appearances.

Missing fields stay unknown, not zero. Supplemental data leaves historic card
IDs/ratings and the v1/v2 replay dataset fingerprint intact.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
from build_data import ROOT, csv_rows, eligible, num, read_json, write_json

FIELDS = ("wardsplaced", "wardskilled", "controlwardsbought")


def build(raw_dir):
    rules = read_json(ROOT / "data/league_tiers.json")
    rows, seen, sources = collections.defaultdict(list), set(), []
    for path in sorted(Path(raw_dir).glob("*.csv")):
        sources.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        for row in csv_rows(path):
            unique = (row.get("gameid"), row.get("playerid"), row.get("position"))
            if unique in seen or not eligible(row, rules):
                continue
            seen.add(unique)
            key = (int(float(row["year"])), row["playerid"], row["teamid"], row["position"])
            cid = hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:20]
            rows[cid].append(row)
    if not rows:
        raise ValueError("No eligible vision records; existing supplement preserved")
    cards = {}
    for cid, appearances in sorted(rows.items()):
        stats = {"games": len(appearances), "source": "Oracle's Elixir"}
        for field in FIELDS:
            measured = [(num(r.get(field)), num(r["gamelength"])) for r in appearances
                        if num(r.get(field)) is not None and num(r[field]) >= 0]
            stats[field] = {"samples": len(measured),
                            "total": round(sum(v for v, _ in measured), 3),
                            "per_minute": round(sum(v for v, _ in measured) * 60 / sum(t for _, t in measured), 5)
                            if measured else None}
        cards[cid] = stats
    payload = {"schema": 1, "cards": cards, "sources": sources,
               "source": "https://oracleselixir.com/tools/downloads", "appearances": len(seen)}
    payload["revision"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    write_json(ROOT / "data/seed/vision.json", payload)
    print(f"Vision: {len(cards)} cards, {len(seen)} measured appearances; {payload['revision']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, required=True)
    build(parser.parse_args().raw_dir)
