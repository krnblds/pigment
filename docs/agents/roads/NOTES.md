# roads: open-world roads with no seams

The town's roads used to be the 20 m `street_segment` piece repeated along each curve, and every
junction was a separate Pigment project. Each one had its own baked texture, so the asphalt tone,
paving grid and grime jumped at every 20 m join and at every junction mouth, and the manholes and
drains repeated every 20 m. The roads are now built the way open-world games build them:

- spline road meshes with continuous UVs;
- shared seamless materials authored in Pigment, plus a curb and gutter trim sheet;
- decals from a Pigment atlas for everything unique;
- world-space masks for wetness and macro variation.

| | |
|---|---|
| `join_before_after.png` | close-up at a run-to-run join (where pieces 2 and 3 of the old street met) |
| `junction_before_after.png` | close-up where run J1->J2 meets junction J1's mouth |
| `night_before_after.png` | low street-level night shot |
| `top_before_after.png` | orthographic top view of junction J1 and its runs: the old 20 m repeats vs. none |
| `pigment_sheets.png` | the Pigment textures: tiles shown 2x2 / 3x3 (no seams), trim sheet, decal atlas |

## 1. Pigment: flat sheet projects (seamless tile, trim sheet, decal atlas)

`new_project` takes `tile` instead of `mesh`. The project is a flat plane in world XZ (y up, in
metres; u -> +x, v -> +z) whose UVs fill the texture, so every generator works in true metres.
`pigment_core::tile::TileSpec` is stored in the document (`Document.tile`, serde default, so old
projects load unchanged) and survives save and reopen.

```json
{"tool": "new_project", "args": {"tile": {"size_m": [4, 4]}, "resolution": 4096, "material": "Asphalt"}}
{"tool": "new_project", "args": {"tile": {"size_m": 2.0, "strips": [{"name": "Curb top", "height_m": 0.3}, {"name": "Gutter", "height_m": 0.45}]}}}
{"tool": "new_project", "args": {"tile": {"cells": [{"name": "manhole", "size_m": [0.9, 0.9]}, {"name": "arrow", "size_m": [1, 5]}], "padding_px": 24}}}
```

`tile` args:

- `size_m`: `[w, h]` or a single number. For a trim sheet this is its width.
- `wrap`: `both | u | v | none`. Defaults: tile `both`, trim `u`, atlas `none`.
- `strips`: `[{name, height_m}]`. Makes a trim sheet. Strips stack from v = 0 down.
- `cells`: `[{name, size_m}]`. Makes a decal atlas, shelf-packed at one texel density.
- `padding_px` (atlas, default 16).
- `folders` (default true): one folder per strip or cell, masked to its part.
- `offset_m`: world `[x, z]` of the sheet centre. Moving a tile scrolls its pattern.
- `name`: the export name.

What wraps in a seamless tile:

- **Generators.** Every world-space noise is periodic over the tile (`composite.wgsl`: `fbm_s`,
  `fbm_p`, `vnoise_p`). Each noise scale is snapped so a whole number of lattice cells fits the
  period, and the lattice hash wraps, which makes a periodic hash lattice. Each octave rounds its
  period to stay a whole number.
  - This covers grunge, dirt, edge wear, spots (including its domain warp), scratches, streaks,
    stripes and panel lines.
  - In `gen_weather.wgsl` it also covers puddles, moss and leaks, and tiles: bricks get an even row
    count, columns and rows are snapped, and cell ids wrap; hexes are slightly anisotropic.
  - In tile mode, patterns are anchored to the world origin.
  - Outside tile mode `fbm_s` gets the original expression, so ordinary projects composite
    bit-identically to before.
- **Strokes and decals.** The GPU mesh of a sheet project is the plane plus copies one period away
  on each wrapping axis (`TileSpec::wrap_mesh`, `MeshGpu::with_wrap`). Brush stamps, camera decals
  and box decals rasterise all copies, so anything that crosses an edge comes back on the other
  side. The UV raster (position, normal and part maps) only uses the original
  (`MeshGpu::uv_index_count`). Undo tile tracking (`ScreenBins`, `Placement::mark_tiles`) uses the
  wrap mesh too, so one undo removes both halves.
- **Normals.** The finalize pass's height-to-normal wraps its texel neighbours (`twrap`), so the
  exported normal map is continuous across the edges.
- **Image fills.** UV tiling is rounded to whole repeats. Triplanar top projections are snapped to
  the tile.
- **Viewport.** The `render` tool shows the 3 x 3 neighbourhood, so seams would show at a glance.

A **trim sheet** strip is its own mesh part. Neighbouring strips get different grid column counts,
so they share no edge and stay separate parts. Each strip gets a folder masked to it, so
`add_layer {parent: "Gutter", ...}` lands only in the gutter. An **atlas** cell is a part with a
folder, and the atlas base starts transparent (opacity 0).

`export_textures` also writes these for sheet projects:

- `<name>_layout.json`: kind, size_m, wrap, resolution, texels_per_m, and per strip or cell its
  name, part, `uv` (v down), `uv_gl` (Blender / OpenGL, v up), `px` and `size_m`.
- For atlases, `<name>_BaseColorAlpha.png`: sRGB colour with opacity as alpha, transparent outside
  every cell (seam padding would otherwise smear cells into the gaps).

Code: `crates/core/src/tile.rs`, `crates/app/src/app/automation/sheet_tools.rs`, plus small hooks:

- `automation.rs`: `new_project`, `export_textures`.
- `app.rs`: `load_mesh_gpu`, the `wrap_mesh` field, `ScreenBins`.
- `app/decals.rs`: `mark_tiles`.
- `render/mod.rs`: `uv_index_count`, `with_wrap`.
- `render/texset.rs`: `tile_period`, and the shared uniform `res.zw`, which was unused before.
- The `pigment-mcp.rs` schema.

There is no UI entry yet (`ui.rs` is untouched): a sheet project is MCP / `Session` only, but
opens and paints normally in the app once saved.

## 2. Content (Pigment scripts)

`python tools/road_textures.py --run` writes `assets/decals/roads/*.png` and
`scenes/town/scripts/roads/*.jsonl`, then runs every script:

| script | sheet | what |
|---|---|---|
| `asphalt` | 4 x 4 m tile, 4096 | binder tone, 3 aggregate sizes, worn binder, pores, crack network (ridged `scratches`) + tar sealing, hairline cracks, damp low spots, dust |
| `paving` | 2 x 2 m tile, 2048 | 0.5 m slabs (`tiles` square) over dark recessed joints, moss in joints, slab tone, chips, stains, gum |
| `setts` | 2 x 2 m tile, 2048 | granite setts in running bond, polish, grime (made, not used in the town yet) |
| `concrete` | 2 x 2 m tile, 2048 | cast tone, pores, aggregate, hairline cracks, water stains, moss (road skirts, retaining walls, stairs) |
| `trim` | 2 m trim sheet, 2048 | strips Curb top 0.30, Curb face 0.20, Gutter 0.45, Walk edge 0.35, Kerb paint 0.20, Drain grate 0.50. Joints, red kerb blocks and grate slots are box decals of a bar stencil; the rest are generators per strip folder |
| `atlas` | decal atlas, 4096, 18 cells | zebra bar, stop line, lane dash, 3 edge-line variants, 2 arrows, 3 crack networks, 2 patches, manhole, drain grate, 2 oil stains, tyre skid |

All of the material, wear and relief is Pigment:

- generators on fill layers;
- `project_decal` (anchored on each cell's part, `face: top`) for shapes;
- opacity painting;
- an edge fade on crack and oil cells, made by stamping a soft ellipse into a layer mask.

The stencils are only white shapes with alpha.

Each script exports to `scenes/town/textures/roads/<name>/` (git ignored) and saves
`scenes/town/projects/roads/<name>.pigment`. The whole run takes about 35 s.

## 3. Blender (headless)

`tools/town_roads.py` is loaded by `tools/blender_town.py`.

- **Meshes.** Runs and junctions share one cross-section. In metres from the curb line:
  - asphalt to -0.4;
  - gutter -0.4..0;
  - curb face, then curb top 0..0.25;
  - walk edge 0.25..0.6;
  - paving 0.6..3.0;
  - concrete skirt.

  Heights are the same as the old kit: road 0.2, curb 0.355, walk 0.35.
  - Asphalt UVs are **world-space planar** (metres) on runs and junctions alike, so a run flows
    into a junction with no seam.
  - Paving and trim use an along-path U that is scaled to a whole number of 2 m tiles between
    junction mouths, and on each junction corner from mouth to mouth. Paving V is the distance
    from the walk edge. Slab grids, curb joints and trim strips therefore line up at every join.
  - Curb, gutter and walk-edge faces map onto their trim strips through `trim_layout.json`.
  - Junction asphalt is gridded so the wetness attribute and shading have interior vertices.
- **Materials.** There is one material each for every piece: `RoadAsphalt`, `RoadPaving`,
  `RoadTrim`, `RoadConcrete`, and `RoadDecals` for the atlas.
  - Anti-tiling: a second sample of the same tile, rotated 37 degrees and offset, blended by
    world-space noise. Relief goes through a Bump node on the height maps, so the blend stays
    correct.
  - Macro variation: world noise at about 20 m drives the tone (±25 % on asphalt) and the
    roughness.
  - Concrete is world box-mapped. It is also used for retaining walls and stairs when the tiles
    exist.
- **Wetness.** In the shader, puddles come from three things: world-space noise, a per-vertex
  `wet_bias` attribute, and the texture's own low spots (height).
  - `wet_bias` is high in gutters, at the sag points of each run's grade profile, and along
    junction curbs.
  - Where it is wet the shader darkens the colour, sets roughness to 0.03 and flattens the bump.
    Damp rims are less rough.
  - Decals get the same mask, so paint in a puddle is wet too.
- **Decals.** `RoadDecals` is one mesh of quads, gridded every 0.5 m so they follow the road's
  curve and grade, 6–12 mm above the surface. Each category has its own height, so overlaps never
  z-fight. Everything is seeded (`town_roads.SEED`) and randomly spaced, with no fixed period. Per
  run:
  - edge lines in 4 m pieces, each a random wear variant out of 3;
  - centre dashes;
  - turn or straight arrows in the incoming left-hand-traffic lane before junctions;
  - cracks (about 1 per 11 m), patches, oil, skids, manholes every 32–58 m, and gutter drains
    every 18–34 m.

  Per junction: zebra bars and a stop line at every arm mouth, plus some wear in the middle. A
  full build has about 970 decals.
- **Fallback.** Without `scenes/town/textures/roads/`, the same meshes get the old flat fallback
  materials and no decals, and a message is printed.
- **Cleanup.** These are gone: `sweep_street`, `dense_street`, the junction UV packer,
  `assets/town/junction_j*.glb` and `.parts.json`, `scenes/town/scripts/junction_j*.jsonl`,
  `scenes/town/projects/junction_j*.pigment`, `tools/town_junction_textures.py` and the driver's
  `--export-junctions`. The `street_segment` kit piece and its texture script are still in the
  repo, but the town no longer places it.

## Running it

```
cargo build --release -j 6 --bin pigment-mcp
python tools/road_textures.py --run                      # textures -> scenes/town/textures/roads/
blender -b --factory-startup --python tools/town_layout_driver.py -- --verify --no-render   # builds, verifies, saves the .blend
blender -b --factory-startup --python tools/roads_proof.py -- --out target/roads/after      # proof shots
```

`roads_proof.py --town <file>` renders the same shots with another `blender_town.py`. The "before"
images used master's.

## Tests

- core `tile::tests` (4):
  - the plane is sized in metres, faces up, and its wrap copies come first;
  - trim strips are separate parts in order, with the layout JSON;
  - atlas cells don't overlap, keep their size and use more than 45 % of the sheet;
  - serde round trip and defaults.
- app `app::tile_tests` (GPU, through `Session`):
  - `seamless_tile_maps_wrap`: a 9-layer stack using every noise kind (including bricks, hexes,
    panel lines, puddles and moss).
    - A tile scrolled by half a period in x and a quarter in z gives the same maps, rolled.
      Colour, normal and ORM all differ by less than 1–1.5 / 255. Unrolled, they differ by over
      5x as much.
    - The left/right and top/bottom edge texels differ no more than interior neighbours do.
    - The height gradient extrapolated across the seam is as accurate as it is in the interior.
  - `strokes_and_decals_wrap_across_tile_edges`:
    - a box decal over the right edge appears on both sides, and one undo removes both halves;
    - a brush stroke past the left edge continues on the right.
  - `trim_and_atlas_layouts`:
    - folders per strip, and a layer in the Gutter folder lands only at v 0.25..0.5;
    - `trim_layout.json` (`uv` and `uv_gl`);
    - save and reopen keeps the sheet and its wrap period;
    - atlas cells start transparent, a cell's layer makes only that cell opaque, and
      `BaseColorAlpha` is written;
    - bad args fail.
- Every `scenes/town/scripts/roads/*.jsonl` passes the existing `every_repo_script_matches_the_tool_schemas`.
- `cargo test --release -- --test-threads=2`: all green (app 61 passed / 5 ignored, core 103, pigment-mcp bin 4).
- Layout `--verify`: 20,000 samples, **0 points of terrain above a road or sidewalk**, 0 floating
  lamps or poles.

## Known limits

- Noise scales are snapped to whole cells per tile, so a tile's grunge or brick size can differ a
  few % from the number in the script. A rotated triplanar image fill doesn't tile.
- The asphalt is world-planar, so its grain doesn't follow the road direction. That's fine for
  isotropic asphalt; directional wear (wheel tracks) comes from decals.
- Paving U is mirrored at junction mouths, because along-coordinates run away from each mouth.
  The mirror line always falls on a slab joint, so it doesn't show. Paving is stretched slightly
  on tight outer curves.
- Edge lines are 4 m decal pieces. A lane line drawn as one continuous strip with a tiling cell
  would avoid the tiny gaps where pieces meet on tight curves.
- Junctions are still flat (as before), and the decals assume flat cross-sections (no camber).
- The atlas project is 16 MB in git (4K paint layers).
- The puddles are sparser than the old baked ones. The threshold is `lo` in
  `town_roads._wetness`: lower it for a wetter street. At night, a puddle only reads where it
  reflects a light.
