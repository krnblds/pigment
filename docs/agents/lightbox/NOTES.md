# Lightbox and showroom

## Blender lightbox

`tools/lightbox/lightbox_scene.py` is a headless Cycles studio for product shots of any glb in the repo: the six vehicles (with their liveries), props and town kit pieces. It works as a module (import it inside Blender) and as a CLI. `tools/lightbox/sheets.py` builds contact sheets with PIL. `tools/lightbox/make_hero_cars.py` rebuilds `docs/readme/hero_cars.png`.

![light](grid_light.png)
![dark](grid_dark.png)

### What it builds

- **Seamless cyclorama.** A floor curves through a quarter-circle cove into a back wall. It is made of 40 floor rows, 48 cove rows and 24 wall rows by 48 columns, all smooth shaded. Its size comes from the asset: the wall sits behind the circle the asset sweeps as it turns, so turntables and every preset keep the sweep behind the asset.
- **Two looks.**
  - `light`: a light-grey matte sweep with a big overhead softbox for the soft contact shadow. A key comes from front-left and a weak fill from front-right. A long thin strip high at the back puts a clean line on hoods and roofs, and a long horizontal strip at camera-right puts a line along the near flank. A wash lights the wall. Two black flags just out of frame stop white paint from turning to mush; they are invisible to the camera. Exposure is -0.3, so the floor stays just under clipping.
  - `dark`: a car-commercial look with a near-black glossy sweep. It has the same strip layout (two hood-line strips, a flank strip, a low front flank strip, thin vertical rims and a dim key), plus one large soft glow on the cove.
    - Through **light linking**, every light except the glow skips the sweep. The black mirror floor therefore shows the car's reflection and a soft horizon. It shows no rectangles from the lights.
- **Lights** are rectangular area lights scaled with the asset. Their energy scales with the square of the size, and they are hidden from the camera (`visible_camera = False`).
- **Camera presets:** `front34`, `side`, `rear34`, `rear`, `front`, `top` and `detail`.
  - The camera always looks along +Y at the sweep, and a preset turns the asset instead.
  - Framing is exact: `fit()` solves the perspective frustum in closed form against the asset's vertices, so the limiting pair of frame edges touches the asset at `1/pad` and the other pair is centred.
  - `top` dims the lights directly overhead, which would otherwise mirror into the roof.
  - `detail` frames the front-lower quarter (headlamp and front wheel) at 90 mm, f/2.8.
- **Render settings:** Cycles on OptiX GPU with adaptive sampling and OIDN denoise. The view transform is AgX with the Medium High Contrast look. Indirect clamp is 6.
- **Turntable:** the asset turns about its footprint centre and the camera and lights stay fixed. The camera is framed on the union of every angle, so nothing jumps between frames. `--anim` keyframes the turn linearly over frames 1..N, and `--blend` saves the scene.
- **Any glb.** Objects named `Collider*` are hidden. The asset is centred on its footprint and stands on z = 0, at the lowest visible vertex. Vehicles already have their origin on the ground.

### Liveries

Each vehicle glb carries its liveries as `KHR_materials_variants` on `Body` (see `docs/agents/fleet/NOTES.md` and `assets/vehicles/index.json`). Blender 5.2's glTF importer keeps them:

- `bpy.context.scene.gltf2_KHR_materials_variants_variants`: the variant names and indices, in the same order as `index.json`;
- `mesh.gltf2_variant_mesh_data`: one entry per mapping, with `material_slot_index`, `material` and the `variants` that use it.

`set_livery(asset, name_or_index)` assigns each mapping that lists the wanted variant to its slot. This is the importer's own "display variant", and the same method as `tools/vehicles/render.py`. If an imported mesh has no mapping data, it falls back to the material named `<id>_<variant>`.

### CLI

```
B="/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"
L=tools/lightbox/lightbox_scene.py

# one still: preset, look, livery
"$B" -b --factory-startup --python $L -- still --asset hayate --preset front34 --look dark --livery racing --res 1600x1000
# any glb (props, town kit)
"$B" -b --factory-startup --python $L -- still --asset assets/props/vending_machine.glb --look light
# beauty grid of the six vehicles in both looks (grid_light.png, grid_dark.png)
"$B" -b --factory-startup --python $L -- grid --look both --res 960x600 --samples 160 --width 1600
# every livery of one vehicle
"$B" -b --factory-startup --python $L -- liveries --asset kago --look light
# all vehicles x all liveries, fleet_variants.png layout (rows mame..kaiun, 8 cells of 480x300 -> 1600x750)
"$B" -b --factory-startup --python $L -- fleet --look both --samples 64
# turntable: 8 frames + sheet; --anim keyframes it, --frames-dir keeps the frames, --blend saves the scene
"$B" -b --factory-startup --python $L -- turntable --asset tsubame --look dark --frames 8 --width 1600 --anim
# every camera preset of one asset
"$B" -b --factory-startup --python $L -- presets --asset hayate --look light
# props in both looks stacked into one file
"$B" -b --factory-startup --python $L -- grid --assets assets/props/ramen_cart.glb,assets/props/bus_stop.glb --cols 2 --look both --stack --out docs/agents/lightbox/props.png
# README hero, same 1600x1728 layout, lightbox sheet in place of fleet_variants.png
python tools/lightbox/make_hero_cars.py --sheet path/to/fleet_liveries_dark_nolabels.png
```

Common options:
- `--res WxH` sets the size of each image or cell. `--samples N` defaults to 128 for stills and 64 for livery cells.
- `--labels 0` turns off the cell labels. `--width N` sets the final width of a sheet.
- `--lod _lod1` picks a vehicle LOD. `--yaw DEG` adds a turn on top of the preset.

Sheets are composed by the system Python, because Blender's own Python has no PIL. The script finds it on `PATH`; set `LIGHTBOX_PYTHON` to override. `save_small` keeps every PNG under 1.5 MB: if full colour does not fit, it quantises to 256 colours with dither.

As a module:

```python
import sys; sys.path.insert(0, "tools/lightbox"); import lightbox_scene as LB
LB.reset(); LB.setup_render((1600, 1000), 128)
a = LB.import_asset("hayate"); LB.set_livery(a, "racing")
LB.build_studio(a, look="dark")
LB.render(LB.shoot_camera(a, "front34", (1600, 1000)), "out.png")
```

### Proof

| file | what |
|---|---|
| `grid_light.png`, `grid_dark.png` | the six vehicles, default livery, `front34`, 960x600 cells at 160 samples |
| `fleet_liveries_dark.png`, `fleet_liveries_light.png` | all 47 liveries in the `fleet_variants.png` layout, labelled |
| `tsubame_turntable_dark.png` | 8 angles of the Tsubame-4 cruiser; the camera is fixed and the car turns |
| `props.png` | vending machine, ramen cart, data kiosk and bus stop, light look above and dark look below |
| `../../readme/hero_cars.png` | the README hero, rebuilt with the dark lightbox livery sheet (no labels) |

The hero keeps the original layout. The top 900 px are `pigment_ui_car.png`. A 78 px caption band follows, with the same text redrawn in Segoe UI and the ink widths matched to the original. The bottom is the 1600x750 livery sheet.

### Known limits

- **Town kit.** The meshes in `assets/town/*.glb` carry no textures; Pigment exports them into a git-ignored folder. They render as white clay, which disappears into the light sweep, so the proof uses props. Apply `tools/blender_pigment.py` materials first for textured buildings.
- **Paint.**
  - The fleet paints are rough metallic base plus coat, from textures. Under big soft lights they show broad sheen as well as the strip lines; the dark look keeps the lights narrow to limit this.
  - Pale liveries in the light look read a little low in contrast. That is the honest result of white paint in a white room.
- **Blown areas.** Very white vans can reach the top of the AgX curve on the flank lit by the flank strip in the dark look, about 1 % of the cell.
- **Framing.** Framing uses the vertices of the visible meshes, so alpha-0 hidden parts still count, such as the Tsubame's light bar in civilian liveries. Wheels count too.
- **Rigs.** The light rigs are tuned for assets that face -Y (the repo's glTF +Z front). Other assets still frame correctly, but presets like `front34` then show a different side.
- **GPU sharing.** Livery sheets use 64 samples per 480x300 cell, enough after denoise at the sheet's final 200x125. Raise `--samples` for print.
