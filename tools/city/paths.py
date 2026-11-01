"""Where things are: the repo root, the cache, and the external tools (Blender, Godot, pigment-mcp).

Every tool path can be overridden with an environment variable:
    CITY_BLENDER, CITY_GODOT, PIGMENT_MCP, CITY_PYTHON
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE = Path(os.environ.get("CITY_CACHE", ROOT / ".citycache"))
MODELS = ROOT / "city" / "models"
LIVE = ROOT / "game" / "assets" / ".live"          # hot-swap event queue for game/scripts/live_link.gd
BLENDER_QUEUE = ROOT / ".citycache" / "blender_events.jsonl"   # read by the Pigment Bridge add-on
GAME = ROOT / "game"
WORLD_EXPORT = GAME / "assets" / "world"


def rel(p) -> str:
    """Repo-relative POSIX path (paths outside the repo stay absolute)."""
    p = Path(p)
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def absp(r) -> Path:
    p = Path(r)
    return p if p.is_absolute() else ROOT / p


def main_checkout() -> Path | None:
    """The main checkout when this is a git worktree (it holds the built pigment-mcp)."""
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT, capture_output=True, text=True,
                                timeout=10).stdout.strip()
    except Exception:
        return None
    if not common:
        return None
    c = Path(common)
    if not c.is_absolute():
        c = (ROOT / c).resolve()
    return c.parent if c.name == ".git" else None


def _first(*cands):
    for c in cands:
        if c and Path(c).is_file():
            return str(c)
    return None


def blender() -> str | None:
    return _first(os.environ.get("CITY_BLENDER"),
                  r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
                  shutil.which("blender"))


def godot() -> str | None:
    return _first(os.environ.get("CITY_GODOT"),
                  Path.home() / "Desktop" / "Godot_v4.7.2-stable_win64.exe" / "Godot_v4.7.2-stable_win64_console.exe",
                  shutil.which("godot"))


def pigment_mcp() -> str | None:
    mc = main_checkout()
    return _first(os.environ.get("PIGMENT_MCP"),
                  ROOT / "target" / "release" / "pigment-mcp.exe",
                  mc / "target" / "release" / "pigment-mcp.exe" if mc else None,
                  shutil.which("pigment-mcp"))


def pigment_app() -> str | None:
    mc = main_checkout()
    return _first(os.environ.get("PIGMENT_APP"),
                  ROOT / "target" / "release" / "pigment.exe",
                  mc / "target" / "release" / "pigment.exe" if mc else None)


def python() -> str:
    return os.environ.get("CITY_PYTHON") or sys.executable
