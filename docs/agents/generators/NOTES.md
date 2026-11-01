# Workstream: generators (urban weathering)

Five new procedural mask generators for a rainy cyberpunk city, plus two new
mesh bakes they need. All are reachable from the MCP (`add_layer` /
`update_layer` `mask.generator`, also as mask `effects`) and from the UI
generator list (Layer > Mask > Generator), with per-kind slider labels.

| id (MCP) | GPU id | What | Uses |
|---|---|---|---|
| `leaks` | 10 | Drip streaks that start under protruding features (sills, AC units, balconies, eaves) and run down the wall below, fading over the drip length | **drip bake**, AO, world normal, world position |
| `puddles` | 11 | Standing water on near-level, rain-exposed surfaces: low spots of a micro-relief, concave gutters, occluded corners. Drive low roughness + darker colour | **rain-exposure bake**, curvature, AO, normal, position |
| `moss` | 12 | Moss / grime build-up on up-facing ledges and in AO crevices / concave corners, in clumps | AO, curvature, normal, position |
| `tiles` | 13 | Bricks (running bond), square tiles or hexagons with per-cell jitter; amount = fraction of cells kept (invert for mortar) | normal, position |
| `window_grid` | 14 | Storey-high cells on walls, a random `amount` of them lit, brightness varied by breakup; for buildings whose windows aren't separate parts | normal, position, mesh bounds |

Aliases accepted by `generator`: `drips`, `wetness`, `bricks`/`brick`/`square`/`hex` (also pick the tile variant), `windows`.

## Parameters (existing slots, as packed into `gp` / `gp2`)

`gp = amount, softness, scale, breakup`; `gp2 = seed, ao_influence slot, curvature_weight slot, variant`.
Only one new field: `Generator::variant` (`gp2.w`, serde default 0, skipped when 0, so old projects are unchanged).
Named MCP args map onto the slots (`apply_weather_fields` in `automation.rs`):

- **leaks**: `scale` streaks per metre across the wall, `breakup` how broken into runs, `drip_length` (m, = `curvature_weight`, default 2.5), `ao_influence` extra damp under overhangs.
- **puddles**: `scale` puddles per metre, `breakup` relief contrast, `curvature_weight` pooling in cavities/gutters, `ao_influence` pooling in corners.
- **moss**: `scale` clump frequency, `breakup` clump contrast, `ao_influence` crevice growth, `curvature_weight` concave-corner growth.
- **tiles**: `variant` `bricks|square|hex` (or 0/1/2), `scale` rows per metre, `aspect` cell w/h (= `curvature_weight`, 2 for bricks, use 1 for square), `mortar` (fraction of a row, = `ao_influence`), `breakup` row-offset jitter + tone variation.
- **window_grid**: `cell_size` (m, storey height, = `scale`), `aspect` cell w/h, `frame` (fraction of the cell, = `ao_influence`), `fill` / `amount` lit fraction, `breakup` brightness variation, `seed` picks which cells. Two layers with the same seed and amounts a < b light nested subsets (`amount 1` = every pane, for dark glass under the lit ones).

Example (MCP script line):
```json
{"tool": "add_layer", "args": {"name": "Leaks", "mask": {"generator": "leaks", "parts": [1, 39, 40], "amount": 0.55, "scale": 2.5, "breakup": 0.6, "drip_length": 3.0}, "values": {"base_color": [0.05, 0.045, 0.04], "roughness": 0.3}, "opacity": 0.75}}
{"tool": "add_layer", "args": {"name": "Lit windows", "mask": {"generator": "window_grid", "cell_size": 3.2, "aspect": 0.55, "frame": 0.2, "fill": 0.3}, "values": {"emissive": [1, 0.72, 0.42], "emissive_strength": 2.4}}}
```

Also new: `render` takes `target: [x, y, z]` (orbit centre in world metres) for close-ups.

## New bakes (`bake` tool; both automatic, in the unused channels of the bakes texture)

- **bakes.b = drip**: `1 / (1 + metres down to the nearest protrusion above)`, 0 where nothing sticks out above. The mesh is cut into horizontal slices (step = height / 256, at least 2 cm); per slice an orthographic depth map looks straight *up* from the slice top, so it holds the lowest surface above it within 6 m. Wall texels in the slice band look up the column just outside their wall (pushed out ~2.5 depth texels, about 1-2 cm, along the horizontal normal): anything there sticks out of the wall above them. This finds the *nearest* feature, so stacked sills on every floor each get their own leaks (the AO shadow maps only keep the first hit from above). Depth map size scales with the mesh (~8 mm texels, 512..4096). `render/bake.rs: bake_drip`, `bake_ao.wgsl: fs_drip`.
- **bakes.a = rain exposure**: fraction of near-vertical directions (cos-weighted towards straight up) from which the texel is unoccluded at any distance, computed in the existing AO pass. Open ground ~0.9, a wall ~0.5 (rain from its own side), under an awning ~0. Unbaked default 1.

Bake cost: up to 257 extra depth renders plus full-screen passes (like the AO's 128 directions); not separately timed, and the whole 4096² building_a script, bake included, runs in well under a minute here.

## Proof

- `building_leaks.png`: building_a, Pigment render tool, before/after. Leaks run down from under every sill, AC unit, balcony and the awning edge, nowhere else.
- `building_ledges.png`: roughness view from above: rain water standing on the awning and balcony floors, leak streaks on the walls.
- `street_puddles.png`: street_segment, grunge puddles (before) vs the puddles generator + damp rim (after), material and roughness views.
- `tower_windows_tiles.png`: a plain tower with no modelled windows (made in headless Blender, `make_tower.py`): window grid (dark glass + 30% warm + 6% cyan lit), brick base below the first-floor ledge (tiles + ground-gradient effect), square tiles on the ledge, leaks under the ledge and AC units.
- `blender_night.png`: headless Blender (Cycles, OptiX) of building_a at night on a wet street, before/after, with Pigment-exported textures (`blender_night.py`, uses `tools/blender_pigment.py`).

Reproduce: `cargo build --release --bins`, then `python docs/agents/generators/make_demo.py 4096`, `blender -b --factory-startup --python docs/agents/generators/make_tower.py -- target/pg/tower.glb`, `python docs/agents/generators/tower_demo.py`, `blender -b --factory-startup --python docs/agents/generators/blender_night.py -- assets/town/building_a.glb target/pg/building_a_tex building_a target/pg/night_after.png`, `python docs/agents/generators/compose.py`.

Town pipeline: `tools/town_textures.py` now adds Leaks (shell), Ledge moss and Rain water (shell + trim + roof parts) to every building, and replaces the road's grunge puddles with the puddles generator plus a damp rim.

## Tests

- naga: `shader_tests::composite` and `shader_tests::folder` validate `composite.wgsl + gen_weather.wgsl` (+ `folder.wgsl`); `bake_ao` / `bake_resolve` cover the bake changes.
- GPU (`gpu_tests_weather.rs`, a facade test mesh: wall, 30 cm sill, ground):
  - `drip_and_rain_bakes_see_the_sill`: drip under the sill ~0.66, 0 on open wall; rain exposure ground 0.88 vs wall 0.55.
  - `leaks_run_down_from_under_the_sill`: under the sill 0.61, open wall and ground 0; fades with distance.
  - `puddles_and_moss_settle_on_up_facing_surfaces`: puddles ground 0.50, wall 0; moss sill top 0.94, ground 0.48, wall 0.
  - `tiles_and_window_grid_are_regular_patterns`: bricks ~11% mortar, half-kept at amount 0.5, hex mortar; window grid all / none / half lit, never on the ground.
- core: generator ids round-trip (`generator_kinds_round_trip_by_id` covers the new kinds); old generator JSON still loads.
- `cargo test --release`: all green (42 app/GPU + 85 core, 5 ignored as before).

## Edge wear vs Substance (documented behaviour)

Substance 3D Painter's Metal Edge Wear generator documents: Wear Level (total amount), Wear Contrast, Grunge Amount / Scale, Edges Smoothness, Ambient Occlusion Masking (keeps occluded areas free of wear), Curvature Weight ("a very low weight can remove all edge wear, leaving only the grunge"), triplanar grunge, and optional micro height / normal details feeding the curvature. Pigment's `edge_wear` (`v = convex_curvature * curvature_weight + (noise - 0.5) * breakup - (1 - AO) * ao_influence`, then `smoothstep` around `1 - amount` with `softness`) maps one-to-one: amount = Wear Level, softness = Wear Contrast (inverse), breakup/scale = Grunge Amount/Scale (world-space 3D noise, so no triplanar seams), ao_influence = AO masking, curvature_weight = Curvature Weight (0 leaves only noise, as documented), bake `curvature_radius` = Edges Smoothness. The behaviour matches, so I made no code change. Gaps: no custom grunge texture, and painted height / normal details don't feed the curvature (Substance's Micro Height / Micro Normal). Source: https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/metal-edge-wear

## Known limits

- Drip bake assumes Y up and metres; protrusions thinner than ~1-2 cm (the outward probe offset) don't count; a feature is only found within 6 m above. Water is not routed along sloped surfaces (leaks run straight down).
- Puddle "low spots" come from a world-space micro-relief plus mesh cavities; there is no flow simulation over the real geometry (a hillside road doesn't drain downhill).
- Tiles / window grid use a dominant-axis surface frame, so they suit axis-aligned walls; on angled facades the grid stretches.
- The window grid starts at the mesh's min corner; use a ground-gradient effect (op subtract) to keep a shop floor free of windows, as the tower demo does.
- `town_textures.py` changes only take effect when the lead regenerates the town scripts / textures.
