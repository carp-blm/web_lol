"""Package an explicit static allowlist for GitHub project Pages."""
import argparse
import ast
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path
from build_data import ROOT

PYTHON_FILES = ("engine.py", "combat.py", "abilities.py", "legacy_engine.py", "legacy_engine_v2.py", "legacy_abilities_v2.py")
FRONTEND_FILES = ("index.html", "app.js", "worker.js", "style.css")
DATA_FILES = ("cards.json", "champions.json", "media.json")


class StripDocs(ast.NodeTransformer):
    def generic_visit(self, node):
        super().generic_visit(node)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                node.body.pop(0)
                if not node.body:
                    node.body.append(ast.Pass())
        return node


def runtime_archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in PYTHON_FILES:
            tree = StripDocs().visit(ast.parse((ROOT / "web" / name).read_text(encoding="utf-8-sig")))
            source = ast.unparse(tree) + "\n"
            compile(source, name, "exec")
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source)
    return stream.getvalue()


def validate():
    web = ROOT / "web"
    for file in (*FRONTEND_FILES, *PYTHON_FILES, *(f"data/{name}" for name in DATA_FILES)):
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
    for name in FRONTEND_FILES:
        shutil.copy2(ROOT / "web" / name, dest / name)
    (dest / "data").mkdir(exist_ok=True)
    for name in DATA_FILES:
        shutil.copy2(ROOT / "web/data" / name, dest / "data" / name)
    # Assets must be referenced by the app or approved media registry, never arbitrary files.
    assets = {"assets/mark.svg", "assets/skill-placeholder.svg", "assets/player-placeholder.svg", "assets/team-placeholder.svg"}
    media = json.loads((ROOT / "web/data/media.json").read_text(encoding="utf8"))
    for item in media["assets"].values():
        display = item.get("display", "")
        if display.startswith("assets/approved/") and item.get("verified") and item.get("permission") in ("granted", "open-license"):
            assets.add(display)
    for name in assets:
        path = (ROOT / "web" / name).resolve()
        if not path.is_relative_to((ROOT / "web/assets").resolve()) or path.suffix.lower() not in (".svg", ".png", ".webp", ".jpg", ".jpeg"):
            raise ValueError("Invalid packaged media path")
        (dest / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest / name)
    packed = runtime_archive()
    (dest / "runtime.zip").write_bytes(packed)
    digest = hashlib.sha256(packed).hexdigest()
    worker = (dest / "worker.js").read_text(encoding="utf8")
    a, b = worker.index("  // RUNTIME_FILES_START"), worker.index("  // RUNTIME_FILES_END")+len("  // RUNTIME_FILES_END")
    worker = worker[:a] + f'''  const response = await fetch(new URL('runtime.zip', ROOT), {{cache:'no-cache'}});
  if (!response.ok) throw new Error('Runtime unavailable');
  const packed = await response.arrayBuffer();
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', packed)), b => b.toString(16).padStart(2,'0')).join('');
  if (digest !== '{digest}') throw new Error('Runtime integrity mismatch');
  py.unpackArchive(packed, 'zip', {{extractDir:'/home/pyodide'}});
''' + worker[b:]
    (dest / "worker.js").write_text(worker, encoding="utf8")
    # Delete only explicit obsolete build outputs; refuse unexpected files rather than publish them.
    for name in PYTHON_FILES:
        old = dest / name
        if old.is_file():
            old.unlink()
    (dest / ".nojekyll").write_text("", encoding="utf8")
    allowed = {*FRONTEND_FILES, *(f"data/{n}" for n in DATA_FILES), *assets, "runtime.zip", ".nojekyll"}
    unexpected = [str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file() and p.relative_to(dest).as_posix() not in allowed]
    if unexpected:
        raise ValueError(f"Unapproved files in dist; move them outside before packaging: {unexpected}")
    print(f"Static site built: {dest}; {len(cards['cards'])} cards; no backend required")


if __name__ == "__main__":
    build()
