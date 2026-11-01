"""city watch: poll the sources, rebuild what they feed, hot-swap the results.

Watched: every smart model (city/models), every node's tools, and every input file that no
node produces (the true sources: generator scripts, decal images, recipes, configs), plus the
Pigment projects (a project saved in the Pigment app pins its node to the project, see
tools/city/pins.py). Polling (stat only) every --interval seconds; no extra dependency.

On a change: (re)load the graph if a manifest changed, build the stale part of the targets
(the Godot re-import is left out, it is not needed for the live swap), and send each node's
changed outputs to Godot / Blender as soon as that node finishes. Prints the time from the
file change to the last acknowledged swap.
"""
import os
import time

from . import cache, engine as E, hashing, live, paths, pins, rules
from . import manifest as M


def _sources(g, ids):
    """Input / tool files of the nodes that no node produces (+ Pigment projects, + manifests)."""
    import fnmatch
    exact, globs = set(), []
    for n in g.nodes.values():
        for o in n.outputs:      # mutable outputs (decal images...) are also hand-edited sources: watched
            o = hashing.split_projection(o)[0]
            if o.endswith(".pigment"):
                continue
            if hashing.has_magic(o):
                globs.append(o)
            else:
                exact.add(o.rstrip("/"))

    def produced(r):
        parts = r.split("/")
        for i in range(1, len(parts) + 1):
            if "/".join(parts[:i]) in exact:
                return True
        return any(fnmatch.fnmatchcase(r, gp) or fnmatch.fnmatchcase("/".join(parts[:gp.count("/") + 1]), gp) for gp in globs)

    files = set()
    for n in ids:
        nd = g.nodes[n]
        for pat in nd.inputs + nd.tools:
            for f in hashing.expand(pat):
                if not produced(paths.rel(f)):
                    files.add(str(f))
        for o in nd.outputs:            # Pigment projects (folders): edited in the app
            if o.endswith(".pigment"):
                files |= {str(f) for f in hashing.expand(o)}
    for p in paths.MODELS.glob("*/*.toml"):
        files.add(str(p))
    return files


def _snapshot(files):
    out = {}
    for f in files:
        try:
            st = os.stat(f)
            out[f] = (st.st_size, st.st_mtime_ns)
        except OSError:
            out[f] = None
    return out


def watch(a):
    def load():
        g = rules.build_graph(M.load_all())
        ids = g.select(a.targets) if a.targets else rules.default_targets(g)
        ids.discard("godot.import")
        return g, ids

    g, ids = load()
    files = _sources(g, g.upstream(ids))
    snap = _snapshot(files)
    print(f"city watch: {len(files)} source file(s) for {len(ids)} target node(s); "
          f"Godot live link {'connected' if live.godot_listening() else 'not running (events are queued)'}. Ctrl+C to stop.")
    if a.fast:
        print("  --fast: decal-only changes re-export just the affected variants from the saved project (partial)")
    while True:
        time.sleep(a.interval)
        now = _snapshot(files)
        changed = [f for f in now if now[f] != snap.get(f)]
        if not changed:
            continue
        time.sleep(0.3)                     # let the writer finish (editors save in steps)
        now = _snapshot(files)
        changed = [f for f in now if now[f] != snap.get(f)]
        t_change = time.time()
        rels = [paths.rel(f) for f in changed]
        print(f"\n[{time.strftime('%H:%M:%S')}] changed: {', '.join(rels[:6])}{' ...' if len(rels) > 6 else ''}")
        if any(r.startswith("city/models/") for r in rels):
            g, ids = load()
        projects = {r[:r.index(".pigment") + 8] for r in rels if ".pigment" in r}
        for r in sorted(projects):
            if True:
                nid = pins.node_for_project(g, r)
                if nid and pins.project_edited(g.nodes[nid], r):
                    pins.pin(nid, r)
                    print(f"  {r} was saved outside the build: {nid} is now pinned to the project "
                          f"(`city unpin {nid}` goes back to the recipe)")
                    g, ids = load()
        swaps = []

        def on_done(n, r):
            if r.get("changed") or r.get("events"):
                from .cli import _hot_swap
                swaps.extend(_hot_swap({n: r}, out=lambda s: print("  " + s)))

        eng = E.Engine(g, pools=_pools(a.pool), verbose=a.verbose, keep_going=True, fast=a.fast, on_done=on_done)
        res = eng.build(ids)
        E.summary(res, t_change)
        print(f"  change -> last swap acknowledged: {time.time() - t_change:.1f} s ({len(swaps)} event(s))")
        if a.import_after:
            E.Engine(g, verbose=a.verbose).build({"godot.import"})
        files = _sources(g, g.upstream(ids))
        snap = _snapshot(files)
        if a.once:
            return res


def _pools(specs):
    out = {}
    for s in specs or []:
        k, v = s.split("=", 1)
        out[k] = int(v)
    return out
