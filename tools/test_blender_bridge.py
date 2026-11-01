"""Headless end-to-end test of the Pigment Bridge add-on (Blender 5.2).

Prerequisites (from the repo root):
  cargo build --release                      # target/release/pigment-mcp(.exe)
  target/release/pigment-mcp --script scenes/town/scripts/blender_bridge_variants.jsonl

Run (from the repo root):
  "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup \
      --python tools/test_blender_bridge.py [-- --quick] [-- --out docs/agents/blender-bridge]

What it does:
  1. zips tools/blender_addon/pigment_bridge and installs it as an extension into a
     throw-away local repository (temp dir; the user's Blender is untouched), enables it;
  2. imports the exact mesh Pigment painted (Import Pigment Mesh), makes linked
     duplicates, links them all with "Random variant per object" and checks
     variants / material sharing / determinism;
  3. checks every map: ORM + DirectX normals (unreal preset), emission driver
     (= emissive_scale x multiplier), bump vs displacement;
  4. live reload: re-exports a linked folder with pigment-mcp (changed colours and
     emission) and checks the timer's check picks it up (rebuild), then touches
     one PNG only (in-place image reload);
  5. links a .pigment project (exported via pigment-mcp --export-for-blender) and
     watches it for re-export;
  6. renders the street (Cycles) to <out>/bridge_town.png and the reload
     before/after to <out>/bridge_reload.png.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import addon_utils
import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
QUICK = "--quick" in ARGS
OUT = os.path.join(REPO, "docs", "agents", "blender-bridge")
if "--out" in ARGS:
    OUT = os.path.abspath(ARGS[ARGS.index("--out") + 1])
TEX = os.path.join(REPO, "scenes", "town", "textures", "blender")
EXE = next((p for p in (os.path.join(REPO, "target", "release", e) for e in ("pigment-mcp.exe", "pigment-mcp")) if os.path.isfile(p)), None)
TMP = os.path.join(tempfile.gettempdir(), "pigment_bridge_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
os.makedirs(OUT, exist_ok=True)
if EXE:
    os.environ["PIGMENT_MCP"] = EXE

print("Blender", bpy.app.version_string, "| pigment-mcp:", EXE)
assert os.path.isdir(os.path.join(TEX, "building_a__warm")), "run scenes/town/scripts/blender_bridge_variants.jsonl first"
t_start = time.time()


def step(msg):
    print(f"\n== {msg}  ({time.time() - t_start:.0f}s)")
    sys.stdout.flush()


# ------------------------------------------------------------------ 1. install
step("install the add-on from a path")
zpath = os.path.join(TMP, "pigment_bridge.zip")
src = os.path.join(HERE, "blender_addon", "pigment_bridge")
with zipfile.ZipFile(zpath, "w") as z:
    for root, _, files in os.walk(src):
        for f in files:
            if "__pycache__" in root or f.endswith(".pyc"):
                continue
            full = os.path.join(root, f)
            z.write(full, os.path.join("pigment_bridge", os.path.relpath(full, src)))
repo_dir = os.path.join(TMP, "ext_repo")
os.makedirs(repo_dir)
bpy.ops.preferences.extension_repo_add(name="pigment_test", type="LOCAL", custom_directory=repo_dir, use_custom_directory=True)
repo = next(r for r in bpy.context.preferences.extensions.repos if r.name == "pigment_test")
bpy.ops.extensions.package_install_files(filepath=zpath, repo=repo.module, enable_on_install=True)
modname = f"bl_ext.{repo.module}.pigment_bridge"
assert modname in bpy.context.preferences.addons, [a.module for a in bpy.context.preferences.addons]
addon = sys.modules[modname]
core = addon.core
assert os.path.dirname(addon.__file__).startswith(repo_dir), addon.__file__
assert hasattr(bpy.types.Scene, "pigment_bridge") and hasattr(bpy.ops.pigment, "link")
assert bpy.app.timers.is_registered(addon._tick), "auto-reload timer not registered"
print("installed", modname, "from", addon.__file__)

# ------------------------------------------------------------------ scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
scene = bpy.context.scene
S = scene.pigment_bridge


def select(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def pmat(o):
    return o.material_slots[0].material if o.material_slots else None


# ------------------------------------------------------------------ 2. mesh round trip + variants
step("import Pigment's mesh, link duplicates with random variants")
S.source = os.path.join(TEX, "building_a__warm")
assert bpy.ops.pigment.import_mesh() == {"FINISHED"}
imported = [o for o in bpy.data.objects if o.type == "MESH"]
assert len(imported) == 1, imported
bld = imported[0]
spec = core.discover(S.source)
# the exact mesh Pigment painted: same vertex and triangle count as the exported glb
import struct
with open(spec["mesh"], "rb") as f:
    f.read(12)
    jlen = struct.unpack("<I", f.read(4))[0]
    f.read(4)
    gl = json.loads(f.read(jlen))
nverts = gl["accessors"][0]["count"]
ntris = gl["accessors"][4]["count"] // 3
me = bld.data
me.calc_loop_triangles()
print(f"glb: {nverts} verts {ntris} tris | blender: {len(me.vertices)} verts {len(me.loop_triangles)} tris")
assert len(me.loop_triangles) == ntris
assert "TANGENT" in gl["meshes"][0]["primitives"][0]["attributes"]
assert pmat(bld).get("pigment_name") == "building_a"
dims = bld.dimensions.copy()
print("building size (m):", tuple(round(d, 1) for d in dims))

W = max(dims.x, dims.y) + 4.0
row_a = [bld]
for i in range(1, 7):
    o = bld.copy()  # linked duplicate: shares the mesh
    scene.collection.objects.link(o)
    o.name = f"building_a.{i:03d}"
    row_a.append(o)
for i, o in enumerate(row_a):
    o.location = (i * W - 3 * W, 14.0, 0)
    o.rotation_euler = (0, 0, math.radians(180))
select(row_a)
S.use_variants = True
S.seed = 7
S.height_mode = "BUMP"
assert bpy.ops.pigment.link() == {"FINISHED"}
pick = {o.name: pmat(o).get("pigment_folder") for o in row_a}
variants = core.variant_folders(S.source)
print("variants:", [os.path.basename(v) for v in variants])
for n, f in pick.items():
    print(f"  {n:16s} -> {os.path.basename(f)}  ({pmat(bpy.data.objects[n]).name})")
assert len(variants) == 3
assert set(pick.values()) <= set(variants) and len(set(pick.values())) >= 2, pick
# shared: one material per variant, however many objects use it
mats_a = {pmat(o) for o in row_a}
assert len(mats_a) == len(set(pick.values())), mats_a
for o in row_a:
    assert o.material_slots[0].link == "OBJECT"  # instances keep their own variant
# deterministic per object name + seed
bpy.ops.pigment.link()
assert {o.name: pmat(o).get("pigment_folder") for o in row_a} == pick
# re-roll changes at least one pick
core.reroll_variants(row_a)
rerolled = {o.name: pmat(o).get("pigment_folder") for o in row_a}
assert rerolled != pick
bpy.ops.pigment.link()  # back to seed 7 picks
assert {o.name: pmat(o).get("pigment_folder") for o in row_a} == pick

# building_c: plain asset path (folder 'building_c' doesn't exist; variants are its siblings)
step("building_c variants from the plain asset path")
S.source = os.path.join(TEX, "building_c__steel")
bpy.ops.pigment.import_mesh()
bc = [o for o in bpy.data.objects if o.type == "MESH" and o not in row_a][0]
dims_c = bc.dimensions.copy()
row_c = [bc]
for i in range(1, 5):
    o = bc.copy()
    scene.collection.objects.link(o)
    row_c.append(o)
Wc = max(dims_c.x, dims_c.y) + 4.0
for i, o in enumerate(row_c):
    o.location = (i * Wc - 2 * Wc, -14.0, 0)
select(row_c)
S.source = os.path.join(TEX, "building_c")
S.seed = 2
bpy.ops.pigment.link()
pick_c = {o.name: os.path.basename(pmat(o)["pigment_folder"]) for o in row_c}
print("building_c picks:", pick_c)
assert set(pick_c.values()) == {"building_c__rust", "building_c__steel"}, pick_c

# ------------------------------------------------------------------ 3. maps
step("every map: separate maps, ORM + DirectX normal, emission driver, bump / displacement")


def has_link(m, from_pred, to_type, to_name):
    return any(from_pred(l.from_node) and l.to_node.bl_idname == to_type and to_name in (l.to_socket.name, l.to_socket.identifier)
               for l in m.node_tree.links)


P = "ShaderNodeBsdfPrincipled"
lab = lambda s: (lambda n: n.label == s)
typ = lambda s: (lambda n: n.bl_idname == s)
m = pmat(row_a[0])
for to in ("Metallic", "Roughness", "Emission Color"):
    assert any(l.to_node.bl_idname == P and l.to_socket.name == to for l in m.node_tree.links), to
assert has_link(m, lab("AO Multiply"), P, "Base Color")
assert has_link(m, typ("ShaderNodeBump"), P, "Normal")
assert has_link(m, typ("ShaderNodeNormalMap"), "ShaderNodeBump", "Normal")
assert has_link(m, lab("Pigment Height"), "ShaderNodeBump", "Height")
assert m.displacement_method == "BUMP"
assert set(m["pigment_channels"].split(",")) == {"base_color", "roughness", "metallic", "ao", "normal", "height", "emissive"}

# emission strength is driven by the exported emissive_scale x multiplier
bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
scale = core.discover(m["pigment_folder"])["emissive_scale"]
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
dg.update()
ev = m.evaluated_get(dg)
ebsdf = next(n for n in ev.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
print("emissive_scale", scale, "strength", ebsdf.inputs["Emission Strength"].default_value)
assert abs(ebsdf.inputs["Emission Strength"].default_value - scale) < 1e-4
fc = m.node_tree.animation_data.drivers[0]
assert fc.driver.is_valid and fc.driver.is_simple_expression
m["pigment_emission_mult"] = 2.0
m.update_tag()  # what a UI edit does
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
ev = m.evaluated_get(dg)
v = next(n for n in ev.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Emission Strength"].default_value
print("x2 multiplier ->", v)
assert abs(v - 2 * scale) < 1e-4, v
m["pigment_emission_mult"] = 1.0

# ORM + DirectX normal from the unreal preset (with the sidecar)
cube_mesh = bpy.data.meshes.new("probe")
import bmesh
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bm.to_mesh(cube_mesh)
bm.free()
cube_mesh.uv_layers.new(name="UVMap")
probe = bpy.data.objects.new("probe", cube_mesh)
scene.collection.objects.link(probe)
probe.location = (0, 0, -50)
core.link_objects([probe], os.path.join(TEX, "building_c_unreal"))
mu = pmat(probe)
orm = next(n for n in mu.node_tree.nodes if n.type == "TEX_IMAGE" and "OcclusionRoughnessMetallic" in n.image.filepath)
split = [l.to_node for l in mu.node_tree.links if l.from_node == orm and l.to_node.bl_idname == "ShaderNodeSeparateColor"][0]
routes = {(l.from_socket.name, l.to_node.bl_idname, l.to_socket.name) for l in mu.node_tree.links if l.from_node == split}
print("ORM split ->", sorted(routes))
assert ("Green", P, "Roughness") in routes and ("Blue", P, "Metallic") in routes and ("Red", "ShaderNodeMix", "B") in {(a, b, c[:1]) for a, b, c in routes}
assert any(n.label == "DirectX to OpenGL normal" for n in mu.node_tree.nodes)
assert has_link(mu, typ("ShaderNodeCombineColor"), "ShaderNodeNormalMap", "Color")
# same pixels without a sidecar (suffix detection)
nosc = os.path.join(TMP, "unreal_nosidecar")
shutil.copytree(os.path.join(TEX, "building_c_unreal"), nosc)
os.remove(os.path.join(nosc, "material.json"))
sp = core.discover(nosc)
assert sp["normal_convention"] == "directx" and sp["sidecar"] is None, sp
assert any(m_["sources"] == ["ao", "roughness", "metallic"] for m_ in sp["maps"])

# displacement mode via the panel's Rebuild on a shared material
select([probe])
S.height_mode = "DISPLACEMENT"
S.add_subdivision = True
bpy.ops.pigment.rebuild()
assert mu.displacement_method == "BOTH"
assert has_link(mu, typ("ShaderNodeDisplacement"), "ShaderNodeOutputMaterial", "Displacement")
assert has_link(mu, lab("Pigment Height"), "ShaderNodeDisplacement", "Height")
assert not any(n.bl_idname == "ShaderNodeBump" for n in mu.node_tree.nodes)
mod = probe.modifiers.get("Pigment Displacement")
assert mod is not None and mod.use_adaptive_subdivision
S.height_mode = "NONE"
bpy.ops.pigment.rebuild()
assert not any(n.label == "Pigment Height" for n in mu.node_tree.nodes)
S.height_mode = "BUMP"
bpy.data.objects.remove(probe, do_unlink=True)

# ------------------------------------------------------------------ 4. live reload
step("live reload after a Pigment re-export")
live = os.path.join(TMP, "live", "building_a")
shutil.copytree(os.path.join(TEX, "building_a__warm"), live)
lo = bld.copy()
scene.collection.objects.link(lo)
lo.name = "LiveBuilding"
lo.location = (0, 60, 0)
S.use_variants = False
core.link_objects([lo], live)
lm = pmat(lo)
assert lm["pigment_folder"] == os.path.normpath(live)


def img_mean(mat, label):
    n = next(n for n in mat.node_tree.nodes if n.label == label)
    px = np.empty(len(n.image.pixels), np.float32)
    n.image.pixels.foreach_get(px)
    return px.reshape(-1, 4)[:, :3].mean(axis=0)


assert core.check_reload() == {"reloaded": [], "rebuilt": [], "exporting": []}
before = img_mean(lm, "Pigment BaseColor")
scale_before = lm["pigment_emissive_scale"]


def render_live(path):
    sc = bpy.context.scene
    keep = (sc.camera, sc.render.resolution_x, sc.render.resolution_y, sc.render.filepath)
    cam = bpy.data.objects.new("LiveCam", bpy.data.cameras.new("LiveCam"))
    sc.collection.objects.link(cam)
    d = lo.dimensions
    cam.location = (lo.location.x + d.x * 0.9, lo.location.y + d.y * 2.6 + 4, d.z * 0.55)
    look = lo.location.copy()
    look.z = d.z * 0.45
    cam.rotation_euler = (look - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 28
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = 480, 640
    sc.render.filepath = path
    hidden = [o for o in sc.objects if o.type == "MESH" and o != lo and o.name != "Ground" and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    bpy.ops.render.render(write_still=True)
    for o in hidden:
        o.hide_render = False
    sc.camera, sc.render.resolution_x, sc.render.resolution_y, sc.render.filepath = keep
    bpy.data.objects.remove(cam, do_unlink=True)


def setup_render(samples):
    sc = bpy.context.scene
    try:
        sc.render.engine = "CYCLES"
    except TypeError as e:
        print("no Cycles:", e)
    try:
        cp = bpy.context.preferences.addons["cycles"].preferences
        cp.compute_device_type = "OPTIX"
        cp.get_devices()
        for d in cp.devices:
            d.use = True
        sc.cycles.device = "GPU"
    except Exception as e:
        print("GPU setup failed, CPU render:", e)
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Punchy" if "AgX - Punchy" in [i.identifier for i in bpy.types.ColorManagedViewSettings.bl_rna.properties["look"].enum_items] else "None"
    sc.view_settings.exposure = 0.3


# night lighting + ground for every render
world = bpy.data.worlds.new("Night")
scene.world = world
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (0.012, 0.018, 0.045, 1)
bg.inputs["Strength"].default_value = 1.0
moon = bpy.data.objects.new("Moon", bpy.data.lights.new("Moon", "SUN"))
moon.data.energy = 0.6
moon.data.color = (0.6, 0.7, 1.0)
moon.rotation_euler = (math.radians(55), 0, math.radians(-35))
scene.collection.objects.link(moon)
bpy.ops.mesh.primitive_plane_add(size=600, location=(0, 0, 0))
ground = bpy.context.active_object
ground.name = "Ground"
gm = bpy.data.materials.new("Wet asphalt")
gb = next(n for n in gm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
gb.inputs["Base Color"].default_value = (0.02, 0.02, 0.025, 1)
gb.inputs["Roughness"].default_value = 0.18
ground.data.materials.append(gm)
for i, (x, col) in enumerate(((-20, (1.0, 0.25, 0.7)), (0, (0.3, 0.8, 1.0)), (20, (1.0, 0.6, 0.3)))):
    L = bpy.data.objects.new(f"Street{i}", bpy.data.lights.new(f"Street{i}", "POINT"))
    L.data.energy = 2500
    L.data.color = col
    L.data.shadow_soft_size = 0.5
    L.location = (x, 0, 7)
    scene.collection.objects.link(L)
setup_render(16 if QUICK else 48)
REL_A = os.path.join(TMP, "reload_before.png")
REL_B = os.path.join(TMP, "reload_after.png")
render_live(REL_A)

# Re-export from Pigment into the linked folder: concrete turns red, the warm
# windows become brighter green (emissive_scale changes -> sidecar changes)
assert EXE, "pigment-mcp not built"
script = os.path.join(TMP, "reexport.jsonl")
with open(script, "w") as f:
    for line in (
        {"tool": "open_project", "args": {"path": os.path.join(REPO, "scenes/town/projects/building_a.pigment")}},
        {"tool": "update_layer", "args": {"layer": "Base", "values": {"base_color": [0.62, 0.12, 0.1]}}},
        {"tool": "update_layer", "args": {"layer": "Lit windows (warm)", "values": {"base_color": [0.3, 1.0, 0.4], "emissive": [0.3, 1.0, 0.4], "emissive_strength": 9.0}}},
        {"tool": "send_to_blender", "args": {"dir": live, "name": "building_a", "mesh": False}},
    ):
        f.write(json.dumps(line) + "\n")
r = subprocess.run([EXE, "--script", script], capture_output=True, text=True)
assert r.returncode == 0, r.stderr[-2000:]
res = addon._tick()  # what the auto-reload timer runs
assert abs(res - S.interval) < 1e-6
rep = core.last_report
print("timer tick:", rep)
assert lm.name in rep["rebuilt"], rep  # sidecar changed -> rebuilt in place
after = img_mean(lm, "Pigment BaseColor")
print("BaseColor mean before", before, "after", after, "| emissive_scale", scale_before, "->", lm["pigment_emissive_scale"])
assert after[0] - after[2] > before[0] - before[2] + 0.05, (before, after)  # redder
assert lm["pigment_emissive_scale"] > scale_before
assert pmat(lo) is lm  # same material object, updated in place
render_live(REL_B)

# only a PNG changes (no sidecar change): the image is reloaded in place
step("in-place image reload on a changed PNG")
assert core.check_reload() == {"reloaded": [], "rebuilt": [], "exporting": []}
rough = os.path.join(live, "building_a_Roughness.png")
img = bpy.data.images.load(rough, check_existing=False)
img.name = "scratch"
core.set_colorspace(img, False)
px = np.empty(len(img.pixels), np.float32)
img.pixels.foreach_get(px)
px[:] = 0.9
px[3::4] = 1.0
img.pixels.foreach_set(px)
img.filepath_raw = rough
img.file_format = "PNG"
img.save()
bpy.data.images.remove(img)
os.utime(rough, (time.time() + 5, time.time() + 5))
r = core.check_reload()
print("png touch:", r)
assert r["rebuilt"] == [] and any("Roughness" in n for n in r["reloaded"]), r
rn = next(n for n in lm.node_tree.nodes if n.label == "Pigment Roughness")
v = np.empty(len(rn.image.pixels), np.float32)
rn.image.pixels.foreach_get(v)
assert abs(v[0::4].mean() - 0.9) < 0.02, v[0::4].mean()

# ------------------------------------------------------------------ 5. project link
step("link a .pigment project (export via pigment-mcp) and watch it")
proj = os.path.join(TMP, "projects", "crate.pigment")
with open(os.path.join(TMP, "mkproj.jsonl"), "w") as f:
    for line in (
        {"tool": "new_project", "args": {"mesh": os.path.join(REPO, "assets/ammo_box.glb"), "resolution": 512, "smart_material": "Hazard stripes"}},
        {"tool": "save_project", "args": {"path": proj}},
    ):
        f.write(json.dumps(line) + "\n")
r = subprocess.run([EXE, "--script", os.path.join(TMP, "mkproj.jsonl")], capture_output=True, text=True)
assert r.returncode == 0, r.stderr[-2000:]
cr = bpy.data.objects.new("Crate", cube_mesh.copy())
scene.collection.objects.link(cr)
cr.location = (0, 0, -50)
S.source = proj
select([cr])
assert bpy.ops.pigment.link() == {"FINISHED"}
cm = pmat(cr)
exp_dir = core.project_export_dir(proj)
print("project exported to", exp_dir, os.listdir(exp_dir))
assert os.path.normpath(cm["pigment_folder"]) == os.path.normpath(exp_dir)
assert os.path.normpath(cm["pigment_project"]) == os.path.normpath(proj)
assert os.path.isfile(os.path.join(exp_dir, "ammo_box.glb"))
# project saved again -> watch re-exports in the background, next tick rebuilds
time.sleep(1.1)
os.utime(os.path.join(proj, "project.json"))
r = core.check_reload(watch_projects=True)
assert r["exporting"], r
job = next(iter(core._jobs.values()))
job.wait(timeout=300)
r = core.check_reload(watch_projects=True)
print("after project re-export:", r)
assert cm.name in r["rebuilt"], r
bpy.data.objects.remove(cr, do_unlink=True)

# ------------------------------------------------------------------ 6. renders
step("render the street")
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
scene.collection.objects.link(cam)
cam.data.lens = 22
cam.location = (-3 * W - 6, -2.0, 2.2)
target = cam.location.copy()
target.x += 40
target.z = 7.5
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
lo.hide_render = True
scene.render.resolution_x, scene.render.resolution_y = (800, 450) if QUICK else (1600, 900)
scene.render.filepath = os.path.join(OUT, "bridge_town.png")
setup_render(32 if QUICK else 128)
bpy.ops.render.render(write_still=True)
print("RENDERED", scene.render.filepath)

# reload before/after side by side
a = bpy.data.images.load(REL_A)
b = bpy.data.images.load(REL_B)
w, h = a.size
pa = np.empty(w * h * 4, np.float32)
pb = np.empty(w * h * 4, np.float32)
a.pixels.foreach_get(pa)
b.pixels.foreach_get(pb)
gap = 8
both = np.ones((h, 2 * w + gap, 4), np.float32)
both[:, :w] = pa.reshape(h, w, 4)
both[:, w + gap:] = pb.reshape(h, w, 4)
out = bpy.data.images.new("reload_ab", 2 * w + gap, h, alpha=False)
out.pixels.foreach_set(both.ravel())
out.filepath_raw = os.path.join(OUT, "bridge_reload.png")
out.file_format = "PNG"
out.save()
print("SAVED", out.filepath_raw)
print(f"\nALL BRIDGE TESTS PASSED in {time.time() - t_start:.0f}s")
sys.stdout.flush()
