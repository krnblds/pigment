# trees: a procedural tree kit for the city (workstream `trees`)

The old trees were cones and blobs: the props kit's `street_tree` / `palm_tree`, and 2,136 world
`tree_pine` / `tree_broad` meshes of 60–92 triangles. They are replaced by an original, procedural kit
of Japanese species. The kit has:
- real branching;
- alpha-tested leaf, needle and blossom cards;
- Pigment bark tiles and a Pigment leaf atlas;
- LOD0 / LOD1 / impostor;
- trunk-capsule colliders;
- wind, translucency and rain in Godot.

Trees are placed by context across the open world and, sparingly, in the small town.

Part 2, the "lame assets" audit and rebuild, is written up in [ASSETS.md](ASSETS.md): 7 assets rebuilt.

| image | what |
|---|---|
| `lineup_studio.jpg` | Every species (plus looks) in Cycles, studio daylight, with LOD triangle counts |
| `lineup_night.jpg` | The same at night: warm and cool street lamps behind and in front of the crowns, a neon wash, a wet ground |
| `avenue_cycles.jpg` | A downtown avenue lined with zelkova in tree pits, Cycles (world preview region, `world_render` avenue camera) |
| `godot_avenue_night_rain.jpg` | Godot, the same avenue at night in the rain: the canopy closes over the road |
| `godot_mountain_forest_night_rain.jpg` | Godot, the mountain road through the cedar / black pine forest, night, rain |
| `godot_mountain_road_night_rain.jpg`, `godot_lookout_night_rain.jpg` | Higher up the switchbacks, and a black pine at the summit lookout |
| `lame_before_after*.jpg`, `lame_after_closeups.jpg`, `audit_contact_sheet_*.jpg` | Part 2 (see ASSETS.md) |

## Species (36 variants + a grate)

| species | role | shapes / looks | LOD0 tris | LOD1 tris | height |
|---|---|---|---|---|---|
| Japanese pagoda tree (*Styphnolobium japonicum*, "Japanese acacia") | old-town avenues, parks, mid slopes | 4 | 4,046–5,066 | 570–820 | 13–15 m |
| Japanese zelkova (keyaki) | downtown avenues (vase of upright leaders) | 4 | 4,106–4,572 | 888–1,068 | 12–15 m |
| Ginkgo | midtown avenues | 3 + 2 gold (autumn) | 3,430–3,570 | 696–754 | 12–16 m |
| Cherry (Somei-yoshino) | Kagero hills avenues, park groves, lookout | 3 blossom + 2 green | 4,120–4,176 | 728–768 | 8–9 m |
| Japanese black pine (kuromatsu) | shores, mountain-road verge, ridges, lookout | 4 | 4,270–4,918 | 530–808 | 10–12 m |
| Japanese cedar (sugi) | mountain forest | 4 | 4,676–4,772 | 580–590 | 25–27 m |
| Canary Island date palm | corporate island | 3 | 3,300–3,792 | 478–532 | 12 m |
| Azalea (tsutsuji) | park borders, planters | 2 + 2 in bloom, + planter size | 276–416 | 90–110 | 0.7–1.3 m |
| Box hedge | park borders, planters | 1 + planter size | 296–408 | 98–130 | 0.7–0.8 m |
| `tree_grate` | cast-iron pit grate (real bars) | 1 | 1,920 | (LOD0 only, 90 m) | |

**LOD2 (every variant) is 8 triangles:** 3 crossed vertical quads plus a top quad (for views from the lookout).
- The impostors are baked from LOD0 in Cycles: albedo times crown occlusion, and object-space normals.
- All 36 variants share one 4096² atlas.

**LOD distances (m), in `species.LODS`:**

| | LOD1 from | impostor from | gone at |
|---|---|---|---|
| default | 38 | 110 | 650 |
| cedar | 30 | 85 | 900 |
| palm | 45 | 130 | 650 |
| shrubs | 18 | 55 | 140 |

Cross-fades between LODs are dithered over 6 m.

## How it is built (tools/trees/)

| step | command | output |
|---|---|---|
| shapes | `python tools/trees/stencils.py [--preview]` | `scenes/trees/stencils/` (git-ignored): leaf, needle and blossom card art (colour + relief + blade masks) and seamless bark relief / cavity / ridge / colour, all procedural (numpy, PIL, scipy: FFT noise, periodic Voronoi) |
| textures (Pigment) | `python tools/trees/tree_textures.py --run` (`cargo build --release -j 4 --bin pigment-mcp` first) | `scenes/trees/scripts/*.jsonl` (committed), then `assets/trees/textures/` (committed, 14 MB) |
| meshes | `blender -b --factory-startup --python tools/trees/build_trees.py [-- keys or species] [--no-impostors]` (about 4 min) | `assets/trees/<key>.glb`, `_lod1.glb`, `_lod2.glb`, `tree_grate.glb`, `index.json`; per-variant impostor renders in `scenes/trees/impostors/` (git-ignored) |
| impostor atlas | `python tools/trees/impostor_atlas.py` | `assets/trees/impostors/atlas_{albedo,normal}.png` and the `impostor` entries in `index.json` |
| Godot | `python tools/trees/sync_godot.py`, then `godot --headless --path game --import` | `game/assets/trees/` (git-ignored there) |
| proofs | `blender ... render_trees.py -- sheet [--night] --keys ...`, then `python tools/trees/contact_sheet.py OUT keys [--suffix _night_lod0]` | lineups |

### Pigment usage
- **Leaf atlas.** A decal-atlas project (`new_project {tile: {cells: [...]}}`, 4096, 14 cells). Per cell, the card art goes on as decals:
  - the colour into base colour, roughness and opacity;
  - the relief into height with `alpha_from_luminance` (leaf domes, midribs, round twigs, so the normals come out right);
  - the blade mask into transmission, which is the translucency hint the game reads.

  Fills masked by generators sit on top: tone variation (grunge), dry and scorched patches (spots), city dust (Grime), and a wet sheen (roughness only).
  - Export: `BaseColorAlpha`, Normal, Roughness and Transmission, packed by `tree_textures.pack()` into `leaves_albedo.png` (RGBA), `leaves_normal.jpg` and `leaves_mask.jpg` (R roughness, G translucency).
  - One paint layer holds every cell's decals. A layer stack per cell ran out of GPU memory on the shared card.
- **Bark.** 7 seamless tile projects (`tile: {size_m}`, 1024).
  - The relief is an image fill into height.
  - The colour detail is the base image fill, times a multiply tint.
  - Furrows and ridges are fills whose masks are the cavity / ridge stencils projected into the mask.
  - Then lichen (spots), moss (moss generator), rain streaks (streaks plus Grime), tone, and city soot.
  - Each species has its own look:
    - pagoda / ginkgo: interlaced vertical furrows;
    - zelkova: smooth grey with orange flakes and lenticels;
    - cherry: glossy, with horizontal lenticel bands;
    - pine: deep plates;
    - cedar: fibrous strips;
    - palm: diamond leaf-base scars.

### Generator (`treegen.py`: pure numpy, deterministic per species and shape seed)
- **Recursive branches.** Trunk, optional split into leaders (zelkova vase, cherry), then 1–3 branch levels. Each level has:
  - count, position band, angle along the parent, phyllotaxis;
  - length (level 0 through a Weber & Penn crown envelope: hemispherical / flame / tapered / spherical / conical);
  - curvature, random wobble, gravity or phototropism by thickness, an outward pull;
  - downwind lean and shortening for the windswept pine.
- **Trunks.** Root-flare lobes, buried 0.35 m. Palm trunks get ring relief and a crown "boot".
- **Bark UVs.** Tile in metres (a whole number of tiles around), with parallel-transported tube frames.
- **Leaf cards.** Placed along twigs and the outer part of their parent branches, picking tips first, up to a per-species budget. Card modes:
  - spray (broadleaf);
  - crossed tufts (pine);
  - hanging sprays (cedar);
  - a folded strip along each rachis (palm fronds);
  - a volume cloud (shrubs).

  Card normals are bent towards the crown's outward direction, so the crown shades as one volume.
- **Vertex data for the game.** `COLOR_0` = (branch flex, phase per scaffold, leaf flutter from 0 at the stem to 1 at the tip, crown occlusion). `TEXCOORD_1` = (height / tree height, 0 bark / 1 card / 2 impostor).
- **LOD1.** The same skeleton: trunk and thick scaffolds only, and about a quarter of the cards, scaled up to keep the coverage.
- **Collider.** A trunk capsule only (radius at 1.35 m, up to the split or the crown base, 2–6 m). Shrubs and grates have none.

## Placement (`tools/trees/tree_placement.py`, called from `tools/world/placement.py`)

World seed 2077: **9,638 kit instances**.

| context | what | count |
|---|---|---|
| avenues | One species per avenue, in pits 1.1 m behind the curb, every 8–10 m, both sides, with a `tree_grate`. Downtown zelkova, midtown ginkgo (35% of avenues gold), old town pagoda, hills cherry (40% green), corporate palm (no grate). Skips decks, junction mouths (14 m) and 3.2 m around lamps / poles / signals / masts | 1,266 trees, 1,103 grates |
| streets | The props kit's `street_tree` / `palm_tree` scatter spots become a smaller kit tree of the district's species (scale 0.62–0.8), with a grate | 286 |
| planters | Every props-kit `planter` gets a planter-sized box or azalea shrub on its soil (it rides the planter in the ground snap) | 272 |
| parks / temple grounds | Groves of 3–5 cherry / pagoda trees with azalea / box borders on free urban land (old town, midtown, hills) | 27 groves, 96 trees |
| mountain forest (> 32 m) | Cedar in noise-driven clusters, thinning towards the summit; black pine on steep or high ground | 2,868 cedar |
| shore (low natural land near the sea) | Black pine | 2,849 pine (all zones) |
| mid slopes | Cedar / pine / pagoda / zelkova mix | 280 pagoda, 195 zelkova |
| mountain road and lookout | Black pines on the verge outside the guard rail; a ring of cherries and pines around the summit plaza | 76 |

- The props scatter now treats trees as blocked discs (1.6 m), so bollards, bikes and the like keep clear of the pits.
- **Obstacle-free roads.** `world_gen.clear_carriageways` still runs last and passes. It dropped 22 palms that props-kit palm spots had put on carriageways, as it did before for the old palms.
- **World verify** (`--stages gen,build,verify`):
  - terrain above roads 0;
  - props floating / buried 0 / 0 (18,308 checked);
  - buildings floating 0;
  - footprint overlaps 0;
  - grades within limits;
  - deck clearance 7.46 m;
  - ground snap 11,264 moved, 2 dropped.
- **Small town** (`tools/blender_town.py`, after the lamps / poles): 9 cherry / pagoda street trees with grates on alternate runs, 44 m apart, clear of lamps and poles. The town export (`tools/godot/export_town.py`) picks them up as `cat: tree`.

## Godot (`game/scripts/`)

- **`tree_kit.gd`** (new). Loads `res://assets/trees/index.json` and builds the materials:
  - `tree_leaves.gdshader`:
    - alpha scissor 0.42, with mip-coverage compensation (`textureQueryLod`);
    - two-sided without the engine's back-face normal flip, so cards keep the crown normal;
    - `BACKLIGHT` translucency from the Pigment transmission map, so leaves glow against street lamps;
    - crown occlusion and rain wetness.
  - `tree_bark.gdshader` (tiling Pigment bark, wet darkening).
  - `tree_impostor.gdshader`.
  - All three share `tree_common.gdshaderinc`:
    - **Wind:** a height² main bend with a drifting gust field, branch sway by flex, leaf flutter along the card normal; the phase comes from the instance position plus the scaffold phase.
    - **Per-instance LOD:** every LOD mesh is drawn for its band only. The vertex shader measures the instance's own distance to the camera and collapses instances outside the band; the fragment shader dithers a 6 m cross-fade.
  - Globals in `project.godot [shader_globals]`:
    - `tree_cam`, set every frame from the player camera, so shadow passes pick the same LOD;
    - `tree_wind` (direction, strength, wetness; `set_road_rain()` drives the wetness).
- **`town_loader.gd`** (additive, same API). Layout meshes whose key is a kit variant get policy `"tree"`, and `_build_trees()`:
  - **LOD0:** MultiMesh per variant per 64 m cell, streamed by the existing cell streamer, with shadows.
  - **LOD1:** MultiMesh per variant per 256 m region (unit `z = 2`), no shadows.
  - **Impostors:** one MultiMesh per 256 m region for every species. It uses a unit mesh with the variant in `INSTANCE_CUSTOM` (atlas cell, quad sizes, LOD start, far distance), so species never add impostor draws.
  - **Collision:** trunk capsules in the collision cells (new `"cap"` shape kind).
  - Without `assets/trees` the old path is used unchanged.

## Performance (RTX 4070 Ti, 1920×1080, `--bench-spots`, traffic on)

This machine is shared with about 10 agents, and runs are bimodal. Render-thread CPU swings between about 1.5 and 3.8 ms run to run, with or without trees: the same "before" layout gave avenue 85 / 121 / 137 fps in three runs. So the stable signals are GPU time and draw calls. The fps figures are the best and the median of paired runs.

| spot | draw calls before → after | primitives (M) | GPU ms before → after | fps with trees, best run | fps, same-moment pair (no trees / trees) |
|---|---|---|---|---|---|
| downtown avenue | 1,045 → 1,240 | 3.64 → 4.04 | 3.40 → 4.2 | 188 | 137 / 115 |
| arch bridge → skyline | 1,165 → 1,028 | 1.65 → 1.51 | 2.66 → 2.6 | 251 | 168 / 158 |
| lookout → skyline | 935 → 928 | 1.21 → 1.22 | 2.72 → 2.8 | 261 | 92 / 95–99 |
| mountain road (forest) | 957 → 972 | 2.13 → 2.30 | 2.85 → 3.3 | 230 | 100 / 99–107 |
| mountain road, upper | 83 → 159 | 0.24 → 0.52 | 1.95 → 2.6 | 307 | 150 / 151–176 |
| autopilot drive 30 s | 1,210–1,260 → 1,310–1,430 | 3.8 → 3.9–4.1 | 4.1 → 4.7 | 127 | 61 / 52–59 |

- **Cost of 9,638 trees:** +0.4–0.8 ms GPU, about +100–200 draw calls near trees, and 341 multimeshes in total (the same as before).
- **Load:** +2–3 s (`load_ms`), mostly the kit glbs.
- **The ~120 fps target:** reached whenever the machine is in its fast mode (all spots 127–307 fps). In the slow mode the game is CPU-bound with or without trees: `process_ms` is 9–15 ms in the baseline too.
- **The first version cost more than this.** It had a MultiMesh per variant per region for the impostors (1,238 multimeshes, +1.4 ms render CPU). Fixed by the shared impostor atlas and the region-level LOD1.

## Regenerate / re-export (after merge)

```
cargo build --release -j 4 --bin pigment-mcp
python tools/trees/stencils.py
python tools/trees/tree_textures.py --run                       # Pigment: leaves atlas + 7 bark tiles (about 30 s), packs assets/trees/textures
blender -b --factory-startup --python tools/trees/build_trees.py   # about 4 min
python tools/trees/impostor_atlas.py
python tools/trees/sync_godot.py
# world: placement changed (trees + props scatter), so regenerate world.json and the export
blender -b --factory-startup --python tools/world/world_driver.py -- --stages gen,build,verify
blender -b --factory-startup --python tools/world/world_driver.py -- --stages build,export     # 55 min
# or, quick (no mesh re-export): patch only props / trees / shrubs into an existing export
python tools/trees/patch_world_export.py --world scenes/world/world.json --layout game/assets/world/world_layout.json
blender -b --factory-startup --python tools/godot/export_town.py   # town trees
godot --headless --path game --import
```

The committed `scenes/world/world.json` is already regenerated. The Godot screenshots in this folder used the patch tool on the main checkout's export.

## Merge notes

**Shared files touched** (all additive):
- `tools/world/placement.py`:
  - `tree_kit()`;
  - `place_trees()` delegates to the kit;
  - an avenue pass before `scatter_street_props`, then street swaps and parks after it;
  - `"tree"` in the blocked kinds.
- `tools/world/world_build.py`: kit trees are routed to `tree_blender.kit_mesh` in the instance loop; the ground snap gets a `shrub` kind (planter shrubs follow their planter). Not `build_bridge`: the bridges belong to the bridges workstream.
- `tools/blender_town.py`: a street-tree block after the lamps / poles.
- `game/scripts/town_loader.gd`:
  - the `_trees` field and the `"tree"` policy;
  - `_build_trees`, `_build_tree_impostors`;
  - a `"cap"` collision shape;
  - a `tree_cam` update at the top of `_process`;
  - `set_road_rain` also sets the tree wetness.
- `game/project.godot`: a new `[shader_globals]` section.
- `.gitignore` / `game/.gitignore`: `scenes/trees/*` and `game/assets/trees/`.

**Behaviour to know:**
- **Props kit.** `street_tree` / `palm_tree` stay in the catalog as scatter slots, but the world turns them into kit trees. `planter` keeps its old blob shrubs, now mostly hidden by the kit shrub. Remodelling the planter needs the props Pigment textures and was left out.
- **Port meshes (Part 2).** The rebuilt container (3,224 tris, 967 at LOD1) is placed 3,131 times. The world loader doesn't switch prop LODs, so after the full re-export check the port views; give `container` / `crane_sts` a visibility range or use the LOD1 glbs. Details are in ASSETS.md.
- `cargo test --release`: no Rust changes in this workstream.

## Known limits

- **LOD1** is the same skeleton thinned out, not a hand-made silhouette. **Impostors** are crossed quads, not octahedral, so the switch shows at about 110 m in clear air (fog hides most of it at night).
- **Night lighting:** street lamps light the crowns, but the canopy reads dark at night without lamps nearby, as real street trees do.
- **One leaf atlas** holds every species. The palm frond's tall cell wastes some atlas space; a second atlas page would raise card texel density.
- **Wind** is a vertex effect: no bending of colliders, and no per-branch hierarchy beyond the flex weights.
- **The patch tool** rebuilds only prop / tree / shrub instances. Use the full export for anything else that changed.
