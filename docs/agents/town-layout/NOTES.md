# town-layout: road network, junctions, hillside terrain

User feedback: "The way roads connect needs to be better". Their screenshot showed humps of paving
beside buildings and at curbs, branch roads overlapping the crossroad sidewalks with curbs that
didn't line up, the open arm of a T-junction leading nowhere, and pinched curves.

## What I built (`tools/blender_town.py`, rewritten)

- **Road graph.** `NODES` holds 5 junctions: an X, two T and two Y forks. Each has an elevation and
  its arm angles. `EDGES` joins arm to arm, or an arm to a free end at the map edge, with optional
  waypoints. Every arm continues into a road, so no arm is left dead.
- **Procedural junctions (`Junction`).** The geometry comes from the arm angles:
  - curbs are filleted between neighbouring arms (r 6 m on concave corners, 3 m on convex ones);
  - the curb and sidewalk lines are concentric offsets of the same fillet, so corner sidewalks are
    continuous;
  - each arm ends in a mouth with exactly the street kit's cross-section (road ±4 m at z 0.2, curb
    0.25 m, sidewalk to ±7 m at z 0.35), so the runs butt on cleanly with no overlap;
  - zebra crossings and stop lines are painted at every mouth;
  - arm length is computed so the fillets always fit.
- **Runs.** `sweep_street()` tiles the Pigment-textured `street_segment` along each 3D path. It
  replaces the Curve modifier. Arc length maps to x and the path normal maps to y, with z kept
  vertical. Tiles are stretched evenly so they end exactly at the junction mouths.
- **Smooth paths.** The splines are length-normalised Hermite curves, so uneven control points no
  longer overshoot or cusp. That overshoot was the old "pinch". The minimum radius is printed per
  edge (≥ 11 m against a 7 m half width). Grades ease to 0 at each junction (flat junctions) and
  stay under 10 % in between.
- **Terrain.** Every point takes the level of the nearest road's sidewalk (−1 cm) within 25 m, the
  building lots. Beyond that it takes a blend of road levels plus rolling hills. The grid is 0.6 m
  and is ray cast against the road and junction meshes:
  - grid faces under asphalt are deleted;
  - vertices under sidewalks sit 1.5 cm below them.

  No humps, no curb steps baked into the heightfield.
- **Retaining walls.** Where the level field steps (> 0.35 m), marching squares finds the step.
  Each crossing is bisected onto the exact step line, chained, smoothed and built as a 1.9 m-thick
  wall that swallows the steep grid triangles. Railings run on wall tops over 1 m.
- **Stairs.** Stairs climb along tall walls on their low side: 0.17 m risers, solid to the ground,
  with a handrail and lights at the top and foot. Buildings keep their foot and top clear.
- **Buildings.**
  - Front rows face the street and also fill the junction corners. Back rows fill the hillside.
  - Each building sits at the highest ground under its footprint, on a concrete footing that
    reaches 0.8 m below the lowest ground, so slopes keep their footings.
  - Sites must clear roads (7.25 m), walls and other buildings.
  - About 22 % of gaps are 2.6–4 m alleys with a coloured alley light.
- **Variant contract.** `variant_materials()` scans `scenes/town/textures/<asset>__<variant>/` for
  `<asset>_BaseColor.png`, builds `Pigment_<asset>__<variant>` with `apply_pigment_material`, and
  assigns a random one per instance through an object-level material slot (kit mesh stays linked).
  The kit material stays in the mix. With no variant folders, every instance uses the kit material
  from `scenes/town/textures/<asset>/`. I tested this with a temporary red `building_a__redtest`
  folder; mixed instances rendered correctly.
- **Street furniture.** Lamps alternate sides every 22 m, with more lamps on junction corners.
  Power poles every 31 m carry five sagging wires each.
- **Story set-dressing (Blender-side only).** Story decals are pasted on the retaining walls, which
  are Blender materials and not Pigment surfaces:
  - MISSING / UNPLUG posters, graffiti, curfew plates;
  - lit Meridian / Dreamlink / Noctis billboards on walls over 5.5 m.

## Pigment for the generated junctions

1. `town_layout_driver.py --export-junctions` writes `assets/town/junction_j1..j5.glb`
   (junction-local, planar top UVs in [0, 0.86], curb faces packed as strips in u > 0.88). It also
   writes a `.parts.json` sidecar that labels every connected part (road / curb / walk / paint) by
   its glTF-space bounding box.
2. `python tools/town_junction_textures.py` lists parts with Pigment and matches them to the
   sidecar. It then builds the same stack as `town_textures.street()` on those part masks:
   - asphalt, cracks, puddles;
   - concrete curbs;
   - paving with joints and grime;
   - zebra paint with wear;
   - wet grime.

   It exports to `scenes/town/textures/junction_*/` and saves `scenes/town/projects/junction_*.pigment`.
   About 2 min per junction at 4096.
3. The next build picks those maps up automatically. Without them, flat fallback materials are used.

No MCP tools were added. This workstream only uses `new_project`, `bake`, `list_parts`,
`add_layer` (part masks), `render`, `export_textures` and `save_project` via `pigment-mcp --script`.

## Running it

```
cargo build --release -j 4 --bin pigment-mcp
copy target/release/pigment-mcp.exe target/showcase/release/   (path town_textures.py expects;
                                                                 or set PIGMENT_MCP for junctions)
python tools/town_textures.py                      # kit textures (git-ignored folder)
blender -b --factory-startup --python tools/town_layout_driver.py -- --export-junctions
python tools/town_junction_textures.py
blender -b --factory-startup --python tools/town_layout_driver.py -- --verify
```

The driver options are `--samples`, `--res`, `--shots`, `--no-render`, `--no-save`, `--verify`,
`--debug <filter>` (daylight top/oblique views to `target/debug_shots/`) and `--layout <old.py>`.

## Tests / proof

- `--verify` picks 20,000 random points on the road and junction top faces and ray casts the
  terrain above each one. **0 points where the terrain is above a road or sidewalk.** It also found
  **0 floating lamps or poles**: every one rests on a road or terrain surface within 5 cm.
- Renders (Cycles, OptiX, night, fog, lamp lights) in this folder:
  - `before.png`: the old layout;
  - `overview.png`;
  - `yfork.png`;
  - `tjunction.png`;
  - `crossroads.png`;
  - `stairs.png`.
- The build takes ≈ 40 s. Each shot takes 1–4 min at 1440×810 with 128 samples.

## Known limits

- The junctions are flat. Grades happen only on the runs, which is how real hill towns do it, but
  it means no junction sits on a slope.
- The terrain is a 0.6 m grid. Where a step is under 0.35 m there is no wall, just a short ramp.
- Wall and stair concrete is a Blender procedural material, not Pigment. A Pigment wall tile would
  be a good follow-up.
- On tight bends the kit's curb props (drains, covers) compress slightly on the inner side.
- Building facades are set back by the kit bounding box (awnings included), which leaves a 1–2 m
  forecourt.
- The kit `crossroad.glb` is no longer placed. Junctions are generated instead.
