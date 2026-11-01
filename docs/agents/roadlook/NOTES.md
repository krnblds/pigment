# roadlook: the game's roads like the Blender / Cycles roads

Branch `roadlook-workstream` (from main a249a17).

## Side by side

`*_compare.png`: before (game, main a249a17) | after (game, this branch) | Blender / Cycles, all from the same camera.
The game writes its spots as Blender cameras: `--bench-spots=<dir> ... ` writes `<dir>/cams.json`.
`tools/world/world_render.py --cams <dir>/cams.json` renders them. Godot's fov is vertical, so the
camera uses sensor fit VERTICAL. The screenshots use rain on, `--clean` (no HUD, no rain streaks; the roads stay wet).

| spot | what |
|---|---|
| avenue | the existing street-level avenue spot |
| junction | the X junction nearest downtown whose arms are all curb streets. View from 14 m up an arm, across the zebra |
| curb | the sidewalk edge of the same arm, looking along curb / gutter / paving into the junction |
| wet | 0.9 m over a downtown avenue, looking down it at the neon |

Regenerate:
```
godot --path game -- --bench-spots=<T>/after --spot-secs=1 --no-drive --clean --spots=avenue,junction,curb,wet
blender -b --factory-startup --python tools/world/world_driver.py -- --out <copy of scenes/world> \
    --stages build,render --region -300,-280,140,40 --cams <T>/after/cams.json --render-dir <T>/blender --samples 96
python tools/godot/side_by_side.py --out docs/agents/roadlook "before=<dir>" "after=<dir>" "Blender / Cycles=<dir>" -- avenue junction curb wet
```
The region build plus 4 Cycles shots takes about 100 s.

## Why the asphalt read flat dark grey
- **Damp was matte.** The first port darkened everything but only took roughness to about 0.6 outside the puddles. At that roughness SSR and specular show nothing, so the road looked like dry, flat, dark paint.
- **Blender's damp depends on the height of each texel.** The damp mask includes the height map's low spots (`(0.5 - h) * 0.9`). So in Cycles the aggregate reads as a glossy / rough speckle, not a uniform tone.
- **The trim sheet got no wetness.** Curb, gutter and drain used a `StandardMaterial3D` with no wetness. In the game the curb was a light, dry strip, but in Blender it is wet and dark.
- **The decal atlas (markings, cracks, patches) had no wetness.**
- **SSR stopped short.** It used 72 steps and fade-out 2.5, so wet asphalt lost the reflection of a sign 20-30 m away.
- **Anisotropic filtering was at the project default (4x).** The 1 mm/texel asphalt tile blurred at grazing angles.

## What changed
- **`game/scripts/road_common.gdshaderinc`** (new): noise and the wet model shared by the road shaders.
  - `rd_wetness()` is a direct port of `town_roads._wetness`: broad noise, `wet_bias * 0.32`, fine noise and `(0.5 - h) * 0.9`, with the same `lo = 0.545 - 0.1 (strength - 1)`. It returns puddle and damp.
  - `rd_ripples()`: rain-drop rings on a jittered grid in 2 layers, as a normal offset. Only evaluated where there is a puddle.
- **`game/scripts/road_surface.gdshader`**, now used for asphalt, paving, concrete and **trim**:
  - **Wet model.** damp = max(Blender damp, `film`) while it rains.
    - Albedo ×0.6 when damp and ×0.5 in puddles (porous darkening).
    - Roughness goes to a film of 0.05. The aggregate's high points (`smoothstep(0.6, 0.85, h)`) poke through at up to 0.3, so the aggregate stays visible.
    - Puddles have roughness 0.02, no metal, a flat normal plus ripples.
    - The normal is scaled down under the film (×0.55) and removed in puddles.
  - The trim sheet keeps its metallic drain grates.
  - `wet_bias` is read from the vertex colour (R = 1 - wet_bias, so meshes without colours are dry).
- **`game/scripts/road_decal.gdshader`** (new): the decal atlas gets the same puddle mask and film. Paint darkens less than asphalt.
- **`town_loader.gd`**
  - `ROAD_SURFACES` now covers trim. The table gains `film` per surface: asphalt 0.85, paving 0.55, trim 0.6, concrete 0.
  - **wet_bias.** It is not in the current glb exports. `_wet_bias()` rebuilds it while merging each region on worker threads, as in `town_roads.py`:
    - Trim-sheet gutter strip (UV.v 0.25..0.475): 0.36 at the road edge, up to 0.6 at the curb.
    - Asphalt: 0.8 at the gutter, fading to 0 over 1.2 m (distance to the gutter's road-edge vertices).
    - Cost: merge time 87 → 153 ms at load. It is skipped when the mesh already has the colour.
- **`tools/godot/export_town.py`**: `export_mesh()` writes the `wet_bias` attribute as `COLOR_0` (FLOAT_COLOR, R = 1 - wet_bias, `export_vertex_color="ACTIVE"`). Checked with a headless test export: values 0 / .25 / .5 / 1 come out as 1 / .75 / .5 / 0. This also brings over the sag points, which the Godot fallback can't see.
- **`main.gd` SSR:** steps 72 → 160, fade in 0.1 → 0.05, fade out 2.5 → 0.8, depth tolerance 0.3 → 1.0. They can be overridden with `--ssr-steps= --ssr-in= --ssr-out= --ssr-depth=`.
- **`project.godot`:** `textures/default_filters/anisotropic_filtering_level=4` (16x).
- **Street lamps:**
  - The lamp OmniLights now exist and light only within 60 m (fade 45..60 m, was 70..100 m). Masts are unchanged at 70..100 m; alley and other lights use 35..50 m. The fades are in a `LIGHT_FADE` table.
  - Beyond 60 m, `_lamp_glows()` draws every street lamp as one MultiMesh of additive, unshaded, camera-facing glow sprites (`lamp_glow.gdshader`). They fade in where the light fades out, so an avenue keeps its row of lamp halos to the horizon. Live lights at the spawn: 19 → 5.
  - Lamp range / energy were checked against Blender: at 6 m (the lamp height) and 15 m the irradiance is within about 30 % of Cycles' 420 W point light with the render's exposure, so they were left as they were.
- **`automation.gd`**
  - New spots `junction`, `curb`, `wet`.
  - `--spots=a,b` filter.
  - `--clean`: no HUD and no rain streaks.
  - `--no-drive`: skip the drive at the end.
  - `cams.json` writer.
- **`world_render.py`:** `--cams <file>` (game camera spots, vertical fov).
- **`tools/godot/side_by_side.py`:** the comparison strips.

## Perf (1080p, RTX 4070 Ti; rain and HUD on; `perf_before.json` / `perf_after.json`)
| | before fps / GPU ms | after fps / GPU ms |
|---|---|---|
| `--bench=20` | 102.1 / 4.83 | 104.1 / 4.81 |
| bench-spots drive | 88.5 / 4.85 | 82.4 / 5.18 |
| avenue | 133.6 / 4.03 | 155.4 / 3.91 |
| junction | 112.6 / 3.94 | 135.6 / 4.16 |
| curb | 106.9 / 3.88 | 110.4 / 4.38 |
| wet | 147.4 / 4.31 | 135.9 / 4.59 |
| bridge | 149.0 / 3.19 | 185.1 / 3.23 |
| lookout | 174.3 / 2.97 | 139.6 / 3.75 |
| mountain_road_30 / _65 | 133.4 / 294.8 | 187.2 / 278.2 |

- **The world is CPU-bound, not GPU-bound.** GPU time is about 4-5 ms (200+ fps worth) at every spot, but the frames take 7-12 ms. `--bench-matrix --spot=avenue` shows hiding the traffic takes 136 → 201 fps, while hiding all town lights only gains about 7 fps / 0.5 ms GPU.
- **The 120 fps average is not met on this machine today, before or after this branch.** The before run of main a249a17 gave 102 fps on `--bench=20` and was measured in the same session. The machine was shared: about 10 other agents were building and running `pigment-mcp` on the CPU, though the GPU itself was idle at 0 %. The 186 fps quoted before the lamp change can't be reproduced under this load.
- **The road shader adds about 0.1-0.4 ms GPU** at street level (ripples are only evaluated in puddles). The fps differences between runs are mostly CPU noise from the shared machine.

## Tests
- `--drive-test`: pass (all checks).
- `--curb-test`: pass (100 cases, 0 fails).
- `--traffic-test=60`: pass.

Physics surface detection uses the collision categories, which this branch doesn't touch.

## Known limits / what still differs from Cycles
- **The biggest remaining gap is what the road reflects, not the road.**
  - In the Cycles shots the buildings have many large lit window panels. With the assets in this worktree (copied from main before the building re-export finished), the game's facades are mostly dark, so there is less for wet asphalt to mirror. Re-check after the new building kit export.
  - The game's sky / fog (`CitySky`, volumetric fog) also gives the street a strong red-magenta cast that Cycles doesn't have. The road's mean colour is about (0.032, 0.006, 0.007) in the game against (0.031, 0.023, 0.021) in Cycles. That belongs to the sky / fog setup; it was left alone here.
- **SSR's limits.**
  - It only reflects what is on screen, and isotropically. The long vertical neon streaks of `town_street.png` (anisotropic wet highlights) are not reproduced.
  - Transparent things (glow sprites, decals) are not in SSR.
  - Reflection probes or a planar reflection were not needed for the puddles to read; not done.
- **wet_bias from the Godot fallback has no profile sag points.** Those come with a re-export using the new `export_town.py`.

## Merge notes
- **Re-export.** The world / town must be re-exported (`world_driver.py --stages ...,export` / `export_town.py`) to get `wet_bias` as vertex colours. Until then the loader fallback handles gutters, so nothing breaks either way.
- **Hot spots:**
  - `town_loader.gd`: the road material block, `_merge_job`, the lights section.
  - `main.gd`: the SSR lines in `_setup_environment`.
  - `automation.gd`: `_bench_spots`, `_spots`.
- **No asset or texture regeneration needed.** `pack_textures.py road_maps()` is unchanged; trim / atlas maps were already copied.
- **Untouched import files.** The Godot import run modifies a few tracked `*.import` files (sky HDRs, car / traffic stand-ins) through line endings only. They were left out of the commits.
