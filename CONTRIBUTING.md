# Contributing to Pigment

Thanks for wanting to help. Bug reports, ideas, docs fixes and code are all welcome.

## Before you start

- **Small fix?** Just open a pull request.
- **Bigger change?** Open an issue first so we can agree on the shape before you spend time on it.
- Be kind. Everyone here follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

You need [Rust](https://rustup.rs/) (stable) and a GPU with Vulkan, DX12 or Metal.
On Linux, also install the window and GTK packages listed in [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

```bash
git clone https://github.com/krnblds/pigment.git
cd pigment
cargo build --release
cargo run --release -p pigment
```

## Test

```bash
cargo test --release -- --test-threads=2          # everything (needs a GPU)
cargo test --release -p pigment-core              # GPU-free core only (what CI runs)
cargo test --release -p pigment --lib -- mcp:: cli::   # MCP scripts vs. tool schemas, agent CLI
```

GPU and UI tests skip themselves when there is no GPU; CI covers the core crate, MCP schemas, and CPU-only CLI tests
and the MCP schemas. If your change touches rendering, painting or the UI, run the full
suite locally and say so in the pull request.

## Making a change

1. Fork the repo and make a branch from `main`.
2. Keep the change focused on one thing.
3. Run `cargo fmt` and `cargo clippy --workspace`, and fix what they flag.
4. Add or update tests where it makes sense.
5. If you add or change an MCP tool, update its schema, the scripts in `scenes/`, and the
   matching notes in [`docs/agents/`](docs/agents).
6. For visual changes, add a before/after screenshot to the pull request.

## Commit messages

Start with the area, then say what changed in plain words:

```text
viewport: soft contact shadow under the lightbox stage
game: damage follows the car you drive out of the garage
```

## Where things live

| Folder | What it is |
|---|---|
| `crates/core` | GPU-free document model, export, project files |
| `crates/app` | the app (egui + wgpu), shaders, MCP server |
| `tools/` | Blender add-on, asset generators, city build |
| `game/` | the Godot showcase game |
| `docs/` | guides, design system, per-feature notes |

See [docs/DESIGN.md](docs/DESIGN.md) for the architecture.

## License

By contributing, you agree your work is released under the [MIT License](LICENSE).
