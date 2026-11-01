# traffic: living traffic for the Godot game

The night town now has traffic. Cars follow lanes and keep their distance from the car ahead. They
stop at red lights, give way at junctions and change lanes. They brake and honk for the player, and
the player can shove them around. Parked cars line the kerbs, Hoshikawa Security cruisers patrol
with their light bars flashing, and pedestrians walk the sidewalks.

Everything is data-driven:

- **Roads** come from a lane graph. It is built from the town layout now, and from the world
  workstream's `world.json` when that lands.
- **Vehicles** come from a vehicle index. Today that is a stand-in fleet made from the hero car;
  the fleet workstream's `assets/vehicles/index.json` replaces it when synced in.

Both drop-ins are already exercised against the other workstreams' current output (see "Tests").

| | |
|---|---|
| `01_busy_junction.png` | the J1 crossroads at night, signals running |
| `02_red_light_jam.png` | a queue held at a red light (brake lights; the props' pole light showing red) |
| `03_chase_traffic.png` | chase cam: the autopilot drives the hero through traffic |
| `04_security_cruiser.png` | a Hoshikawa Security patrol, light bar flashing |
| `perf.json` | numbers from the same run (see "Performance") |

## How to run

```
# once: the town (git-ignored), see docs/agents/godot/NOTES.md "Regenerate", then
godot --headless --path game --import
godot --path game                                    # play: traffic is on by default (--no-traffic to skip)

# optional: the fleet / props workstreams' assets (git-ignored copies), then re-import
python tools/godot/sync_vehicles.py [--src <checkout with assets/vehicles>]

# tests and proof (user args after "--")
godot --headless --path game -- --traffic-test=60 [--traffic-out=res.json]          # town, exit 0 = pass
godot --headless --path game -- --no-town --world=res://tests/data/test_world.json --traffic-test=60
godot --headless --path game -- --no-town --world=<path>/world.json --traffic-test=60   # the world workstream's map
godot --path game -- --traffic=60 --traffic-shots=<abs dir>     # 4 screenshots + perf.json (opens a window, ~2 min)
godot --path game -- --traffic=60 --bench-traffic               # fps with 0 / 30 / 60 / 80 cars
godot --path game -- --bench-matrix                             # now includes a "traffic_hidden" line
godot --headless --path game --script res://tests/debug_graph.gd -- <world json> [junction]   # dump a graph
```

Other args:

- `--traffic=<n>`: a fixed number of moving cars. The default is adaptive: 24–80 cars, capped at
  38 per lane-km. The town has 1.4 lane-km, so it gets about 53.
- `--world=<path>`: build the lane graph from a world file instead of the town layout.
- `res://assets/world/world.json` is picked up automatically if it exists.

Stand-in assets:

- `blender -b --factory-startup --python tools/godot/make_traffic_standins.py` rebuilds
  `game/assets/traffic/standin/` (committed): the cab and security liveries, LOD1 and LOD2. It
  needs the car's Pigment textures in `scenes/car/textures/`.
- `python tools/traffic/make_test_world.py` rebuilds the synthetic test world.

## Code (`game/scripts/traffic/`)

| file | what |
|---|---|
| `lane_graph.gd` | lanes, connectors, junctions; town and world importers; precomputed navigation data |
| `traffic_manager.gd` | spawning / pool / LOD bookkeeping, the AI, physics hand-off, parked cars, patrols, lights, horn, stats |
| `traffic_car.gd` | one pooled vehicle (RigidBody3D): LOD meshes, wheels, lamp quads, light bar |
| `signals.gd` | signal controllers (phases, actuation) and signal heads (props or built-in) |
| `vehicle_library.gd` | the vehicle index, LOD templates, variants |
| `pedestrians.gd` | sidewalk walkers (MultiMesh) |
| `traffic_automation.gd` | `--traffic-test`, `--traffic-shots`, `--bench-traffic` |

Changes outside `game/scripts/traffic/`, all additive:

- `main.gd`: creates the TrafficManager, adds the new args, and makes the autopilot brake for
  traffic (`hero_safe_speed`).
- `automation.gd`: one bench-matrix line.
- `tools/godot/export_town.py`: writes `road_info`, `drive_side`, and junction `kind` / `arms` /
  `arm_len` into `town_layout.json`.
- `project.godot`: enables `addons/fleet_variants`.
- `.gitignore`: entries for the synced copies.

## The lane graph

A **lane** is a polyline with cumulative lengths. A car's state is `(lane, s)`. **Connectors**
(paths through a junction) are lanes too, so a car's route is always lane → connector → lane.

Precomputed when the graph is built:

- **Successors and neighbours**
  - `next` / `prev`.
  - `left` / `right`: same-direction neighbours, used for lane changes.
  - `group`: the lanes of one road and direction. A turn may start in any of them; the car changes
    lanes to reach it.
- **Approaches:** the incoming lane groups of each junction, with their direction and a
  major / minor flag.
- **Connectors:**
  - Generated from kerb-side lane matching when the data has none. When driving on the left:
    - left (kerb-side) turns go from the kerb lane to the kerb lane;
    - right (crossing) turns go from the centre lane to the centre lane;
    - straight connects lane i to lane i.
  - Otherwise taken from the data, including the world's own curve points.
- **Conflicts:** connector pairs of one junction whose paths come within 3 m of each other, or
  that merge into the same exit. Pairs that leave from the same lane don't conflict, because those
  cars queue anyway.
- **Rank:** 10 for the major road, plus straight 3 > kerb turn 2 > crossing turn 1 > U-turn 0.
- **Spatial hash:** of the lane samples (16 m cells), used for nearest-lane queries: ring spawns,
  recovery after a crash, tests.
- **`dist_to_exit`:** distance to the nearest dead end, by reverse Dijkstra.
- **`route(a, b)`:** Dijkstra over lane lengths.
- **`snap_to_ground()`:** raycasts every lane sample onto the real road surface once the collision
  exists (1364 samples in the town).

### From the town layout (now)

`export_town.py` now also writes:

- `road_info[i]`: per road, `{from: {junction, arm}, to: {junction, arm} | null, half_width: 4.0, surface_dy: 0.2, lanes_each_way: 1}`;
- `drive_side: "left"`;
- per junction: `kind` (X / T / Y), `arms` (Godot directions) and `arm_len`.

Without `road_info` (an older export), road ends are matched to the nearest junction within 30 m.

The town has one lane each way, 1.92 m off the crown, and drives on the left. Roads are clipped to
the playable area, like the hero's autopilot does. X and Y junctions get signals; T junctions are
give-way junctions with the through road as the major road.

The town's graph:

- 11 roads, 5 junctions;
- 22 road lanes and 36 connectors;
- 1.4 lane-km;
- 55 conflict pairs.

### From `world.json` (the world workstream: `pigment-world/1`)

The importer reads the world workstream's `world.json` exactly as `tools/world/world_gen.py`
writes it today. It is tested against their current output: 263 roads, 163 nodes, 708 drive lanes,
1436 connectors, 88.5 lane-km, 0 AI collisions in 60 s. The fields used are below. Anything else
is ignored, so the world can keep adding fields.

```jsonc
{
  "format": "pigment-world/1",
  "coords": "Blender world space: ...",  // starts with "blender" or "up": "z" -> (x, y, z) becomes Godot (x, z, -y);
                                         // anything else = already Godot (x, y up, z)
  "traffic": "left-hand",                // or "drive_side": "left" | "right"
  "roads": [{
    "id": "r12",
    "points": [[x, y, z], ...],          // centreline ON the road surface, any spacing (resampled to 3 m)
    "start": {"node": "n3", "arm": 0},   // or {"junction": id}, a bare id, or null = dead end
    "end":   {"node": "n7", "arm": 2},
    "half_width": 5.0,                   // kerb to centreline (parking-on-sidewalk offset, fallback lane widths)
    "speed_kmh": 40,                     // or "speed_limit" in m/s
    "lanes": [                           // index in this array = the lane id used by "connections"
      {"id": 0, "offset": 1.6,  "dir": 1,  "width": 3.2, "kind": "drive"},    // offset: metres, + = LEFT of the point order
      {"id": 1, "offset": -1.6, "dir": -1, "width": 3.2, "kind": "drive"},    // dir: +1 along the points, -1 against them
      {"id": 2, "offset": 4.0,  "dir": 1,  "width": 1.6, "kind": "parking"}   // parking lanes get parked cars, no traffic
    ]
  }],
  "junctions": [{                        // every node (transitions and dead ends too)
    "id": "n7", "pos": [x, y, z],
    "kind": "X",                         // X / T / L / multi / plaza / transition / end ...
    "signalised": true,                  // or "control": "signal" | "yield" | "stop" | "none"
    "arms": [{"road": "r2", "length": 20.25, "half_width": 6.8}],   // optional: lane ends inside 0.6 x the shortest arm are trimmed;
                                                                  // the widest arms are the major road at yield junctions
    "connections": [{                    // optional; generated from kerb-side matching when absent
      "from": {"road": "r2", "lane": 0}, "to": {"road": "r10", "lane": 1},
      "turn": "right",                   // straight | left | right | uturn
      "points": [[x, y, z], ...]         // optional connector curve (else a Bezier between the lane ends)
    }],
    "phases": [{"roads": ["r2", "r11"], "green": 14, "amber": 3}],  // optional (else from the signals' phase letters,
                                                                    // else opposite arms share a phase)
    "priority_roads": ["r2", "r11"]      // optional: the major road at a yield junction
  }],
  "signals": [{                          // optional heads; otherwise one per approach on the kerb corner
    "id": "s7_0", "junction": "n7", "controls": {"road": "r2", "end": "end"},
    "pos": [x, y, z], "facing": [fx, fy],  // facing = the way the lamps shine (towards approaching cars)
    "mast": 6.0,                         // > 3 m: the props' mast-arm light, else the pole light
    "phase": "A"                         // signals sharing a letter share a green
  }],
  "spawn": {"pos": [x, y, z]}            // the traffic test centres itself here
}
```

Also accepted, for hand-written or test files (see `game/tests/data/test_world.json`):

- `"lanes_forward": 2, "lanes_backward": 2, "lane_width": 3.4, "median": 1.0, "one_way": false`
  instead of `lanes`;
- `"parking": ["left", "right"]` (kerb-side parking);
- a top-level `"connections"`;
- the whole structure under a top-level `"traffic"` key.

Hooks for when the world loads in Godot:

- **Placed signal props:** the world places its own signal poles (instances with `"signal": id`).
  Once its loader has spawned them, call `traffic.signals.attach_instance(signal_id, node)`. The
  traffic lights then drive that prop's lamps instead of spawning their own.
- **World files:** put the world file at `res://assets/world/world.json` (or pass `--world=`). Give
  the roads collision, so `snap_to_ground` and the parked-car placement can find the surface.

## Vehicles: the index

`vehicle_library.gd` reads `res://assets/vehicles/index.json` first, then the stand-in
`res://assets/traffic/standin/index.json`. It understands two formats:

- **The fleet's `vehicle-index` v1** (`tools/vehicles/export.py write_index()`), as written today:
  `vehicles[]` with
  - `id`, `class`, `spawn_weight`;
  - `files: {lod0, lod1, lod2, json}` (relative to the index);
  - `lod_distances_m: {lod0: 0, lod1: 25, lod2: 70}` (where each LOD starts);
  - `dimensions`, `default_variant`;
  - `variants[{name, index, kind, weight}]`.

  Variants are KHR_materials_variants on `Body`. Godot ignores that extension, so:
  - `tools/godot/sync_vehicles.py` copies the fleet's `tools/vehicles/godot/vehicle_variants.gd`
    into `game/addons/fleet_variants/`. The `fleet_variants` editor plugin (committed, enabled in
    `project.godot`) registers it for imports, and every variant's materials survive.
  - Without it, the body's variant materials are parsed from the glb at runtime and
    S3TC-compressed (slower start-up).

  Variant `kind` `police` / `security` cars are only used by the patrols. Civilians never get them.
- **The stand-in format**: `vehicles[]` with
  - `name`, `class`, `spawn_weight`, `spec` (car.json);
  - `lods: [{file, max_distance}]`;
  - `variants: [{name, weight, tint: [r, g, b] | albedo: tex | material: res, kind}]`;
  - `patrol: true` to mark a patrol vehicle.

Every LOD glb follows the car contract:

- `Body`;
- `Wheel_FL/FR/RL/RR` at the hubs (they spin; a LOD without them, such as a merged LOD2, is fine);
- `Collider`, the convex hull used as the collision shape;
- `Headlight_*` / `Taillight_*` empties, where the lamp quads go.

Glass keeps its depth pre-pass only on LODs that end within 30 m. Further LODs are opaque (dark
glossy panes, like the town's windows).

**The stand-in fleet** (`tools/godot/make_traffic_standins.py`):

- The Kanzaki Tsubame in the Kōen Cab livery, plus five tinted paints (midnight, rust, jade,
  violet, graphite).
- The Hoshikawa Security livery, for the patrols.
- Per livery a LOD1 (about 10k triangles, 1024 px) and a merged, decimated LOD2 (about 2k
  triangles, 512 px). The security car's LOD0 is the hero's `car.glb`.

Synced, the fleet's own vehicles replace it. They were tested with hakobi, hayate and mame (3 LODs
and 8 variants each, loaded in 0.5 s). The hayate "pursuit" variant then becomes the patrol car.

## The AI

The per-car cost stays at about 1 ms per 120 Hz physics tick for 55–80 cars, including the
occupancy rebuild:

- every car integrates and is posed each tick;
- the full AI ("think") runs every 4th tick per car, staggered (30 Hz);
- cars more than 110 m from the camera are posed every 3rd tick.

- **Lane following.** Position along the lane polyline. The heading is the chord across the
  wheelbase (rear axle to front axle), so cars turn in on bends like a bicycle model. During a
  lane change the lateral offset follows a smoothstep, with the matching yaw.
- **Car following, IDM:**
  - parameters: a = 1.8 m/s², b = 2.6 m/s², s0 = 2.6 m, T = 1.25 s;
  - desired speed = lane speed × a per-driver factor of 0.82–1.12 (patrols ×1.12; connectors
    7.5 m/s for turns);
  - the leader is searched along the lane and up to 3 lanes ahead on the planned route, within
    90 m.
- **Obstacles.**
  - The player, loose (knocked) cars and loose parked cars count as leaders when they are within
    a car width of the path ahead.
  - Red / amber lights and stop lines are virtual stopped leaders.
- **Junctions.** A car may enter its connector only if all of these hold:
  - its signal is green, or amber and it can't stop comfortably (3.2 m/s²);
  - at a stop junction, it has come to a halt at the line;
  - the exit lane has room for it ("don't block the box");
  - no conflicting connector is occupied or reserved;
  - no higher-ranked conflicting car with right of way will arrive within 4 s.

  Clearance latches 6 m (or 1.6 s) before the line and reserves the connector. After 9 s of
  waiting, priority is waived and only physically close or moving conflicts block, which breaks
  deadlocks.
- **Signals.**
  - Phases: green 14 s (11.2 s for a phase with a single approach), amber 3 s, all-red 2 s.
  - Junctions start at random offsets.
  - Actuated: after 6 s, a green with nobody approaching gaps out when cars wait on red.
- **Lane changes.**
  - Mandatory: towards the source lane of the planned turn. If it is too late, the car takes a
    turn from its current lane instead.
  - Discretionary: overtaking a leader that is slower than 0.7 × the desired speed within 30 m,
    when the other lane gives at least 12 m more.
  - Safety gaps ahead and behind scale with the speed difference.
  - Until it is half way across, the car is still a leader in the lane it leaves, and it keeps its
    distance to that lane's leader.
- **Lights.**
  - Head- and tail-lamp quads at the model's lamp empties, using shared emissive materials. Brake
    lamps (the bright material) come on when decelerating harder than 0.6 m/s² or standing still.
  - The 6 cars nearest the camera get a real headlight SpotLight3D and a tail OmniLight3D,
    re-assigned every 0.25 s.
  - Headlights follow `night` (always on in this town).
- **Player.**
  - Cars brake for the player in their path.
  - They honk (a synthesised two-tone horn, AudioStreamPlayer3D) after 2.5 s blocked or when cut
    up, with a 70 % chance and a 5–11 s cooldown.
  - Within 55 m, a car's convex collider turns on: it is a frozen kinematic RigidBody3D that the
    hero's VehicleBody3D collides with.
  - When the hero touches it (`get_colliding_bodies`), it becomes a dynamic rigid body carrying
    its lane velocity. Loose cars that hit kinematic ones knock them loose too (pile-ups).
  - Once it has been at rest for 1.2 s, and the player has backed off 5.5 m, it blends over 1.4 s
    back onto the nearest lane facing its way and drives on. If it is flipped or lost and out of
    view, it is despawned.
- **Spawning.**
  - A pool of `max` cars, plus 2 patrols.
  - Cars appear 45–260 m from the player and out of view (in the camera frustum within 170 m
    counts as visible), on a free lane spot.
  - In big worlds, spots are sampled in the ring through the spatial hash.
  - Cars despawn beyond 290 m when out of view, at dead ends (the map edges), or after 90 s
    stalled out of view (a last resort; the tests count stalls separately).
  - The count adapts to the frame rate: −4 below 72 fps, +2 above 110 fps.
- **LOD.**
  - Per-LOD visibility ranges: LOD0 to 14 m, LOD1 to 45 m, LOD2 beyond, with the fleet's own
    distances when present.
  - Wheel spin only on LODs that have wheels.
  - Shadows from all but a far LOD.
  - Lamp quads to 260–320 m.
- **Variants.** Each spawn picks a model by spawn weight, then a variant by weight. Materials are
  shared per variant.
- **Parked cars.**
  - Along every road side: on the sidewalk next to the kerb in the town (`half_width` + 1.35 m),
    or in the world's parking lanes.
  - Spaced 7–34 m apart, at least 9 m from junction mouths.
  - A spot is kept only if the ground is flat under the whole footprint (5 rays, within 0.18 m)
    and a box query finds no lamp, pole, building or wall there.
  - They are static bodies that the player can knock loose; they settle again and stay where
    they land.
  - The town fits 12–14 (its sidewalks are full of lamps and poles).
- **Patrols.**
  - Every 25–45 s a free patrol appears 70–170 m away, out of view, on a lane heading towards the
    player.
  - At junctions patrols prefer connectors that lead towards the player.
  - 60 % run with the light bar flashing: an add-on red / blue bar with 2 volumetric OmniLights,
    in a 7 Hz double-flash pattern.
- **Pedestrians** (optional, done light):
  - 40 walkers on sidewalk paths: the road centre lines offset to the sidewalk, cut where the
    ground jumps or near junctions.
  - Each is a capsule body and head, swinging legs and a glowing LED collar.
  - 5 MultiMeshes (5 draw calls for all of them).
  - Walkers more than 110 m from the player respawn 30–90 m away, out of view.
  - They never cross roads, so cars never need to stop for them.

## Tests

`--traffic-test=<s>` runs headless. The player is frozen out of the way while it measures, every
second, on every lane-following car:

- **off-road:**
  - the car must be within 0.6 m of its lane (allowing for the lane-change offset);
  - in the town, 3 rays under the car must hit a road or junction collider (`cat == "road"` in the
    layout).
- **stuck:** no car may stand still for more than 75 s.
- **signals:** every approach of every signalled junction has shown green and red.
- **AI–AI collisions:** new overlaps of two car footprints (separating axis test, 8 % shrink),
  counted 8 times a second. The limit is 3 or fewer.
- **flow:** junctions are traversed, at least 60 % of the target count stays active, and the
  average speed is above 3 m/s.

Then the player tests:

- **brakes for the player:** the hero is parked 26 m ahead of a moving car in its lane. The car must
  stop without touching it.
- **bumped and recovers:** the hero is pushed into that car at about 8 m/s. The car must be knocked
  loose and later recover onto its lane.

Results (60 s each, all pass):

| map | lanes | AI collisions | lane changes | avg speed | stuck | off-road samples | player brake / bump |
|---|---|---|---|---|---|---|---|
| town (stand-in fleet) | 22 + 36 connectors | 0 | – (1 lane each way) | 3.7 m/s | 0 | 0 / 2931 | stops 7.6 m short, 2 honks / knocked 2 (pile-up), recovered in 4.7 s |
| town (fleet: hakobi, hayate, mame; 30 s) | | 0 | – | | 0 | 0 | pass |
| test world (3×3 grid, avenues 2+2, yield / stop / signal) | 56 + 96 | 0 | 35 | 5.4 m/s | 0 | 0 / 4579 | stops 2.6 m short / knocked 1, recovered in 4.7 s |
| world workstream's `world.json` (no terrain yet) | 708 + 1436 | 0 | 33 | 5.9 m/s | 0 | 0 / 4556 | skipped (no ground under the lanes) |

The longest stand-still in any run was 48 s (a long red); the stuck limit is 75 s. CPU: 1.2 ms per
physics tick with about 40–55 cars in the town, 1.9–2.7 ms with 80 cars on the big maps. The machine
was shared with other agents' builds and renders.

The town's average speed is low on purpose: it is small (1.4 lane-km for about 50 cars) with a
signal or give-way junction every 60 m.

## Performance

RTX 4070 Ti, 1920×1080, vsync off, SDFGI on, idle GPU. Numbers from `perf.json` (the `--traffic-shots`
run), `--bench-traffic`, and the existing `--bench`. All of them include the parked cars, 40
pedestrians and the signal heads.

| scene | moving cars | avg fps | 1 % low | GPU ms | draw calls | traffic CPU per physics tick |
|---|---|---|---|---|---|---|
| `--bench`, autopilot drive, `--no-traffic` (baseline) | – | 249 | 183 | | 297 | – |
| `--bench`, autopilot drive, traffic on (adaptive) | about 53 | 229 | 173 | | 467 | |
| perf matrix (chase drive): 0 cars | 2 (patrols) | 202 | 81 | 4.3 | 413 | 0.14 ms |
| 30 cars | 32 | 249 | 160 | 3.6 | 301 | 0.51 ms |
| 60 cars | 61 | 233 | 136 | 3.9 | 566 | 0.79 ms |
| 80 cars (the town is full at about 80) | 82 | 218 | 139 | 4.1 | 522 | 1.14 ms |
| chase cam through dense traffic (shot 3) | 68 | 128 | 61 | 5.0 | 702 | 1.8 ms |
| busy-junction view (shot 1) | 69 | 177 | 79 | 4.6 | 667 | 1.4 ms |

60+ fps with 60 cars holds with a wide margin. The averages vary with the view: the matrix rows
are consecutive 6 s windows while the autopilot drives. The GPU cost of 60 to 80 cars is about
0.5 ms. The traffic CPU cost is 0.8–1.8 ms per 120 Hz tick (about 1 tick per frame at these
rates). `--bench-matrix` now has a `traffic_hidden` line (traffic not rendered, AI still running).

Measuring needs an idle GPU. While other agents' Cycles renders held 11.7 of the 12 GB of VRAM
at 100 % utilisation, every configuration ran at about 10 fps, even with no cars. Those runs are
not representative.

## Known limits

- **Lanes.** The town has one lane each way, so lane changes only happen on world data. Lane
  changes snap the car to the target lane's `s` (parallel lanes only), and there are no lane
  changes inside junctions.
- **Junctions.** There is no explicit gridlock solver beyond "don't block the box" plus the 9 s
  patience rule. A car stalled for 90 s out of view is despawned; the tests never needed it.
- **Steering.** Kinematic cars don't model tyre slip: steering is the wheelbase chord (smooth, but
  no understeer).
- **Hand-off.** A loose car is a rigid body on its convex hull with no wheels. That is fine for
  bumps and pile-ups, but it slides rather than rolls. Recovery is a 1.4 s blend, so a car can
  ghost through something on the way back.
- **Horns.** The horn is synthesised (two square tones), with no engine sounds. Audio is not
  heard in headless tests.
- **Pedestrians.** They are silhouettes with a procedural walk and never cross roads.
- **Spawning.** It only checks frustum visibility, not occlusion. Cars despawn at dead ends even
  in view, but in the town those are at the fogged map edges.
- **Traffic lights.** The props' traffic lights (merged from master b80fc1b) are used once
  `sync_vehicles.py` has copied `assets/props/` into `game/assets/props/`. Mast-arm and pole lights
  alternate per approach, and the heads are raycast onto the sidewalk.
  - Lamps are switched the way the props NOTES say: lit = the shared material; off = an override
    with emission off.
  - Pedestrian Walk/Stop lamps show walk while their approach is red.
  - Without the props, a built-in pole and three-lamp head is used.
  - Only the lod0 glb is used (2–4k triangles); the props' lod1 is ignored.
- **Fleet variants.** Without the fleet's import extension the variant materials are decoded at
  runtime, which costs about 6 s at start-up and more VRAM. Run `sync_vehicles.py` and re-import.

## Merge notes

- **Shared files**, all additive edits:
  - `game/scripts/main.gd`: a preload, the `traffic` var, the args block, two lines in
    `autopilot_step`;
  - `game/scripts/automation.gd`: one bench-matrix line;
  - `game/project.godot`: an `[editor_plugins]` section;
  - `game/.gitignore`;
  - `tools/godot/export_town.py`: `road_info`, `drive_side`, junction `kind` / `arms` /
    `arm_len`.
- **Re-export.** Re-run `tools/godot/export_town.py` so `town_layout.json` carries `road_info`.
  Old layouts still work (junctions are inferred).
- **Missing base texture folders.** On master, `tools/town_textures.py` only writes the variant
  folders (`building_a__capsules`...). `export_town.py` needs the base folders
  (`scenes/town/textures/building_a/` and so on), or `blender_town.build()` fails with
  `material_slots[0]`. For this run they were seeded from the first variant (git-ignored data). The
  main checkout still has old base folders, so it isn't affected.
- **Master merged.** Master (the street props kit, b80fc1b) is merged into this branch. Run
  `python tools/godot/sync_vehicles.py` (it copies the props too) and re-import, so the signals
  use the props' traffic lights.
- **Fleet.** Once `assets/vehicles/` is on master, run `python tools/godot/sync_vehicles.py` and
  re-import. If the fleet workstream adds its variant extension to `game/` itself, point
  `addons/fleet_variants/plugin.gd` (`EXT`) at it, or drop the plugin.
- **World.** Load `world.json` (or `--world=`), give the roads collision, and call
  `signals.attach_instance()` for the world's placed signal props.
- **Stand-in data.** `game/assets/traffic/standin/` is about 10 MB of glbs. It can be deleted once
  the fleet is in; the security patrol falls back to any police variant.
