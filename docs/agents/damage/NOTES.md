# damage: crumple, falling panels, and a city that breaks

The user's request: *"Proper damage effects on all the 3D models: the bonnet crumpling, doors falling off, running over fire hydrants so they burst water, knocking down lamp posts, etc."*
Follow-ups: *"Just more crumple"*, and the car must never explode.

Cars now dent and crumple where they're hit, and the damage builds up with each impact. Panels come loose and fall off, glass breaks, and lamps go dark. Street props snap, burst, topple or get knocked about. Damage is cosmetic and mechanical only:

- no fire and no explosion;
- no "wrecked" state;
- the worst a car gets is limp mode (about 25 % power and a slight steering pull);
- **R** repairs it, and so does any teleport (`car.place()`).

| | |
|---|---|
| `01_crumpled_bonnet.jpg` | 60 km/h into a concrete block. The nose is pushed in and shortened, the bonnet buckles up, the windscreen is cracked (the Pigment overlay), steam comes off, one headlamp is out and the bumper is gone |
| `02_door_hanging.jpg` | A side hit on the front door. The skin caves in with creases, the glass shatters, and the door swings open on its HingeJoint3D |
| `03_debris_on_road.jpg` | Driving through rubbish bags, boxes and cones. The bags split into separate bodies and scatter litter |
| `04_lamp_post_sparks.jpg`, `04b_…` | A street lamp hit at 55 km/h. It shears at the base and falls with a spark burst while its light flickers and dies. The stump stays |
| `05_hydrant_geyser_rain.jpg`, `05b_…` | A burst hydrant at night in the rain: a 9 m jet, mist, splashes and a puddle that grows |

All of these come from `--damage-shots` (windowed, real gameplay code). The door shot applies an 11 kN·s side impulse with `apply_impact()` to a car standing still. The others are real drives.

## 1. Vehicles

### The export: detachable panels (`tools/vehicles/damage_panels.py`, called from `export.py`)

LOD0 now keeps these panels as their own nodes, each with its pivot as the node origin:

- `Door_FL/FR/RL/RR` (or the sliding `Door_SL/SR`), hinged on the front edge;
- `Hood`, hinged at the windscreen;
- `Trunk` (the lid hinges at its front edge; a hatch or tailgate at its top);
- `Bumper_F/R`;
- `Mirror_L/R`, pivoted at the stalk;
- `Glass_*`;
- `Lens_Head_*` / `Lens_Tail_*`, and `Lamp_*` (the emitters behind the lenses).

Small attached parts go with their panel: handles, locks, seals, door cards, plates, intakes, louvres and the wing. LOD1 and LOD2 are unchanged.

How it works:

- Faces are matched to the `<id>_parts.json` records by connected piece: centre within 3 mm and the same triangle count. All 6 vehicles match with 0 unmatched pieces (18–26 panels each).
- Panels are separated with Blender's `separate`, so custom normals, UVs and KHR_materials_variants (set on every panel mesh) survive.
- `<id>.json` and `car.json` gain a `damage` section. For each panel it lists node, kind, parent, pivot, `hinge_axis`, `open_sign`, `limits_deg`, `mass_kg`, `aabb`, `lamps` and parts. `index.json` gains a `panels[]` list per vehicle.
- The node contract still holds (`Body`, `Wheel_*`, `Collider`, the lamp empties). `car.gd` and the traffic library already take every mesh that isn't a wheel, caliper or collider, so an undamaged car looks exactly as before.

### Damage (`game/scripts/damage/vehicle_damage.gd`, `vehicle_deform.gd`)

- **Impact detection.** The body's velocity change per 120 Hz tick, while there are contacts, counts as an impact above 1.25 m/s (about 15 g). The ticks of one crash are summed: impulse J = m·|Δv|, the point is taken from the contact positions, and the direction is Δv.
  - A 30 km/h wall hit gives J ≈ 9.4k N·s; 60 km/h gives ≈ 18.5k.
  - A kinematic or parked traffic car that the hero hits gets the mirrored impulse.
- **Crumple (CPU, on impacts only).** The vertices of `Body` and the door, hood, trunk and bumper meshes move within a radius of the hit (0.4–1.15 m), with a depth of up to 0.36 m:
  - a push along the impact direction, over a crushed plateau with a falloff;
  - an upward buckle across the push. This is what makes the bonnet buckle up and the wings and doors fold;
  - a ridged-noise crease pattern with its own phase per panel, so folds break at the shut lines;
  - fine per-vertex crumple;
  - normals follow the gradient of the displacement field, so the creases catch the light.
- **Stability limits.** A single hit moves a vertex at most 1.4 × the depth, and no vertex ever ends up more than 0.55 m from where it started. Vertices at the same position move identically, so seams stay closed.
- **Deformation cost.** Vertices are found through a 25 cm grid, built on a worker thread and shared by every instance of a mesh. Each car gets its own ArrayMesh copy the first time it is dented.
- **Panels.** Each panel has health, and loses `e × 4.5 × K(kind) × falloff`.
  - At 55 health or below, doors, hood and trunk come **loose** on a HingeJoint3D.
    - The door hinge axis leans out at the top, so gravity swings the door open.
    - A loose hood is lifted by the wind at speed.
    - Bumpers hang from the end away from the hit.
  - At 0 health a panel falls off as **debris**, together with whatever is mounted on it.
  - Mirrors snap off.
  - Side glass shatters and disappears in a burst of shards.
  - The windscreen and rear window **crack** first (a projected overlay, `glass_crack.gdshader`), then shatter.
  - Lenses break: the matching `Lamp_*` emitters go dark (an override with emission off), and the hero's real SpotLight / OmniLight for that lamp turns off. On traffic, the shared lamp quads turn off once both sides are out.
- **Zones and engine.**
  - The car has front, rear, left and right damage zones.
  - Front hits damage the engine. Above 0.35 it steams; above about 0.62 the smoke turns black.
  - `car.power_scale` falls to at least 0.25.
  - A hit front wheel sets `car.steer_pull` (at most ±0.07 rad).
- **Scrapes.** Any contact sliding past at more than 2.6 m/s throws sparks every 45 ms and plays a grinding loop.
- **HUD.** `damage_hud.gd` (top left) shows a top-down car whose zones go cyan → amber → red, amber or red dots for loose or missing panels, the engine bar, a glass count, lamps out, wheels/ALIGN!, and a percentage.
- **Traffic.** A traffic car gets the same damage node when it turns into a physics body near the hero (within 70 m, at most 10 at once), or when the hero hits it.
  - It deforms only within 40 m of the camera.
  - A damaged car keeps its LOD0 until it is recycled. On despawn the damage is reset, and the panels go back into the LOD bookkeeping.

## 2. The destructible world (`destructibles.gd`, `game/data/damage/props.json`)

`tools/props/damage_table.py` writes the per-prop behaviour from `assets/props/index.json` (collider shapes, lights) and the props' source pieces (glass panes, chunks).

All 16,580 prop instances in the world layout are indexed in an 8 m grid at load. No nodes are created for that.

| kind | props | what happens |
|---|---|---|
| snap | street_lamp, power_pole, traffic_light_pole/mast, ped_signal, street_name_sign, bollard, parking_meter, cctv_pole, drone_mast, holo_pylon | static until the closing impulse (car mass × closing speed) passes its threshold (bollard 8k, lamp 10k, mast 20k, power pole 24k N·s); then it shears, falls as a rigid body (tipped away from the car) and leaves a stump. Lamps: the streamed light is killed for good (`kill_lights_near`), a light rides on the falling pole, flickers with sparks and fizz, and dies |
| burst | fire_hydrant | snaps (5.5k) → 9 m water jet + mist + splash ring + spray glow + a puddle decal that grows to 7.5 m over 70 s; runs 4 min, then dies down; paused (time kept) beyond 220 m |
| topple | vending_machine, data_kiosk, phone_kiosk | glass/screens shatter from 2–2.5k (glassless mesh swapped in); topple from 7–12k; vending machines spill cans |
| shelter | bus_stop | stays; its glass panes shatter from 2.5k |
| knock | traffic_cone, trash_bag_pile (splits into its bags + litter), trash_bin, cardboard_boxes / crate_stack (split into boxes / crates), pallet, bicycle, scooter, bench, planter, ramen_cart, skewer_stall, crash_barrier | become rigid bodies just before the car touches them; the physics shoves them |
| heavy | jersey_barrier | 1.8 t rigid body: barely moves |
| bend | guard_rail | breaks loose above 18k |
| none | rooftop / wall props, cables, trees, decals | — |

- **Prediction.** Each tick, the hero (and loose traffic) is checked against the props near it: its box is grown by its next 3 ticks of travel.
  - Anchored props that should stop a slow car get **armed** static colliders within 32 m. The town kit's lamps and poles already have the loader's colliders.
  - A hit the prediction missed is caught from the car's impact (the damage `hit` signal).
- **Persistence.** Broken state is kept per instance for the session.
  - `town_loader.hide_instance()` edits the stored MultiMesh buffers as well as the live MultiMesh, so a cell that streams out and back in stays broken. No lamp post pops back up.
  - `remove_collision_near()` removes the static shape from the stored cell too.
  - Debris far away is pooled away; stumps and puddles stay.
- **Debris pool (`debris.gd`).**
  - Bodies are pooled and removed from the physics world while idle.
  - At most **60 awake** bodies: beyond that the oldest and farthest are frozen.
  - Bodies freeze beyond 70 m and despawn beyond 170 m. The oldest go once there are more than 140.
  - `life` ends small things once they are out of sight.
  - Debris sits on layer 4 (value 8). The hero's body and loose traffic collide with it, but wheel rays don't, so a car doesn't jolt over a cone.

## 3. Audio (`damage_audio.gd`, `tools/audio/make_damage_sounds.py`)

The sounds are synthesised with numpy and scipy from noise, modal resonators and envelopes. They are original and use no samples. There are 23 wavs (3 MB) in `game/assets/audio/damage/`.

Sounds by event:

- metal crunch, light or heavy by impulse, with volume and pitch from the impulse;
- metal scrape (loop);
- glass shatter;
- plastic clatter;
- wood knock, cardboard thud and bag thump;
- water burst and water hiss (loop);
- pole clang;
- electrical fizz;
- can rattle.

Debris plays its material's sound when it lands.

**Sound-pack hook.** Put files in `game/assets/audio/damage_pack/` with these base names. Formats can be wav, ogg or mp3. Variations are `<name>_1`, `<name>_2`, … up to `_8`, picked at random. Any name found there replaces the generated sound:

```
metal_crunch_light  metal_crunch_heavy  metal_scrape (loop)  glass_shatter  plastic_clatter
wood_knock  cardboard_thud  bag_thump  water_burst  water_hiss (loop)  pole_clang  electric_fizz  can_rattle
```

Missing names are skipped silently.

## 4. Tests and numbers

```
godot --headless --fixed-fps 120 --path game -- --damage-test [--damage-out=res.json]
godot --path game -- --damage-shots=<abs dir>        # the screenshots (windowed, ~5 min)
godot --path game -- --damage-bench                  # fps: 0 / 40 debris / 3 geysers (windowed)
godot --path game -- --bench=20 --damage-prof        # damage script cost per physics tick
python tools/props/damage_table.py ; python tools/audio/make_damage_sounds.py ; python tools/damage/make_glass_crack.py
blender -b --factory-startup --python tools/vehicles/export.py -- all      # panels (needs the src .blend + textures)
```

`--damage-test` (world map, about 3 s headless): **PASS**, 11 checks.

| check | result |
|---|---|
| hero panels | 24 (Tsubame) |
| wall 30 km/h | J 9.4k N·s, 5,042 vertices moved, max offset 0.21 m, bumper loose, lens broken, engine 0.23, power 0.84 |
| wall 60 km/h | J 18.5k, 7,389 vertices, offset 0.41 m (nose visibly shorter), 1 panel detached, hood loose, windscreen cracked, engine 0.44, power 0.69 |
| reset (R / `place`) | all panels ok, no dented meshes, power 1.0 |
| door (side impulse) | loose, swings open to 77° outward |
| lamp post at 50 km/h | broken first try, body tipped 90–163°, collision gone, light killed |
| hydrant at 40 km/h | burst, jet running (900-particle jet) |
| cone at 35 km/h | knocked |
| 40 debris bodies in a heap | headless tick 0.60 → 1.66 ms average (one 100 ms tick when they spawn), 40 awake ≤ 60 budget |

Existing tests on the final code:

| test | result |
|---|---|
| `--drive-test` | PASS, all 9 checks |
| `--curb-test` | PASS, 0 fails (35 of 40 kerbs climbed with damage on, 37 with `--no-damage`; both pass) |
| `--traffic-test=60` | PASS |

**Performance** (windowed 1080p; the RTX 4070 Ti was shared with other agents, so fps varied ±40 % run to run):

- The damage scripts cost **about 0.09 ms per physics tick** while driving (`--damage-prof`: destructibles 50–75 µs, hero damage 12–20 µs, debris housekeeping < 1 µs).
- `--bench=20` with and without damage was within the machine noise (60–118 vs 64–96 fps across alternating runs).
- `--damage-bench` at the spawn (same session):

| | fps | 1 % low |
|---|---|---|
| empty | 100.8 | 70.6 |
| 40 debris falling | 95.6 | 69.4 |
| 40 debris resting | 93.3 | 61.5 |
| 40 debris + 3 geysers | 91.0 | 46.7 |

- A dent costs 14–32 ms of CPU, once per crash (the spike when a hit lands). The first prop split or glassless mesh of a kind takes a few ms, and is then cached.

## Merge notes

- **Assets:** `assets/vehicles/<id>/<id>.glb`, `.json`, `index.json`, `assets/car/car.glb`, `car.json` and `game/assets/car/car.glb`, `car.json` are re-exported (LOD0 only; LOD1 and LOD2 are untouched). Run `python tools/godot/sync_vehicles.py` and `godot --headless --path game --import`.
- **Shared files** (all additive):
  - `game/scripts/car.gd`: `power_scale`, `steer_pull`, a damage reset in `place()`.
  - `game/scripts/main.gd`: the args doc lines, the `damage` var, creating the manager, test routing, `reset_car()` → `damage.reset_hero()`.
  - `game/scripts/town_loader.gd` (the perf workstream's file): `"key"` in cell entries, `e["mmi"]` in `_make_entry`, dead lights skipped in `_stream_lights`, the glow index in `_lamp_glows`, and the new functions at the end: `hide_instance`, `remove_collision_near`, `kill_lights_near`.
  - `game/scripts/traffic/vehicle_library.gd`: `Model.damage`, `Model.wheel_positions`, and the node name as the 5th element of a part.
  - `game/scripts/traffic/traffic_car.gd`: mesh names from the parts; loose cars also mask debris (8).
- **New:**
  - `game/scripts/damage/*`, `game/data/damage/props.json`, `game/assets/audio/damage/*`, `game/assets/damage/glass_crack.png`;
  - `tools/vehicles/damage_panels.py`, `tools/props/damage_table.py`, `tools/audio/make_damage_sounds.py`, `tools/damage/make_glass_crack.py`.
- **Cracked glass:** the crack web is painted in Pigment by `tools/damage/make_glass_crack.py`, which runs `pigment-mcp --script` with a `cell_edges` mask on a 1 m sheet; the script then adds the impact star. There is a numpy fallback without the binary.
- **Turn it off** with `--no-damage`.

## Known limits

- **The deformation is visual.** The collider hull doesn't change, so a crumpled nose still collides at its original length. Dents are CPU work: one 14–32 ms hitch per crash on the hero. Traffic deforms only near the camera.
- **No roll-over or roof test.** Roof dents follow from the same field (a push from below on an upside-down car), but no automated roll-over test checks them.
- **Doors.** The hinge limit sign is the one Jolt measures (checked by the door test). A loose door can clip through the body's interior, because there is a collision exception with its own car.
- **Debris** pieces use box or cylinder shapes from the prop index, not their meshes.
- **Bags and boxes split by source-piece boxes**, so a few litter triangles go to the nearest bag.
- **World barriers.** Highway jersey barriers and guard rails that are part of the road meshes (not props) are not destructible. The props' `jersey_barrier` and `guard_rail` are, wherever they are placed.
- **Puddles** are decals. They darken and gloss whatever they lie on, but don't change the tyre grip.
- **The proof shots** are night street scenes and come out dark in places. `04b` (the lamp post lying on the sidewalk) is only lit by a fill light.
- **Performance figures** were taken on a shared, busy GPU. Re-measure on an idle machine before judging the 120 fps budget; the script cost itself is small (about 0.1 ms per tick).
