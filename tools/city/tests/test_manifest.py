"""Smart-model manifests: TOML round trip, validation, refresh, config merge, script patches,
and the real city/models compiling into an acyclic graph."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.city import manifest as M
from tools.city import paths, pigscript, toml_io

SAMPLE = {
    "model": {"name": "building_x", "kind": "building", "title": "Test \"quoted\" title: a/b", "derived": ["pigment.variants", "game"]},
    "mesh": {"runner": "blender", "generator": "assets/blender/town/building_x.py", "args": ["assets/town/building_x.glb"],
             "outputs": ["assets/town/building_x.glb"], "deps": [], "params": {"floors": 6, "height_m": 21.0, "awning": True}},
    "pigment": {"scripts": ["scenes/town/scripts/building_x.jsonl"], "resolution": 2048, "variants": ["a", "b"],
                "decal_slots": {"blade": ["blade_soba", "blade_yume"], "post w1": ["poster"]},
                "patch": [{"match": {"tool": "add_layer", "name": "Concrete"}, "set": {"opacity": 0.5, "base_color": [0.5, 0.2, 0.1]}}]},
    "game": {"category": "building", "collision": "box", "tris": 46774, "proxy": True, "world_keys": ["building_x__a"],
             "lights": [{"name": "Light_Ring", "color": [0.1, 0.9, 1.0], "energy": 0.4}], "lod": {"lod0_tris": 1, "visible_to_m": 60.0}},
    "placement": {"instances": 3, "districts": {"downtown": 1, "old_town": 2}, "scatter": {"density": {"default": 2.5}, "slots": ["curb"]}},
    "config": {},
}


class TestToml(unittest.TestCase):
    def test_round_trip(self):
        text = toml_io.dumps(SAMPLE)
        back = toml_io.loads(text)
        self.assertEqual(back, SAMPLE)
        self.assertEqual(toml_io.dumps(back), text)          # deterministic

    def test_round_trip_through_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "building" / "building_x.toml"
            M.save(SAMPLE, p)
            back = M.load(p)
            self.assertEqual(back, SAMPLE)
            self.assertTrue(p.read_text(encoding="utf-8").startswith("# Smart model (building/building_x)"))

    def test_scalars(self):
        doc = {"t": {"f": 1.0, "e": 1e-07, "neg": -3, "s": "line\nbreak \\ tab\t", "u": "Shinkai \u6e7e", "empty": [], "nested": [[1, 2], [3]]}}
        self.assertEqual(toml_io.loads(toml_io.dumps(doc)), doc)


class TestValidate(unittest.TestCase):
    def test_errors(self):
        with self.assertRaises(M.ManifestError):
            M.validate({"model": {"name": "x"}})
        with self.assertRaises(M.ManifestError):
            M.validate({"model": {"name": "x", "kind": "spaceship"}})
        with self.assertRaises(M.ManifestError):
            M.validate({"model": {"name": "x", "kind": "prop"}, "weird": {}})
        with self.assertRaises(M.ManifestError):
            M.validate({"model": {"name": "x", "kind": "prop"}, "mesh": {"runner": "maya"}})
        with self.assertRaises(M.ManifestError):
            M.validate({"model": {"name": "x", "kind": "prop"}, "pigment": {"patch": [{"set": {}}]}})
        M.validate(SAMPLE)

    def test_refresh_keeps_user_fields(self):
        old = json.loads(json.dumps(SAMPLE))
        old["mesh"]["params"]["floors"] = 9              # user edit
        old["game"]["collision"] = "trimesh"             # inside a derived section: refreshed
        new = json.loads(json.dumps(SAMPLE))
        new["pigment"]["variants"] = ["a", "b", "c"]
        new["placement"]["instances"] = 99               # not in derived: kept
        out = M.refresh(old, new)
        self.assertEqual(out["mesh"]["params"]["floors"], 9)
        self.assertEqual(out["pigment"]["variants"], ["a", "b", "c"])
        self.assertEqual(out["game"]["collision"], "box")
        self.assertEqual(out["placement"]["instances"], 3)

    def test_deep_merge_by_name(self):
        base = {"seed": 1, "districts": [{"name": "downtown", "radius": 420, "towers": {"density": 0.5}}, {"name": "port", "radius": 300}]}
        over = {"seed": 7, "districts": [{"name": "downtown", "towers": {"density": 0.8}}, {"name": "new", "radius": 10}]}
        out = M.deep_merge(base, over)
        self.assertEqual(out["seed"], 7)
        self.assertEqual(out["districts"][0], {"name": "downtown", "radius": 420, "towers": {"density": 0.8}})
        self.assertEqual(out["districts"][1]["name"], "port")
        self.assertEqual(out["districts"][2]["name"], "new")
        self.assertEqual(base["districts"][0]["towers"]["density"], 0.5)      # not mutated


class TestPigmentScripts(unittest.TestCase):
    LINES = [
        {"tool": "new_project", "args": {"mesh": "assets/town/building_x.glb", "resolution": 2048}},
        {"tool": "add_layer", "args": {"name": "Concrete", "opacity": 1.0}},
        {"tool": "project_decal", "args": {"image": "assets/decals/story/blade_soba.png", "name": "blade/blade_soba"}},
        {"tool": "export_variants", "args": {"dir": "scenes/town/textures", "name": "building_x",
                                             "variants": [{"name": "soba", "enable": ["blade/blade_soba"]}, {"name": "dark"}]}},
        {"tool": "export_textures", "args": {"dir": "scenes/town/textures/building_x"}},
        {"tool": "save_project", "args": {"path": "scenes/town/projects/building_x.pigment"}},
        {"tool": "render", "args": {"path": "C:/Temp/preview.png"}},
    ]

    def test_scan(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("\n".join(json.dumps(l) for l in self.LINES), encoding="utf-8")
            sc = pigscript.scan(p)
        self.assertEqual(sc["inputs"], ["assets/decals/story/blade_soba.png", "assets/town/building_x.glb"])
        self.assertEqual(sc["outputs"], ["scenes/town/projects/building_x.pigment", "scenes/town/textures/building_x",
                                         "scenes/town/textures/building_x__dark", "scenes/town/textures/building_x__soba"])
        self.assertEqual(sc["variants"], ["soba", "dark"])
        self.assertEqual(sc["decal_slots"], {"blade": ["blade_soba"]})
        self.assertEqual(sc["resolution"], 2048)

    def test_patch(self):
        out = pigscript.apply_patches(self.LINES, [
            {"match": {"tool": "add_layer", "name": "Concrete"}, "set": {"opacity": 0.4, "tint.r": 0.9}},
            {"append": {"tool": "add_layer", "args": {"name": "Extra grime"}}}])
        layer = next(s for s in out if s["args"].get("name") == "Concrete")
        self.assertEqual(layer["args"]["opacity"], 0.4)
        self.assertEqual(layer["args"]["tint"], {"r": 0.9})
        i_extra = next(i for i, s in enumerate(out) if s["args"].get("name") == "Extra grime")
        i_export = next(i for i, s in enumerate(out) if s["tool"] == "export_variants")
        self.assertEqual(i_extra, i_export - 1)
        self.assertEqual(self.LINES[1]["args"]["opacity"], 1.0)           # input untouched
        with self.assertRaises(ValueError):
            pigscript.apply_patches(self.LINES, [{"match": {"tool": "add_layer", "name": "Nope"}, "set": {}}])


class TestRealModels(unittest.TestCase):
    """The committed city/models load, validate and compile into an acyclic graph."""

    @unittest.skipUnless((paths.MODELS / "building").is_dir(), "no city/models yet")
    def test_models_compile(self):
        from tools.city import rules
        models = M.load_all()
        kinds = {d["model"]["kind"] for d in models.values()}
        self.assertTrue({"building", "prop", "vehicle", "road_set", "decal_set", "tile_set", "sky", "terrain", "district",
                         "world"} <= kinds)
        g = rules.build_graph(models)          # links and checks for cycles
        self.assertIn("pigment:building_a", g.nodes)
        self.assertIn("world.mesh:building_a", g.upstream({"godot.import"}))
        self.assertEqual(g.deps["godot.tex:building_a__soba"], {"pigment:building_a"})
        for mid, doc in models.items():
            text = toml_io.dumps({k: v for k, v in doc.items() if k != "_path"})
            self.assertEqual(toml_io.loads(text), {k: v for k, v in doc.items() if k != "_path"}, mid)


if __name__ == "__main__":
    unittest.main()
