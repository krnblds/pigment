# physics: kerbs that don't trap the car, and a real vehicle model

The user's request: *"It tends to get stuck on curbs, and can you make the driving more realistic?"*

- **Kerbs.** The car no longer gets stuck. It climbs sidewalks at any angle, and it glances off or
  backs away from concrete (jersey) barriers and guard rails. `--curb-test` drives at all three and
  checks the result: **0 stuck and 0 flipped in 132 runs** (before: 29 of 68 kerb runs stuck).
- **Driving.** `game/scripts/car.gd` is now its own vehicle model on a `RigidBody3D`, replacing
  `VehicleBody3D`. It has per-wheel suspension, combined-slip tyres with surface grip, a drivetrain
  with clutch, gearbox and LSD, ABS / traction control / stability control, generated engine and
  squeal audio, skid marks, tyre smoke and a tachometer. All the parameters are data
  (`game/data/vehicles/`).

| | |
|---|---|
| `01_drift_smoke.png`, `01b_…`, `01c_…` | a handbrake flick into a power slide on the downtown avenue: smoke, skid marks, the tach (TC / ESC off) |
| `03_hud_tach_launch.png` | full-throttle launch: tach, speed, gear, AUTO, the assist lamps |

## 1. Why it got stuck on kerbs

Measured with `--curb-test` on the old car. At the moment the car stopped, the test logged where its
body touched the world, for example:

```
curb 20 deg 15 km/h  stuck  contacts: body(0.83, 0.09, -0.11) n.y=1.00 h=0.17 ... wheels [1, 0, 0, 1]
```

The car's convex `Collider` hull reaches down to **9 cm** (`y = 0.09` in car space). That is under the
15 cm kerb. When the car crossed a kerb at an angle:

- the flat underside of the hull slid onto the kerb top (the contact normals point straight up, about
  0.15–0.17 m above the road);
- the car was **high-centred**: on every stuck run, one or two wheels hung in the air (`[1, 0, 0, 1]`),
  usually a driven rear wheel;
- `VehicleWheel3D` casts a single ray down from the hub. A wheel that reaches the kerb face sinks into
  it until its centre is past the edge, and then snaps up. The wheels never lifted the body clear.

So the car could go neither forwards nor back. Old car: **15 of 32** town kerb runs and **14 of 36**
world kerb runs stuck. The jersey barrier and guard-rail runs were fine. Trimesh ghost edges were not
the cause: no stuck run had an edge contact.

## 2. The fix

- **Body collider above the wheel line.** `_build_collider()` takes the glb's convex hull and lifts
  its underside to `body.clearance` (27 cm). Beyond `axle ± 0.6 r` the floor rises at the
  approach / departure angle (`body.approach`), so the overhangs are chamfered. Only the tyres touch
  a kerb. Walls and barriers still meet the body (friction 0.3, so it scrapes along them).
- **Wheel-profile probes instead of one hub ray.**
  - Each wheel casts 3–4 rays down across the tyre's circle along its direction of travel: the hub,
    `0.55 r` and `0.88 r` ahead, and `0.6 r` behind when slow.
  - The contact is the hub height that keeps the round tyre on the highest point, so a kerb lifts the
    wheel smoothly before the hub reaches it.
  - On an edge, the suspension force tilts a little towards the edge (`edge_push`). Climbing a kerb
    costs speed, like a real bump.
  - The middle sample is skipped when the centre and leading samples see the same ground.
- **Kerb or wall: the probe decides.** A hit is ignored, and the ray looks past it, when it is:
  - more than `max_step` (24 cm) above the ground the wheel last stood on. This is measured from the
    ground, not from the hub, so a body lifted by a crash cannot "climb" a barrier;
  - a face steeper than 45° that is more than 12 cm up;
  - a face steeper than 72°.

  The tyre may ride the bottom of a jersey barrier's slope, as real ones are designed to allow.
  Anything taller is the body collider's job.
- **Low-speed traction that can always get out.**
  - The automatic clutch slips like a torque converter: capacity ~ rpm², with a stall speed of about
    3000 rpm at full throttle. It locks once the slip is small. The old on/off clutch stalled and
    bogged against a kerb.
  - Below 8 km/h, traction control brakes the spinning wheel, like a locking diff, and keeps 45 %
    throttle instead of cutting to 8 %. A car with one wheel light (half on a kerb, nose on a
    barrier) still pulls away.
- **Jolt** was already the physics engine (`3d/physics_engine="Jolt Physics"`, 120 Hz). No change was
  needed.
- **No export change.** I did not bevel the kerbs in the collision meshes: the probe already rolls the
  tyre up a square kerb.
- **Surface per material.** `town_loader.gd` now splits road collision by surface material:
  - kinds: asphalt, kerb (`RoadTrim`), paving, concrete, metal;
  - each kind is its own body. It keeps the `Col_<mesh>` name, so `cat` lookups still work, and it
    carries `meta("surface")`.

## 3. The vehicle model (`game/scripts/car.gd`)

The model runs on the 120 Hz physics tick. The tyres and drivetrain take 4 sub-steps per tick.

| part | model |
|---|---|
| suspension | per-wheel springs. Rates come from the ride frequency of each corner's sprung mass (1.45 / 1.6 Hz front / rear). Preload equals the static load, so the modelled ride height holds at rest. 10 cm bump; droop just past the static sag. Digressive dampers (bump 0.28, rebound 0.45 of critical, blow-off above 0.25 m/s). Progressive rubber bump stops that also damp, so landings don't bounce. Anti-roll bars of 21 / 9 kN/m. Load transfer comes out of these. |
| tyres | magic formula, `F = μN·sin(C·atan(B·s))` with B set so the peak sits at normalised slip 1. Combined slip uses the normalised slip vector (sx = κ/κpeak, sy = tanα/αpeak), which gives a friction ellipse. Load sensitivity is 12 %, clamped to 0.6–1.25. Slip ratio and slip angle come from the contact-patch velocity through relaxation lengths (implicit, so they stay stable down to a standstill and the car parks on hills). Slip-velocity damping at walking pace. Lateral force acts at roll-centre height. |
| surfaces | grip as [dry, wet]: asphalt [1.0, 0.72], kerb / paving [0.86, 0.6], concrete [0.95, 0.68], metal [0.6, 0.42], grass/dirt (world terrain) [0.62, 0.46] with 5 % rolling resistance. Found from the collider: `meta("surface")`, else the `Col_<mesh>` category, else its single material name. |
| engine | torque curve (196 Nm at 4800 rpm, about 115 kW at 6200), idle governor (850 rpm), rev limiter (7000 rpm), friction and pumping losses for engine braking, inertia 0.13 kg·m². The Tsubame has a 180 km/h fuel-cut limiter (the JDM gentlemen's agreement). |
| clutch / gearbox | automatic clutch, rpm²-capacity launch. Clutch coupling is solved implicitly with the carrier. 5 speeds (3.29 / 1.89 / 1.28 / 0.97 / 0.80) and final drive 4.3. Automatic shifting by throttle-dependent shift points (with kickdown), or manual (M). 0.2 s shifts with a throttle lift on upshifts and a blip on downshifts, and a gentle re-engagement. Reverse: hold brake at a stop (automatic) or shift below 1st (manual). |
| differential | open or LSD. The LSD is a clutch type: 40 Nm preload plus a lock of 0.3 × the input torque. Integrated as sum and difference modes of the driven axle. RWD for the Tsubame; FWD (and the class data) for others. |
| brakes | 1.45 g of torque, bias 0.68 front, per-wheel Coulomb friction that holds a stopped wheel. ABS is a per-wheel slip controller running on every sub-step, holding about 0.85 × peak slip (toggle B). The handbrake locks the rear wheels (2600 Nm) and opens the clutch. |
| assists (toggleable) | **TC**: cuts throttle above 1.35 × peak slip, and brakes the spinning wheel at low speed. **ESC** (light): brakes the outer front wheel when the yaw rate passes the bicycle-model rate by 0.07 rad/s, and trims throttle. It is off while the handbrake is held, so drifts work. **Steering assist**: speed-sensitive lock (full input asks for about the front tyres' peak slip, not past it) and self-aligning (with the wheel let go, the fronts turn towards where the rear axle is going: counter-steer in a slide, about centred in a normal corner). |
| inputs | keyboard throttle and brake ramp (3.5 / 4.5 per second up, faster down); keyboard steering rate 2.7 → 1.5 rad-fraction/s with speed, returning at 4/s; analogue triggers and stick pass through with a light filter. Auto-hold: stopped with no pedals pressed, the automatic holds the car. |
| body | mass, centre of mass (0.48 m, the real value with no arcade lowering) and wheel positions from `car.json`. Inertia is set explicitly (yaw ≈ m·a·b). Aero drag Cd 0.34 × frontal area. Optional downforce in the data. |
| feedback | `vehicle_fx.gd`: skid marks (one MultiMesh ring buffer of 2400 quads, a single draw call), tyre smoke (a GPUParticles3D per wheel, hidden when idle; wet roads make less), generated audio (a 4-cylinder loop pitched by rpm with on- and off-load layers, intake hiss, a tyre-squeal loop following the slide; no samples). `tacho.gd`: rpm arc, redline, speed, gear, AUTO / MAN, ABS / TC / ESC lamps (lit when working, red when off), WET / DRY. Camera shake on impacts and hard bump-stop hits (`h_offset` / `v_offset`, so it never fights the follow). |

## Tuning guide (`game/data/vehicles/`)

Parameters are built by `scripts/vehicle/vehicle_params.gd`, in three layers:

1. **`classes.json`**: class defaults for `sedan`, `sports`, `van`, `kei`, `robotaxi` (electric) and
   `truck`.
2. **Derived from the car contract json** (`car.json` or the fleet's `<id>.json`):
   - mass, centre of mass, wheel positions, radius and width, dimensions;
   - inertia, static loads, spring rates (from `ride_hz_*`), damping (from fractions of critical);
   - brake torque (from `max_decel_g`), frontal area.
3. **`<id>.json`** (for example `tsubame.json`): any single value overrides, for example
   `{"engine": {"speed_limiter_kmh": 180}}`.

| to change | edit |
|---|---|
| acceleration | `engine.torque_curve` (rpm, Nm), `gearbox.final_drive`, `gearbox.ratios` |
| top speed | `engine.speed_limiter_kmh` (0 = none), `aero.cd`, the top gear |
| braking distance | the tyres' `mu`, `brakes.max_decel_g`, `brakes.bias_front` |
| understeer / oversteer | `suspension.arb_front` / `arb_rear` (stiffer front = more understeer), the front / rear `peak_slip_angle_deg` (a larger front value = softer front = more understeer), `differential.lock_ratio` (more = more power oversteer) |
| roll and pitch | `ride_hz_*`, `damping_*`, the ARBs, `roll_centre_*` |
| kerb behaviour | `body.clearance`, `body.approach`, `suspension.max_step` (kerb vs wall), `edge_push` |
| steering feel | `steering.lock_deg`, `rate`, `rate_high_speed`, `return_rate`, `self_align` |
| assists' defaults | `assists.{abs, tc, esc, steer_assist}` |
| drivetrain | `drive` (RWD / FWD), `differential.type` (open / lsd) |

**Other fleet cars.** `--vehicle=hayate|mame|hakobi|kago|kaiun|tsubame` drives any fleet car
(`assets/vehicles/<id>/`) with its class's physics. Results:

| car | 0–100 | top speed | 100–0 dry / wet | skidpad |
|---|---|---|---|---|
| hayate (sports) | 6.4 s | 252 km/h | 39 m / 53 m | 0.95 g |
| mame (kei) | 17 s | 137 km/h | 45 m / 60 m | 0.82 g |
| kaiun (3.9 t truck) | 27 s | 129 km/h | 51 m / 68 m | 0.66 g |

All three are stable in the lane change and the handbrake turn.

## Controls

| | Keyboard | Gamepad |
|---|---|---|
| throttle / brake (hold brake at a stop: reverse) | W / S (arrows) | RT / LT (analogue) |
| steer | A / D | left stick |
| handbrake | Space | A |
| manual gearbox on / off | M | Start |
| shift up / down (switches to manual) | E / Q | B / LB |
| traction control / stability control / ABS / steering assist | T / J / B / K | |
| rain on / off (also wet / dry road) | F | |
| reset, camera, light bar, GI, stats, quit | R, C, L, G, F3, Esc (unchanged) | Y, RB, X, Back |

The road is wet while it rains (the default). `--dry` or `--wet` overrides that.

## Tests and numbers

Run headless. `--fixed-fps 120` runs faster than real time.

```
godot --headless --fixed-fps 120 --path game -- --drive-test [--map=town] [--vehicle=<id>] [--drive-out=res.json]
godot --headless --fixed-fps 120 --path game -- --curb-test [--map=town] [--curb-out=res.json] [--curb-only=curb:30:20 --curb-trace]
godot --headless --path game -- [--map=town] --traffic-test=60
godot --path game -- --bench=20                 # windowed
godot --path game -- --car-cost                 # windowed: parked cost of the tach / fx / car tick
godot --path game -- --physics-shots=<dir>      # windowed: the screenshots here
```

`--drive-old` still runs the old drive test (`automation.gd`).

### `--drive-test` (Tsubame, on a flat 6 km asphalt pad off the map, plus a 30 s autopilot drive on the map)

| | before (VehicleBody3D) | **after** | target |
|---|---|---|---|
| 0–60 km/h | 2.5 s | **4.5 s** | |
| 0–100 km/h | never (top speed about 83 km/h on the autopilot run) | **9.0 s** (shifts at 55 and 97 km/h) | 8–9 s |
| top speed | about 187 km/h by design | **179 km/h** (limiter) | about 180 |
| 100–0, dry, ABS | 73→0 in 15.5 m (about 1.4 g) | **42.6 m** / 3.0 s (no ABS: 58 m) | about 40 m |
| 100–0, wet, ABS | (one grip level) | **57.5 m** (no ABS: 79 m) | about 55 m |
| 0–100, wet | | 10.4 s (TC working) | |
| 60 m skidpad | | **0.89 g** at 58 km/h, understeering at the limit | |
| lane change 3.5 m at 120 km/h, smooth driver | | max body slip **0.3°**, final heading 0.1° | no spin |
| same, keyboard taps (full lock 0.3 s, then the catch) | | max slip 2.1°, yaw rate 23°/s, settles | no spin |
| handbrake turn from 50 km/h | | rotates **166°** | rotates |
| power on in a 30 m turn at 40 km/h, 2nd gear, dry | | tail out 4.6° with TC off, 3.7° with TC on | only when provoked |
| 30 s autopilot on the map | no rollover | no rollover (min up 0.94 world, 0.98 town), reset upright | |
| car physics cost per tick | (native) | about 180 µs headless, 250 µs in game | |

The pad numbers are the same from `--map=town` and from the world: all checks pass on both. The
before 0–60 / brake numbers are from the old `--drive-test`, which accelerated and braked on the map
under the autopilot.

### `--curb-test`

The test picks sites by itself. In the world: 3 kerb sites (street / avenue sidewalks), 2 highway
jersey barriers, 2 mountain guard rails. In the town: 4 kerb sites.

- A site is used only if the sidewalk it drives onto is clear and has nothing hanging over it lower
  than the roof (a 0.5 m sign or footing box wedges any car).
- In the town, angles whose path is blocked by lamps are skipped per site.

Each run starts on the road aimed at the kerb at 15°, 30°, 50° and 80°, at 10, 20, 30 and 40 km/h,
then holds that speed. After a hit (speed halved) the driver lifts. If the car has stopped, the
driver tries to drive away forwards, then in reverse.

The run fails if the car is:

- **stuck** (cannot move 1 m either way);
- **flipped**;
- a kerb at 30° or more that it didn't climb (both axles over the kerb line).

| | runs | stuck | flipped | kerbs climbed (required) |
|---|---|---|---|---|
| world, **before** | 100 | **14** (all kerbs) | 0 | 9 of 36 (4 of 24) |
| world, **after** | 100 | **0** | **0** | 33 of 36 (24 of 24) |
| town, **before** | 32 | **15** | 0 | 12 of 32 (7 of 16) |
| town, **after** | 32 | **0** | **0** | 28 of 32 (16 of 16) |

The final run is after the surface split in `town_loader.gd`: both maps pass, with 0 fails.

### Traffic

Bumped traffic cars keep their existing rigid-body path. The traffic code is unchanged; it only types
the hero as `RigidBody3D` now.

| | result |
|---|---|
| `--traffic-test=60` (world) | **PASS**, all 7 checks. Brakes for the player (2.3 m short), bumped and recovered (4.8 s) |
| `--map=town --traffic-test=60` | **PASS**, all 7 checks |


### Performance (`--bench=20`, open world, adaptive traffic, RTX 4070 Ti shared with other agents)

Runs alternated before / after, with the same assets and the same session. The machine was busy with
other agents' jobs, and the run-to-run noise was ±20 %.

| | avg fps | 1 % low | draw calls |
|---|---|---|---|
| before (VehicleBody3D) | 175.5 / 166.8 / 158.1 (mean 167) | 90 / 78 / 56 | about 1050 |
| after | 172.2 / 128.7 / 137.6 (mean 146) | 85 / 61 / 49 | about 1150 |
| no traffic, before / after | 215 / 172 vs 212 / 156 | | 770 vs 900 |

A last set of three alternations, after the road surface split, ran while another agent had the GPU
saturated. Both versions measured a flat 10 fps (the VRAM-starved state the godot NOTES describe),
so those runs say nothing. Re-measure on an idle GPU before judging the 10 % budget.

`--car-cost` measures the parked cost with a static camera:

- frame rate within noise (313 with everything, 320 without the tach, 316 without the car's tick);
- the tach adds about 35 2D draw calls;
- the car's own tick costs about 0.25 ms of script per physics step.

Most of the gap in the driving bench is route and noise: the new car drives the autopilot route at
different speeds, so it sees different parts of the city. That said, the mean is about 12 % under
before, slightly over the 10 % budget. The levers, if it matters:

- `SUBSTEPS` (4 → 3);
- fewer probe rays per wheel;
- `--no-tach`-style batching of the gauge (render it to a texture);
- moving the tick to C++ / GDExtension.

## Merge notes

- **Replaced:** `game/scripts/car.gd` (same file, same public API: `setup`, `place`, `forward_speed`,
  `needs_reset`, `toggle_lightbar`, `input_throttle / input_steer / input_handbrake / autopilot`,
  `wheels[].is_in_contact()`, `impact`, `braking / reversing`). It now `extends RigidBody3D`.
  - `input_throttle < 0` still brakes, for the autopilot and old callers.
  - New: `input_brake`, `steer_override`, `prime_speed(v)`, `gear_label()`, `wet`, `town`.
- **Type changes** (`VehicleBody3D` → `RigidBody3D`): `main.gd`, `chase_camera.gd`, `hud.gd`,
  `automation.gd`, `traffic/traffic_automation.gd`. These are one-line edits.
- **`main.gd`** (additive):
  - new input actions: `shift_up`, `shift_down`, `toggle_manual`, `toggle_abs`, `toggle_tc`,
    `toggle_esc`, `toggle_steer_assist`;
  - `car.town`, `car.wet` (from the rain, `--dry` / `--wet`), camera shake hooks, `--vehicle=`;
  - routing for `--drive-test` / `--curb-test` / `--physics-shots` / `--car-cost` to
    `scripts/vehicle/vehicle_tests.gd`.
- **`automation.gd`:** its old drive test is now `--drive-old`. `BENCH` gains `car_tick_us`.
- **`hud.gd`:** adds the tach and the new controls hint, and shows `D` / `M` / `N` / `R` in the gear
  label. The old speed label sits off-screen (a pre-existing anchor issue, not touched); the tach
  shows the speed.
- **`chase_camera.gd`:** adds `shake()`.
- **`town_loader.gd`** (the perf workstream's file): one local change. `_faces_job` and
  `_prepare_collision` split the **road** category's trimesh by surface material (`SURF_KINDS`,
  `surface_kind()`), and `_make_collision` sets `meta("surface")`.
  - Bodies keep the `Col_<mesh>` names, so the traffic test's `cat == "road"` checks still work.
    Each surface body sits under its own `S_road_<kind>` holder node, because siblings sharing a
    name would be renamed (`@StaticBody3D@7`). That renaming broke the traffic off-road check once.
  - Road cells now have up to 5 trimesh bodies instead of 1. There are the same triangles in total.
- **New:**
  - `game/data/vehicles/{classes,tsubame}.json`;
  - `game/scripts/vehicle/{vehicle_params,vehicle_fx,vehicle_tests,tacho}.gd`.
- **No asset or export changes.** No re-import needed beyond what Godot does for the new scripts.

## Known limits

- **Low overhangs.** A box that hangs over a sidewalk 0.5–0.7 m up can wedge the nose under it, with
  the rear wheels lifted. This happens in the town, where the kit buildings' collision boxes include
  their awnings. The curb test skips such sites. R resets.
- **Kerbs at 15°.** At 10 km/h the car scrubs along the kerb rather than climbing it, as real tyres do.
  It is never stuck.
- **Probe geometry.** The wheel profile is sampled along the direction of travel, plus the hub. A kerb
  met exactly sideways (a 90° slide) is seen by the leading samples of the slide direction only.
- **Puddles** have no grip of their own: a wet road is wet everywhere.
- **Traffic cars** still use the kinematic and slide-on-impact model (unchanged). They don't roll.
- **Audio** is three loops pitched and mixed. It is not granular synthesis. It is not heard headless.
- **Smoke** is lit by the scene, so it is subtle at night away from street lights.
