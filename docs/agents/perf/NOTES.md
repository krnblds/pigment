# perf: the open world in Godot at 120+ fps

The open world (`--map=world`, the default) ran at about 50–70 fps with 1 % lows near 30. It now
runs at 180–200 fps while driving, and 250–350 fps at the fixed views. The look is kept: night neon,
fog, rain, wet roads and traffic. The wet roads now reflect, too (see "Look changes").

| | |
|---|---|
| `avenue_before_after.png` | Downtown avenue at street level (left: before, right: after) |
| `bridge_before_after.png` | Tenjin arch bridge deck, looking at the skyline. Far buildings are now proxies with lit windows |
| `lookout_before_after.png` | Summit lookout, looking at the skyline (40° FOV) |

## Before / after

Setup: RTX 4070 Ti at 1920×1080, vsync off, the fresh export (road obstacles removed, 12:30), and
default traffic (adaptive, 24–80 cars). "Before" is master 02783e9's `town_loader.gd`,
`traffic_car.gd` and `traffic_manager.gd`, run with the same bench code.

**Spots** come from `--bench-spots=<dir>`: 5 s per spot, then 30 s of autopilot. Measuring starts
once 60 frames in a row took under 25 ms.

| | avg fps | 1 % low | min | draw calls | primitives | VRAM |
|---|---|---|---|---|---|---|
| downtown avenue, before | 75.4 | 28.3 | 24.5 | 6,429 | 15.75 M | 2.50 GB |
| downtown avenue, **after** | **256.3** | **130.2** | 76.5 | 998 | 3.61 M | 2.58 GB |
| arch bridge → skyline, before | 29.0 | 20.8 | 19.9 | 15,104 | 44.76 M | 2.50 GB |
| arch bridge → skyline, **after** | **325.6** | **172.2** | 47.5 | 1,177 | 1.65 M | 2.58 GB |
| mountain lookout → skyline, before | 52.3 | 34.5 | 29.0 | 9,374 | 23.09 M | 2.50 GB |
| mountain lookout → skyline, **after** | **346.5** | **187.9** | 56.2 | 948 | 1.23 M | 2.58 GB |
| autopilot drive 30 s, before | 86.9 | 45.5 | 36.8 | 4,610 | 12.57 M | 2.50 GB |
| autopilot drive 30 s, **after** | **182.2** | **86.5** | 36.6 | 1,076 | 3.27 M | 2.58 GB |

**`--bench=20`**, the same run as the original 50.8 fps number. Two runs each, alternating:

| | avg fps | 1 % low | min | draw calls | primitives |
|---|---|---|---|---|---|
| before | 61.6 / 68.7 | 31.4 / 39.8 | 26.7 / 27.5 | 5,780 | 14.7 M |
| **after** | **206.4 / 178.2** | **93.1 / 80.8** | 44.5 / 43.0 | 1,060 | 3.2 M |

Where the frame goes (avenue spot):

| | before | after |
|---|---|---|
| render-thread CPU | 8.3 ms | 1.6 ms |
| GPU | 5.3 ms | 2.6 ms |
| drawn objects | 8,391 | 2,960 |

At the bridge, before was 20.7 ms CPU, 10.4 ms GPU and 18.5k objects.

**Load time**

| | before | after |
|---|---|---|
| `town_loader` load | 9.9 s | 2.7 s |
| engine start → end of `main._ready` | 13.4 s | 6.2 s |
| engine start → steady frames (`settled_ms`) | 22.6 s | 9.5 s |
| headless load (tests) | 7.5 s | 0.9 s |

**Hitches:** one frame over 25 ms (27 ms) in the 30 s drive. Startup is not counted.

**VRAM** stays at about 2.5 GB. It is mostly textures, and I didn't change them.

Notes on reading the numbers:
- The drive numbers depend on traffic. The adaptive count grows towards 80 cars when fps > 110 and
  shrinks below 72, so the game spends spare frame time on cars.
- Before, the bench never settled: frames over 25 ms kept coming, and the drive measured fewer cars.
- The GPU is shared with other agents' work; run-to-run noise is about ±15 %.

## What was done (all in `game/scripts/`)

### `town_loader.gd`: rewritten as a streamed loader (same API)

Each (mesh, material set) group gets a policy (`_policy`):

| policy | what | applies to |
|---|---|---|
| `cell` | MultiMesh per 64 m cell with a visibility range, streamed in and out around the camera | props (150 m; they had no range before), signs 220, lamps / poles 260, footings 260 |
| `heavy` | Detailed buildings (kit, 47k tris each) as streamed 64 m MultiMesh cells, plus a **far proxy** per 256 m region (HLOD) | kit buildings |
| `region` | One MultiMesh per 256 m region, no range | repeated small meshes: containers, trees, footing boxes, cranes |
| `merge` | Merged per 256 m region and material into one mesh, on worker threads | unique or rare small meshes: roads, junctions, decals (range 150 m + region), towers, landmarks, warehouses, sea walls. 419 roads (1,669 draws) become about 60 meshes |
| `single` | As before | terrain chunks (auto LOD), bridges, water, wires |

More on `heavy`:
- The proxy is one box per building, sized to its bounds, with `proxy_building.gdshader`: a dark wet
  facade and a hashed grid of lit windows, seeded per building through `INSTANCE_CUSTOM`.
- The proxy is the detailed cells' `visibility_parent`. A region shows its detailed buildings while its
  centre is within 330 m (`PROXY_NEAR`), and its proxies beyond that.
- At that distance the depth fog is at about 85 %, so only the silhouette and the window glow read.
  The skyline now glows instead of being black.

Other loader changes:
- **Meshes are dressed in place.** The old `mesh.duplicate()` per group was a GPU read-back plus a
  second upload of every building mesh.
- **Merge and collision geometry come from the glbs directly.** `GLTFDocument` parses them on worker
  threads at about 0.4 ms a file, with no GPU round trip. If a glb is missing (an exported build),
  the loader falls back to `surface_get_arrays`.
- **Streaming.**
  - Visual cells, collision and lights are created from a queue with a 2.5 ms per-frame budget, one
    MultiMesh or collision cell per item.
  - Collision follows `collision_focus` (the car) within 300 m. That covers the traffic ring of up
    to 290 m.
  - A jump of more than 30 m in one tick (a reset or teleport) streams the collision in at once.
  - `stream_now(p)` streams everything around `p` synchronously; automation uses it for camera spots.
  - `ensure_collision(p)` builds collision on demand. Traffic uses it to place parked cars anywhere.
- **Collision.**
  - All collision goes into 64 m cells: one StaticBody of boxes and cylinders, and one trimesh body
    per category. The trimesh body holds that category's triangles cut up by centroid, and is named
    `Col_<a mesh of that category>` so ray hits still map to `layout.meshes[...].cat`, which the
    traffic test relies on.
  - Before, a 1.6 km viaduct trimesh took about 40 ms to build on the main thread.
  - Terrain uses `HeightMapShape3D` from `heightfield.f32` (rows flipped: Godot +z is Blender −y).
  - The faces and heights are prepared on worker threads.
  - Before: 17,310 shapes, always present. After: about 1,700 shapes live.
- **Lights.** 1,736 OmniLights become about 16–25 live. A light exists only within its fade distance
  plus 15 m, so the visible lighting is the same.
- **Image materials are opaque unless the texture really has alpha** (`Texture2D.has_alpha()`).
  - The export flags every image `"alpha": true`, so roads, terrain, facades and concrete were
    rendered in the alpha pass.
  - Alpha-pass objects get no depth pre-pass, and no SSR or SSAO.
  - The decal atlas and one billboard keep alpha.

### Traffic (small, local changes; the traffic workstream owns the rest)

- `traffic_car.gd` `update_lods(cam_dist)`:
  - Only the LODs whose visibility range is near the camera distance stay in the tree. The others
    are detached, and are freed on `PREDELETE`.
  - About 60 nodes per car were re-transformed every tick before. Scene nodes went from 18.4k to
    15.0k. Drive fps with 60 cars rose from 108 to about 135, before the other fixes.
- `traffic_car.gd` collision layers (`_update_layers`, run from the `mode` setter and `set_collision`):
  - A car without collision (far from the player) is on no layer and has no mask.
  - Lane followers and parked cars never mask the world (layer 1); only `DYNAMIC` (knocked) cars do.
  - Jolt had been pairing these kinematic and static bodies with the road and terrain shapes.
- `traffic_manager.gd`:
  - calls `update_lods` from housekeeping and `_place`;
  - calls `town.ensure_collision(c)` before each parked-car ray test.
- The traffic AI itself (about 1.4 ms per physics tick with 60 cars) is unchanged. It is now the
  largest per-frame cost while driving (physics frame about 4 ms with traffic, 0.5 ms without). Next
  steps for its owner:
  - fewer `_pose` writes for far cars;
  - fewer pedestrian MultiMesh writes;
  - the signals tick, about 0.5 ms with 0 cars.

### Tooling (`automation.gd`, `main.gd`)

- **`BENCH`** now also has:
  - `render_cpu_ms` and `gpu_ms` (viewport measured render time);
  - `physics_ms`, `objects`, `nodes`.
- **`--bench-spots=<dir>`** `[--spot-secs=5] [--drive-secs=20]`:
  - avenue / bridge / lookout from `world.json`, then the autopilot drive;
  - writes `spot_*.png` and `spots.json` (with the load stats, `startup_ms` and `settled_ms`).
- **`--bench-matrix --spot=<name>`**: the effect matrix at a spot.
  - New lines: `traffic_hidden_paused`, `town_lights_hidden`, `+no_sdfgi`, `+no_visuals`.
  - `--probe-traffic` adds the traffic body probes.
  - `--bench-matrix` now actually starts the automation; before, it fell through.
- **`--bench-prof`**:
  - hitch log (frames over 25 ms, with the stream queue size);
  - physics frame split into scripts and server step;
  - traffic µs per tick and node counts.
- Benches wait for steady frames (`_settle`) before measuring.
- `main.stream_now(p)`; `town.collision_focus = car`.

**Effect costs at the avenue spot** (`--bench-matrix`, after the changes):
- SDFGI about 0.8 ms GPU;
- SSR + SSAO about 0.4 ms;
- volumetric fog about 0.3 ms;
- lamp shadows: none active (see below).

All kept as they were.

## Look changes (intended, small)

- **Wet roads reflect.** Roads are now opaque, so SSR and SSAO apply to them as on the town map.
- **Distant kit buildings are boxes with lit windows**, beyond about 330–500 m. They used to be
  black, fully detailed silhouettes.
- **Props vanish beyond 150 m.** Before, they were drawn at any distance.

## Tests

All on the fresh export.

| test | result |
|---|---|
| `--headless -- --drive-test` (world) | no rollovers or auto-resets; same as before (0–60 in 3.03 s, rest speed 0.89) |
| `--headless -- --map=town --drive-test` | same as before: 99 m, top 42 km/h. Before was 92 m, top 42 km/h; the town start is a hill |
| `--headless -- --traffic-test=60` (world) | **PASS**: all 7 checks, 0 off-road samples |
| `--headless -- --map=town --traffic-test=60` | **PASS** |

- `cargo test`: no Rust changes.
- Traffic-test caveat: the first world run failed. Off-road samples came from cars beyond the
  240 m collision radius, and the player teleport had no ground. Both are fixed: 300 m radius and
  synchronous teleport streaming.

## Regenerate / run

There are **no export changes**: any `world_layout.json` export works as is, with nothing to bake.

```
# world assets (git-ignored): tools/world/world_driver.py --stages build,export (~55 min), then
godot --headless --path game --import
godot --path game -- --bench-spots=C:/tmp/spots [--drive-secs=30] [--bench-prof]
godot --path game -- --bench=20
godot --path game -- --bench-matrix --spot=bridge
```

## Known limits / follow-ups

- **World lamps use the fallback light settings** (7 m range, no shadows). The world export names
  lamp kinds `Light_lamp` / `Light_alley`, but the loader matches `LampLight` / `AlleyLight`. This
  was true before too, and I kept it so the look stays the same. Matching both kinds would give the
  town's 20 m lamps with fog cones and 3 shadowed lamps. That is a look decision, not a perf one:
  the light streaming already handles it.
- **Far lanes are not snapped.** Traffic snaps lanes to the ground once, at setup, so lanes far from
  the spawn keep their `world.json` heights. Those are the road surface, within centimetres.
- **Kit building variants** are still one MultiMesh per variant per cell. Texture arrays plus
  `INSTANCE_CUSTOM` would cut the near draws further. They weren't needed for the target.
- **Export speed** is untouched: one glb per mesh, about 55 min. Batching would need a layout format
  change, `file#node`. Note that the loader already parses unique meshes straight from the glbs.
- **Startup** still spends about 2 s in traffic setup (lane graph, vehicle library) and about 3 s in
  first-frame pipeline compilation.
- `PowerLines`, a single 504k-triangle mesh, is still one instance with a 200 m centre-based range.

## Merge notes

- `town_loader.gd` is a rewrite with the same public API:
  - unchanged: `load_town`, `layout`, `road_points`, `bounds`, `lamp_lights`, `stats`,
    `nearest_road`, `road_polylines`, `spawn_transform`, `car_transform`, `material()`;
  - new: `stream_now`, `ensure_collision`, `collision_focus`.
  - Other branches that edit the old loader will conflict. Re-apply their changes to the policy
    functions.
- The collision node layout changed: `TownCollision` / `TrimeshCollision` are now
  `Collision/ColCell/{Shapes, Col_<mesh>}`. Ray hits still give `Col_<mesh>` names.
- Changes to traffic files are additive:
  - `traffic_car.gd`: `mode` setter, `_update_layers`, `update_lods`, `_notification`;
  - `traffic_manager.gd`: 3 call sites.
- New files: `game/scripts/proxy_building.gdshader` (+ `.uid`).
