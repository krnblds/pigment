# Pigment

Open-source PBR texture painter: paint base color, roughness, metallic, height and
normal directly onto 3D meshes, build materials from paint and fill layers with
masks and procedural generators, bake mesh maps, and export to Unreal, Unity or Godot.

Rust + wgpu (Vulkan / DX12 / Metal) + egui. Windows, Linux and macOS.

See [docs/DESIGN.md](docs/DESIGN.md) for the architecture, project format and the graphics techniques.

## Run

```
cargo run -p pigment --release                 # opens with a test torus
cargo run -p pigment --release -- model.glb     # new project from a mesh
cargo run -p pigment --release -- my.pigment    # open a project folder
```

## Using it

| Action | How |
|---|---|
| Paint | Left-drag on the model |
| Orbit / pan / zoom | Alt+left-drag or right-drag / middle-drag / wheel (or Alt+right-drag) |
| Brush size | `[` and `]` |
| Eraser | `E` |
| Mask colour (white shows, black hides) | `X` |
| Frame the model | `F` |
| Material ↔ base colour view | `M` |
| Undo / redo | Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) |
| Save / save as / open | Ctrl+S / Ctrl+Shift+S / Ctrl+O |
| Export textures | Ctrl+Shift+E |
| New project from a mesh | File menu, or drop an `.obj` / `.gltf` / `.glb` on the window |
| Load an HDRI | Display panel, or drop a `.hdr` / `.exr` on the window |

**Layers** (right panel): `+ Paint`, `+ Fill`, and the one-click `+ Edge wear` / `+ Dirt`
smart layers. Select a layer to edit its opacity, per-channel blend modes and
opacity, fill values, and mask. A mask can carry a generator (edge wear or dirt),
which uses the baked AO and curvature; paint black on the mask to protect areas.

**Texture set** (left panel): resolution (512 to 4096) and the AO / curvature bake.

## Tests

```
cargo test                                                       # 70+ tests, ~5 s
cargo test -p pigment --release perf_targets -- --ignored --nocapture   # performance check
```

The core crate (document model, blend math, undo, strokes, tiles, curvature,
export packing, project files, IBL math) is GPU-free. The app crate validates every
WGSL shader offline with naga, and runs headless GPU tests that paint, undo, redo,
composite, bake, export, save and reload on a real device without opening a window.
