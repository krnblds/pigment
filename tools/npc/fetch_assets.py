"""Fetch the CC0 source assets the citizen pipeline uses (system Python, needs curl).

    python tools/npc/fetch_assets.py [--packs-only | --anims-only]

* MakeHuman community asset packs (all CC0, https://static.makehumancommunity.org/assets/assetpacks.html):
  clothes, shoes, hats, hair, masks, glasses and sci-fi suits.  Downloaded to .npccache/downloads/ and
  unpacked into MPFB's user data dir (%APPDATA%/Blender Foundation/Blender/5.2/extensions/.user/
  user_default/mpfb/data), where MPFB's asset service finds them.  The "MakeHuman system assets" pack
  (skins, proxies, eyes, system clothes) must already be installed in MPFB (it is installed by MPFB's
  own "Load pack" button; this script installs it too when it is missing).
* Quaternius "Universal Animation Library" 1 + 2, Standard (CC0, https://quaternius.com): the itch.io free
  download (no account needed) -> .npccache/ual/UAL1_Standard.glb, UAL2_Standard.glb.

Everything lands in git-ignored folders; re-running skips what is already there.
"""
import concurrent.futures as cf
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, ".npccache")
DL = os.path.join(CACHE, "downloads")
MPFB_DATA = os.path.join(os.environ.get("APPDATA", ""), "Blender Foundation", "Blender", "5.2", "extensions", ".user",
                         "user_default", "mpfb", "data")
MIRRORS = ["https://files2.makehumancommunity.org/asset_packs", "https://files.makehumancommunity.org/asset_packs"]
# (pack, zip name) - CC0 only
PACKS = [("makehuman_system_assets", "makehuman_system_assets_cc0"), ("shirts01", "shirts01_cc0"),
         ("pants01", "pants01_cc0"), ("shoes01", "shoes01_cc0"), ("hats01", "hats01_cc0"), ("hair01", "hair01_cc0"),
         ("masks01", "masks01_cc0"), ("glasses01", "glasses01_cc0"), ("suits02", "suits02_cc0")]
UAL = [("universal-animation-library", "UAL1_Standard.glb"), ("universal-animation-library-2", "UAL2_Standard.glb")]


def curl(args, out=None):
    cmd = ["curl", "-sSL", "--retry", "5", "--retry-delay", "3", "--connect-timeout", "30"] + args
    if out:
        cmd += ["-o", out]
    return subprocess.run(cmd, capture_output=True, text=out is None, check=False)


def ok_zip(p):
    try:
        with zipfile.ZipFile(p) as z:
            return z.testzip() is None
    except Exception:
        return False


def fetch_pack(pack, name):
    os.makedirs(DL, exist_ok=True)
    out = os.path.join(DL, name + ".zip")
    if os.path.isfile(out) and ok_zip(out):
        return out
    for attempt in range(6):
        for m in MIRRORS:
            curl(["-C", "-", f"{m}/{pack}/{name}.zip"], out)        # resume partial files
            if ok_zip(out):
                return out
    raise RuntimeError(f"could not download {pack}")


def install_pack(zp):
    """Unpack the asset folders into MPFB's user data dir (only CC0 assets: check each .mhclo licence)."""
    n = 0
    with zipfile.ZipFile(zp) as z:
        for info in z.infolist():
            rel = info.filename.replace("\\", "/")
            if info.is_dir() or rel.startswith("/") or ".." in rel.split("/"):
                continue
            dst = os.path.join(MPFB_DATA, *rel.split("/"))
            if os.path.exists(dst):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(info) as src, open(dst, "wb") as f:
                shutil.copyfileobj(src, f)
            n += 1
    return n


def licence_report():
    """{asset: licence} for every clothes/hair item MPFB has (from the .mhclo header)."""
    rep = {}
    for p in glob.glob(os.path.join(MPFB_DATA, "*", "*", "*.mhclo")):
        lic = "unknown"
        author = ""
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                low = line.lower()
                if low.startswith("license") or "license" in low[:12]:
                    lic = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else lic
                if "explicitly released as cc0" in low:
                    lic = "CC0"
                if low.startswith("author"):
                    author = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else ""
                if low.startswith("verts") or low.startswith("obj_file"):
                    break
        rep[os.path.splitext(os.path.basename(p))[0]] = {"license": lic, "author": author,
                                                         "kind": os.path.basename(os.path.dirname(os.path.dirname(p)))}
    return rep


def fetch_ual(slug, want):
    d = os.path.join(CACHE, "ual")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, want)
    if os.path.isfile(out) and os.path.getsize(out) > 1_000_000:
        return out
    tmp = os.path.join(CACHE, "tmp_" + slug)
    os.makedirs(tmp, exist_ok=True)
    jar = os.path.join(tmp, "cookies.txt")
    base = f"https://quaternius.itch.io/{slug}"
    page = curl(["-c", jar, "-b", jar, base]).stdout
    tok = re.search(r'csrf_token" value="([^"]+)', page).group(1)
    r = curl(["-c", jar, "-b", jar, "-X", "POST", "--data-urlencode", f"csrf_token={tok}", base + "/download_url"]).stdout
    url = json.loads(r)["url"]
    page = curl(["-c", jar, "-b", jar, url]).stdout
    tok = re.search(r'csrf_token" value="([^"]+)', page).group(1)
    # the free "[Standard].zip" upload
    m = re.search(r'data-upload_id="(\d+)"[^<]*</a><div class="info_column"><div class="upload_name"><strong title="([^"]*Standard[^"]*)"', page)
    uid = m.group(1) if m else re.search(r'data-upload_id="(\d+)"', page).group(1)
    r = curl(["-c", jar, "-b", jar, "-X", "POST", "--data-urlencode", f"csrf_token={tok}",
              f"{base}/file/{uid}?source=game_download"]).stdout
    zp = os.path.join(tmp, "pack.zip")
    curl([json.loads(r)["url"]], zp)
    with zipfile.ZipFile(zp) as z:
        for n in z.namelist():
            if n.endswith("/" + want) and "Unreal-Godot" in n:
                with z.open(n) as src, open(out, "wb") as f:
                    shutil.copyfileobj(src, f)
            if n.endswith("License.txt") and not os.path.exists(os.path.join(d, "LICENSE_" + slug + ".txt")):
                with z.open(n) as src, open(os.path.join(d, "LICENSE_" + slug + ".txt"), "wb") as f:
                    shutil.copyfileobj(src, f)
    shutil.rmtree(tmp, ignore_errors=True)
    if not os.path.isfile(out):
        raise RuntimeError(f"{want} not found in the {slug} download")
    return out


def main():
    anims = "--packs-only" not in sys.argv
    packs = "--anims-only" not in sys.argv
    if anims:
        for slug, want in UAL:
            print("animations:", fetch_ual(slug, want))
    if packs:
        if not os.path.isdir(os.path.dirname(MPFB_DATA)):
            sys.exit("MPFB is not installed for Blender 5.2 (" + MPFB_DATA + ")")
        todo = PACKS if not os.path.isdir(os.path.join(MPFB_DATA, "skins")) else PACKS[1:]
        with cf.ThreadPoolExecutor(4) as ex:
            futs = {ex.submit(fetch_pack, p, n): p for p, n in todo}
            for f in cf.as_completed(futs):
                zp = f.result()
                print("pack %-24s %4d new files" % (futs[f], install_pack(zp)))
        rep = licence_report()
        with open(os.path.join(CACHE, "mpfb_licences.json"), "w") as f:
            json.dump(rep, f, indent=1, sort_keys=True)
        bad = {k: v for k, v in rep.items() if v["license"] != "CC0"}
        print("%d MPFB clothes/hair items, %d not marked CC0 (build_citizens.py only uses CC0 ones): %s" %
              (len(rep), len(bad), ", ".join(sorted(bad))[:400]))


if __name__ == "__main__":
    main()
