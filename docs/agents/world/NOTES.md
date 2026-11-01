# world: open-world map generator (workstream `world`)

The town was one 400 m hillside neighbourhood. `tools/world/` now generates a 4 x 4 km bay from a
seed and a config. It has four islands joined by three kinds of bridge, a city expressway on a
viaduct, a road hierarchy with multi-lane junctions and signals, and a mountain with a switchback
road up to a lookout. Each district is dressed with the town kit, procedural towers, the port kit
and the street-props kit. The output is data plus reusable meshes: `world.json`, a heightfield,
and mesh glbs for Godot.

| | |
|---|---|
| `aerial.png` | Dusk, from over the bay: downtown towers, the mountain, the arch bridge to the corporate island |
| `bridge.png` | Night, from the water: the cable-stayed Bay Expressway bridge (LED stays) and the port cranes |
| `mountain.png` | Dusk, from the switchback road below the summit: the guard rail, the hairpin below, downtown and the port |
| `avenue.png` | Night, at street level on a downtown avenue (4 lanes, wet asphalt, towers with lit windows, props) |
| `map.png` | Top-down map from `world.json`: hillshade, roads by class, signalised junctions (red), pylons, footprints, containers, spawn |
| `verify.json` | Output of the `--verify` stage, reproduced below |

All four renders are Cycles, 1600 x 900, 128 samples, denoised. Each takes 20-110 s on a shared RTX 4070 Ti.

## Regenerate

```
cargo build --release -j 6 --bin pigment-mcp            # only for the textures below
python tools/road_textures.py --run                     # road tiles / trim / atlas (existing)
python tools/town_textures.py world                     # NEW: world sheets -> scenes/town/textures/world/
blender -b --factory-startup --python tools/world/world_driver.py -- --stages gen,build,verify,render
blender -b --factory-startup --python tools/world/world_driver.py -- --stages build,save --region preview
blender -b --factory-startup --python tools/world/world_driver.py -- --stages build,export   # -> game/assets/world/
python tools/world/world_map.py --out docs/agents/world/map.png
```

- The `gen` stage takes about 35 s and `build` about 3 min. `verify` takes about 30 s, and the full
  `render` run about 3 min.
- The export writes one glb per mesh key: 1,194 glbs plus 234 terrain LODs, 285 MB. It takes about 55 min,
  because Blender's glTF exporter costs about 2.5 s per file.
- Driver options:
  - `--config FILE` (default `tools/world/world_config.json`)
  - `--seed N`
  - `--out scenes/world`
  - `--region x0,y0,x1,y1` or `preview`
  - `--samples`, `--res`, `--shots aerial,bridge,mountain,avenue,top`
  - `--day` (flat debug light), `--cpu`, `--render-dir`
  - `--no-trees`, `--no-lights`
  - `--export-dir`
- Outputs:
  - `scenes/world/world.json` (committed);
  - `heightfield.f32` and `masks_urban.npy` (git-ignored, regenerated);
  - `world_preview.blend` (git-ignored, about 0.6 km^2 of downtown and the expressway; build it with
    `--region preview`).
- The textures folder is git-ignored. In a worktree, junction-link `scenes/town/textures` to the
  main checkout (I did).
- The build is deterministic for a given seed and config: no Python `hash()`, and the RNGs are
  seeded.

## What it builds (tools/world/)

| file | role |
|---|---|
| `world_config.json` | Size, seed, islands, road classes, grade limits, district grids, districts, links (bridges and expressway), mountain road, props, preview region |
| `terrain.py` | numpy only. Seeded Perlin, fbm, ridged multifractal, domain warp. Island shapes (superellipse plus coast noise; quay islands drop steeply to the sea, others have beaches). Mountains along a ridge polyline. Thermal erosion, then stream-power erosion (D8 flow accumulation), then thermal again, on an 8 m grid. Upsampled to 2 m with detail noise. `Heightfield.sample_tri` matches the mesh triangulation exactly |
| `network.py` | Grids per island: warped, avenue every n-th line, random street drops that keep it connected, coast margin and slope limits. Links pick a grid node with a free arm angle (at least 52 degrees from the others). Dead ends are pruned and straight degree-2 nodes merged. Junctions use `blender_town.Junction` with per-arm widths. The vertical profile is a Lipschitz fit. Crossings and transitions are handled here too (see below) |
| `world_gen.py` | The data stage: urban flattening, cut/fill to the roads, decks and structures, sea walls (marching squares), lane graph, signals, placement. Writes `world.json` |
| `placement.py` | Kit buildings (the town's frontage rows plus back rows) per district, procedural towers, the port, lamps, poles and wires, the props kit scatter, signals, trees |
| `world_meshes.py` | Procedural meshes and materials: terrain chunks, water, towers (setback tiers, crowns, story billboards), warehouses, containers, STS cranes, light masts, fallback signal poles, trees; facade, terrain and painted materials |
| `world_build.py` | `world.json` to a Blender scene, in collections (below). It also snaps terrain and instances to the built surfaces |
| `world_verify.py`, `world_render.py`, `world_export.py`, `world_map.py`, `world_driver.py` | Checks, proof shots, Godot export, map, command line |

### Geography (seed 2077)

The world is 4096 m square, the sea floor is at -26 m, and there is 4.85 km^2 of land.

- **Shinkai**: the central city island, 2.4 x 1.9 km.
  - Downtown, midtown and old town are a 150 x 125 m grid rotated 8 degrees, with avenues on every
    third line.
  - The NW outskirts are mountains, eroded, up to 268 m.
  - The southern shore is a beach; urban shores have sea walls.
- **Minato port**: rectangular reclaimed land (superellipse p=7) with quay walls all round.
  - 41 gantry cranes along the quays.
  - 3,131 containers in stacked yards.
  - 68 corrugated warehouses and 89 light masts.
- **Kagero hills**: rolling hills to about 60 m, with a strongly warped 130 m grid of streets that
  follow the terrain.
- **Tenjin corporate island**: the HOSHIKAWA HQ (310 m) and MERIDIAN spire (265 m) landmarks, 51
  corporate towers and building_c corporate variants. Quay walls.

### Road hierarchy

Road classes are in `world_config.json` `classes`. All use the open-world road system
(`town_roads.build_run`): continuous world-planar asphalt UVs, the shared Pigment
asphalt/paving/trim/concrete materials, and atlas decals.

| class | carriageway | total | lanes | sides | speed |
|---|---|---|---|---|---|
| street | 10 m | 16 m | 1+1 and a parking lane each side | curb + 3 m sidewalk | 40 |
| avenue | 13.6 m | 19.6 m | 2+2 | curb + sidewalk | 60 |
| highway_urban | 22 m | 28 m | 2+2 + 3 m painted median | curb + sidewalk (the 45 m lead-in at junctions) | 60 |
| highway | 22 m | 23 m | 2+2 + 0.8 m concrete median barrier, shoulders | jersey barriers | 100 |
| mountain | 10 m | 12.2 m | 1+1 | verge + W-beam guard rail on posts | 50 |

- **Markings follow the lanes.**
  - Streets: centre dash and parking lines.
  - Avenues: double solid centre, lane dashes and edge lines.
  - Highways: median edges, lane dashes with a 9 m gap, and edge lines.
  - Mountain road: double solid centre and edge lines.
  - Every driving lane gets an arrow before a junction.
  - Wear decals (cracks, patches, oil, skids) are scaled per class. Manholes and drains are placed
    only on curbed roads.
- **Junctions** use `blender_town.Junction`, which now takes per-arm half widths:
  - avenue x street and highway_urban x avenue corners are filleted (9 m concave, 4 m convex);
  - each arm mouth gets a zebra across the whole mouth;
  - the stop line spans the incoming carriageway (left-hand traffic).
- **Signals**: every junction with 3 or more arms and an avenue or wider arm is signalised: 73
  junctions, 265 approaches.
  - Each approach gets a `traffic_light_mast` from the props kit. The pole stands on the kerb
    corner, the arm spans the incoming lanes and the heads face the traffic.
  - Every crosswalk end gets a `ped_signal` (530).
  - All signals are recorded in `world.json` `signals`, with their phase group A/B.
- **Profiles** (`network.lipschitz_fit`):
  - The road follows the terrain where it can.
  - It stays within its class grade limit, and the limit eases to near 0 within 16 m of a junction,
    so junctions are flat.
  - It stays above clearance requirements: water channels, and the roads the expressway crosses.
  - This is done with exact O(n) Lipschitz envelopes, then smoothed (vertical curves) and
    re-clamped.
- **Transitions**: links start as `highway_urban` (curbed) at their junctions. A transition node
  45 m out switches them to `highway` (barriers), with the same carriageway on both sides. The
  mountain road does the same: its first 35 m is `street`.
- **City expressway**: a 1.6 km viaduct crosses downtown diagonally over the grid.
  - Crossings are found by segment intersection and must clear 7.5 m. The minimum measured
    clearance is 7.46 m.
  - Grid roads that cannot be cleared near the at-grade ends are removed (1 here).
  - Piers are moved off roads and junctions.
- **Mountain road**: A* over (cell, heading) on a 10 m grid.
  - There are 16 headings and at most 45 degrees of turn per step, so hairpins have about a 12 m
    radius.
  - Slope above the target grade (8.5%) costs heavily. The grid is the terrain blurred by 30 m,
    since cut/fill takes the rest.
  - The road is 3.3 km with switchbacks and a max grade of 11.6%. It ends at the **summit lookout**:
    a round plaza (a `Plaza` with the Junction interface, built by `town_roads.build_junction`)
    with a railing.

### Bridges and structures

A sample becomes a deck where the road is more than 2.5 m above natural ground or over water. Short
gaps are closed.

| | span | form |
|---|---|---|
| Bay Expressway (city to port) | 629 m deck | **Cable-stayed**: two H pylons 96 m above the deck, 112 LED stays in two fan planes, 4 approach piers |
| City Expressway | 1,550 m | **Viaduct**: box girder on 37 hammerhead / twin-column piers, lamps on the barriers |
| Kagero Viaduct (city to hills) | 398 m | **Girder**: 3.2 m deep box girder, 8 piers |
| Tenjin Arch (city to corporate) | 554 m | **Tied arch**: two parabolic ribs, 38 hangers, an avenue deck with sidewalks |

- Approach grades are at most 5.5% (max measured 5.54%).
- Every deck has LED strips under its edges and steel railings on the barriers. Pylon tops have
  aviation lights.
- The mountain road also gets short girder viaducts where it would otherwise be a tall fill.

### Districts and dressing

| district | style | contents |
|---|---|---|
| downtown (r 420 m) | towers 70-230 m | 139 towers (10 archetypes, setback tiers, crowns: spire / halo / billboard / flat), 517 kit buildings (building_c heavy) |
| midtown (r 900 m) | dense | 2,394 kit buildings, 65 mid-rise towers |
| old town | dense | 848 kit buildings |
| hillside | hillside | 624 kit buildings on footings (up to 4 m spread) |
| port | port | cranes, containers, warehouses, masts |
| corporate | corporate | 2 landmarks, 49 towers, 74 building_c |

- **Kit buildings** reuse the town's frontage logic: a front row facing the street with 0.3-1.2 m
  gaps, 22% of gaps are alleys with an alley light, and overhead signs. Back rows fill the blocks.
  - Kit buildings use a random Pigment texture variant (`<asset>__<variant>`), never the same as the
    previous one.
  - In Blender, each variant is a **mesh copy with the variant material**, not an object-level
    override. Cycles keys geometry by material, and 4,000 overrides made 4,000 BVHs.
- **Towers** use new Pigment facade sheets from `town_textures.py world` (8 x 8 m, 4 bays x 2
  storeys): glass_blue, glass_dark, concrete_warm, panel_cyan.
  - UVs are in metres, so the tile is at true scale.
  - Night windows are procedural per pane. A hash of the 2 m x 4 m window cell and the object picks
    lit or dark and one of four interior colours, exactly where the tile's glass decals are.
  - Crown billboards use the story decals (Meridian, Score, Dreamlink, Noctis...).
- **The port** uses the Pigment corrugated tile (box-mapped, tinted per instance through the object
  colour) for warehouses and containers.
- **Terrain** uses the Pigment rock / grass / dirt / sand tiles.
  - The shader blends rock by slope (above about 35 degrees) and height (above 210-250 m), dirt
    under the rock and by noise, sand on low natural shores, and wet ground below the waterline.
  - City lots (vertex attribute `urban`) get the road concrete tile.
- **Water**: one 120 km plane at sea level. It is dark, glossy (roughness 0.035), with wave texture
  plus two noise scales in the normal. Reflections do the rest. There is also a coarse sea floor.
- **Street furniture**:
  - lamps alternate sides along every road: on the sidewalk, on the barrier top on highways and
    bridges, or behind the guard rail on the mountain road;
  - power poles with five sagging wires run along streets and the mountain road;
  - 2,136 trees (pine / broadleaf) grow on natural land.
- **Props kit** (`assets/props`, merged from master): every district is dressed through
  `tools/props/scatter.py`.
  - `placement.scatter_street_props` builds one context per district:
    - curb, walk and frontage lines along both sides of every curbed road;
    - concave junction corners, with their two curb directions;
    - crossings at every zebra end;
    - tower rooftops as rooftop areas;
    - lamps, poles and signals as blocked discs.
  - District mapping: downtown to downtown, midtown to commercial, old_town to market, hillside to
    residential, port to industrial, corporate to luxury.
  - The result is 16,926 props (bollards, bikes, meters, scooters, vending machines, bins, benches,
    bus stops, kiosks, holo pylons, street trees, palms, AC units, dishes, tanks...). Placements
    come back in Godot space and are converted (`rz = yaw`, pos `(x, -z, y)`).
  - The traffic lights are placed by `signal_instances()` rather than the generic corner rule.
- **Props hook**: `placement.scatter_props(P, edge, props, rng)` stays as a simple line scatter for
  `world_config.json` `props.extra`, for props outside the kit.

## world.json (format `pigment-world/1`)

- Coordinates are Blender world space in metres: x east, y north, z up. Godot is `(x, z, -y)`.
- Traffic is **left-hand**. The road `points` z is the **road surface** (path level + 0.2).

```
format, name, seed, units, up, coords, traffic: "left-hand", size_m, sea_level
terrain: {heightfield: "heightfield.f32" (float32 LE, row-major [iy][ix]), n: 2049, cell_m: 2, origin: [-2048, -2048],
          chunk_m: 256, chunk_cells: 128, lod_cells_m: [2, 8, 32], sea_floor_m,
          chunks: [{id: "t<ix>_<iy>", ix, iy, origin, size_m, zmin, zmax, land}]}        # open-sea chunks omitted
islands: [{name, kind, center, radius, rotation}]
districts: [{name, island, style, center, radius, counts}]
road_classes: {class: {half, side, median, speed_kmh, lanes: [...], markings: [[y, solid|dash]], ...}}
roads: [{id: "r12", class, name, kind: grid|link|mountain,
         start: {node: "n4", arm: 2}, end: {node, arm},              # arm = index in that junction's arms
         length, half_width, width (curb to curb + sidewalks), carriageway, side, median, speed_kmh,
         one_way, lanes_per_dir: {forward, backward},
         lanes: [{id, offset (m, + = left of the centreline direction), dir (+1 along points, -1 against), width, kind: drive|parking}],
         max_grade, points: [[x, y, z], ...] (adaptive, dense on curves: chord error < ~2 cm),
         deck: [0|1 per point]}]                                       # 1 = bridge / viaduct deck
junctions: [{id: "n4", kind: X|T|L|multi|plaza|transition, pos: [x, y, z_surface], z (path level),
             geom: {arms_deg, halves, r_concave, r_convex, min_arm} | {plaza: {angle, R, half}},   # rebuild with blender_town.Junction / network.Plaza
             arms: [{index, angle, dir, length (centre to mouth), half_width, road, end: start|end, mouth: [x, y]}],
             roads: [{road, end}], signalised,
             connections: [{from: {road, lane}, to: {road, lane}, turn: left|straight|right, points: [[x, y, z] x 9]}],  # lane graph
             ped_signals: [{arm, pos, facing}]}]
signals: [{id, junction, arm, controls: {road, end}, pos, facing (2D, towards the approaching traffic), mast,
           phase: A|B, stop_line: [x, y], prop: traffic_light_mast, heads: ["A", "B", "C"]}]
bridges: [{name, type: cable_stayed|viaduct|girder|arch, edge (road number), s: [s0, s1] along that road, half, depth,
           piers: [{s, pos, dir, top, bottom, heavy?}], pylons: [{pos, dir, deck, top, bottom}],
           cables: [[a, b]], arches: [[[x, y, z]...]], hangers: [[a, b]]}]
sea_walls: [{points: [[x, y]], top: [z per point], bottom}]
instances: [{asset, variant, pos: [x, y, z], rot (about z, radians), scale, district, kind, footing?, file?, slot?, signal?}]
towers: [{id, mesh, tiers: [[w, d, h]...], height, crown, footprint, pos, rot, facade, district, landmark}]
wires: [{a, b, sag}]          lights: [{pos, color, energy, kind: lamp|alley|mast|aviation}]
spawn: {pos, dir, road}       metrics: {...}
```

- **Lane graph.**
  - A lane is `road.points` offset by `lane.offset` along the left normal of the point order.
  - `dir` +1 lanes travel from `start` to `end`. Under left-hand traffic they sit at positive offsets.
  - At a junction, `connections` join incoming lanes to outgoing lanes. Left turns go from the
    kerb-side lane and right turns from the centre-side lane; straight connections go lane by lane.
    Each connection has a 9-point Bezier.
  - `transition` nodes (no mesh) connect lanes straight through.
- **Signals.**
  - `controls` names the road end each signal stops.
  - `phase` A or B groups arms by axis, so A and B alternate.
  - The lamp node names (`Lamp_<head>_<Red|Amber|Green>`) are in `assets/props/index.json`.
- **Instances.**
  - `asset` is a town kit mesh (`assets/town/<asset>.glb`), a props-kit prop (`file` = its glb, so
    Godot can use the original with its driven lamp nodes), or a procedural mesh key. Procedural
    keys: `tower_*`, `landmark_*`, `warehouse_LxWxH`, `container`, `crane_sts`, `light_mast`,
    `tree_pine`, `tree_broad`, and the fallback `signal_pole*`.
  - Procedural meshes are exported as glbs by key.
  - `variant` is a Pigment texture variant, a facade style, or a paint colour.
  - Rotation: local -Y, the glTF +Z front, turns onto the facing direction.

### Godot export (`--stages build,export`, default `game/assets/world/`)

- **Format.** `world_layout.json` uses the **same format the game already loads**
  (`town_layout.json`: meshes, materials, instances with Godot `xf`, lights, roads, spawn). It is
  written by the Godot workstream's `tools/godot/export_town.py`, which I refactored into a reusable
  `export_layout(collection, out, roads, junctions, spawn, stats)`. The town export is unchanged.
- **Meshes.**
  - Shared mesh data becomes one glb: kit buildings per variant, tower archetypes, containers,
    cranes, trees, props.
  - Unique pieces are 256 m terrain chunks, roads, junctions, decals, bridges and sea walls.
  - That is 1,194 glbs for 36,941 placed instances (footings included). Never one mesh.
- **Other output.**
  - `terrain_lod/<chunk>_{8,32}m.glb` holds terrain LODs.
  - `world.json` and `heightfield.f32` are copied next to the layout.
- **Collision classes** for the new names were added to `export_town.COLLIDE`:
  - Terrain_ / Girder_ / Bridge_ / SeaWall: trimesh;
  - towers / warehouses / containers: box;
  - poles / signals / trees: cylinder;
  - decals / water: none.
- **Godot side.**
  - The loader needs a path switch (`res://assets/world/world_layout.json`).
  - For traffic, read `world.json` roads, junctions and signals.

## Verify (`--stages ...,verify`, `scenes/world/verify.json`)

| check | result |
|---|---|
| terrain above a road / junction / lookout top surface (60,000 random area-weighted samples, exact triangle heights) | **0** (worst 0 mm) |
| terrain inside a bridge girder (4,857 samples along every deck, 15 m from the abutments) | **0** |
| floating / buried props, lamps, poles, signals, masts, containers (19,058, ray cast to roads, barriers, walls, terrain) | **0 / 0** |
| buildings floating (base vs ground, footing reach) | **0** of 4,780 |
| max grade (10 m window): street 11.5% (the mountain road's street lead-in), avenue 8.0%, highway 5.5% (bridges 5.5-5.6%), mountain 11.6% | **0 over limit** (12% / 6% bridges) |
| overlapping footprints (buildings, towers, warehouses; SAT, 2% tolerance) | **0**, 0 on road keep-outs |
| deck clearance over roads / piers on roads at grade | min **7.46 m** / **0** piers |

Two build-time passes make these exact:

- **Terrain snap.** The data stage cuts and fills on a 2 m grid. The build then lowers any terrain
  cell within a grid cell of a road or junction top-surface vertex to 4 cm below it (70k cells), and
  writes the heightfield back.
- **Ground snap.** Street furniture, props and container stacks are moved onto the built surfaces:
  roads, sidewalks, barrier tops or terrain. 3,550 were moved, 1 dropped (over 4 m off), and
  `world.json` is rewritten.

## Performance and counts

| | |
|---|---|
| roads | 263 runs, 32.2 km: street 16.9, avenue 9.0, highway 2.7 (+0.3 urban), mountain 3.3 |
| junctions | 156 (73 signalised), plus transitions and the lookout |
| instances | 31,139 total: 16,926 props, 4,457 kit buildings, 255 towers, 3,131 containers, 2,136 trees, 1,487 signs, 1,164 lamps, 795 signals, 590 poles, 89 masts, 68 warehouses, 41 cranes. 82 distinct assets |
| lights | 1,736 point lights |
| Blender scene | 38.7k objects, 1,192 unique meshes, 6.3 M unique triangles, **240 M rendered triangles** (instanced) |
| terrain | 117 land / coast chunks of 256 m: 2 m grid, 33k triangles each; LODs at 8 m (2k) and 32 m (128) |
| world.json | 6.8 MB |

- Cycles needs every material's `emission_sampling = NONE` (set in `world_render.setup`): with
  emissive windows on thousands of instances, the light tree never finishes otherwise.
- **Godot budget.** The kit buildings are 40-60k triangles each with no LOD. Use visibility ranges
  or impostors beyond about 300 m. Props have LOD1, and the terrain has LODs.

## Shared files touched (merge notes)

- `tools/blender_town.py`:
  - `Junction(..., halves=None, min_arm=10.0)` takes per-arm half widths. The defaults are
    unchanged, and the town builds identically (`--verify`: 0 / 0).
- `tools/town_roads.py` (all additive; the town path is unchanged):
  - `TOWN_PROFILE`, `stations()` (adaptive sampling);
  - `build_run(..., profile=None)` with `side` = curb / jersey / guardrail and a median barrier;
  - `SectionBuilder.extrude()` and `.box()`, `metal_material()`;
  - `scatter_run_decals(..., profile=None)` leads to `lane_decals()`;
  - `junction_decals(..., arms=None)` leads to `junction_decals_wide()`;
  - `DecalBuilder.on_path(step=...)`.
- `tools/town_layout_driver.py`: `main()` is guarded by `if __name__ == "__main__"` so `tools/world`
  can import `import_kit()`. Running it is unchanged.
- `tools/godot/export_town.py`: `main()` is split into `export_layout()` and `pack()`, it has a
  `__main__` guard, and more `COLLIDE` prefixes. The town export output is unchanged.
- `tools/town_textures.py`: the new `world` job (`world_sheets`, `WORLD_JOBS`, facade / terrain /
  corrugated sheets, rib stencil). `python tools/town_textures.py` with no args still runs only the
  town jobs.
- `.gitignore`, `game/.gitignore`: the world outputs.
- No Rust changes.

## Known limits

- **No highway ramps.** Links meet the grids only at signalised at-grade junctions at their ends.
  There are no slip roads or interchanges, and the expressway has no exits mid-city.
- **Bridge clearances fall short of the config.** The configured navigation clearance is not fully
  reached within the 5.5% grade limit on these short water gaps: the cable-stayed deck is 5.3 m
  short of 20 m, the girder 3 m short of 12 m. The data stage prints these as `infeasible`. Decks
  still clear the water and the roads.
- **Mountain terrain** is steep after erosion (talus about 29 degrees), so the switchback road has
  big cut faces. The A* plans on a 30 m-blurred field and cut/fill does the rest.
- **The hillside district** has no terraces or retaining walls like the town. Buildings stand on
  footings and roads cut and fill. Junctions are flat, as in the town.
- **Tower windows** are a shader effect: their emission is not in the Pigment maps, so Godot needs
  the same per-pane hash, or a baked variant. The facade UVs are in metres (tile 8 m).
- **Props.**
  - Variant swaps (albedo) aren't applied in Blender: props render with their default look.
  - Props are joined into one mesh per prop in Blender. Use the original glbs in Godot for the
    driven lamp nodes.
- **Not committed.** The preview `.blend` and the export are regenerated, not committed (they are
  heavy).
