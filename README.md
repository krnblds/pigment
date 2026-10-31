# Pigment

Open-source PBR texture painter: paint base color, roughness, metallic, height and
normal directly onto 3D meshes. Rust + wgpu + egui. See [docs/DESIGN.md](docs/DESIGN.md)
for the architecture, project format and milestone plan.

## Run

```
cargo run -p pigment --release            # opens with a test torus
cargo run -p pigment --release -- model.glb
cargo test                                # core logic tests (no GPU needed)
```

Controls: drag to orbit, middle-drag to pan, wheel or Alt+right-drag to zoom, F to frame.
Drop an `.obj`, `.gltf` or `.glb` onto the window to open it.
