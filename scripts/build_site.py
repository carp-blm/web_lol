"""Package an explicit static allowlist for GitHub project Pages."""
import argparse
import json
import shutil
from pathlib import Path
from build_data import ROOT


def validate():
    web = ROOT / "web"
    for file in ("index.html", "app.js", "worker.js", "engine.py", "style.css", "data/cards.json", "data/champions.json", "data/media.json"):
        if not (web / file).is_file():
            raise ValueError(f"Missing required file: {file}")
    cards = json.loads((web / "data/cards.json").read_text(encoding="utf8"))
    champions = json.loads((web / "data/champions.json").read_text(encoding="utf8"))
    if not cards["cards"] or len(champions["champions"]) < 100:
        raise ValueError("Incomplete data")
    ids = [c["id"] for c in cards["cards"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate card IDs")
    for c in cards["cards"]:
        if c["games"] < 1 or c["tier"] not in (1, 2) or not c["evidence"]["first_game"]:
            raise ValueError("Card lacks a verified source appearance")
    return cards


def build(output=None):
    cards = validate()
    dest = Path(output or ROOT / "dist").resolve()
    if dest != (ROOT / "dist").resolve():
        raise ValueError("Build output is restricted to the project's dist directory")
    dest.mkdir(exist_ok=True)
    # No recursive delete. Only known frontend files are written, never source or raw CSVs.
    for name in ("index.html", "app.js", "worker.js", "engine.py", "style.css"):
        shutil.copy2(ROOT / "web" / name, dest / name)
    for directory in ("assets", "data"):
        shutil.copytree(ROOT / "web" / directory, dest / directory, dirs_exist_ok=True)
    (dest / ".nojekyll").write_text("", encoding="utf8")
    print(f"Static site built: {dest}; {len(cards['cards'])} cards; no backend required")


if __name__ == "__main__":
    build()
