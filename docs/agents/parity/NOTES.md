# Parity workstream: closing the gaps with industry-standard texture painters

Six features, done in order. Each section: what it does, MCP, UI, tests, proof, limits.

## 1. Filters / adjustment layers and anchor points

![before / after](filters_before_after.png)

*building_a, 4096. Left: the town stack. Right: painted dents set as an anchor; grime gathers in them and the rims chip (both generators read the anchor's height); the Leaks mask is warped and slope-blurred; a Grade filter layer adds colour balance and roughness noise.*
Reproduce: `python docs/agents/parity/filters_demo.py 4096` (writes and runs `scenes/town/scripts/parity_filters_demo.jsonl`).

### What it does (`crates/core/src/filters.rs`)

**Filters** live in ordered stacks with enable toggles, in three places:

| where | runs on | gate |
|---|---|---|
| `Mask::filters` | the layer's evaluated mask (painted × generator × parts × invert) | – |
| `Layer::filters` | the composited stack right after the layer | the layer's mask (whole surface without one) |
| filter layer (`LayerKind::Filter`) | the stack below it | its mask × opacity |

Kinds: `levels` (in black / white / gamma, out black / white, per RGB and master), `hsl`, `color_balance` (shadows / midtones / highlights), `invert`, `clamp`, `blur` (separable gaussian), `directional_blur`, `sharpen` (unsharp mask), `warp` (world-space noise displacement), `slope_blur` (smear down the slope of noise or of the stack's height), `edge_detect` (Sobel), `height_to_normal` (keep the height = stronger bumps; off = convert height into normal detail and flatten it), `fill_holes` / `grow` / `shrink` (masks only), `noise_overlay` (MatFinish-style world noise on colour / roughness / height / mask). Layer filters have a `channels` list (default per kind).

**Seam-aware.** Every neighbourhood tap reads through the jump-flood padding map (`src_texel`), like the curvature blur: a tap that leaves a UV island takes the island's nearest texel, never background. Warp / slope blur / noise use world-space noise, so they are continuous across seams.

**Anchor points.** `Layer::anchor = Some(name)` on a layer or folder. After that step the compositor captures an Rgba16F texture: height, the anchor layer's mask × coverage × opacity, and colour luminance. Layers above read it through the mask generator's `input: {anchor, channel, strength, radius}`:
- every curvature-based generator (edge wear, dirt, grunge...) gets the anchor channel's *relief* (value minus its local ring average) added to its curvature: raised rims count as convex edges, dents as cavities. So edge wear follows painted scratches and dirt gathers in painted dents.
- the new `anchor` generator uses the channel directly as the mask (threshold = amount, softness, breakup).
An anchor can only be read by layers composited after it (checked by the MCP and offered that way in the UI).

**Persistence.** All new fields use serde defaults and are skipped when empty, so old projects load unchanged and projects without filters save byte-for-byte as before (test `old_projects_load_without_filters_or_anchors`).

### GPU (`render/texset.rs`, `shaders/filter.wgsl`, `composite.wgsl`)

- `LayerParams` grew by one `vec4` (`ext`: mask precomputed flag, anchor input mode, relief radius, strength): **496 of 512 bytes**. Further per-layer data must go into a storage buffer, as part masks did.
- A layer whose mask has filters, that has filters itself, or that is a filter layer has its mask evaluated once (`fs_mask_eval`) into `mask_cache[layer]` (R16F), then filtered by ping-pong over two scratch textures. The layer pass then binds the cached mask (`ext.x = 1`); the generator still runs for its side channels (height profile, jitter) when the ground options need them.
- Acc filters (`fs_filter_acc`) read the accumulation set (group 1), the filter's input (group 3) and a gate texture. Separable filters take two passes through a pool slot. Only the selected channels change; opacity, transmission, coat and flake never do.
- The anchor input texture is binding 15 of the layer / folder groups (22 sampled textures per stage, limit 32).
- **Partial composites (painting).** Spatial filters read neighbours that pool slots only hold where they were just written. So when filters are present, every pass is widened by the total reach of all filters and anchor lookups; the region shrinks as filters consume their reach, and the final pass still covers the rect plus everything the change can spread to. Persistent textures (mask caches, anchors) are only written where valid. Stacks without filters run exactly the passes they did before.

### MCP

| tool | args |
|---|---|
| `add_filter` | `layer`, `kind`, `target` (`layer` default / `mask`), `index`, plus filter fields: `radius` (texels at 2048, scales with resolution), `amount`/`strength`, `angle`, `scale`, `seed`, `levels {in_black, in_white, gamma, out_black, out_white}` (number = master, or `[r, g, b(, master)]`), `hue`, `saturation`, `lightness`, `shadows`/`midtones`/`highlights` `[r, g, b]`, `min`, `max`, `use_height`, `channels`, `enabled` |
| `update_filter` | `layer`, `target`, `index`, any filter field, `move_to` (a different `kind` resets the parameters) |
| `remove_filter` | `layer`, `target`, `index` |
| `set_anchor` | `layer`, `anchor` (name; default the layer's name; `null` removes) |
| `add_layer` / `update_layer` | `kind: "filter"` (default position: top), `filters: [...]`, `anchor`, `mask.input {anchor, channel: height\|mask\|color, strength, radius}` (`null` = bakes), `mask.filters: [...]`, generator `anchor` |
| `list_layers` | `kind: "filter"`, `filters`, `anchor`, `mask.filters`, `mask.input` |

Errors name the problem: unknown kind, a mask-only filter on a layer, an anchor that doesn't exist or isn't below the layer.

### UI

- Properties panel: a **Filters** section (filter cards with enable switch, move up / down, remove, the kind's parameters and a channel picker; *Add filter…*), and an **Anchor point** switch with a name field.
- Mask panel: **Input** (mesh bakes or *anchor · channel*, with strength and radius) under the generator, and **Mask filters**.
- Add layer menu: **Filter layer**. Filter layers show a sliders icon and their filters in the subtitle.
All built from `design::` components (lint test passes).

### Tests

- core: `filters::tests` (4): kinds round trip and targets, reach scaling, old projects unchanged, filters / anchors / generator input round trip, `anchors_below`.
- GPU (`gpu_tests_filters.rs`, flat quad with a hard gradient mask): mask blur softens, grow / shrink move the edge, disabled = identical; filter layer invert, opacity 0.5, inverted mask gate, levels; the `anchor` generator reproduces the anchor's mask; edge wear with anchor height finds the rim of a raised area only; **partial composites under blur + sharpen filter layers equal a full composite** (max diff ≤ 2).
- shaders: `shader_tests::filter` (naga).
- Session: `filters_and_anchors_over_mcp` (HSL / levels change renders, toggles, errors, input + mask filters, save / reopen identical, undo).
- UI: `filter_stacks_and_anchor_in_panels` (clicking a layer filter's and a mask filter's switch disables it).
- `ui_frame_timing` (4096): idle 1.15 / 1.35 ms, painting 3.5 / 4.1 ms (p95 8.6 / 9.7 ms), unchanged.

### Known limits

- Layer filters act on the stack *result* inside the layer's mask, not on the layer's content before blending; a blur on an unmasked paint layer therefore blurs the stack below too. Use a mask, or put the filter in the mask.
- Grow / shrink / fill holes use a square (separable) structuring element. Blur and morphology cap at 32 taps per side (larger radii are sampled sparsely).
- Seam-aware means "stays on its island", not "continues on the neighbouring island across the seam".
- A spatial filter at the top of a big stack widens every pass while painting (cost grows with the radius).
- Each anchor costs one Rgba16F texture (128 MB at 4096); each filtered mask one R16F texture.
