# City build: change one asset, see it in the running game

`tools/city` builds the whole city (kit meshes, Pigment textures, decals, the open world, the
Godot project) from **smart models**, one manifest per asset, and rebuilds only what a change
touches. While the game runs with `--live`, results are hot-swapped in place.

```
python -m tools.city status              # what is stale, and why
python -m tools.city build               # rebuild what is stale (in parallel, GPU-aware)
python -m tools.city watch --live        # rebuild on every save, swap into the running game
```

`python tools/city.py ...` works too.

## First run in a checkout

The generated assets (textures, world export, Godot copies) are git-ignored. Either build them
(`city build`, hours of GPU for every Pigment set) or copy them from a checkout that has them,
then tell the build they are current:

```
python -m tools.city discover        # only when city/models is missing or you add assets (--refresh updates facts)
python -m tools.city adopt           # stamp every node whose outputs already exist (runs nothing)
python -m tools.city status          # -> 338 node(s): fresh 338
```

`pigment-mcp` comes from `target/release/` (this checkout, else the main checkout), or
`$PIGMENT_MCP`. Blender and Godot are found at their usual paths, or `$CITY_BLENDER` / `$CITY_GODOT`.

## Smart models

`city/models/<kind>/<name>.toml`, kinds: `building`, `prop`, `vehicle`, `road_set`, `decal_set`,
`tile_set`, `sky`, `terrain`, `district`, `world`. A model is the one place to change an asset:

| section | what it drives |
|---|---|
| `[mesh]` | the generator (`runner`, `generator`, `args`, `outputs`) and its **`params`**, passed as `$CITY_PARAMS` (props read them with `Prop.param()`) |
| `[recipe]` | the script that *writes* the Pigment script (`tools/town_textures.py` job, `props_textures.py --no-run`, ...) |
| `[pigment]` | the Pigment scripts it runs, their variants, decals and decal slots (read from the scripts), and **`patch`** ops applied before running |
| `[export]` | the textured game export (props, vehicles) |
| `[game]` | collision, streaming policy (`cell` / `heavy` + far proxy / `region` / `merge` / `single`), LOD, lights, the mesh keys in `world_layout.json` |
| `[placement]` | where the world puts it: counts per district, the scatter rule (from the props catalog) |
| `[config]` | (world, terrain, district) deep-merged into `tools/world/world_config.json` before the world is generated |

Fields listed in `model.derived` are facts read from the pipeline (`discover --refresh` updates
them); everything else is yours.

### Examples

Make the bollards taller (mesh parameter):

```toml
# city/models/prop/bollard.toml
[mesh]
params = { height = 1.6 }
```

Repaint building_b's shell without touching `tools/town_textures.py` (Pigment patch):

```toml
# city/models/building/building_b.toml
[pigment]
patch = [
  { match = { tool = "add_layer", name = "Teal paint" }, set = { values = { base_color = [0.62, 0.07, 0.05] } } },
]
```

`match` selects script steps by tool and argument values (dotted keys reach nested args);
`set` merges into their args; `{append = {tool = ..., args = ...}}` inserts a step before the
first export.

Move a district (world config override):

```toml
# city/models/district/downtown.toml
[config]
radius = 380
```

Then `python -m tools.city build` (or let `watch` do it).

## What a change rebuilds

Every build step is a node; edges come from the files each step reads and writes. A node is
stale when the hash of its inputs, its tools (the scripts that implement it) or its parameters
changed. After a node runs, its consumers compare the *new* file hashes: a step that produced
identical bytes stops the rebuild there (early cut-off). Outputs go into a content-addressed
cache (`.citycache/objects`), so undoing an edit restores the old outputs instead of rebuilding.

| you change | rebuilds |
|---|---|
| a decal image (`assets/decals/story/*.png`) | the Pigment scripts that project it, their texture sets' Godot packs, image materials that show it directly (tower billboards) |
| a building's recipe (manifest `patch`, or its part of `town_textures.py`) | that building's Pigment run (all its variants), their Godot packs. Editing `town_textures.py` re-writes every town script, but Pigment only re-runs where the script text changed |
| a prop's mesh parameter | its mesh, Pigment script + run, export, the props index, its world glb, its Godot pack. The world itself is **not** regenerated (it only reads the placement-relevant part of the props index) |
| a kit building's mesh script | its mesh, Pigment, and its world glbs (`world.mesh:<asset>`, one per variant): seconds, not the 4 km world |
| world config / world scripts / seed | the world (gen + build), then only the world glbs whose geometry changed (fingerprinted) |

Godot's headless re-import (`godot.import`) runs last; it is not needed for the live swap.

## Commands

```
city status [targets] [-v]          stale nodes and the reason (input / tool / parameter / upstream / output changed)
city build [targets] [--dry] [--force] [--pool pigment=1] [--keep-going] [--no-import] [--live] [-v]
city watch [targets] [--fast] [--import-after]
city verify [gates]                  world verify (Blender), road obstacle scan, decal audit, pigment-mcp --check on every script
city graph [--out f.html|f.dot]      the graph with each node's state; .citycache/graph.html by default
city show <model>                    a model, its nodes and their state
city open <model>                    its Pigment project in the Pigment app (save there; watch picks it up)
city unpin <node>                    a project edited in the app stops being the source of its textures
city adopt [targets]                 stamp existing outputs as built
city clean [targets] | --gc | --all
city live ping | screenshot <png> | '<json event>'
```

Targets are node ids (`pigment:building_a`), model names (`building_a`, `prop/bollard`), node
kinds (`pigment`, `world.mesh`) or globs (`godot.tex:building_b__*`). A target builds with
everything upstream of it.

Pools: at most `pigment=2`, `blender=1`, `godot=1` jobs at once (GPU / RAM); CPU steps use half
the cores.

## Hot swap

Run the game with the live link, then build or watch:

```
godot --path game -- --live [--no-traffic]
python -m tools.city watch --live
```

`game/scripts/live_link.gd` (an autoload, idle without `--live`) tails
`game/assets/.live/events.jsonl` and acknowledges each event in `acks.jsonl`. It reads the
changed files straight from disk (no import wait):

- a texture set: every material using that folder gets the new albedo / ORM / normal / emission;
- an image: every image material showing it;
- a mesh: every MultiMesh cell (streamed in or not yet), single mesh and merged region that uses it;
- emissive scale / opacity changes from the layout.

The car keeps its position; nothing restarts. Collision and the far proxy boxes are not rebuilt
by a swap (a restart does that).

**Blender**: the Pigment Bridge add-on's timer also reads `.citycache/blender_events.jsonl`:
texture-folder events rebuild the linked Pigment materials, mesh events swap the mesh of objects
tagged with `core.link_city_mesh(obj, glb)`.

**Pigment**: `city open building_c` opens the project in the app. When you save, `city watch`
sees a project it did not write and *pins* the node to it: the texture sets are exported from
your saved project (not the recipe) and flow downstream; `city unpin pigment:building_c` goes
back to the recipe.

**`watch --fast`**: when only decal images changed, the Pigment node re-exports just the
variants that show them from the saved project (`open_project` + `export_variants only=`). It is
marked partial, so the next plain `city build` runs the full script.

## Measured

See `docs/agents/citybuild/NOTES.md` for the timings and the hot-swap proof images.
