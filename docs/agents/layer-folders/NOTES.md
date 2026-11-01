# Layer folders + saved smart materials

## What it does

**Folders.** A folder is a layer of kind `Folder { collapsed }`. It has its own opacity, per-channel enable/blend/opacity, mask (painted pixels, generator, effects, parts) and visibility. A layer's new `parent: Option<LayerId>` field says which folder it is in. The stack stays a flat bottom-to-top `Vec<Layer>`, so all the code that walks it keeps working. Canonical order puts each folder's contents directly below the folder.

Folders can nest up to `MAX_FOLDER_DEPTH` = 4 levels in the UI and MCP; the compositor itself has no limit.

**Compositing** (`texset.rs` + new `shaders/folder.wgsl`):
- `Document::composite_plan()` turns the tree into steps: `Layer(i)`, `Begin(folder)` and `End(folder)`.
- At `Begin`, the stack below the folder (B) is kept. The children are composited on top of B, which gives C.
- At `End`, one folder pass blends C onto B: `out = blend(B, C, folder opacity × channel opacity × folder mask)`. With Normal blend, the folder's opacity and mask multiply every child's.
- Hidden folders hide everything inside them. Empty folders cost nothing.
- Folders support the blend modes Normal, Multiply, Screen, Overlay, Darken and Lighten. Height only supports Normal, Darken and Lighten, and normals always mix. Add, Subtract, Replace and Combine act as Normal (see the limits section).
- The accumulation textures are now a pool. Slot 0 is the final result; extra slots are only allocated for folder nesting. A stack without folders runs exactly the same passes as before. Partial (painting) composites stay correct.
- The folder pass has its own bind group (mask and params only), which keeps it under the limit of 16 sampled textures per shader stage.

**Smart materials (`.pigsmart`, `crates/core/src/smart.rs`).** This saves a folder, or a single fill layer, as JSON. The file is part-agnostic:
- It keeps fills, channel settings, blend modes, opacities, generator masks and mask effects.
- It drops mask part selections and painted pixels. Paint layers are skipped, and a hand-painted mask becomes white. Every drop is listed in `warnings`.
- Applying a file gives every layer and mask new ids and remaps the parent links. The optional `parts` argument limits the whole material to those mesh parts through the root folder's mask.

**UI (layer panel).**
- Rows are indented by folder depth and drawn with guide lines. Folders get a folder icon and a collapse arrow; collapsed contents are hidden.
- The row title is greyed out when the layer is hidden by a folder above it.
- **+ Add layer** has two new entries: **Folder** and **Smart material from file...**.
- New buttons: **Group** (wrap the selection in a new folder), **Out of folder**, and **Into folder ▸** (a menu of target folders).
- **Up/Down** now move a layer among its siblings, so folders stay intact. **Delete** and **Duplicate** act on a whole folder.
- A folder's properties use folder blend modes and have a **Save as smart material...** button.
- Painting on a folder that has no mask gives it a white mask; the brush then hides parts of the folder.

## MCP

| tool | args |
|---|---|
| `add_layer` | `kind: "folder"`; `parent` (folder name, `"A/B"` path or index; omitted or null = top level); `index` is the position among the folder's children when `parent` is given |
| `update_layer` | `parent` (folder, or `null` = out to the top level, just above the folder it was in); `move_to` is the sibling position inside a folder; `collapsed` |
| `delete_layer` | deletes a folder together with its contents |
| `list_layers` | once any folder exists, each entry also has `id`, `depth`, `parent` (index of its folder), `path`, plus `children` and `collapsed` for folders; `tree: true` returns a nested tree (`layers` under each folder). Stacks without folders list exactly as before |
| `save_smart_material` | `layer`, `path` (`.pigsmart` added if missing), `name?` → `{saved, layers, warnings}` |
| `apply_smart_material` | `path`, `parts?`, `parent?`, and `name/opacity/visible/blend/channels` overrides on the new folder |

Every tool that takes a layer (`layer`, `parent`) also accepts a `"Folder/Sub/Layer"` path.

## Proof (town)

`python tools/folders_demo.py` writes and runs `scenes/town/scripts/folders_demo.jsonl` at 2048. It needs `target/release/pigment-mcp.exe`.

1. It rebuilds **building_a**'s stack from `building_a.jsonl` as folders:
   - **Shell**: slab joints, trim, trim rust, AC units, grilles, cables, LED strips.
   - **Windows**: glass, lit windows, frames.
   - **Weathering**: a nested **Wall stains** folder (its mask selects the wall parts) holding damp patches and rain streaks, plus street grime.
   - **Signs**: the `Neon` paint layer, with the decal aimed at `"Signs/Neon"`.

   The weathering opacities and amounts are set higher than in the town script so the effect is visible in the renders.
2. It renders building_a with Weathering hidden and shown: `building_a_weathering_off.png` and `building_a_folders.png`.
3. It saves Weathering to `scenes/town/smart/weathering.pigsmart`. The one warning is that the Wall stains part selection was dropped.
4. It builds **building_b** without its own weathering layers (`building_b_before*.png`). It then applies the smart material, points `Weathering/Wall stains` at building_b's wall parts with one `update_layer`, and renders again (`building_b_after*.png`; the `_close` images are close-ups).

## Tests

- **Core:** `folders.rs` has 7 tests (canonical order, composite plan, moving in and out, depth limit, repair of broken parent links, grouping and old projects loading, folder blend fallback). `smart.rs` has 2 tests (part-agnostic save, file round trip, instancing twice with unique ids and parts, paint-layer rejection, rejection of newer file formats).
- **GPU:** `gpu_tests::folders_composite_as_sub_stacks` checks:
  - folder opacity 0.5 gives 0.5, and nested 0.5 × 0.5 gives 0.25;
  - a folder mask × a child mask gives 0.25;
  - a disabled folder channel and a hidden folder both remove the children's effect;
  - a partial composite matches a full one;
  - after removing the folders, the result equals the flat stack.
- **Shaders:** `shader_tests::folder` validates `composite.wgsl` + `folder.wgsl` with naga.
- **Session:** `folders_and_saved_smart_materials_over_mcp` covers the MCP flow end to end: folders, paths, tree, save, reopen with an identical render, and applying to the vending machine with parts, delete and undo.
- `cargo test --release` passes: 72 core + 31 app tests. On a crowded GPU (other agents were using about 10 GB of the 12 GB card), the parallel GPU tests can hit wgpu "Out of Memory". They pass with `-- --test-threads=1`.

## Known limits

- Folder content is pass-through: C already contains the stack below. So Add, Subtract and Replace on a folder act as Normal, and height and normal always mix. Substance-style isolated groups would need per-channel coverage in the accumulator.
- Smart materials can't carry painted pixels (paint layers, hand-painted masks) or part ids. Use `parts` or `update_layer` on a sub-folder's mask after applying to aim the material at parts again.
- `FORMAT_VERSION` was not bumped. Older Pigment builds will fail to parse a project that contains a folder, but projects without folders save byte-for-byte as before.
