"""city: build the whole city incrementally from smart models.

    python -m tools.city <command> [...]          (or: python tools/city.py <command>)

    discover [--refresh]          write city/models/<kind>/<name>.toml from the existing pipeline
    models [kind]                 list the smart models
    show <model>                  a model's manifest, its build nodes and their state
    status [targets] [-v]         what is stale, and why
    build [targets] [options]     incremental build (default: everything but the gates)
         --dry                    say what would run           --force    rebuild the targets anyway
         --pool pigment=1         concurrency per pool (blender, pigment, godot, cpu)
         --keep-going             don't stop at the first failure
         --no-import              skip the Godot headless re-import
         --only                   just the targets (leave their stale upstream alone)
         --live                   send hot-swap events to a running Godot / Blender
         -v                       stream the tools' output
    adopt [targets]               record existing outputs as built (bootstrap a checkout that
                                  already has generated assets; never runs anything)
    verify [gates]                run the checks: world verify, road obstacle scan, decal audit,
                                  pigment-mcp --check on every script
    watch [targets] [--fast]      rebuild on change, then hot swap (--fast: decal fast path)
    graph [targets] [--out f]     write the graph (.dot or .html; default .citycache/graph.html)
    open <model>                  open the model's Pigment project in the Pigment app
    live <json|ping|screenshot P> send an event to a running `godot -- --live`
    unpin <node>                  a project edited in the app stops being the source
    clean [targets] [--all] [--gc]

Targets: node ids (pigment:building_a), models (building_a, prop/bollard), node kinds
(pigment, world.mesh) or globs (godot.tex:building_a__*). A target builds with its upstream.
"""
import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import cache, discover as D, engine as E, graph as G, hashing, live, manifest as M, paths, rules


def _graph():
    t0 = time.time()
    models = M.load_all()
    if not models:
        raise SystemExit("no smart models yet: run  python -m tools.city discover")
    g = rules.build_graph(models)
    return g, models, time.time() - t0


def _targets(g, names, default_all=True):
    if not names:
        return rules.default_targets(g) if default_all else set()
    try:
        return g.select(names)
    except KeyError as e:
        raise SystemExit(str(e))


def _pools(specs):
    out = {}
    for s in specs or []:
        k, v = s.split("=", 1)
        out[k] = int(v)
    return out


# ---------------------------------------------------------------- commands
def cmd_discover(a):
    D.discover(refresh=a.refresh)


def cmd_models(a):
    models = M.load_all()
    by = {}
    for mid, d in models.items():
        by.setdefault(d["model"]["kind"], []).append(d)
    for kind in M.KINDS:
        if a.kind and kind != a.kind:
            continue
        lst = by.get(kind, [])
        if lst:
            print(f"{kind} ({len(lst)}):")
            for d in lst:
                print(f"  {d['model']['name']:<26} {d['model'].get('title', '')}")


def cmd_show(a):
    g, models, _ = _graph()
    mid = next((m for m in models if m == a.model or m.split("/")[-1] == a.model), None)
    if not mid:
        raise SystemExit(f"no model {a.model}")
    print(f"# {models[mid]['_path']}\n")
    print(Path(paths.ROOT / models[mid]["_path"]).read_text(encoding="utf-8"))
    ids = [n for n, nd in g.nodes.items() if nd.model == mid]
    eng = E.Engine(g)
    st = eng.status(ids)
    print("# nodes")
    for n in g.topo(set(ids)):
        s, why = st[n]
        print(f"  {s:<8} {n}" + (f"   <- {why[0]}" if why and s != "fresh" else ""))
        down = sorted(g.users[n])
        if down:
            print(f"           feeds: {', '.join(down[:6])}{' ...' if len(down) > 6 else ''}")


def cmd_status(a):
    g, models, tg = _graph()
    ids = _targets(g, a.targets)
    t0 = time.time()
    st = E.Engine(g).status(ids)
    counts = {}
    for n, (s, why) in st.items():
        counts[s] = counts.get(s, 0) + 1
    for n in g.topo(set(st)):
        s, why = st[n]
        if s == "fresh" and not a.verbose:
            continue
        if s == "blocked" and not a.verbose:
            continue
        print(f"{s:<8} {n}")
        for w in why[: (8 if a.verbose else 3)]:
            print(f"           {w}")
        if len(why) > 3 and not a.verbose:
            print(f"           ... (+{len(why) - 3})")
    blocked = counts.get("blocked", 0)
    print(f"\n{len(st)} node(s): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
          + (f"  (blocked = waiting on a stale upstream; -v lists them)" if blocked and not a.verbose else "")
          + f"   [{len(models)} models, graph {tg:.2f} s, status {time.time() - t0:.2f} s]")


def _hot_swap(results, out=print):
    changed = sorted({f for r in results.values() for f in r.get("changed", [])})
    ev = live.events_for(changed)
    for r in results.values():
        for e in r.get("events", []):
            if e.get("type") == "material":
                ev.append(e)
    if ev:
        if live.godot_listening():
            acks = live.send(ev, wait=True, timeout=120)
            ok = sum(1 for x in acks if x.get("ok"))
            out(f"hot swap: {ok}/{len(acks)} event(s) applied in Godot "
                f"({', '.join(sorted({e['type'] for e in ev}))}; max {max((x.get('ms', 0) for x in acks), default=0)} ms)")
        else:
            live.send(ev)
            out(f"hot swap: {len(ev)} event(s) queued (no live Godot running)")
    bev = live.blender_events(changed)
    if bev:
        live.send_blender(bev)
        out(f"hot swap: {len(bev)} Blender reload event(s) queued")
    return ev


def cmd_build(a):
    t0 = time.time()
    g, models, tg = _graph()
    ids = _targets(g, a.targets)
    if a.no_import:
        ids.discard("godot.import")
    force = g.select(a.targets) if a.force and a.targets else (set(g.nodes) if a.force else set())
    swapped = []

    def on_done(n, r):
        if a.live and r.get("changed"):
            swapped.extend(_hot_swap({n: r}))

    eng = E.Engine(g, pools=_pools(a.pool), verbose=a.verbose, keep_going=a.keep_going, dry=a.dry, force=force,
                   fast=getattr(a, "fast", False), on_done=on_done)
    res = eng.build(ids, upstream=not a.only)
    by = E.summary(res, t0)
    _write_timings(res, t0, a)
    if by.get("failed"):
        sys.exit(1)
    return res


def _write_timings(res, t0, a):
    rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "argv": sys.argv[1:], "total_s": round(time.time() - t0, 2),
           "nodes": {n: {"state": r["state"], "s": round(r["seconds"], 2), "note": r.get("note", "")} for n, r in res.items()
                     if r["state"] != "fresh"},
           "fresh": sum(1 for r in res.values() if r["state"] == "fresh")}
    p = paths.CACHE / "timings.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def cmd_adopt(a):
    """Stamp nodes whose outputs already exist as built, in dependency order, without running them."""
    g, models, _ = _graph()
    ids = g.upstream(_targets(g, a.targets))
    if a.exclude:
        ids -= g.select(a.exclude)
    n_ok = n_skip = 0
    for n in g.topo(ids):
        node = g.nodes[n]
        if node.always:
            continue
        outs = cache.output_files(node)
        declared = [p for p in node.outputs if not hashing.has_magic(p)]
        missing = [p for p in declared if not hashing.expand(p)]
        if missing or (node.outputs and not outs):
            n_skip += 1
            print(f"skip   {n}  (missing: {', '.join(missing[:3]) or 'outputs'})")
            continue
        key, detail = G.node_key(node)
        if node.cache and not a.no_store:
            cache.store(outs, key, n)
        cache.write_stamp(node, key, detail, outs, 0.0, note="adopted (existing outputs)")
        n_ok += 1
    hashing.stat_cache().save()
    print(f"adopt: {n_ok} node(s) stamped from existing outputs, {n_skip} left stale (outputs missing)")


def cmd_verify(a):
    t0 = time.time()
    g, models, _ = _graph()
    gates = [n for n in g.nodes if n.startswith("verify:")]
    sel = gates if not a.gates else [n for n in gates if any(fnmatch.fnmatchcase(n, x) or n == "verify:" + x for x in a.gates)]
    if a.skip:
        sel = [n for n in sel if not any(n == "verify:" + s or n == s for s in a.skip)]
    eng = E.Engine(g, verbose=a.verbose, keep_going=True)
    # gates only (their inputs are files; don't rebuild upstream here)
    res = {}
    for i, n in enumerate(sel):
        res[n] = None
        ok = eng._one(n, i + 1, len(sel))
        res[n] = eng.results[n]
    by = E.summary(eng.results, t0)
    for n in sel:
        r = eng.results[n]
        print(f"  {r['state']:<7} {n}: {r.get('note') or r.get('error', '')[:300]}")
    if by.get("failed"):
        sys.exit(1)


def cmd_graph(a):
    g, models, _ = _graph()
    if a.targets:       # a model's neighbourhood: what feeds it and what it feeds
        sel = _targets(g, a.targets)
        ids = g.upstream(sel) | g.downstream(sel)
    else:
        ids = set(g.nodes)
    out = Path(a.out or (paths.CACHE / "graph.html"))
    out.parent.mkdir(parents=True, exist_ok=True)
    st = E.Engine(g).status(ids) if not a.no_status else {}
    if out.suffix == ".dot":
        out.write_text(_dot(g, ids, st), encoding="utf-8")
    else:
        out.write_text(_html(g, ids, st, models), encoding="utf-8")
    print(f"graph: {len(ids)} nodes, {sum(len(g.deps[n] & ids) for n in ids)} edges -> {out}")


COLORS = {"fresh": "#2e7d32", "stale": "#c62828", "cached": "#1565c0", "blocked": "#ef6c00"}


def _dot(g, ids, st):
    lines = ["digraph city {", "  rankdir=LR; node [shape=box, fontname=Consolas, fontsize=10];"]
    groups = {}
    for n in ids:
        groups.setdefault(g.nodes[n].model or "(global)", []).append(n)
    for i, (m, ns) in enumerate(sorted(groups.items())):
        lines.append(f'  subgraph cluster_{i} {{ label="{m}"; color="#999999";')
        for n in sorted(ns):
            c = COLORS.get(st.get(n, ("?",))[0], "#555555")
            lines.append(f'    "{n}" [color="{c}"];')
        lines.append("  }")
    for n in sorted(ids):
        for d in sorted(g.deps[n] & ids):
            lines.append(f'  "{d}" -> "{n}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _html(g, ids, st, models):
    data = []
    for n in g.topo(ids):
        nd = g.nodes[n]
        s, why = st.get(n, ("?", []))
        data.append({"id": n, "model": nd.model or "(global)", "kind": nd.kind, "pool": nd.pool, "state": s, "why": why[:6],
                     "deps": sorted(g.deps[n] & ids), "users": sorted(g.users[n] & ids), "inputs": nd.inputs[:30],
                     "outputs": nd.outputs[:30], "title": nd.title})
    return """<!doctype html><html><head><meta charset="utf-8"><title>city build graph</title>
<style>
body{font:13px/1.4 Consolas,monospace;margin:0;background:#111;color:#ddd}
header{padding:10px 16px;background:#1b1b1b;position:sticky;top:0;border-bottom:1px solid #333}
input{background:#222;color:#eee;border:1px solid #444;padding:4px 8px;width:320px}
.n{border-left:4px solid #555;margin:6px 16px;padding:6px 10px;background:#181818;cursor:pointer}
.n .d{display:none;color:#aaa;white-space:pre-wrap;margin-top:6px}.n.open .d{display:block}
.fresh{border-color:#2e7d32}.stale{border-color:#c62828}.cached{border-color:#1565c0}.blocked{border-color:#ef6c00}
.tag{color:#888;margin-left:8px}a{color:#8cf}
</style></head><body><header><b>city build graph</b> <input id=q placeholder="filter: id, model, kind, state">
<span id=c></span> &nbsp; <span style="color:#2e7d32">fresh</span> <span style="color:#c62828">stale</span>
<span style="color:#1565c0">cached</span> <span style="color:#ef6c00">blocked</span></header><div id=list></div>
<script>
const D=""" + json.dumps(data) + """;
const L=document.getElementById('list'),Q=document.getElementById('q'),C=document.getElementById('c');
function esc(s){return String(s).replace(/[&<]/g,c=>c=='&'?'&amp;':'&lt;')}
function draw(){const q=Q.value.toLowerCase();let n=0;L.innerHTML='';for(const x of D){
 const hay=(x.id+' '+x.model+' '+x.kind+' '+x.state).toLowerCase(); if(q&&!hay.includes(q))continue; n++;
 const e=document.createElement('div');e.className='n '+x.state;e.id=x.id;
 e.innerHTML='<b>'+esc(x.id)+'</b><span class=tag>'+esc(x.model)+' | '+esc(x.kind)+' | pool '+esc(x.pool)+' | '+esc(x.state)+'</span>'
 +'<div class=d>'+esc(x.title)+'\\n'+(x.why.length?'why: '+esc(x.why.join('\\n     '))+'\\n':'')
 +'after: '+x.deps.map(d=>'<a href="#'+esc(d)+'">'+esc(d)+'</a>').join(', ')+'\\nfeeds: '+x.users.map(d=>'<a href="#'+esc(d)+'">'+esc(d)+'</a>').join(', ')
 +'\\ninputs: '+esc(x.inputs.join('\\n        '))+'\\noutputs: '+esc(x.outputs.join('\\n         '))+'</div>';
 e.onclick=ev=>{if(ev.target.tagName!='A')e.classList.toggle('open')};L.appendChild(e)} C.textContent=n+' / '+D.length+' nodes'}
Q.oninput=draw;draw();
</script></body></html>"""


def cmd_clean(a):
    if a.all:
        cache.clean(everything=True)
        print("removed .citycache/ (stamps, cache, logs)")
        return
    if a.gc:
        dropped, freed = cache.gc(a.keep)
        print(f"gc: dropped {dropped} old key(s), freed {freed / 1e6:.1f} MB; cache now {cache.size_bytes() / 1e6:.1f} MB")
        return
    g, models, _ = _graph()
    ids = _targets(g, a.targets, default_all=False) if a.targets else set(g.nodes)
    cache.clean(ids)
    print(f"cleared {len(ids)} stamp(s): those nodes rebuild (or restore from the cache) on the next build")


def cmd_open(a):
    models = M.load_all()
    mid = next((m for m in models if m == a.model or m.split("/")[-1] == a.model), None)
    if not mid:
        raise SystemExit(f"no model {a.model}")
    projs = [o for o in (models[mid].get("pigment") or {}).get("outputs", []) if o.endswith(".pigment")]
    if not projs:
        raise SystemExit(f"{mid} has no Pigment project")
    proj = paths.absp(projs[0])
    if not proj.is_file():
        raise SystemExit(f"{projs[0]} does not exist yet: city build pigment:{a.model}")
    app = paths.pigment_app()
    if not app:
        raise SystemExit("Pigment app not found (set PIGMENT_APP)")
    print(f"opening {projs[0]} in Pigment. Save it there; `city watch` picks the project up:")
    print("  the project is exported (pigment-mcp --export-for-blender) and the Godot / Blender copies are refreshed.")
    if a.dry:
        print(f"  (dry) {app} {proj}")
        return
    subprocess.Popen([app, str(proj)], cwd=str(paths.ROOT))


def cmd_live(a):
    if a.what == "ping":
        ev = [{"type": "ping"}]
    elif a.what == "screenshot":
        ev = [{"type": "screenshot", "path": str(Path(a.arg).resolve())}]
    else:
        ev = [json.loads(a.what)]
    acks = live.send(ev, wait=True, timeout=a.timeout)
    print(json.dumps(acks, indent=1))


def cmd_unpin(a):
    from . import pins
    g, models, _ = _graph()
    for n in _targets(g, a.targets, default_all=False):
        if pins.pinned(n):
            pins.unpin(n)
            print(f"unpinned {n}: the next build runs its recipe again")


def cmd_watch(a):
    from . import watch
    watch.watch(a)


def main(argv=None):
    p = argparse.ArgumentParser(prog="city", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("discover"); s.add_argument("--refresh", action="store_true"); s.set_defaults(fn=cmd_discover)
    s = sub.add_parser("models"); s.add_argument("kind", nargs="?"); s.set_defaults(fn=cmd_models)
    s = sub.add_parser("show"); s.add_argument("model"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("status"); s.add_argument("targets", nargs="*"); s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_status)
    for name in ("build", "watch"):
        s = sub.add_parser(name)
        s.add_argument("targets", nargs="*")
        s.add_argument("--dry", action="store_true")
        s.add_argument("--force", action="store_true")
        s.add_argument("--keep-going", action="store_true")
        s.add_argument("--no-import", action="store_true")
        s.add_argument("--live", action="store_true")
        s.add_argument("--fast", action="store_true")
        s.add_argument("--only", action="store_true", help="build just the targets, not their stale upstream")
        s.add_argument("--pool", action="append")
        s.add_argument("-v", "--verbose", action="store_true")
        if name == "watch":
            s.add_argument("--interval", type=float, default=0.5)
            s.add_argument("--once", action="store_true", help="exit after the first rebuild (tests)")
            s.add_argument("--import-after", action="store_true", help="also run the Godot re-import after each swap")
        s.set_defaults(fn=cmd_build if name == "build" else cmd_watch)
    s = sub.add_parser("adopt"); s.add_argument("targets", nargs="*"); s.add_argument("--no-store", action="store_true")
    s.add_argument("--exclude", action="append", help="leave these nodes stale (patterns like targets)")
    s.set_defaults(fn=cmd_adopt)
    s = sub.add_parser("verify"); s.add_argument("gates", nargs="*"); s.add_argument("--skip", action="append")
    s.add_argument("-v", "--verbose", action="store_true"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("graph"); s.add_argument("targets", nargs="*"); s.add_argument("--out")
    s.add_argument("--no-status", action="store_true"); s.set_defaults(fn=cmd_graph)
    s = sub.add_parser("open"); s.add_argument("model"); s.add_argument("--dry", action="store_true"); s.set_defaults(fn=cmd_open)
    s = sub.add_parser("live"); s.add_argument("what"); s.add_argument("arg", nargs="?"); s.add_argument("--timeout", type=float, default=30)
    s.set_defaults(fn=cmd_live)
    s = sub.add_parser("unpin"); s.add_argument("targets", nargs="+"); s.set_defaults(fn=cmd_unpin)
    s = sub.add_parser("clean"); s.add_argument("targets", nargs="*"); s.add_argument("--all", action="store_true")
    s.add_argument("--gc", action="store_true"); s.add_argument("--keep", type=int, default=2); s.set_defaults(fn=cmd_clean)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
