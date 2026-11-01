"""Copy the tree kit into the Godot project: assets/trees -> game/assets/trees (git-ignored there).

    python tools/trees/sync_godot.py [--dest game/assets/trees]
Then let Godot import it (godot --headless --path game --import, or open the editor).
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def main():
    src = ROOT / "assets" / "trees"
    dest = Path(sys.argv[sys.argv.index("--dest") + 1]) if "--dest" in sys.argv else ROOT / "game" / "assets" / "trees"
    n = 0
    for p in src.rglob("*"):
        if p.is_dir() or p.suffix.lower() not in (".glb", ".json", ".png", ".jpg"):
            continue
        q = dest / p.relative_to(src)
        q.parent.mkdir(parents=True, exist_ok=True)
        if not q.exists() or q.stat().st_mtime < p.stat().st_mtime or q.stat().st_size != p.stat().st_size:
            shutil.copy2(p, q)
            n += 1
    print(f"tree kit -> {dest}: {n} files updated")


if __name__ == "__main__":
    main()
