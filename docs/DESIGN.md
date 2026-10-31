# Pigment — design plan

A desktop app for painting PBR textures directly onto 3D meshes.

## Decisions on the open choices

The brief left a few blanks. These are the picks, and why.

| Blank | Pick | Why |
|---|---|---|
| Where we beat Substance | **1. Open source (MIT/Apache-2.0)**, **2. git-friendly project files**, **3. speed on large meshes** | The first two are structural advantages Adobe can't copy. Speed is a stretch goal: it's where Painter is weakest on big meshes, and the architecture below (UV-space GPU stamps, GPU compositing, dirty tiles) is built for it. Native Linux comes for free with wgpu (Vulkan), so we get it without counting it as a pick. |
| Target user | Indie game artists exporting to **Unreal, Unity and Godot** | Matches the export presets in the MVP. |
| Stack | **Rust + wgpu + egui (eframe)** | wgpu gives us Vulkan, DX12 and Metal from one codebase, so Linux, Windows and macOS all work, and WGSL shaders are validated when they load. egui is immediate-mode, which suits a tool UI that changes all the time. Rust lets the CPU side (undo, file I/O, mesh processing) be tested without a GPU. C++/Vulkan/ImGui would give a bit more control but cost about 3x the engineering for the same features. |

## Things in the brief that need correcting

1. **"20 layers at 4K" won't fit in VRAM if every layer is a dense texture.** One paint layer holds base color, roughness, metallic, height and normal, plus a mask. At 4K that's about 200 MB per layer, so 20 layers is about **4 GB**. That's fine on a 12 GB RTX 3060 and over budget on the 8 GB card. The fixes:
   - Fill layers store no pixels. They're a few parameters plus a mask, so most of a real stack is cheap.
   - Paint layers use **sparse tiles** (256×256). Only tiles you've actually painted get allocated. This lands in the performance milestone (M8). Until then, use 2K for heavy stacks.
2. **"Under 16 ms per brush stamp" is too loose.** A fast stroke produces 10–50 stamps per frame, so 16 ms per stamp would mean 1–5 fps while painting. The real target is **under 0.5 ms per stamp, batched, so a whole frame of stamps fits in about 4 ms**. That's what the design aims for.
3. **"Paint the normal channel" and "paint height" overlap.** Both make the surface look bumpy. Height gets converted to a normal at composite time, and painted normals are blended on top using the Reoriented Normal Mapping (RNM) method. Both are kept, but artists will mostly use height.

## Architecture

```
crates/
  core/   pigment-core: no GPU. Mesh import, project model, layer stack,
          blend math (CPU reference), undo stack, project file I/O, export
          channel packing. Fully unit-tested.
  app/    pigment: wgpu renderer + egui UI.
          render/   viewport (PBR, IBL, tone mapping), picking, depth prepass
          paint/    stroke sampler, stamp pass (UV-space projection), seam dilation
          composite/ GPU layer compositor (compute shaders)
          bake/     AO / curvature / world-normal bakers
          ui/       panels, tool settings, layer stack widget
```

The rule is that everything in `core` is plain data plus pure functions. The GPU side mirrors core's data, and core never calls the GPU. That keeps the undo stack, the file format and the blend math testable, and it keeps them independent of the renderer when UDIMs or plugins arrive later.

### Data flow: from brush input to the screen

```
pointer events ──► StrokeSampler (core)
                    resamples the cursor path at `spacing × size`,
                    giving Stamps {screen_pos, size, opacity, pressure}
                      │
                      ▼
              StampPass (GPU, per stamp, batched per frame)
   draws the MESH with its UV coordinates used as screen position,
   so every texel that gets drawn is a point on the surface.
   For that texel the fragment shader:
     1. has its world position (interpolated) and normal
     2. projects the world position with the viewport camera, giving a screen pixel
     3. brush falloff = f(distance from the stamp centre, hardness)
     4. visibility: compares its depth with the viewport depth prepass
        (so we don't paint through the mesh), and fades with N·V
     5. writes MAX(stroke_mask, falloff × opacity) into a per-stroke mask
                      │
                      ▼
       Stroke apply: layer = lerp(layer_before_stroke, brush_value, stroke_mask)
       (uses the max, not a sum, so overlapping stamps inside one stroke
        don't build up opacity — this matches Painter's behaviour)
                      │  marks dirty tiles
                      ▼
              Compositor (GPU compute, dirty tiles only)
   for each layer, bottom to top, for each channel:
     out = blend_mode(out, layer.channel) × layer.opacity × mask
   height ─► normal (Sobel) ─► RNM blend with painted normals
                      │
                      ▼
              Seam dilation (GPU, jump flood) ──► material textures
                      │                            (baseColor, ORM, normal, height)
                      ▼
              Viewport PBR shader samples the material textures
```

### Brush projection

Painter projects the brush from the screen, but stores pixels in UV space. The usual approach of drawing a quad in screen space and back-projecting through a UV buffer breaks down at UV seams and at grazing angles.

This design goes the other way round. The **mesh is drawn into the texture** (vertex position = `uv * 2 - 1`), so each fragment is exactly one texel of the layer. The texel then asks "where am I on screen?" and "is my brush covering me?". The results:

- **Seams are painted on both sides correctly.** Two texels on opposite sides of a UV seam share a world position, so they land on the same screen pixel and get the same brush value. Nothing has to stitch the islands together.
- **No stretching.** Brush size is measured in screen pixels, so a stroke looks the same on screen however the UVs are laid out.
- **Occlusion** comes from a depth prepass of the viewport. A texel is only painted if its projected depth is within a small epsilon of the visible depth.

### Seam padding (dilation)

Bilinear filtering and mipmaps read texels *outside* each UV island, and those texels are normally empty, which shows up as dark lines along seams. After compositing, a **jump-flood** pass fills every empty texel with the nearest island texel. It takes log2(N) passes, about 12 at 4K, and only runs on dirty tiles. The UV island mask comes from drawing the mesh in UV space once when the mesh loads.

### Undo

`core::undo::UndoStack` holds `Command`s. Structural edits (add or delete a layer, change a parameter) are small, reversible commands. A stroke command stores the **dirty tiles before the stroke**: the GPU copies those tiles into a pooled snapshot buffer, and undo copies them back. There's a memory budget, and old snapshots go to system RAM first and are then dropped. The stack logic is GPU-free and tested. Snapshot storage is behind a trait.

## Project file format (git-friendly)

A project is a **folder**, so git can diff it and store it efficiently:

```
my_asset.pigment/
  project.json              # format version, mesh path, resolution, layer stack, every
                            # parameter, bake + export settings. Pretty-printed with
                            # stable ids, so diffs are readable.
  mesh/<file>               # copy of the source mesh (+ .bin/.png files for .gltf)
  layers/<res-id>/
    base_color.png          # RGBA8: sRGB colour + coverage
    roughness.png           # LA8: value + coverage
    metallic.png            # LA8
    height.png              # LA16: height (-1..1 mapped to 0..65535) + coverage
    normal.png              # RGBA8: tangent-space normal (OpenGL) + coverage
  masks/<res-id>.png        # L8
  .gitignore
```

- A channel nobody painted has no file. Saving only rewrites the pixel files of
  resources changed since the last save, and removes files nothing references.
- Every layer's pixels live under a *resource id*, separate from the layer id. A
  fresh id is minted whenever new pixels are created (new layer, duplicate, new
  mask), so undo history can never point at pixels that were overwritten.
- Mesh maps (AO, curvature) aren't stored: the bake takes well under a second
  (0.3 s for 100k triangles at 4K), so it reruns when a project opens.
- The manifest carries `"format": 1`. Newer formats are refused with a clear
  message, and older ones get migrated on load.

## Milestones (each one gives you something you can run)

| # | Milestone | You can… |
|---|---|---|
| **M1** | Window, mesh import (OBJ / glTF), orbit / pan / zoom viewport, UV checker preview | open a model and look around it |
| M2 | PBR (GGX, metallic/roughness), HDRI image-based lighting (prefiltered specular, irradiance, BRDF LUT), ACES tone mapping, exposure | see a realistic material under an HDRI |
| M3 | Painting on one layer: brush (size, opacity, hardness, spacing), UV-space projection, all 5 channels, seam dilation, stroke undo | paint on the model with no visible seams |
| M4 | Layer stack: paint and fill layers, per-channel blend modes, opacity, masks, GPU compositor, undo for every action | build a material from several layers |
| M5 | Save and load the project folder | close the app and pick up where you left off |
| M6 | Bake AO, curvature and world-space normal, plus the edge-wear generator (curvature + AO) | get automatic edge wear on a fill layer |
| M7 | Export PNGs: Unreal (BaseColor, Normal, packed ORM), Unity (Albedo, Normal, MetallicSmoothness), Godot | drop the textures into an engine |
| M8 | Performance: 100k triangles, 4K, 20 layers, 60 fps. Sparse tiles, per-stamp triangle culling, GPU timings overlay | check the targets on an RTX 3060 |

Built so these can come later without rewrites: **UDIMs** (a texture set is a list of tiles, and the stamp pass already works per tile), **high-to-low baking** (the bakers take a "source mesh" input that's the same mesh for now), **particle brushes** (they're just another stamp producer), **smart materials** (a layer stack saved as JSON), and a **plugin / Python API** (the core model plus the command-based undo is the scripting surface).

## Status (all MVP milestones implemented)

| | |
|---|---|
| M1 import + viewport | OBJ / glTF / GLB (scene transforms applied), orbit / pan / zoom, reverse-Z camera |
| M2 PBR + IBL | GGX-prefiltered environment (filtered importance sampling), SH9 diffuse, split-sum BRDF LUT, specular occlusion, ACES. Procedural studio HDRI built in, plus `.hdr` / `.exr` loading |
| M3 painting | 5 channels, size / opacity / hardness / spacing, eraser, UV-space projection with depth occlusion and facing fade, jump-flood seam padding |
| M4 layers | Paint and fill layers, 10 blend modes (RNM for normals), per-channel opacity, black/white masks, GPU compositor with dirty-rect updates |
| M5 save / load | Project folders as above |
| M6 bakes + generators | Many-direction shadow-map AO, dihedral curvature, world normal. Edge wear and dirt generators (curvature + AO + world-space fBm noise) |
| M7 export | Unreal (packed ORM, DirectX normal, 16-bit height), Unity (MetallicSmoothness), Godot (ORM), separate maps |
| Undo | Every document edit (diffs, coalesced per interaction) + strokes (GPU tile snapshots, 1.5 GB budget) |

### Measured performance (RTX 4070 Ti, release build, `perf_targets` test)

100k-triangle mesh, 4096² textures, 20 layers (10 paint, 10 fill, 5 masks with generators):

| | time |
|---|---|
| Viewport frame, 1600×1000, MSAA 4× | 0.37 ms |
| Painting frame: 8 stamps + apply + recomposite of the dirty rect through 20 layers | 6.1 ms (0.77 ms/stamp) |
| Full recomposite (stroke end, layer edits) | 24 ms |
| Stroke start (CPU screen binning of 100k triangles) | 3.2 ms |
| Bake AO (128 directions) + curvature | 0.3 s |
| Layer VRAM for that stack | 2.6 GB |

An RTX 3060 has roughly 40% of this card's throughput, so expect about 15 ms
painting frames at 4K with 20 layers, and comfortable 60 fps at 2K.

### Checked against production practice

A research pass compared the generators and bakers with Substance Painter's
documentation. Verified correct: chips and painted dents are recessed
(negative height), height-to-normal sign conventions (OpenGL, DirectX flip on
export), and the RNM blend. Changed as a result:

- **Height stacks:** the default height blend is Add, as in Substance, and
  height is HDR (no clamp until export).
- **Generator controls:** generators expose *AO influence* and *curvature
  weight*.
- **AO max distance:** the AO bake has a max occluder distance (Substance:
  "Max Occluder Distance").
- **No smearing on big triangles:** vertex curvature is faded by distance from
  each corner, so large flat triangles next to a bevel no longer inherit its
  curvature.

### Known limitations and next steps

- **Seams in height-derived normals.** Colour and painted channels are seamless
  (texels on both sides of a seam take their brush value from the same world
  position). Normals computed from *height* use one-sided slopes at island
  borders, which leaves a faint 1-texel line where a stroke crosses a seam
  diagonally. The fix is a cross-seam neighbour map (each border texel finds its
  3D neighbour on the other island). Planned.
- **Tangents** use Lengyel's method with seam welding, not MikkTSpace, so baked
  normal maps from other tools may shade slightly differently. Add `mikktspace`
  before importing external normal maps.
- **VRAM.** Paint layers are dense. The sparse 256² tile allocation from the plan
  is the next performance step, for 8 GB cards at 4K.
- **AO** has no max-distance (shadow maps see the first hit only), so deep
  cavities read darker than in a ray-traced bake.
- **No pen pressure** yet (egui doesn't expose tablet pressure on all platforms).
- UVs must be in the 0..1 range (no UDIM / tiling), as scoped.
- Changing resolution resamples every layer and clears the undo history.
