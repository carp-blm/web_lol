"""Offline, reproducible enrichment of the pinned, official Data Dragon snapshot."""
import gzip
import json
from build_data import ROOT, read_json, write_json
from skill_variants import enrich


def build():
    details = json.loads(gzip.decompress((ROOT / "data/champion_details.json.gz").read_bytes()))
    snapshot = read_json(ROOT / "web/data/champions.json")
    if details["version"] != snapshot["version"] or set(details["champions"]) != set(snapshot["champions"]):
        raise ValueError("Official detail cache does not match the base champion snapshot")
    for cid, c in details["champions"].items():
        for key, source in [("P", c["passive"]), *zip("QWER", c["spells"])]:
            target = next(s for s in snapshot["champions"][cid]["skills"] if s["key"] == key)
            if target["name"] != source["name"]:
                raise ValueError(f"Base skill differs from the official pinned data: {cid} {key}")
    result = enrich(snapshot)
    write_json(ROOT / "web/data/champions.json", result)
    print(f"Audited {len(result['champions'])} champions; {len(result['variant_audit']['families'])} ability families; revision {result['revision']}")


if __name__ == "__main__":
    build()
