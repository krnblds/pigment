# Agent workflows

Build both binaries with `cargo build --release`. `pigment` opens the desktop app
when invoked without arguments or with a mesh/project path. It also supports the
commands below. `pigment-mcp` remains the stdio MCP server and supports its existing
`--script` and `--export-for-blender` interfaces.

## Discover and diagnose

```sh
pigment tools
pigment tools new_project
pigment doctor
pigment doctor --project asset.pigment --export-dir out
pigment doctor --no-gpu
pigment inspect asset.pigment
pigment inspect model.glb
```

Commands emit JSON on stdout (`--json` is accepted explicitly). Exit status is
0 for success, 1 for a failed check or execution, and 2 for invalid input/usage.
`--help` prints human-readable usage. Inspection and schema validation need no GPU.
Doctor checks GPU/device availability and reports missing optional sky assets as
warnings. A requested project or destination failure is an error. Destination
checks create and remove a uniquely named probe in the nearest existing ancestor.

Inspection decodes the mesh, checks UVs and texture dimensions, and follows all
texture-set manifests and image-fill references. Missing paint channel files are
valid transparent channels, as in the project loader.

## Validate before execution

```sh
pigment validate calls.jsonl
pigment run calls.jsonl --feedback out/review
printf '%s\n' '{"tool":"get_project_info"}' | pigment run -
```

JSONL scripts use one `{"tool":"...","args":{...}}` object per line; blank lines
and `//` comment lines are allowed. `-` reads stdin. The CLI validates every call,
including batch members, before executing any. Runtime failures stop execution
unless `--keep-going` is supplied. Results include per-call status and timing.
Schema validation cannot establish that runtime files, GPU resources or layer IDs
exist; use doctor and inspect as well.

## Reusable recipes

```sh
pigment validate examples/recipes/material.json --params '{"mesh":"my.glb"}'
pigment run examples/recipes/material.json --params '{"mesh":"my.glb","roughness":0.8}' --seed 17 --feedback out/review
```

A recipe is a JSON object with `version: 1`, `parameters`, `seed` and `calls`.
`{"$param":"name"}` substitutes the parameter's JSON value, preserving its type.
Unknown overrides and missing references are errors. Paths are relative to the
working directory, just like JSONL tools. The reserved `{"$param":"seed"}` refers
to the recipe seed (default 0), overridden by `--seed`. That seed also supplies
omitted top-level tool seed arguments. Explicit per-call seeds take precedence;
use `$param: seed` for nested generator/batch seed fields. Repeatability assumes
the same inputs, tool version and rendering environment; GPU output need not be
bit-identical across devices.

## Visual review

```sh
pigment feedback asset.pigment out/review
pigment run calls.jsonl --feedback out/review
```

Feedback writes `preview.png` with five model views, individual material-channel
renders, and a labelled `channels.png` sheet. `run --feedback` captures the final
session state, including partial progress if a runtime call fails. These operations
require a usable GPU. MCP clients can call `render_feedback` directly after edits.

## Recoverable saves

Desktop and agent saves stage the complete project, including all texture sets,
then publish it as one generation. Validation, mesh copy or pixel-write failures
leave the prior save intact. An OS file lock prevents simultaneous saves. The
previous generation is restored if opening a project finds an interrupted publish.

```sh
pigment recover asset.pigment
```

The sibling paths `asset.pigment.save-stage`, `.save-backup`, and `.save-lock` are
reserved for recovery. A failed staging directory is discarded on the next save;
recovery never promotes an incomplete stage. The lock file may remain when no
process holds the lock. Existing unrelated files in the project are preserved.
Symlinked project folders or contents are rejected rather than followed. Saves
currently copy the whole project and read all paint resources, trading extra disk
space and save time for consistency. Keep enough space for the staged generation.
Directory publication uses two renames; readers during that short interval may
receive a busy error. This is process-interruption recovery, not a guarantee against
all filesystem/hardware failures. On Unix, staged files and directory entries are
synced before publication.

## Verify exports

```sh
pigment verify-export out/textures --target blender
pigment verify-export out/textures --target unreal
pigment verify-export out/textures --blender /path/to/blender
```

The structural check reads `material.json`, decodes every referenced texture and
exported mesh, and checks required preset maps, dimensions, pixel formats, channel
packing, color spaces and normal conventions. Supported target presets are
`separate`, `blender` (separate maps), `unreal`, `unity`, and `godot`.

`--blender` additionally starts a fresh background Blender process, uses Pigment's
bridge to build material graphs, and imports referenced exported meshes. It does
not open or save a user scene. JSON distinguishes `engine_import_tested` from
structural validation. Unity, Unreal and Godot checks validate export conventions;
they do not launch those editors. Custom export templates without a material
sidecar are not supported by this checker.

The CPU tools `inspect_project`, `verify_export`, and `doctor`, plus GPU tool
`render_feedback`, are also exposed through MCP.

## Verification

```sh
cargo build --workspace
cargo test --workspace -- --test-threads=2
PIGMENT_TEST_BLENDER=/path/to/blender cargo test -p pigment --test agent_cli real_blender_import -- --ignored
```

Sky-name checks run by default. The HDR pack is not in the repository, so the
sky loading test is opt-in and the sky render test (`game_sky_lighting`) skips
itself without it:

```sh
PIGMENT_SKY_DIR=/path/to/skies cargo test -p pigment-core game_skies_resolve_and_load -- --ignored
cargo test -p pigment --test agent_cli gpu_recipe_save_reopen_feedback_and_export -- --ignored
```

GPU tests may skip without an adapter; doctor reports whether one is available.
The explicit CLI GPU workflow test fails if no GPU exists. The Blender integration
test is also opt-in.
