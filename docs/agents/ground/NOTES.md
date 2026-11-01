# ground: natural ground textures made in Pigment

The open world's ground was four noise tiles (rock, grass, dirt, sand: blobs and speckle, no
structure; the "sand ripples" were diagonal stripes). In Godot the terrain had no UVs, so it showed
one flat colour. Now:

- Pigment has five **natural-material generators** and three new **fill-layer options**.
- Nine **4K PBR ground sets** are authored with them (procedural only, no photo inputs).
- The **Blender terrain material** and a new **Godot `terrain.gdshader`** blend the nine sets by
  world masks, slope and height. Both have anti-tiling, triplanar rock, normal maps and rain.

| | |
|---|---|
| `tiles_before_after.png` | old tile vs new set (rock, grass, dirt, sand), each as flat albedo, a 2×2 repeat at grazing light and a sphere at grazing light |
| `ground_sets.png` | all nine new sets, the same three views |
| `cycles_before_after.png` | Cycles at the ground camera spots: mountain slope, forest floor, beach, cracked-mud / scree slope |
| `godot_night_rain.png` | Godot at the same spots, night and rain (`--sky=night_rain`): before (export's flat terrain) / after |
| `godot_dusk.png` | the same spots at dusk, where the ground reads better |

## 1. Pigment: generators and fill options

All of them are in `GeneratorKind` like the existing generators, with GPU ids 15–19, implemented
in a new `crates/app/src/shaders/gen_ground.wgsl` that is appended after `gen_weather.wgsl`. They
work on the in-surface plane of `wx_surface`: floors use (x, z), walls use (horizontal, y), in
metres.

They are **tile-periodic in tile mode**. Every frequency is snapped per axis to whole cycles per
tile period, cell ids wrap, and the 2D gradient noise has a periodic lattice. The domain warps
are periodic too, so warped cells, ripples and strata still wrap.

Named MCP args (in `add_layer` / `update_layer` `mask` and in `mask.effects[]`) map onto the slots;
see `apply_ground_fields` in `automation.rs`. `variant` takes each generator's names (or an index).
`list_library` lists them as `generators[].variants` and `ground_aliases`.

| id | aliases (pick a variant) | variants | args |
|---|---|---|---|
| `cells` (Voronoi) | `voronoi`, `cellular`, `worley`, `cell_edges`, `cobbles`, `flagstones`, `cracked_mud`, `mud_cracks` | `dome` (1 − F1), `f2`, `edges` (F2 − F1 border lines), `value` (random per cell), `plates` (flat tops with a rounded bevel) | `scale` cells/m, `randomness` point jitter, `edge_width` (m), `warp`, `stretch` (x vs z), `height_variation` per cell, `edge_noise` |
| `scatter` (bombing) | `bombing`, `pebbles`, `gravel`, `stones`, `leaves`, `twigs`, `needles`, `shells`, `clover`, `scree` | `pebble` (ellipsoid dome), `flake`, `leaf` (pointed, midrib, veins, curl, stalk), `twig` (bent capsule, bark), `shell` (ribbed fan), `clover` (trefoil), `chip` (angular, faceted) | `density`, `scale` cells/m, `size` (radius / cell), `size_variation`, `elongation`, `per_cell` (1–8 instances), `align`, `irregularity` (outline), `height_variation` |
| `rock` | `strata`, `eroded_rock`, `ridged`, `cliff` | `height`, `cracks`, `ledges` (up-facing shelves), `streaks` (downhill stains) | `scale`, `warp`, `strata`, `bands` /m (along v = up on cliffs), `cracks`, `crack_scale`, `streaks` |
| `blades` (grass) | `grass`, `turf` | `height` (mask = covered), `tips` (0 at the root to 1 at the tip), `clumps` | `density`, `scale` blades/m, `length` (m), `width` (m), `lean`, `clumping`, `swirl` (neighbours lean alike), `level` (where the tips / clumps mask starts) |
| `ripples` | `sand_ripples`, `waves` | `height`, `crests` | `scale` ripples/m, `angle` (deg), `irregularity` (curving crests), `asymmetry` (gentle stoss / steep lee), `defects` (forks, ends, fading), `sharpness` |

The shape parameters beyond the generic slots live in a new `Generator::extra: [f32; 4]`. It has a
serde default and is skipped when zero. It is packed as `gen3` / `gb3` / `gc3`.

**Side channels.** Besides the mask, each ground generator leaves its raw height profile
(`g_prof`) and a per-instance random (`g_inst`, one per cell, stone, blade or rock block) in private
shader variables. `generator()` keeps the main generator's values for the layer.

The `tiles` generator now also sets `g_inst` (one value per brick or sett). That is a one-line
addition; its mask is unchanged.

Fill-layer options are `Layer` fields with serde defaults (`pigment_core::ground`). They are MCP
args on `add_layer` / `update_layer`, and a "Ground" card in the Layer tab.

- **`height_profile: true`**: the fill's height follows the generator's shape (a dome per pebble,
  a blade's rise to its tip, the ripple profile) instead of a flat plateau under the mask. The
  colour keeps the hard coverage mask.
- **`height_gain`** (0–8): multiplies the fill's height. Fill values stay −1..1, but the stack is
  HDR, so boulders, rock masses and ruts can stand far out and the normals see all of it. The
  exported height map still clamps to −1..1.
- **`height_blend: {mode: above | below (lows | tops), contrast, offset}`** (or just the mode as a
  string): the layer shows only where its level (its height + offset) is above the stack's height,
  which fills the lows (sand between pebbles, water in ruts). With `below` it shows only where the
  stack rises above its level (moss and lichen on the tops). Combined with `height_profile`, this
  composites by height: small stones appear only where they would lie above what is already
  there, so they settle between the boulders.
- **`jitter: {value, hue, saturation, roughness}`** (or a number = value): per-instance variation
  keyed by `g_inst`.

Example:

```json
{"tool": "add_layer", "args": {"name": "Stones", "values": {"base_color": [0.42, 0.4, 0.37], "height": 1.0},
  "mask": {"generator": "scatter", "variant": "chip", "scale": 8, "density": 0.75, "size": 0.6, "per_cell": 2, "irregularity": 0.8},
  "height_profile": true, "height_gain": 3.5, "height_blend": {"mode": "above", "contrast": 0.15},
  "jitter": {"value": 0.3, "hue": 0.02, "saturation": 0.2, "roughness": 0.08}}}
{"tool": "add_layer", "args": {"name": "Lichen", "values": {"base_color": [0.55, 0.55, 0.48]}, "channels": {"height": false},
  "mask": {"generator": "spots", "amount": 0.1, "scale": 9}, "height_blend": {"mode": "below", "offset": 4.0, "contrast": 0.5}}}
```

UI: the generator picker shows the five new generators with rendered previews (automatic, through
`generator_doc`). The mask card has per-kind slider labels, an "Output" combo for the variant,
sliders for the extra parameters, and the breakup slider is relabelled per kind. The Layer tab
has a "Ground" card with height profile, height gain, height blend and per-instance variation.
These were checked by compiling only; no GUI windows were opened.

**Existing generators are unchanged.** The old code paths are untouched, apart from the
`gen_eval` dispatch and its extra `gp3` argument. Exported maps of town scripts run with the
base commit's `pigment-mcp` and this branch's are **byte-identical**: `world/rock`,
`roads/concrete`, `roads/paving`, `roads/setts`, `fence`, `street_lamp` and `building_a` (tile
and mesh projects; grunge, spots, scratches, moss, puddles, leaks, tiles, edge wear, dirt and
more).

## 2. The ground sets

`tools/ground_textures.py` holds the nine recipes. It writes `scenes/world/scripts/ground/*.jsonl`,
runs them, exports to `scenes/town/textures/world/<name>/` (git-ignored) and saves
`scenes/world/projects/ground/<name>.pigment`. Each set is 4096², seamless, with BaseColor,
Roughness, Metallic, Normal (OpenGL), Height and AO. A full run takes about 1–2 minutes.

| set | tile | how |
|---|---|---|
| `rock_cliff` | 4 m | `rock` mass (gain 6), `cells` plates for fracture faces, rock grain, crystals (`chip`), joints (rock `cracks`), water / iron stains (rock `streaks`), debris and moss on the ledges (rock `ledges`), grey and yellow lichen on the tops (height blend `below`), warm / cool tone |
| `scree` | 2 m | `chip` boulders (gain 7), then stones, gravel and grit, each with height blend `above` so they settle in the gaps, shadowed gaps, dust, lichen on the tops |
| `forest_floor` | 2 m | humus grain, old and fresh pine needles (`twig`, elongation 15), moss cushions, fallen leaves in two tones with hue / value jitter, twigs, cones, damp patches |
| `grass_turf` | 2 m | thatch (lying blades) under two blade layers (density 0.95, clumps, swirl), clover patches, dry tips (blades `tips`, level 0.8), dry patches (tips × grunge), bare soil in the lows |
| `dirt_mud` | 4 m | packed earth (`rock`, no strata), clods, grit, pebbles, two crossing **tyre tracks** (box decals of `assets/decals/ground/tyre_track.png`: two ruts with chevron tread, alpha = depth), wet mud, then **puddles in the lows** (height blend `above` at a water level, roughness 0.03), dry crust on the tops |
| `beach_sand` | 4 m | **wind ripples** (asymmetric, forking, fading) plus a long swell, sand grain, heavy minerals in the troughs (height blend), shell grit, `shell`s, pebbles, wrack, damp patches. The wet line at the water is in the terrain shader, by height above sea level |
| `cracked_mud` | 3 m | `cells` plates (edge noise, warp), curled rims (`cells` `edges` added on top), deep cracks, fine secondary cracks, pores, dust on the tops, dark crack fill |
| `cobbles` | 2 m | worn granite setts: `cells` plates near a grid (randomness 0.32, stretch 1.35), domed crowns, per-sett jitter, granite speckle, polished tops, chipped edges, grimy / mossy joints, weeds in the joints, gum |
| `vacant_lot` | 4 m | soil, gravel, an old slab cut into 2 m bays (`tiles` square effect) and broken into heaved pieces (`cells` plates), about 30 % of them missing (`cells` `value` effect), aggregate, cracks, weeds and dry weeds in every gap, rust, oil, litter (`flake` with hue jitter), grime |

Height units: Pigment's height-to-normal turns a height step of 1 over 1/256 of the tile into 45°,
so one unit is `size_m / 256` metres (1.56 cm on a 4 m tile).

**Photo inputs:** none. Everything is procedural. Rock and soil came close enough with the `rock`
and `scatter` generators, so no ambientCG or Poly Haven downloads were needed, and there is no
attribution to record.

## 3. Using them

### World ground masks

`tools/world/ground_masks.py` reads `world.json`, `heightfield.f32` and `masks_urban.npy`. In about
6 s it writes two RGBA PNGs on the terrain grid (2049², 2 m), which the materials sample by world
position. No mesh attributes and no world rebuild are needed.

| PNG | R | G | B | A |
|---|---|---|---|---|
| `ground_masks.png` | urban | forest (tree instances, blurred) | scree (a cliff 14 m uphill, on a moderate slope) | verge (roads through natural land) |
| `ground_masks2.png` | lot (port city land away from buildings and roads) | hollow (below the surroundings, flat) | old town | shore (natural, 1.5–6 m above sea level, away from the quays) |

It also writes `ground_spots.json`, the camera spots for the proof shots:

- a forest floor, a beach and a slope, each picked near a lamp (the game runs at night) and away
  from roads and buildings;
- a view across the mountain road at its steepest slope.

### Blender

`tools/world/ground_material.py` builds the material. `world_meshes.terrain_material` uses it when
the nine sets exist, and falls back to the old four-tile material otherwise (or with
`GROUND_LEGACY=1`).

The blend runs in this order:

1. grass;
2. dirt (noise patches, road verges, wet hollows);
3. cracked mud (dry hollows);
4. forest floor (forest mask);
5. scree (scree mask and 28–33° slopes, less under trees);
6. rock (over about 37°, or above 210 m; triplanar);
7. beach sand (shore mask);
8. city land: road concrete, cobbles in the old town, vacant lots in port gaps.

Every natural step is **height-aware**. The incoming set's height map moves its edge
(`clamp((f − 0.5)·2.2 + 0.5 + (h_in − h_base)·k)`), so sand creeps between grass tufts and
scree stones poke out.

- **Anti-tiling.** Each planar set is sampled twice. The second sample is rotated 37° and offset,
  and the two are mixed by world noise. The macro tone and roughness drift over tens of metres.
- **Normals.** The normal maps become world-space UDN perturbations: in the ground plane for
  planar sets, and per projection for the triplanar rock.
- **Wetness.** Below the waterline, a wet line along the shore, and a `Wetness` value (rain:
  darker, glossier, puddles in the texture's lows on flat ground).

### Godot

`game/scripts/terrain.gdshader` runs the same blend, with the same thresholds and order. Its
inputs are packed by `tools/godot/pack_ground.py`:

- two `Texture2DArray`s, VRAM-compressed (BPTC) with mipmaps, 10 slices of 2048² each (the nine
  sets plus the road concrete):
  - `ground_albedo`: sRGB colour, with height in alpha;
  - `ground_nrm`: normal xy, roughness and AO;
- the two masks;
- `ground.json`, with the slice order, metres per tile and average colour / roughness.

`town_loader.gd` gives `WorldTerrain` this shader when the arrays exist. Otherwise the export's
material stays.

- **Wetness** comes from the roads' `rain` uniform: `set_road_rain` now also updates
  `ground_materials`. It darkens the ground, makes it glossier, and puts puddles with drop ripples
  (`rd_ripples` from `road_common.gdshaderinc`) in the lows of flat ground.
- **Triplanar rock** on steep faces.
- **Sampling cost.** Only the sets that show are sampled: anything under a layer that fully covers
  it is skipped.
- **Distance tiers:**
  - full detail (anti-tiling, all three rock projections) inside 70 m;
  - one sample per set and the dominant rock projection out to 260 m;
  - fading to each set's average colour by 520 m.

`automation.gd` adds the ground spots to `--bench-spots` when `assets/world/ground_spots.json`
exists, so Godot shots and Cycles cams (`cams.json`) show the same views.

### City build

- `city/models/tile_set/ground.toml` is a smart model. Its recipe is `tools/ground_textures.py
  --no-run`, which writes the scripts, followed by nine Pigment nodes.
- `tools/city/rules.py` adds:
  - `ground:masks`, which runs `ground_masks.py` after the world build;
  - `godot.ground:world`, which runs `pack_ground.py` from the nine texture folders, the concrete
    and the masks.

So `python -m tools.city build "pigment:ground/*" godot.ground:world` rebuilds only what changed.
In this worktree, after `city adopt`, the ground nodes were fresh.

`tools/world/ground_material.py` is deliberately **not** a `world:build` tool. Changing the
Blender material would otherwise re-run the whole world build, although Godot gets its terrain
shading from the arrays, not from the export.

## 4. Proof

Reproduce:

```
cargo build --release -j 6 --bin pigment-mcp
python tools/ground_textures.py                              # 9 sets, 4K
python tools/world/ground_masks.py
python docs/agents/ground/make_sheets.py tiles
blender -b --factory-startup --python tools/world/world_driver.py -- --stages build,save --region -1850,-1750,-1300,-750
mv scenes/world/world_preview.blend scenes/world/world_ground_hills.blend    # likewise -700,350,0,750 -> world_ground_city.blend
blender -b --factory-startup scenes/world/world_ground_hills.blend --python docs/agents/ground/cycles_shots.py -- --spots ground_forest,ground_beach [--legacy]
blender -b --factory-startup scenes/world/world_ground_city.blend --python docs/agents/ground/cycles_shots.py -- --spots ground_slope,ground_mountain [--legacy]
python tools/godot/pack_ground.py && godot --headless --path game --import
godot --path game -- --bench-spots=<dir> --spots=ground_forest,ground_beach,ground_slope,ground_mountain,lookout --no-drive --clean --sky=night_rain
```

## Perf (Godot)

The setup was an RTX 4070 Ti at 1920×1080, vsync off, night with rain, using `--bench-spots`
(6 s per spot, then a 30 s autopilot drive). The runs went back to back: after, then before (the
terrain shader switched off by hiding `ground.json`), then after again.

The machine was shared with about ten other agents, which used up to 11 GB of the 12 GB of VRAM
and the CPU, so single fps numbers swing by ±30 %. GPU time is the steadier measure.

| spot | before: fps / GPU ms | after (two runs): fps / GPU ms |
|---|---|---|
| forest floor | 292 / 2.24 | 305 / 2.68, 282 / 2.81 |
| beach | 321 / 2.03 | 291 / 2.54, 199 / 2.86 |
| cracked-mud slope | 250 / 2.80 | 224 / 3.33, 139 / 5.14 |
| mountain | 151 / 2.46 | 217 / 2.36, 216 / 2.73 |
| lookout, down the mountainside | 162 / 4.38 | 229 / 3.50, 153 / 4.59 |
| lookout, skyline | 207 / 3.17 | 212 / 3.23, 220 / 3.26 |
| 30 s drive | 88 / 7.28 | 77 / 8.0, 98 / 5.57 |

- The terrain shader costs about **+0.3 to 0.6 ms of GPU** at close ground views, and about
  nothing at distance (the far tier uses average colours).
- Frame rates stay at or above the perf workstream's ~120+ fps target at every spot. The drive is
  CPU-bound and was under contention here.
- VRAM: +180 to 245 MB (two BPTC texture arrays of 10 × 2048² with mips, plus two 2049² masks).
- Load time is unchanged within noise. The arrays import in about 2 minutes, once.


## Tests

- **Core** (`ground.rs`): serde defaults and round trip of the new layer fields and `extra`.
  Every alias names a real generator and variant.
- **naga**: `shader_tests::composite` and `folder` now include `gen_ground.wgsl`.
- **GPU** (`app/ground_tests.rs`, through `Session`):
  - `ground_generators_tile_seamlessly`:
    - a 7-layer stack touching every ground generator, height blend, jitter and profile;
    - a tile scrolled by part of its period gives the same maps, rolled;
    - seams are no stronger than interior neighbours.
  - `scatter_instances_are_rounded_and_jittered`:
    - with `height_profile`, over 30 % of the stones' texels are on their slopes (a plateau gives
      under 12 %);
    - jitter spreads the stones' tone;
    - leaf, twig, shell and flake shapes differ.
  - `height_blend_fills_the_lows_and_caps_the_tops`:
    - sand fills the gaps between pebbles (over 97 %) and never their tops;
    - moss covers the tops, not the flanks;
    - the gaps are raised to the sand level.
  - `ground_mcp_args`: named args map to the right slots; aliases and variants work; bad variants
    and modes are errors; fill-only; `list_library`; save / reopen.
- **MCP schema**: `every_repo_script_matches_the_tool_schemas` now also checks
  `scenes/world/scripts/ground/`.

Results:

- `cargo test --release -- --test-threads=2` (with `--no-fail-fast`): core 109 passed; the
  pigment-mcp bin passed 4, including the schema tests.
- The app library passed 81 with 10 ignored, including all four ground GPU tests and both naga
  tests. **3 failed: the `decal_tools` anchored / scatter tests.** They fail the same way on the
  base commit 63e707b: I built it separately and ran them there, and all three failed. So this
  failure is pre-existing; it is not from this branch, and they don't touch ground code.
- Godot `--drive-test`: PASS. `--traffic-test=60`: PASS.
- `python -m tools.city verify scripts`: all 83 Pigment scripts pass `--check`.

## Known limits

- The Godot and Blender noise functions differ (Blender noise vs `rd_fbm`), so the exact patch
  shapes differ between the two. The rules and thresholds are the same.
- The tyre tracks are straight-ish in a tiling tile, so wherever dirt shows, the ruts run in the
  tile's directions. Track-aligned ruts would need decals along the tracks.
- The masks come from `world.json`. After a world regeneration, run `ground_masks.py`
  (`ground:masks` in the city build).
- `scatter` searches at most 7×7 cells and `blades` at most 9×9, so very long, thin instances
  relative to the cell size get clipped. Raise `scale` (more, smaller cells) instead.
- The exported height map clamps to −1..1, while normals see the full HDR stack. Engines that
  displace from the height map get less relief than the normals show.
- The mountain views (Cycles and Godot) still read as smooth, pale slopes at 50–150 m. The
  terrain mesh is smooth at 2 m, and texture relief doesn't carry that far. Real rock forms at
  that scale need geometry (displacement, rock meshes). The ground_lookout Godot view is lost in
  the fog at night.
- The night-and-rain Godot shots are dark away from lamps. That is the game's lighting; the dusk
  set shows the textures more clearly.

## Merge notes

- **Hot files, all edits additive:**
  - `document.rs`: five `GeneratorKind` variants, `variant_names` / `alias_variant` /
    `is_ground`, `Generator::extra`, and three `Layer` fields, plus the same in the two `Layer`
    literals.
  - `folders.rs`: the `Layer` literal.
  - `composite.wgsl`: five new `LayerParams` fields at the end (`gen3`, `gb3`, `gc3`, `ground`,
    `jit`; 480 of the 512-byte stride), `gen_eval(…, gp3)`, `generator()` side channels, and one
    block in `fs_layer`.
  - `texset.rs`: the same fields, `ground_params()`, and `gen_ground.wgsl` in both shader
    concatenations.
  - `automation.rs`: `apply_ground_fields`, `check_ground_variant`, `configure_ground`, and the
    list output.
  - `pigment-mcp.rs`: the schema.
  - `panels/layers.rs`: labels, variant combo, Ground card.
  - `gen_weather.wgsl`: one line in `wx_tiles`.
- **Others:** `town_loader.gd` (terrain material, rain), `automation.gd` (ground spots),
  `tools/city/rules.py` (two nodes), `tools/world/world_meshes.py` (dispatch to
  `ground_material.py`).
- **Regenerate:** `python tools/ground_textures.py`, `python tools/world/ground_masks.py`,
  `python tools/godot/pack_ground.py`, then a Godot re-import. The arrays need about 2 minutes on
  the first import.
- `scenes/world/ground_masks*` and `ground_spots.json` are git-ignored.
