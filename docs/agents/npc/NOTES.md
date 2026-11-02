# npc: pedestrians in the rain city

Real people on the pavements of the open world: 34 MPFB-generated citizens (32 walkers + the two
Hoshikawa "Waker" player characters) with CC0 clothes, procedural rain coats / jackets / hoodies and
Pigment-weathered atlases, animated with the CC0 Quaternius Universal Animation Library through Godot's
humanoid retargeting.  They walk the sidewalks of `world.json`, keep left, weave round street furniture,
stop at bus stops, benches, vending machines and shop fronts, shelter from the rain or put their
umbrellas up, wait for the red at signalled crossings (traffic stops for them), jump out of the way of
the player's car - and when they don't make it, they ragdoll (Jolt), lie there a moment, get up and
hurry off.  `--no-npc` turns it all off.

| | |
|---|---|
| `lineup.png` | all 34 citizens (LOD0, bind pose): the last two are the Waker player characters |
| `npc_chase_view.png` | the game camera behind the car: people on both pavements in the rain |
| `npc_closeup.png` | a walker with an umbrella (right arm blended to the umbrella pose) |
| `npc_ragdoll.png` | 40 km/h hit: thrown by the impact (physical bones, momentum from the car) |
| `npc_crossing.png` | walkers on a signalled zebra crossing |

All but the line-up come from `--npc-shots=<dir>` (windowed, real gameplay code); the line-up from
`tools/npc/preview_citizens.py` (headless Blender EEVEE).

## How it is built (regenerate after merging)

Everything generated is git-ignored (`.npccache/`, `game/assets/npc/`); only scripts, the bone maps and
recipes are in git.  Exact commands (from the repo root, system Python with numpy + Pillow, `curl`):

```
python tools/npc/build_all.py                 # fetch -> build -> atlases -> Pigment -> Godot (~5 min)
#   = python tools/npc/fetch_assets.py          CC0 packs -> MPFB user data, UAL 1+2 -> .npccache/ual
#     blender -b --factory-startup --python tools/npc/build_citizens.py -- [--only id,id]
#     python tools/npc/compose_atlas.py
#     python tools/npc/paint_citizens.py         (optional: needs target/release/pigment-mcp.exe)
#     python tools/npc/sync_godot.py             (writes import settings, godot --import, builds the anim library)
python tools/npc/convert_extra_anims.py       # only if you dropped extra clips (see below)
blender -b --factory-startup --python tools/npc/preview_citizens.py -- --out docs/agents/npc/lineup.png
```

Requirements: Blender 5.2 with the MPFB 2 extension installed as a user extension (the script enables it
itself, so `--factory-startup` works); MPFB's "MakeHuman system assets" pack (fetch_assets installs it if
missing); Godot 4.7 console exe (`GODOT` env var or `--godot`).  Without built citizens the game prints a
warning and keeps the old traffic silhouettes.

### 1. Characters (`tools/npc/build_citizens.py`, `recipes.py`)

* **Recipes** (`recipes.py`, deterministic, seed 2077): 16 men / 16 women, archetypes dealt in proportion
  (salaryman, street, techwear, worker, elder, student, nightlife, courier), mostly east-Asian mixed
  population, age 25-80, MPFB height / weight / muscle / proportions per body.
* **MPFB**: `HumanService.deserialize_from_dict` with the low-poly body proxy (male1591 / female1605),
  the `game_engine` rig (UE-mannequin bone names), skin by age / race / sex, low-poly eyes, eyebrows,
  hair, clothes and shoes.  The basemesh is dropped; MPFB's clothes delete-groups hide the proxy under
  the clothes.  Every asset is checked: only items whose own header says CC0 are used (the packs also
  contain AGPL- and CC-BY-headed items, which are skipped).
* **Outer layer ("shell")**: there are hardly any CC0 coats, so they are made: the body proxy's torso +
  arms (by bone weights, cut at the waist / wrists / neck) pushed out 2-3 cm and smoothed -> jacket,
  bomber, hoodie, hi-vis vest (no sleeves), raincoat, coat; coats and raincoats get a lofted skirt
  (smooth ellipses round the trunk + legs, rigged pelvis -> thighs so it follows the stride); coats an
  upright collar, hoodies a hood-down roll.  Everything under the shell (body, shirts) is deleted - no
  poke-through.  Trims are painted from a bind-pose position map (zips, hems, cuffs, reflective bands,
  neon piping).
* **Wakers** (`WAKERS`, ids `waker_m`, `waker_f`): long charcoal Hoshikawa field coat with subtle cyan
  Dreamlink piping (front edges, collar, hem, cuffs; emissive at 0.55), a small temple-mounted resonance
  band over the left ear (emissive cyan), cargo trousers, ankle boots.  Same skeleton and LODs.
* **Atlas** (`compose_atlas.py`): every part in one 1024 atlas (buddy allocator): `_albedo` (RGB + alpha
  for hair/brows), `_normal`, `_mask` (R roughness, G rain response, B emission: 1 = trims / band,
  0.5 = sleepwalker glow at the temples and the eyes).  Clothes / hair tinted per recipe; shell fabrics
  procedural per kind (fleece, ripstop, satin quilting, twill, PVC, hi-vis mesh).
* **Pigment** (`paint_citizens.py`, `pigment-mcp --script`): per citizen a project on its LOD0, the
  atlas as a UV image fill, a "Grime" dirt layer and a dark glossy "Rain splash" gradient on hems and
  shoes; the exported BaseColor / Roughness go back into the atlas.  Scripts land in
  `.npccache/citizens/pigment/<id>.jsonl` (with a `render` check view).
* **LODs**, one glb per citizen (`Armature` + `LOD0` + `LOD1` + `LOD2`): LOD0 8.8-14k tris (clothes
  decimated when over 14k), 2 surfaces (opaque + alpha-cut hair/brows); LOD1 2.6k tris, same skeleton;
  LOD2 ~360 tris, static, arms down, vertex colours mark legs / arms for the crowd shader's walk sway.

### 2. Animation (`game/scripts/npc/character/`)

* Quaternius **Universal Animation Library 1 + 2 (Standard, CC0)**, imported with
  `bonemap_ue.tres` (SkeletonProfileHumanoid, retarget "overwrite axis" + "fix silhouette"); the
  citizens import with `bonemap_mpfb.tres`.  Both skeletons become `%GeneralSkeleton` with profile bone
  names, so any humanoid clip plays on any citizen and on the player.
* `anim_library.gd` builds `res://assets/npc/anim/library.res` (40 clips: idle, idle_talk, idle_fold,
  idle_phone, idle_rail, look_around (generated: idle + head/neck turns), walk, walk_formal, jog, sprint,
  sit_enter/idle/talk/exit, flinch, flinch_head, knockback, roll, dodge_jump, jump_*, getup_back (lying
  on the back), getup_front (generated: kneel -> stand, the ragdoll blends into it), consume, interact,
  zombie_idle / zombie_walk (sleepwalkers) ...) and `library_lite.res` (no finger / toe tracks: walkers
  beyond 14 m).  Positions are kept on the hips only, scales dropped.
* `citizen_anim.gd`: the AnimationTree - idle kinds (Transition) / gait BlendSpace1D (walk, jog,
  sprint) blended by speed with time scales matched to the clips' measured speeds and the character's
  size, sleepwalker blend, umbrella arm (filtered Blend2), looping activity, one-shot actions.

### 3. Behaviour (`game/scripts/npc/sidewalks.gd`, `npc_manager.gd`)

* **Network** from `assets/world/world.json` (parsed on a worker thread, ~0.6 s): per junction arm two
  nodes where the crosswalk meets the pavement (2.7 m back from the mouth - where the ped signals stand),
  sidewalks along every curbed street / avenue (curb + 1.75 m, two walking lines +-0.5 m), corners
  between neighbouring arms (intersection of the pavement lines, or a straight link), crossings over
  every arm of T / X junctions.  72 km, 1450 edges, 445 crossings.  Street furniture (lamps, bollards,
  meters, benches, vending machines, bus stops, trees ...) marks the blocked walking line every 2 m;
  POIs: 56 bus stops, 392 benches, 1015 vending machines, kiosks, stalls and 2600 shop fronts.
  Fallback without world.json: straight sidewalks from the lane graph.
* **Walkers** (default 100 within 110 m of the camera, respawned out of view past 128 m): keep left,
  overtake or slow behind slower people, weave round furniture, stop at bus stops (wait 10-45 s, phone /
  look around), sit on benches, use vending machines, loiter at shop fronts (pairs chat), shelter at the
  fronts when it rains (those without umbrellas; the others put theirs up), extra clips (smoking, phone,
  leaning, arguing, sweeping) outside shops and bars when installed.
* **Crossings**: signalled junctions -> only when that arm's cars have red (`signals.state`), all others
  and always: a gap check against the player's car and traffic.  Walkers on a crossing (and anyone lying
  in the road) are obstacles for the traffic AI (`traffic_manager.ped_provider.add_obstacles`), so cars
  brake for them.
* **The player's car**: predicted closest approach < 1.4 s and inside ~2.1 m -> dodge (jump / roll
  sideways out of its path), < 0.35 s -> flinch.  Contact (car box vs walker, 120 Hz) -> `hit()`.
* **Ragdoll** (`character/ragdoll.gd`): 12 PhysicalBone3D (capsules, cone joints, layer 64, scans the
  world only) created on the first hit and freed after; velocity from the impact impulse (80 kg x car
  velocity + lift) plus a spin at the hit bone; settles (hips < 0.35 m/s for 0.7 s, max 5 s), then the
  body root is placed where it lies, getup_back / getup_front plays while the simulator influence fades
  1 -> 0 over 0.55 s, and they walk back onto the pavement, faster, for 10 s.  At most 6 ragdolls at once:
  further hits play a knockback stagger.  A hit also gives the car a small `apply_impact` on its damage
  node (chips, a thud, no deformation), a camera shake and a slight slowdown.  No blood or gore.
* **Sleepwalkers** (for the cases system): `set_sleepwalker(on)` - faint cyan glow at the temples and
  eyes (mask B = 0.5, instance uniform), 45 % zombie posture blend, slower idle and walk.

### 4. Performance

* Near the camera the nearest 32 walkers (within 46 m) have a Citizen node: LOD0 < 12 m, LOD1 beyond,
  AnimationTree advanced manually - every frame < 12 m, every 2nd < 24 m, every 4th beyond, staggered by
  id; the lite library beyond 14 m.  The rest are the LOD2 crowd: one MultiMesh per citizen model,
  buffers rewritten at 30 Hz, walk sway in the vertex shader.  AI at 5 Hz staggered; far walkers move
  every 3rd frame; ground rays every 0.4 s for near walkers only; nodes pooled per model.
* Measured (RTX 4070 Ti, 16 cores shared with other agents' builds - numbers move with the load):
  * headless `--npc-test` (100 walkers, 31-36 with skeletons, the rest crowd), NPC cost per frame
    including the 120 Hz hit tests: **0.86-0.91 ms** (AI 0.13, motion 0.27-0.28, animation 0.35-0.39,
    crowd 0.09, hit tests 0.01-0.02); spikes up to 1.4-1.6 ms when a Citizen node is first built
    (pooled afterwards).  Under 100 % CPU load from parallel `cargo` builds the same run measured 10 ms
    (everything else slowed the same way), so the budget check fails when the machine is saturated.
  * windowed 1600x900 `--npc-bench` (night, rain, SDFGI, traffic on): 13.7-13.9 ms/frame without
    pedestrians, 16.6-16.7 ms with them in steady state (the first phase, which includes the citizens'
    shader compiles and node creation, 19-20 ms).  Of the +2.7-3.0 ms, the NPC scripts are 1.2-1.4 ms;
    the rest is rendering 30+ skinned characters (skeleton updates, skinning, 2 surfaces each, LOD0
    shadows < 12 m) and the crowd batches.  Levers if that is too much: `max_near` (32), `near_radius`
    (46 m), LOD0 range (12 m, `citizen.gd`), shadows.

### 5. Tests

`--npc-test` (headless, exit 0 = pass; `--npc-out=<json>` writes the details), ~70-100 s:

| check | what | typical result |
|---|---|---|
| spawn | 100 walkers placed, the near ones with skeletons | 100 agents, 40 Citizen nodes |
| pavement | 20 s, every walker every 0.5 s: never on a drive lane (lane graph within 2.2 m) outside crossings / dodges / falls; walking pace | 0 of ~3600 samples off the pavement, 1.25-1.36 m/s |
| crossing | a walker sent to the signalled crossing at n17 arrives on green, waits, crosses on red; no crossing ever entered on non-red | waited on green, entered on red, 0 red violations in 7-37 crossings |
| dodge | the car at 60 km/h at a walker in the road | they jump aside, not hit |
| ragdoll | a 45 km/h hit | 12 physical bones, thrown 1-15 m, down 2.5-3.7 s, back on their feet |
| cap | 9 walkers hit at once | 6 ragdolls at most, the rest stagger; none left down after 12 s |
| perf | NPC cost per frame | 0.86-0.91 ms (budget 1.5 ms; see the load caveat above) |

`--npc-shots=<dir>` (windowed) writes the proof PNGs, `--npc-bench` (windowed) the fps comparison.

Regression (headless, with the pedestrians on): `--drive-test` pass, `--traffic-test=60` pass (traffic
reports `"peds": 100`, brakes for the player, no stuck cars), `--showroom-test` pass, `--damage-test`
pass (one earlier run failed `lamp_falls`: the lamp snapped but tipped 17.9 deg instead of > 45 deg on
its second-choice lamp; the rerun and the `--no-npc` run pass - physics variance with walkers around
the test's lamp).

## API for other systems

```gdscript
const CitizenLib := preload("res://scripts/npc/character/citizen_library.gd")
CitizenLib.available() -> bool
CitizenLib.ids(include_players := false) -> PackedStringArray      # "citizen_00".."citizen_31", "waker_m", "waker_f"
CitizenLib.info(id) -> Dictionary                                  # sex, height, hips, archetype, umbrella, clothes ...
var c = CitizenLib.spawn("waker_f", {"lite": false, "umbrella": "", "ragdoll": true, "shadows": true})
add_child(c)                                                        # c: scripts/npc/character/citizen.gd (Node3D)
c.set_speed(v)                     # m/s: idle / walk / jog / sprint, rates matched to the character's size
c.set_idle("idle_phone")           # idle, idle_talk, idle_fold, idle_phone, look_around, idle_rail, sit_idle, consume
c.play_action("flinch")            # any library clip once; c.action_playing()
c.set_activity("sit_idle", 1.0)    # any looping clip over everything (0 / "" = off)
c.set_umbrella("clear")            # clear / black / neon / ""
c.set_sleepwalker(true)            # temples + eyes glow, slack posture, slower idle
c.ragdoll(impulse, at, exclude_body)   # signals fell, stood_up; c.is_down()
c.skeleton(), c.anim_tree()        # %GeneralSkeleton (SkeletonProfileHumanoid names), the AnimationTree
c.anim_auto = false; c.advance(dt) # drive the animation yourself (the crowd does)
```

* The animation library: `preload("res://scripts/npc/character/anim_library.gd").get_library(lite)`;
  the tree: `citizen_anim.gd` `make(lib)`, `set_speed / set_idle / play_action / set_activity /
  set_umbrella / set_sleepwalker`.  Any humanoid model works once it is imported with a
  SkeletonProfileHumanoid bone map and `GeneralSkeleton` as the unique skeleton name (see
  `tools/npc/sync_godot.py` `RETARGET`).
* The ragdoll alone: `character/ragdoll.gd` `setup(skeleton, anim_tree, root, hips_height)`,
  `ragdoll(impulse, at)`, `exclude(body)`, signals `fell`, `stood_up`.
* The crowd (`main.npc`, `npc_manager.gd`): `agents_near(p, r)`, `set_sleepwalker(agent, on)`,
  `hit(agent, impulse, at, by)`, signal `pedestrian_hit(pos, speed)`, `summary()`, `count()`.

## Extra clips (Mixamo etc.) - the user's drop-in

Third-party clips are never committed (Mixamo's terms forbid redistribution; this repo is public).
`game/assets/npc/anim_extra/` is a git-ignored drop folder (with a `.gdignore`, Godot doesn't import it).

1. On mixamo.com pick any character, search for these and download each as **FBX Binary, 30 fps,
   Skin: Without Skin**, tick **In Place** where offered:
   `Smoking`, `Talking On Phone`, `Leaning On A Wall` (or `Wall Lean`), `Arguing`, `Sweeping`
   (more: `Texting While Standing`, `Looking Around`, `Waiting`, `Standing Idle`).
2. Save them into `game/assets/npc/anim_extra/` (the file name becomes the clip: `Smoking.fbx` ->
   `extra_smoking`).
3. `python tools/npc/convert_extra_anims.py` - reads each skeleton, writes a SkeletonProfileHumanoid bone
   map for its prefix (`mixamorig:`, `mixamorig1_` ...), retargets on import exactly like the citizens and
   builds `res://assets/npc/anim/extra/library_extra.res` (git-ignored).
Walkers then use clips whose names contain *smok*, *phone*, *lean*, *argu* or *sweep* as activities at
shop / bar fronts; without them they use the CC0 idles (fold arms, phone, look around, chat).

## Licences and credits

* **Characters**: MakeHuman / MPFB 2 (GPL-3 tool; its output and the assets below are CC0).
  MakeHuman system assets (proxies, skins, eyes, eyebrows, hair, system clothes and shoes): CC0,
  "explicitly released as CC0 in September 2020", Data Collection AB / the MakeHuman team.
  Community asset packs (static.makehumancommunity.org asset packs, CC0 section): shirts01, pants01,
  shoes01, hats01, hair01, masks01, glasses01; only items whose own file header says CC0 are used:
  Margaret Toigo (toigo_* tops, trousers, ankle boots, bobs), Cortu Johnstone (cargo pants, hair),
  Joel Palmius / joepal (crude t-shirt, medical mouth protection), elvs (crude t-shirt), namuhekam (polo
  shirt), aethelraed (cloche hat), spamrakuen (glasses).  CC0 needs no attribution; credited anyway.
  No CC-BY asset is used.
* **Animation**: Quaternius, Universal Animation Library and Universal Animation Library 2, Standard
  editions, CC0 (quaternius.com / quaternius.itch.io).
* **Procedural**: shells, coat skirts, collars, the resonance band, fabrics, umbrellas: this repo.
* **Mixamo**: not shipped, not committed; user drop-in only.

## Known limits

* Coats are body-hugging shells with a lofted skirt: at a sprint or in a ragdoll the skirt can clip
  through the legs; the procedural fabrics are plain at close range.
* Clips are retargeted from the UE mannequin: MPFB's slightly forward head posture shows a little.
  No dedicated face-down get-up exists in the CC0 set (getup_front is the end of a kneel, the ragdoll
  blends into it); no look-around clip either (generated from idle).
* Benches: the sit clip is aligned to the bench position, not its exact seat height.
* Walkers only avoid each other along the pavement (lane change / slow down), not as a full crowd sim;
  furniture is avoided by switching walking line, so a walker can brush past something placed between
  the lines.
* Sidewalks are derived from `world.json`; the old `--map=town` gets straight pavements only.
* Pigment pass: the dirt / gradient generators work on the LOD0 layout; Pigment dilates the islands, so
  the atlas gaps fill with colour (harmless).

## Merge hot spots

* `game/scripts/main.gd`: a flag doc line, `var npc`, one `create()` call after the damage setup, one
  `elif` in the test chain.
* `game/scripts/traffic/traffic_manager.gd`: `var ped_provider` and 3 lines in `_late_setup`
  (`peds = ped_provider` replaces the silhouettes; obstacles / `count()` go through it).
* `.gitignore` (+ `.npccache/`) and `game/.gitignore` (+ `assets/npc/`).
* New: `game/scripts/npc/**`, `tools/npc/**`, `docs/agents/npc/**`.  Nothing in the damage scripts
  changed (the hit uses `damage.hero_damage.apply_impact`).
