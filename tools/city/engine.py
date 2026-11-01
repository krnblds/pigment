"""Incremental, parallel execution of the graph.

For every node needed by the targets, in dependency order:
  1. once its dependencies are done, compute its key from the files as they are *now*
     (so a dependency that rebuilt to identical bytes leaves it fresh: early cut-off);
  2. fresh (key and outputs match the stamp) -> skip;
  3. key in the cache -> copy the outputs back;
  4. otherwise run it, inside its resource pool, then hash, store and stamp its outputs.

Pools limit what may run at once: the GPU-bound Pigment and Blender jobs are 1-2 wide by
default (see POOLS; override with --pool pigment=1). Independent nodes run in parallel.
"""
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import cache, graph as G, hashing, paths

POOLS = {"blender": 1, "pigment": 2, "godot": 1, "cpu": max(2, (os.cpu_count() or 4) // 2)}


class BuildError(Exception):
    pass


class Ctx:
    """What an action gets: its node, the log, a subprocess runner, the previous stamp."""

    def __init__(self, node, engine, prev):
        self.node = node
        self.engine = engine
        self.prev = prev or {}
        self.events = []            # hot-swap events the action wants sent (besides changed files)
        self.note = ""
        self.partial = False        # a fast path that is not the full build of this key (not cached)
        lp = cache.log_path(node.id)
        lp.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(lp, "w", encoding="utf-8", errors="replace")

    def log(self, *a):
        line = " ".join(str(x) for x in a)
        self._log.write(line + "\n")
        self._log.flush()
        if self.engine.verbose:
            self.engine.say(f"    {self.node.id}: {line}")

    def run(self, cmd, env=None, cwd=None, timeout=None, check=True):
        e = dict(os.environ)
        e.setdefault("PYTHONIOENCODING", "utf-8")
        mcp = paths.pigment_mcp()
        if mcp:
            e.setdefault("PIGMENT_MCP", mcp)
        e.update(env or {})
        self.log("$ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd))
        t0 = time.time()
        p = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd or paths.ROOT), env=e, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        tail = []
        for line in p.stdout:
            self._log.write(line)
            tail.append(line.rstrip())
            if self.engine.verbose:
                self.engine.say(f"    | {line.rstrip()}")
        p.wait(timeout=timeout)
        self._log.flush()
        self.log(f"(exit {p.returncode}, {time.time() - t0:.1f} s)")
        if check and p.returncode != 0:
            raise BuildError(f"{cmd[0]} exited {p.returncode}:\n    " + "\n    ".join(tail[-15:]))
        return p.returncode, tail

    def blender(self, script, args=(), env=None):
        b = paths.blender()
        if not b:
            raise BuildError("Blender not found (set CITY_BLENDER)")
        return self.run([b, "-b", "--factory-startup", "--python", paths.absp(script), "--", *args], env=env)

    def python(self, script, args=(), env=None):
        return self.run([paths.python(), paths.absp(script), *args], env=env)

    def close(self):
        if self._log:
            self._log.close()


class Engine:
    def __init__(self, g: G.Graph, pools=None, verbose=False, keep_going=False, dry=False, force=(), out=None,
                 fast=False, on_done=None):
        self.g = g
        self.pools = dict(POOLS, **(pools or {}))
        self.sems = {k: threading.Semaphore(v) for k, v in self.pools.items()}
        self.verbose = verbose
        self.keep_going = keep_going
        self.dry = dry
        self.force = set(force)
        self.fast = fast              # allow fast partial paths (city watch --fast)
        self.on_done = on_done        # callback(node_id, result) as soon as a node finishes (hot swap)
        self.out = out or sys.stdout
        self.lock = threading.Lock()
        self.results = {}        # id -> {"state", "seconds", "why", "changed"}
        self.t0 = time.time()

    def say(self, s):
        with self.lock:
            print(s, file=self.out, flush=True)

    # ------------------------------------------------------------ status (no building)
    def status(self, ids) -> dict:
        """id -> (state, reasons) without running anything. States: fresh, stale, cached, blocked."""
        order = self.g.topo(self.g.upstream(ids))
        st = {}
        for n in order:
            node = self.g.nodes[n]
            prev = cache.read_stamp(n)
            key, detail = G.node_key(node)
            up = [d for d in self.g.deps[n] if st[d][0] in ("stale", "cached", "blocked")]
            if prev and prev.get("key") == key:
                bad = cache.outputs_intact(node, prev)
                if not bad:
                    st[n] = ("fresh", []) if not up else ("blocked", [f"upstream {d} is {st[d][0]}" for d in sorted(up)])
                else:
                    st[n] = ("cached", bad) if cache.lookup(key) else ("stale", bad)
            else:
                why = G.explain(detail, prev)
                if up:
                    why = [f"upstream {d} is {st[d][0]}" for d in sorted(up)] + why
                st[n] = ("cached" if cache.lookup(key) and not up else "stale", why)
        hashing.stat_cache().save()
        return st

    # ------------------------------------------------------------ build
    def build(self, ids) -> dict:
        need = self.g.upstream(ids)
        order = self.g.topo(need)
        total = len(order)
        done, failed = set(), set()
        running = {}
        pending = list(order)
        idx = {n: i + 1 for i, n in enumerate(order)}
        workers = sum(self.pools.values())
        self.say(f"city build: {total} node(s), pools " + ", ".join(f"{k}={v}" for k, v in self.pools.items()))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            while pending or running:
                launched = False
                for n in list(pending):
                    ds = self.g.deps[n] & need
                    if ds & failed:
                        pending.remove(n)
                        failed.add(n)
                        self.results[n] = {"state": "skipped", "seconds": 0, "why": ["upstream failed"]}
                        self.say(f"[{idx[n]:>3}/{total}] skip  {n} (upstream failed)")
                        continue
                    if ds <= done and not (failed and not self.keep_going):
                        pending.remove(n)
                        running[ex.submit(self._one, n, idx[n], total)] = n
                        launched = True
                if failed and not self.keep_going and not running:
                    for n in pending:
                        self.results[n] = {"state": "skipped", "seconds": 0, "why": ["build stopped"]}
                    break
                if not running:
                    if pending and not launched:
                        raise BuildError("scheduler stuck (cycle?)")
                    continue
                fin, _ = wait(list(running), return_when=FIRST_COMPLETED)
                for f in fin:
                    n = running.pop(f)
                    ok = f.result()
                    (done if ok else failed).add(n)
        hashing.stat_cache().save()
        return self.results

    def _one(self, n, i, total) -> bool:
        node = self.g.nodes[n]
        t0 = time.time()
        prev = cache.read_stamp(n)
        key, detail = G.node_key(node)
        tag = f"[{i:>3}/{total}]"
        if prev and prev.get("key") == key and n not in self.force and not node.always:
            bad = cache.outputs_intact(node, prev)
            if not bad:
                self.results[n] = {"state": "fresh", "seconds": time.time() - t0, "why": []}
                if self.verbose:
                    self.say(f"{tag} fresh {n}")
                return True
        why = G.explain(detail, prev) if not (prev and prev.get("key") == key) else ["outputs changed on disk"]
        if n in self.force:
            why = ["forced"] + why
        if node.always:
            why = ["gate (always runs)"]
        rec = cache.lookup(key) if (node.cache and n not in self.force and not node.always) else None
        if self.dry:
            self.results[n] = {"state": "would-restore" if rec else "would-run", "seconds": 0, "why": why}
            self.say(f"{tag} {'restore' if rec else 'run':<7} {n}  <- {why[0]}")
            return True
        if rec:
            copied = cache.restore(rec)
            outs = cache.output_files(node)
            cache.write_stamp(node, key, detail, outs, time.time() - t0, note="restored from cache")
            changed = _changed(prev, outs)
            self.results[n] = {"state": "restored", "seconds": time.time() - t0, "why": why, "changed": changed,
                               "events": []}
            if self.on_done:
                self.on_done(n, self.results[n])
            self.say(f"{tag} cache {n}  ({copied} file(s) restored, {time.time() - t0:.1f} s)")
            return True
        self.say(f"{tag} run   {n}  <- {why[0]}{' (+%d)' % (len(why) - 1) if len(why) > 1 else ''}")
        ctx = Ctx(node, self, prev)
        sem = self.sems.get(node.pool) or self.sems["cpu"]
        try:
            with sem:
                t1 = time.time()
                if node.run is None:
                    raise BuildError(f"node {n} has no action")
                node.run(ctx)
                secs = time.time() - t1
            outs = cache.output_files(node)
            if ctx.partial:     # fast path: not what a full build of this key makes -> not cached, stays stale
                cache.write_stamp(node, "partial:" + key, detail, outs, secs, note=ctx.note)
            else:
                if node.cache:
                    cache.store(outs, key, n)
                cache.write_stamp(node, key, detail, outs, secs, note=ctx.note)
            changed = _changed(prev, outs)
            self.results[n] = {"state": "built", "seconds": secs, "why": why, "changed": changed, "events": ctx.events,
                               "note": ctx.note}
            if self.on_done:
                self.on_done(n, self.results[n])
            self.say(f"{tag} done  {n}  {secs:.1f} s" + (f", {len(changed)} output file(s) changed" if outs else "")
                     + (f"  [{ctx.note}]" if ctx.note else ""))
            return True
        except Exception as e:
            self.results[n] = {"state": "failed", "seconds": time.time() - t0, "why": why, "error": str(e)}
            self.say(f"{tag} FAIL  {n}: {e}\n        log: {paths.rel(cache.log_path(n))}")
            return False
        finally:
            ctx.close()


def _changed(prev, outs) -> list:
    old = (prev or {}).get("outputs", {})
    return sorted(r for r, d in outs.items() if old.get(r) != d)


def summary(results, t0, out=sys.stdout):
    by = {}
    for n, r in results.items():
        by.setdefault(r["state"], []).append(n)
    total = time.time() - t0
    print(f"\ncity build: {total:.1f} s  " + ", ".join(f"{k} {len(v)}" for k, v in sorted(by.items())), file=out)
    slow = sorted(((r["seconds"], n) for n, r in results.items() if r["state"] in ("built", "failed")), reverse=True)[:12]
    if slow:
        print("  slowest:", file=out)
        for s, n in slow:
            print(f"    {s:8.1f} s  {n}", file=out)
    for n in by.get("failed", []):
        print(f"  FAILED {n}: {results[n].get('error', '')[:400]}", file=out)
    return by
