# bridges: the four landmark bridges as engineered structures (workstream `bridges`)

The user's feedback was "that neon bridge sucks too, make it like a construction", then "make a better
design". The bridges were thin stick pylons, glowing cyan cables and a thin flat deck. Every bridge is
now rebuilt by `tools/world/bridge_designs.py` as a believable civil-engineering structure, each with its
own character, textured with new Pigment sheets. The deck centrelines, grades and pier positions from
`world.json` are unchanged, and the drivable surface is still the road run.

| | |
|---|---|
| `design_options.png` | Three massing options per site in clay, at the real sites (deck line, grades, piers). The chosen design is framed |
| `port_before_after.png` | Minato Bay Bridge (cable-stayed, 629 m): night wide, dusk wide, a close-up of the pylon base, truss and anchorage, and the pylon head |
| `expressway_before_after.png` | Shinkai Expressway (1.55 km viaduct): night and dusk over the city, a close-up under the deck at a pier |
| `kagero_before_after.png` | Kagero Viaduct (398 m): night and dusk from the water, a close-up under the deck at the deepest pier |
| `tenjin_before_after.png` | Tenjin Arch (554 m): night and dusk from the water, a close-up from the walkway at the rib springing |
| `godot_before_after.png` | In the game: from the water, from the city shore, driving across the cable-stayed bridge, and the arch |
| `godot_drive_cable_stayed.png`, `godot_shore_cable_stayed.png` | Game screenshots: driving across the cable-stayed bridge (chase camera), and the bridge from the shore |

The Cycles shots are 1280 x 720 with the same cameras before and after (`tools/world/bridge_cams.py`).
"Before" is the base commit's builder (`world_build.py` at `081d2ff`). Most shots are 64 samples on the
GPU. The Kagero and Tenjin "after" shots are 48 samples on the CPU: the GPU was full of other agents'
Blender sessions, and the OptiX render hung twice.

## Designs

Each site got three options (`design_options.png`, `bridge_designs.OPTIONS`). The chosen ones:

| site | design | character |
|---|---|---|
| **port**: Minato Bay Bridge, `bay_expressway_*` (cable-stayed) | Concrete **H pylons** (chamfered octagonal legs, battered, tapering from 7.4 x 5.4 m to 4.8 x 3.3 m) with three cross beams: deck portal or pedestals, mid beam, crown. Steel anchorage boxes on the span faces of the legs. **112 semi-harp stays** (14 per side per plane, 2 planes) in pale HDPE with steel sockets, guide pipes and damper collars. Outrigger anchor beams at the deck. **Steel Warren truss deck** (4.6 m in the spans, tapering to 2.6 m at the abutments), with orthotropic deck plate, edge fairings, floor beams every 10 m, 4 stringers, bottom lateral X bracing, sway frames and a centre inspection catwalk. Portal approach piers, and pile caps with rubber fenders | Heavy, industrial, Yokohama Bay Bridge lineage. Main span 350 m with pylons 96 m above the deck (1:3.6) |
| **expressway**: Shinkai Expressway, `city_expressway_*` (viaduct) | **Brutalist board-formed concrete**: a single-cell box girder (2.4 m, the clearance over the crossed streets is unchanged) with 6.7 m cantilever wings whose soffit **sweeps** in a curve to the webs. Sculpted **tulip hammerhead piers** (superellipse section flaring from 4.0 x 2.8 m to 8.8 x 3.4 m). Elastomeric bearings with steel plates and a shear key, a longitudinal drain under one wing with downpipes on the piers, soffit inspection hatches, a rubber-sealed **expansion joint every 4 spans**, and **curved-top noise barriers** (steel posts, solid lower panels, tinted panels curving in over the road) | Shuto Expressway, cast in place |
| **kagero**: Kagero Viaduct, `kagero_viaduct_*` (girder) | **Weathering-steel plate girders** (4 lines) **haunched** over the piers, 2.1 to 4.1 m. Web stiffeners every 2.5 m, K / X cross frames every 6 m, a concrete deck slab with edge beams. **Battered twin-column portal piers** with a chamfered cap beam, a tie beam on tall piers, pot bearings and pile caps with fenders. A caged service ladder, a centre catwalk, drains and downpipes, and an **under-deck maintenance gantry** on one span (bogies on fascia rails, gridded platform, hazard ends, work lamps, signs) | Rugged, rusty and low-key |
| **tenjin**: Tenjin Arch, `tenjin_arch_*` (arch) | White steel **basket-handle network arch**: the box ribs lean inward from the tie line (11 m) to 2.3 m at the crown and taper towards it. Wind struts and X bracing between the ribs, and a crown slab with the gold **Hoshikawa plaque** (lit logo, aviation reds). **Network hangers** cross at +-22 m with sockets at both ends. A box tie girder stands 0.9 m above the deck and shields the walkway, with floor beams every 6 m. Sculpted thrust piers under the springings, and slender oval tulip columns under the concrete approach spans | The corporate showpiece, elegant and clearly designed |
| every other deck (21 hill streets and mountain decks) | Concrete box girder on single tulip piers with bearings, and a railing | |

**Construction and maintenance** (believable, not cluttered):

- The **second port pylon is under repair**. A tube scaffold wraps one leg from the pile cap to 26 m
  above the deck, with lifts, boards, zig-zag bracing and a works sign. **Hoshikawa hoardings** face the
  road at deck level.
- A **lattice tower crane** stands on the pile cap. It has a 2 m mast, a 55 m jib, a counter-jib with
  hazard-striped counterweights, an apex with pendants, a cab, a trolley and hook, and aviation lights.
- **Kagero** has the under-deck gantry.
- There are caged ladders on the pylons and piers, and catwalks under the port truss and Kagero.
- Signs (PIL-made, `assets/decals/bridges/`): DANGER / works, NO UNAUTHORISED ACCESS, inspection catwalk,
  and the route / load ID plate.

**Lighting**, with no neon:

- Red aviation lights on the pylon heads, at mid height, on the crane, and at the arch crown.
- Warm **uplight washes**: soft cards with the light baked in, the same in Cycles and Godot. They light
  the pylon outer faces from the pile cap and the span faces from the deck, the expressway columns from
  plaza fixtures, and the tall Kagero columns.
- Cool washes run up the arch ribs from the springings.
- In Blender, spot lights at the pylon bases.
- The deck lamps are the existing street lamps on the barriers.

## Materials (Pigment, `tools/world/bridge_textures.py`)

Seamless sheets in metres. `bridge_kit.BM` writes the UVs in metres and divides them by each sheet's tile
at the end. The Blender materials carry `pigment_folder`, so the Godot export packs them as ORM
materials (`godot.tex:bridge_*`).

| sheet | tile | layers |
|---|---|---|
| `bridge_concrete` | 4.8 m | Tone, pour lifts, aggregate, pitting. **2.4 x 1.2 m form-panel joints, tie holes on a 1.2 m grid** (cone and plug), **patch repairs**, tie-hole rust leaks. **Rain streaks**, joint runs, **rust bleeding from the tie holes**, **efflorescence**, grime |
| `bridge_steel_white` | 4 m | Paint tone, a **bolted splice plate** with 2 x 12 bolts, **rust at the bolt heads and runs bleeding below**, chipped paint, rust spots, salt grime runs, dust |
| `bridge_steel_weather` | 4 m | Weathering-steel patina (dark and orange), bolted splice, scale flakes, runoff streaks |
| `bridge_steel_grey` | 2 m | Grey paint worn to zinc, rust, grime runs. Used for railings, catwalks, sockets, scaffold and drains |
| `bridge_cable` | 1 m | Pale HDPE, **helical rib**, UV chalking, **grime runs**, soot |
| `bridge_hoarding` | 6 x 3 m | Hoshikawa logo, HOSHIKAWA SECURITY, the DANGER works notice, panel seams, a gold band, grime |
| `bridge_hazard` | 2 m | Yellow and black stripes, scuffs, grime |

- The deck asphalt is the shared road material (the road run itself).
- On a flat sheet the streaks generator has no geometry to drip from, so it made cloudy blotches. The
  runs are therefore placed decals of a run stencil: below the joints, tie holes and bolts, or scattered,
  all deterministic.
- `leaks` is kept as a light layer.

**Smart model:** `city/models/tile_set/bridge_sheets.toml`. Its recipe is `bridge_textures.py
--no-run`, and its Pigment nodes run the 7 scripts. `python -m tools.city build "godot.tex:bridge_*"`
rebuilds the sheets and their Godot packs: 36 s.

## Rebuild

```
python -m tools.city build bridge_sheets                # Pigment sheets (scripts, stencils, signs, washes)
python -m tools.city build world:build                  # gen + build + incremental export (or: python .citycache/run_node.py world:build, see merge notes)
python -m tools.city build "godot.tex:bridge_*" godot.images:world
godot --headless --path game --import
```

Fast iteration without the city (seconds):

```
blender -b --factory-startup --python tools/world/bridge_options.py -- --stats                 # build only the bridges, triangles per object
blender -b ... bridge_options.py -- --preview --close [--only port]                             # chosen designs on the terrain -> .citycache/bridges/
blender -b ... bridge_options.py -- --sheet                                                     # docs/agents/bridges/design_options.png
python tools/world/bridge_cams.py [--godot --out f.json]                                        # Cycles / game proof cameras
blender -b ... world_driver.py -- --stages build,verify,render --cams .citycache/bridge_cams.json --render-dir <dir> --res 1280x720
godot --path game -- --bridge-shots=<dir> --bridge-cams=<godot cams json> --clean [--spot-secs=6]
python tools/world/bridge_sheet.py --pairs <before dir> <after dir>
```

## Checks

- **World verify:** all zeros.
  - Terrain above roads: 0 of 60,000.
  - **Terrain through bridges: 0 of 4,857.** This now checks against the *built* depth per station
    (`built["bridge_depth"]`), not the 2.4 / 3.2 m from `world.json`.
  - Floating / buried props: 0 / 0. Floating buildings: 0.
  - Grades over the limit: 0 (highway decks 5.54-5.59%).
  - Footprint overlaps: 0.
  - Deck clearance over roads: 7.46 m (unchanged).
  - **Piers on roads: 0 of 105.** Each column of a portal pier is now checked on its own; before, one
    point was checked per pier.
- **`--drive-test` (world): pass.** All 9 checks pass: map drive 160 m, 0 auto-resets, 1,912 collision
  shapes.
- **`--traffic-test=60` (world): PASS.** All 7 checks pass, with 0 off-road samples and 0 AI collisions.
- `python -m pytest tools/city/tests`: 26 passed.
- No Rust changes, so `cargo test` is unaffected.

## Performance

Triangles (export, `world_layout.json`):

| | before | after |
|---|---|---|
| all bridge meshes | 134k | 368k: 163k structure (collision only on decks, piers, pylons), 201k details (drawn within 700 m), 3.1k stay tubes (within 450 m), 0.45k far stay ribbons (beyond 450 m), 0.3k washes |
| port / expressway / kagero / tenjin | 16k / 41k / 8k / 16k | 73k / 130k / 51k / 34k |

Godot, RTX 4070 Ti at 1920 x 1080, `--bridge-shots`, clean HUD. These are runs on a shared machine
(other agents' Blender sessions on the GPU), alternated after, before, after:

| view | before avg / 1% low | after (2 runs) avg / 1% low | draw calls / Mprims before -> after |
|---|---|---|---|
| driving across the cable-stayed bridge (3 legs of 6 s) | 182 / 107, 162 / 100, 133 / 74 | 139 / 95, 131 / 91, 162 / 79 and 139 / 92, 136 / 83, 133 / 87 | 464-511 / 0.56-0.67 -> 549-600 / 0.75-0.89 |
| port bridge from the shore | 253 / 101 | 222 / 142, 196 / 141 | 357 / 0.28 -> 399 / 0.30 |
| port bridge from the water | 211 / 153 | 284 / 155, 249 / 157 | 82 -> 102 |
| arch from the water | 196 / 141 | 414 / 178, 292 / 143 | 43 -> 58 |

- Driving across the cable-stayed bridge stays at **130-160 fps**, about 1 ms more GPU than before.
- Fixed views are within run-to-run noise.
- New loader categories (`town_loader.gd`):
  - `bridge_detail` is drawn to 700 m.
  - `bridge_near` (stay tubes) is drawn to 450 m.
  - `bridge_far` (stay ribbons) is drawn from 450 m (`VIS_BEGIN`).
  - `bridge_wash` casts no shadows.
- Collision: only `Girder_` and `Bridge_` are trimesh. `BridgeSteel_`, `BridgeDetail_`, `BridgeCables*`
  and `BridgeWash_` have none.

## Code

| file | what |
|---|---|
| `tools/world/bridge_kit.py` (new) | `BM` mesh builder (outward-wound faces for Godot's culling, metre UVs per sheet, used materials only), `Rail` stations along a road path, boxes / beams / tubes / lofts / sweeps / variable sweeps / ribbons, the materials (Pigment, flat, emissive, washes, signs, logo) |
| `tools/world/bridge_designs.py` (new) | The designs, the options, `Ctx` (collection, materials, ground sampler, pier records, lights), `build()` |
| `tools/world/bridge_textures.py` (new) | The Pigment recipes, stencils, signs and wash images |
| `tools/world/bridge_options.py`, `bridge_sheet.py`, `bridge_cams.py` (new) | Bridges-only builds, the options sheet, previews, stats, proof cameras, before/after sheets |
| `city/models/tile_set/bridge_sheets.toml` (new) | Smart model |
| `tools/world/world_build.py` | `build_bridge` is replaced by `bridge_designs.build` (heightfield sampler, `bridge_options=` arg). The old function is removed |
| `tools/world/world_verify.py` | Terrain-through-bridges uses the built depth when recorded |
| `tools/world/world_render.py` | `--cams` entries may set `sky` |
| `tools/godot/export_town.py` | `COLLIDE`: `BridgeSteel_`, `BridgeDetail_`, `BridgeCablesFar_`, `BridgeCables_`, `BridgeWash_` |
| `game/scripts/town_loader.gd` | `VIS_END` / `VIS_BEGIN` / `CAST_SHADOWS` entries, and the new categories as `single` |
| `game/scripts/automation.gd`, `main.gd` | `--bridge-shots` |

## Merge notes

- **Shared files**, all small additive edits:
  - `world_build.py`: the bridge call and the removal of `build_bridge`.
  - `world_verify.py`: one block.
  - `export_town.py`: `COLLIDE` lines.
  - `town_loader.gd`: three constants and a `single` branch.
  - `automation.gd`, `main.gd`: a new mode.
  - `world_render.py`: one line.
- **Regenerate after merging.** The world export must be regenerated (`city build world:build`, then
  `godot.tex:bridge_*`, then `godot --import`): the bridge glbs and new mesh keys. The old
  `Bridge_<name>.glb` files are no longer referenced.
- **Pigment projects.** `scenes/town/projects/bridges/*.pigment` are committed (as the world sheets
  are). The texture sets are git-ignored and rebuilt by the city build.
- **`scenes/world/world.json` is not committed.** Regenerating it in this worktree changed only the
  overhead-sign variants of 739 instances, from the props side, not bridges. The bridge data is
  untouched.
- **City build in a fresh worktree.** `city build world:build` also wants every props Pigment node,
  because their projects are not in the checkout. I ran the node alone with a tiny helper
  (`engine._one("world:build")`, the same action, cache and stamps). In a full checkout, plain
  `city build world:build` works.

## Known limits

- **Kagero reads dark and low-key at night.** Weathering steel in a dark bay is dark, and only the tall
  piers have washes.
- **The washes are cards.** A camera grazing a pylon face can see the card edge.
- **The design options are massing sketches.** Only the chosen designs have full detail.
- Stays are straight (no sag). Hanger and stay sockets are simple cylinders.
- The port deck sits low over the water (world data: about 4 m under the truss at the pylons), so the
  pylons' lower cross beam becomes pedestals on the pile cap.
- The expressway wide shot is a city canyon. The viaduct is mostly read from street level, so the
  close-up is the better proof.
