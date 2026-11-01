"""Graph, hashing, staleness, early cut-off, cache restore and cycle tests (no Blender / GPU).

    python -m pytest tools/city/tests -q        (or: python -m unittest discover tools/city/tests)
"""
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.city import cache, engine as E, graph as G, hashing, paths


class Sandbox(unittest.TestCase):
    """Points the city at a temporary repo root."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="citytest_"))
        self._saved = (paths.ROOT, paths.CACHE)
        paths.ROOT = self.tmp
        paths.CACHE = self.tmp / ".citycache"
        hashing._STAT = None
        self.runs = []

    def tearDown(self):
        paths.ROOT, paths.CACHE = self._saved
        hashing._STAT = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))     # make the edit visible to the stat cache
        return p

    def read(self, rel):
        return (self.tmp / rel).read_text(encoding="utf-8")

    # a step: concatenate inputs (optionally transformed) into one output
    def step(self, nid, inputs, output, fn=lambda s: s, tools=(), **kw):
        def run(ctx):
            self.runs.append(nid)
            text = "".join(fn(self.read(i)) for i in inputs)
            self.write(output, text)
        return G.Node(id=nid, kind="test", inputs=list(inputs), outputs=[output], tools=list(tools), run=run, **kw)

    def build(self, g, ids=None, **kw):
        self.runs = []
        eng = E.Engine(g, out=io.StringIO(), **kw)
        return eng.build(set(ids or g.nodes))


class TestPatterns(unittest.TestCase):
    def test_overlap(self):
        o = hashing.overlaps
        self.assertTrue(o("scenes/town/textures/building_a__soba", "scenes/town/textures/building_a__*"))
        self.assertTrue(o("scenes/town/textures", "scenes/town/textures/building_a__soba/x.png"))
        self.assertTrue(o("assets/props/index.json::placement", "assets/props/index.json"))
        self.assertFalse(o("scenes/town/textures/building_a", "scenes/town/textures/building_a__*"))
        self.assertFalse(o("assets/town/building_a.glb", "assets/town/building_b.glb"))
        self.assertTrue(o("assets/props/*.glb", "assets/props/bollard.glb"))
        self.assertFalse(o("assets/props/*.glb", "assets/props/src/bollard.glb"))


class TestGraph(Sandbox):
    def test_edges_follow_files(self):
        g = G.Graph()
        g.add(G.Node(id="a", kind="t", outputs=["out/a.txt"]))
        g.add(G.Node(id="b", kind="t", inputs=["out/a.txt"], outputs=["out/b"]))
        g.add(G.Node(id="c", kind="t", inputs=["out/b/*.png"], outputs=["final.bin"]))
        g.add(G.Node(id="d", kind="t", inputs=["out"], outputs=["all.txt"]))
        g.add(G.Node(id="e", kind="t", inputs=["unrelated.txt"], after=["d"]))
        g.link()
        self.assertEqual(g.deps["b"], {"a"})
        self.assertEqual(g.deps["c"], {"b"})
        self.assertEqual(g.deps["d"], {"a", "b"})
        self.assertEqual(g.deps["e"], {"d"})
        order = g.topo()
        self.assertLess(order.index("a"), order.index("b"))
        self.assertLess(order.index("b"), order.index("c"))
        self.assertEqual(g.upstream({"c"}), {"a", "b", "c"})
        self.assertEqual(g.downstream({"a"}), {"a", "b", "c", "d", "e"})

    def test_cycle_detection(self):
        g = G.Graph()
        g.add(G.Node(id="x", kind="t", inputs=["z.txt"], outputs=["x.txt"]))
        g.add(G.Node(id="y", kind="t", inputs=["x.txt"], outputs=["y.txt"]))
        g.add(G.Node(id="z", kind="t", inputs=["y.txt"], outputs=["z.txt"]))
        g.add(G.Node(id="free", kind="t", outputs=["free.txt"]))
        with self.assertRaises(G.CycleError) as cm:
            g.link()
        cyc = cm.exception.cycle
        self.assertEqual(cyc[0], cyc[-1])
        self.assertEqual(set(cyc), {"x", "y", "z"})

    def test_self_loop_is_not_an_edge(self):
        g = G.Graph()
        g.add(G.Node(id="s", kind="t", inputs=["f.txt"], outputs=["f.txt"]))
        g.link()
        self.assertEqual(g.deps["s"], set())

    def test_select(self):
        g = G.Graph()
        g.add(G.Node(id="pigment:building_a", kind="t", model="building/building_a"))
        g.add(G.Node(id="world.mesh:building_a", kind="t", model="building/building_a"))
        g.add(G.Node(id="pigment:bench", kind="t", model="prop/bench"))
        g.link()
        self.assertEqual(g.select(["building_a"]), {"pigment:building_a", "world.mesh:building_a"})
        self.assertEqual(g.select(["pigment"]), {"pigment:building_a", "pigment:bench"})
        self.assertEqual(g.select(["world.mesh:*"]), {"world.mesh:building_a"})
        with self.assertRaises(KeyError):
            g.select(["nope"])


class TestHashing(Sandbox):
    def test_key_tracks_inputs_params_tools(self):
        self.write("in.txt", "one")
        self.write("tool.py", "print(1)")
        n = G.Node(id="n", kind="t", inputs=["in.txt"], tools=["tool.py"], params={"p": 1})
        k1, _ = G.node_key(n)
        self.assertEqual(k1, G.node_key(n)[0])                    # stable
        self.write("in.txt", "two")
        k2, d2 = G.node_key(n)
        self.assertNotEqual(k1, k2)
        self.write("tool.py", "print(2)")
        k3, _ = G.node_key(n)
        self.assertNotEqual(k2, k3)
        n.params = {"p": 2}
        k4, d4 = G.node_key(n)
        self.assertNotEqual(k3, k4)
        why = G.explain(d4, {"detail": d2})
        self.assertIn("parameters changed", why)
        self.assertIn("tool changed: tool.py", why)

    def test_directory_and_glob_inputs(self):
        self.write("tex/a/x.png", "1")
        self.write("tex/b/x.png", "2")
        h1 = hashing.pattern_hash("tex")[0]
        g1 = hashing.pattern_hash("tex/*")[0]
        self.write("tex/b/x.png", "3")
        self.assertNotEqual(h1, hashing.pattern_hash("tex")[0])
        self.assertNotEqual(g1, hashing.pattern_hash("tex/*")[0])
        self.write("tex/b/x.png.import", "ignored")
        h2 = hashing.pattern_hash("tex")[0]
        self.write("tex/b/x.png.import", "ignored, changed")
        self.assertEqual(h2, hashing.pattern_hash("tex")[0])

    def test_json_projection(self):
        idx = {"props": {"bollard": {"scatter": {"spacing": 1.6}, "footprint": {"w": 0.26}, "lod": {"lod0_tris": 468},
                                     "files": {"lod0": "bollard.glb"}, "collider": {"type": "cylinder"}}}}
        self.write("index.json", json.dumps(idx))
        h = hashing.pattern_hash("index.json::placement")[0]
        idx["props"]["bollard"]["lod"]["lod0_tris"] = 500          # not placement-relevant
        self.write("index.json", json.dumps(idx))
        self.assertEqual(h, hashing.pattern_hash("index.json::placement")[0])
        idx["props"]["bollard"]["scatter"]["spacing"] = 2.0
        self.write("index.json", json.dumps(idx))
        self.assertNotEqual(h, hashing.pattern_hash("index.json::placement")[0])

    def test_stat_cache_reuses_hashes(self):
        p = self.write("big.bin", "x" * 1000)
        sc = hashing.stat_cache()
        d = sc.file_hash(p)
        sc.save()
        hashing._STAT = None
        self.assertEqual(hashing.stat_cache().file_hash(p), d)
        self.assertIn(str(p), hashing.stat_cache().data)


class TestEngine(Sandbox):
    def chain(self):
        g = G.Graph()
        g.add(self.step("upper", ["src/a.txt"], "build/a.up", str.upper))
        g.add(self.step("strip", ["build/a.up"], "build/a.strip", lambda s: s.strip()))
        g.add(self.step("other", ["src/b.txt"], "build/b.out"))
        g.add(self.step("final", ["build/a.strip", "build/b.out"], "final.txt"))
        return g.link()

    def test_incremental(self):
        self.write("src/a.txt", "hello ")
        self.write("src/b.txt", "world")
        g = self.chain()
        self.build(g)
        self.assertEqual(sorted(self.runs), ["final", "other", "strip", "upper"])
        self.assertEqual(self.read("final.txt"), "HELLOworld")
        # no-op
        res = self.build(g)
        self.assertEqual(self.runs, [])
        self.assertTrue(all(r["state"] == "fresh" for r in res.values()))
        # one source changes: only its chain re-runs
        self.write("src/b.txt", "there")
        self.build(g)
        self.assertEqual(sorted(self.runs), ["final", "other"])
        self.assertEqual(self.read("final.txt"), "HELLOthere")

    def test_early_cutoff(self):
        self.write("src/a.txt", "hello")
        self.write("src/b.txt", "world")
        g = self.chain()
        self.build(g)
        # trailing whitespace changes `upper`'s output but not `strip`'s: final must not re-run
        self.write("src/a.txt", "hello   ")
        self.build(g)
        self.assertEqual(sorted(self.runs), ["strip", "upper"])

    def test_status_reports_why(self):
        self.write("src/a.txt", "a")
        self.write("src/b.txt", "b")
        g = self.chain()
        st = E.Engine(g, out=io.StringIO()).status(set(g.nodes))
        self.assertEqual(st["upper"], ("stale", ["never built"]))
        self.build(g)
        self.write("src/a.txt", "A")
        st = E.Engine(g, out=io.StringIO()).status(set(g.nodes))
        self.assertEqual(st["upper"][0], "stale")
        self.assertIn("input changed: src/a.txt", st["upper"][1])
        self.assertEqual(st["strip"][0], "blocked")
        self.assertEqual(st["other"][0], "fresh")

    def test_cache_restores_a_reverted_edit(self):
        self.write("src/a.txt", "v1")
        self.write("src/b.txt", "b")
        g = self.chain()
        self.build(g)
        self.write("src/a.txt", "v2")
        self.build(g)
        self.assertIn("upper", self.runs)
        self.write("src/a.txt", "v1")                   # undo: every key was built before
        res = self.build(g)
        self.assertEqual(self.runs, [])
        self.assertEqual(res["upper"]["state"], "restored")
        self.assertEqual(self.read("final.txt"), "V1b")

    def test_deleted_output_is_restored(self):
        self.write("src/a.txt", "a")
        self.write("src/b.txt", "b")
        g = self.chain()
        self.build(g)
        (self.tmp / "build/b.out").unlink()
        st = E.Engine(g, out=io.StringIO()).status({"other"})
        self.assertEqual(st["other"][0], "cached")
        res = self.build(g)
        self.assertEqual(self.runs, [])
        self.assertEqual(res["other"]["state"], "restored")
        self.assertTrue((self.tmp / "build/b.out").is_file())

    def test_failure_skips_dependents(self):
        self.write("src/a.txt", "a")
        self.write("src/b.txt", "b")
        g = G.Graph()

        def boom(ctx):
            raise RuntimeError("boom")
        g.add(G.Node(id="bad", kind="t", inputs=["src/a.txt"], outputs=["x.txt"], run=boom))
        g.add(self.step("after_bad", ["x.txt"], "y.txt"))
        g.add(self.step("independent", ["src/b.txt"], "z.txt"))
        g.link()
        res = self.build(g, keep_going=True)
        self.assertEqual(res["bad"]["state"], "failed")
        self.assertEqual(res["after_bad"]["state"], "skipped")
        self.assertEqual(res["independent"]["state"], "built")

    def test_pools_limit_concurrency(self):
        import threading
        import time
        live = {"now": 0, "max": 0}
        lock = threading.Lock()

        def slow(ctx):
            with lock:
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            time.sleep(0.15)
            with lock:
                live["now"] -= 1
        g = G.Graph()
        for i in range(4):
            self.write(f"s{i}.txt", str(i))
            g.add(G.Node(id=f"gpu{i}", kind="t", inputs=[f"s{i}.txt"], pool="pigment", run=slow, cache=False))
        g.link()
        self.build(g, pools={"pigment": 2})
        self.assertEqual(live["max"], 2)


if __name__ == "__main__":
    unittest.main()
