//! Pigment MCP server: drives a headless Pigment session over the Model
//! Context Protocol (JSON-RPC 2.0, one message per line on stdin/stdout).
//!
//!   claude mcp add pigment -- <repo>/target/release/pigment-mcp.exe
//!
//! It can also run a script of tool calls without an MCP client:
//!
//!   pigment-mcp --script calls.jsonl     (one {"tool": ..., "args": {...}} per line)
//!
//! or export a project (or mesh) for the Blender bridge add-on:
//!
//!   pigment-mcp --export-for-blender <project.pigment | mesh.glb> <dir> [--name N] [--preset P] [--no-mesh]
//!
//! Script flags: --keep-going (run every step even after an error; exit code
//! 1 if any failed; the default stops at the first error), --check (only
//! validate every line against the tool schemas, no GPU). Per-step timings
//! and a summary go to stderr; tool output stays on stdout.

use base64::Engine;
use pigment_engine::app::automation::Session;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::sync::OnceLock;
use std::time::Instant;

const PROTOCOL: &str = "2025-06-18";

fn tools() -> Value {
    let mut layer_fields = json!({
        "name": { "type": "string" },
        "material": { "type": "string", "description": "Material preset name (see list_library)" },
        "values": { "type": "object", "description": "Override fill values", "properties": {
            "base_color": { "type": "array", "items": { "type": "number" }, "description": "sRGB 0..1" },
            "roughness": { "type": "number" }, "metallic": { "type": "number" }, "height": { "type": "number", "description": "-1..1, negative = recessed" },
            "emissive": { "type": "array", "items": { "type": "number" }, "description": "emission colour, sRGB 0..1" },
            "emissive_strength": { "type": "number", "description": "emission brightness (0 = off; neon ~4-8)" } }, "additionalProperties": false },
        "opacity": { "type": "number" },
        "visible": { "type": "boolean" },
        "channels": { "type": "object", "description": "e.g. {\"height\": false, \"roughness\": true}" },
        "blend": { "type": "object", "description": "per channel, e.g. {\"base_color\": \"multiply\", \"height\": \"add\"}" },
        "mask": mask_schema(),
        "variant": { "type": ["string", "null"], "description": "variant group tag: export_variants can enable/disable every layer or decal in a group" },
        "part_subset": { "type": ["object", "null"], "additionalProperties": false,
            "properties": { "from": { "type": "number" }, "to": { "type": "number" }, "salt": { "type": "integer", "minimum": 0 } },
            "description": "{from, to, salt}: keep only the mask parts whose seeded roll (0..1) is in [from, to). The roll follows the variant seed, so each export_variants variant lights a different set of windows. Layers with the same salt and disjoint ranges get disjoint parts. null removes." }
    });
    let img_path = |d: &str| json!({ "type": ["string", "null"], "description": d });
    layer_fields["image"] = json!({
        "type": ["string", "object", "null"], "additionalProperties": false,
        "description": "Fill layers: channels from tiling images instead of flat values. A string is a tile set folder (e.g. \"assets/tiles/brick\", see list_library tile_sets); null removes it; an object changes only the fields given. Images: sRGB base colour (x tint), grey roughness (remapped to roughness_range), grey height (0.5 = flat, height = (v - 0.5) * height_scale), OpenGL tangent normal.",
        "properties": {
            "tile_set": { "type": "string", "description": "folder with base_color/roughness/height/normal .png (sets all four)" },
            "base_color": img_path("image path (relative paths resolve from the project/mesh folder and its parents, then the working dir); null = flat value"),
            "roughness": img_path("image path or null"), "height": img_path("image path or null"), "normal": img_path("image path or null"),
            "projection": { "type": "string", "enum": ["uv", "triplanar"], "description": "uv: repeats over the UV square; triplanar: world-space box projection, ignores UVs" },
            "tiling": { "type": ["number", "array"], "items": { "type": "number" }, "description": "uv: repeats across UV 0..1, number or [u, v] (default 1)" },
            "tile_size": { "type": "number", "description": "triplanar: metres per repeat (default 1)" },
            "blend_sharpness": { "type": "number", "description": "triplanar: corner blend, 1 soft .. 16 hard (default 4)" },
            "sharpness": { "type": "number", "description": "alias of blend_sharpness" },
            "offset": { "type": ["number", "array"], "items": { "type": "number" }, "description": "shift in tiles, number or [u, v]" },
            "rotation": { "type": "number", "description": "degrees" },
            "tint": { "type": "array", "items": { "type": "number" }, "description": "multiplies base colour, sRGB 0..1" },
            "roughness_range": { "type": ["number", "array"], "items": { "type": "number" }, "description": "[lo, hi] (default [0, 1])" },
            "height_scale": { "type": "number", "description": "default 1" },
            "normal_strength": { "type": "number", "description": "default 1, 0 = flat" }
        }
    });
    // material values beyond the basics: emission, opacity (cut-outs), transmission (glass)
    let value_extras = json!({
        "emissive": { "type": "array", "items": { "type": "number" }, "description": "emitted colour, sRGB 0..1" },
        "emissive_strength": { "type": "number" },
        "opacity": { "type": "number", "description": "material alpha 0..1: 1 = solid, 0 = hole (cut-out: fences, grilles). Not the layer opacity." },
        "transmission": { "type": "number", "description": "0..1, 1 = clear glass (refracts; pair with low roughness and opacity < 1 for see-through windows)" }
    });
    for (k, v) in value_extras.as_object().unwrap() {
        layer_fields["values"]["properties"][k] = v.clone();
    }
    let brush_values = json!({ "type": "object", "description": "brush material values (same keys as a fill's values: base_color, roughness, metallic, height, emissive, emissive_strength, opacity, transmission); opacity/transmission given here are painted too", "properties": layer_fields["values"]["properties"].clone() });
    let camera = json!({
        "yaw": { "type": "number", "description": "degrees around the model (default 35)" },
        "pitch": { "type": "number", "description": "degrees above (default 20)" },
        "zoom": { "type": "number", "description": "1 = framed, 2 = twice as close" },
        "width": { "type": "integer" }, "height": { "type": "integer" },
        "target": { "type": "array", "items": { "type": "number" }, "maxItems": 3, "description": "orbit centre [x, y, z] in world metres (default: the model's centre); combine with zoom or distance for close-ups" },
        "distance": { "type": "number", "minimum": 0, "description": "camera distance from the target in metres (overrides zoom's framing)" }
    });
    let mut add_props = layer_fields.clone();
    let layer_ref = |d: &str| json!({ "type": ["string", "integer"], "description": d });
    let folder_ref = |d: &str| json!({ "type": ["string", "integer", "null"], "description": d });
    add_props["kind"] = json!({ "type": "string", "enum": ["fill", "paint", "folder"], "description": "folder = a group with its own opacity, blend, mask and visibility; its mask multiplies its children's" });
    add_props["index"] = json!({ "type": "integer", "minimum": 0, "description": "stack position (0 = bottom); default: below the top paint layer. With `parent`: position among the folder's children (default: top)" });
    add_props["parent"] = folder_ref("folder to put the new layer in (name, \"Folder/Sub\" path or index); null/omitted = top level");
    let mut upd_props = layer_fields;
    upd_props["layer"] = layer_ref("layer name, \"Folder/Layer\" path, or index (0 = bottom)");
    upd_props["move_to"] = json!({ "type": "integer", "minimum": 0, "description": "new position: flat index at the top level, or the position among the siblings inside a folder" });
    upd_props["parent"] = folder_ref("move into this folder (name/path/index, on top unless move_to), or null to move out to the top level (just above the folder it was in)");
    upd_props["collapsed"] = json!({ "type": "boolean", "description": "folders: collapse in the layer panel" });
    let mut paint_props = camera.clone();
    for (k, v) in [
        ("points", json!({ "type": "array", "items": { "type": "array", "items": { "type": "number" } }, "description": "stroke path in viewport coords 0..1, [[x,y],...], y down" })),
        ("material", json!({ "type": "string" })),
        ("size", json!({ "type": "number", "description": "brush diameter in pixels of the width x height view (default 40)" })),
        ("opacity", json!({ "type": "number" })), ("hardness", json!({ "type": "number" })),
        ("height", json!({ "type": "number", "description": "paint height too (-1..1)" })),
        ("channels", json!({ "type": "array", "items": { "type": "string" } })),
        ("layer", json!({ "type": ["string", "integer"], "description": "target layer (default: top paint layer)" })),
        ("mask", json!({ "type": "boolean", "description": "paint the layer's mask instead" })),
        ("mask_value", json!({ "type": "string", "enum": ["white", "black"] })),
        ("erase", json!({ "type": "boolean" })),
        ("values", brush_values.clone()),
    ] {
        paint_props[k] = v;
    }
    let mut render_props = camera.clone();
    render_props["view"] = json!({ "type": "string", "description": "material (default), base color, roughness, metallic, height, normal, ambient occlusion, curvature, world normal, uv checker, emission, opacity, transmission" });
    render_props["path"] = json!({ "type": "string", "description": "where to save the PNG (default: temp)" });
    render_props["exposure"] = json!({ "type": "number" });
    render_props["background"] = json!({ "type": "boolean" });
    // lighting / post (persist across renders until changed)
    render_props["lighting"] = json!({ "type": "string", "enum": ["studio", "night", "overcast"], "description": "built-in lighting: studio (neutral softboxes), night (dark blue city night, cyan + magenta neon rim lights, sodium lamp), overcast (soft daylight)" });
    render_props["hdri"] = json!({ "type": "string", "description": "light with an equirectangular .hdr / .exr instead (overrides lighting)" });
    render_props["env_rotation"] = json!({ "type": "number", "description": "rotate the lighting around the vertical axis, degrees" });
    render_props["bloom"] = json!({ "type": ["boolean", "object"], "additionalProperties": false, "properties": { "enabled": { "type": "boolean" }, "threshold": { "type": "number" }, "intensity": { "type": "number" }, "radius": { "type": "number" } }, "description": "glow from emissive / HDR highlights: true | false | {threshold (default 1), intensity (0.5), radius (0..1, 0.65)}" });
    let mut sheet_props = render_props.clone();
    render_props["views"] = json!({ "type": ["array", "string", "null"], "items": { "type": "string" }, "description": "contact sheet of named views in one PNG: [\"front\",\"back\",\"left\",\"right\",\"top\",\"bottom\"] or \"all\" (width/height are then per tile, default 384)" });
    render_props["columns"] = json!({ "type": "integer", "description": "with views: tiles per row" });
    sheet_props["frames"] = json!({ "type": "integer", "description": "number of views around the model (default 8)" });
    sheet_props["start_yaw"] = json!({ "type": "number", "description": "yaw of the first frame, degrees (default 0 = front)" });
    sheet_props["columns"] = json!({ "type": "integer", "description": "tiles per row (default 4)" });
    sheet_props["width"] = json!({ "type": "integer", "description": "tile width (default 384)" });
    sheet_props["height"] = json!({ "type": "integer", "description": "tile height (default 384)" });
    let t = |name: &str, desc: &str, props: Value, req: &[&str]| json!({ "name": name, "description": desc, "inputSchema": { "type": "object", "properties": props, "required": req, "additionalProperties": false } });
    // decal wear / layering, shared by project_decal (anchored) and scatter_decals
    let wear_props = json!({
        "wear": { "type": "number", "description": "tear 0..1: noise eats the decal from its edges (more at the bottom), leaving a rim of bare paper; 0.3-0.6 = torn poster" },
        "fade": { "type": "number", "description": "0..1 patchy sun-bleaching and wear-through" },
        "wear_style": { "type": "string", "enum": ["noise", "grunge"], "description": "soft noise (default) or ridged, streaky grunge" },
        "wear_scale": { "type": "number", "description": "noise frequency across the decal (default 5; higher = smaller rips)" },
        "wear_seed": { "type": "number" },
        "paper_rim": { "type": "number", "description": "width of the bare-paper rim along tears (default 0.035, 0 = none)" },
        "overlap_order": { "type": "integer", "minimum": 0, "description": "without `layer`: paint onto paint layer `Decals <n>`, created and stacked so higher n is on top (e.g. posters 0, graffiti 1)" },
        "depth": { "type": "number", "minimum": 0, "description": "half-thickness of the projection box in metres (default 1/4 of the smaller side, 0.02..0.25)" }
    });
    // precise (anchored) placement for project_decal
    let anchored = json!({
        "anchor": { "type": "array", "items": { "type": "number" }, "maxItems": 2, "description": "precise placement: [u, v] in 0..1 across `face` of `part` (or of the whole mesh), (0,0) = top-left seen from outside. The decal is snapped onto the surface there" },
        "face": { "type": "string", "enum": ["front", "back", "left", "right", "top", "bottom", "auto"], "description": "with `anchor`: side of the part's box. front = +Z, right = +X, top = +Y; auto = its thinnest side facing away from the model centre" },
        "position": { "type": "array", "items": { "type": "number" }, "maxItems": 3, "description": "precise placement: world point [x,y,z] (with `normal`), snapped onto the surface" },
        "normal": { "type": "array", "items": { "type": "number" }, "maxItems": 3, "description": "with `position`: outward surface direction" },
        "size": { "type": ["number", "array"], "items": { "type": "number" }, "description": "with anchor/position: width in metres (height from the image aspect) or [width, height]; default 0.5" },
        "rotation": { "type": "number", "description": "with anchor/position: degrees, counter-clockwise seen from outside" }
    });
    let scatter_props = {
        let mut p = json!({
            "images": { "type": "array", "items": { "type": "string" }, "description": "PNGs to scatter; dealt in shuffled rounds so each appears before any repeats" },
            "count": { "type": "integer", "minimum": 0, "description": "how many (default 6, max 500; fewer if the surface can't fit them)" },
            "seed": { "type": "integer", "minimum": 0 },
            "parts": { "type": "array", "items": { "type": "integer", "minimum": 0 }, "description": "only on these parts (default: whole mesh)" },
            "mask": layer_ref("layer (name or index) whose part mask limits where decals go"),
            "region": { "type": "object", "additionalProperties": false, "description": "world box the decal centres must be in",
                        "properties": { "min": { "type": "array", "items": { "type": "number" } }, "max": { "type": "array", "items": { "type": "number" } } } },
            "height": { "type": ["number", "array"], "items": { "type": "number" }, "description": "[min, max] metres above `ground`: the whole decal must fit in it (street level: [0.5, 3])" },
            "ground": { "type": "number", "description": "world Y of the ground (default: the mesh's lowest point)" },
            "size": { "type": ["number", "array"], "items": { "type": "number" }, "description": "decal width in metres: number or [min, max] (default [0.4, 0.6]); height follows the image" },
            "rotation": { "type": "number", "description": "base rotation, degrees" },
            "rotation_jitter": { "type": "number", "description": "+- degrees (default 6)" },
            "min_spacing": { "type": "number", "description": "minimum distance between decal centres, metres (default 0.9 x max size)" },
            "facing": { "type": "string", "enum": ["horizontal", "walls", "any"], "description": "horizontal (default) = only walls, surfaces whose normal is within `max_tilt` of horizontal" },
            "max_tilt": { "type": "number", "description": "degrees (default 20)" },
            "fit": { "type": "boolean", "description": "reject spots where the decal would hang off the surface: over a window, an edge (default true)" },
            "wear_jitter": { "type": "number", "description": "per-decal +- variation of wear and fade (default 0.15)" },
            "tint": { "type": "array", "items": { "type": "number" }, "description": "multiplies the image colour, sRGB 0..1" },
            "material": { "type": "string", "description": "preset for roughness/metallic (default plain paint)" },
            "emissive_strength": { "type": "number" }, "opacity": { "type": "number" },
            "values": brush_values.clone(),
            "channels": { "type": "array", "items": { "type": "string" }, "description": "channels to write (default base_color, roughness, metallic; + emissive when set)" },
            "layer": layer_ref("target layer (default: `Decals <overlap_order>` or the top paint layer)"),
            "alpha_from_luminance": { "type": "boolean" },
            "name": { "type": "string", "description": "decal name for export_variants, shared by every scattered decal (default: each image's file stem)" },
            "variant": { "type": "string", "description": "variant group tag for every scattered decal" },
            "enabled": { "type": "boolean", "description": "false = record them for variants but don't paint them in the authored look" }
        });
        for (k, v) in wear_props.as_object().unwrap() {
            p[k] = v.clone();
        }
        p
    };
    json!([
        t("new_project", "Start a project from a mesh (.glb/.gltf/.obj with UVs), or a flat sheet with `tile` instead of `mesh`: a seamless tile (size_m; strokes, decals, generator noise and normals wrap across the edges), a trim sheet (strips stacked in V, wrapping along U; one part + folder per strip) or a decal atlas (cells packed with padding; one part + folder per cell, transparent base). The sheet lies in world XZ (y up, metres; u -> +x, v -> +z). export_textures then also writes <name>_layout.json (strip/cell UV rects) and, for atlases, <name>_BaseColorAlpha.png. Bakes AO + curvature. Optionally starts from a smart material or a base material; a paint layer goes on top.",
          json!({ "mesh": { "type": "string" }, "resolution": { "type": "integer", "enum": [512, 1024, 2048, 4096] }, "smart_material": { "type": "string" }, "material": { "type": "string" },
                  "tile": { "type": "object", "additionalProperties": false, "description": "flat sheet instead of a mesh",
                            "properties": {
                                "size_m": { "type": ["number", "array"], "items": { "type": "number" }, "description": "seamless tile: [width, height] in metres (or one number); trim: width (height = sum of strips)" },
                                "wrap": { "type": "string", "enum": ["both", "u", "v", "none"], "description": "axes that wrap (default: tile both, trim u, atlas none)" },
                                "strips": { "type": "array", "description": "trim sheet strips, top (v = 0) to bottom", "items": { "type": "object", "additionalProperties": false,
                                            "properties": { "name": { "type": "string" }, "height_m": { "type": "number", "minimum": 0 } } } },
                                "cells": { "type": "array", "description": "decal atlas cells, shelf-packed", "items": { "type": "object", "additionalProperties": false,
                                           "properties": { "name": { "type": "string" }, "size_m": { "type": ["number", "array"], "items": { "type": "number" }, "description": "[width, height] in metres" } } } },
                                "padding_px": { "type": "integer", "minimum": 0, "description": "atlas: texels between cells (default 16)" },
                                "offset_m": { "type": "array", "items": { "type": "number" }, "description": "world [x, z] of the sheet centre (default [0, 0]); moving a tile scrolls its periodic pattern" },
                                "width_m": { "type": "number", "description": "trim: sheet width (same as size_m)" },
                                "folders": { "type": "boolean", "description": "trim / atlas: add a folder masked to each strip / cell (default true)" },
                                "name": { "type": "string", "description": "export name (default: TileWxHm / TrimSheet / DecalAtlas)" }
                            } } }), &[]),
        t("open_project", "Open a .pigment project folder.", json!({ "path": { "type": "string" } }), &["path"]),
        t("save_project", "Save the project folder (git-friendly).", json!({ "path": { "type": "string" } }), &[]),
        t("list_library", "Material presets, smart materials, generators, blend modes, export presets, views.", json!({}), &[]),
        t("list_layers", "The layer stack, bottom to top. With folders each entry also has id, depth, parent (index of its folder), path; `tree: true` nests folder contents under `layers`.",
          json!({ "tree": { "type": "boolean" } }), &[]),
        t("add_smart_material", "Add a multi-layer smart material (e.g. 'Rusty steel', 'Hazard stripes', 'Tech panels', 'Worn olive drab metal').", json!({ "name": { "type": "string" } }), &["name"]),
        t("add_layer", "Add a fill or paint layer, optionally with a material, tiling images (`image`: brick, concrete... UV or triplanar) and a generator mask.", add_props, &[]),
        t("update_layer", "Change a layer: material, values, image fill, opacity, visibility, channels, blend modes, mask/generator, position.", upd_props, &["layer"]),
        t("delete_layer", "Remove a layer (a folder goes with its contents).", json!({ "layer": layer_ref("layer name, \"Folder/Layer\" path, or index (0 = bottom)") }), &["layer"]),
        t("save_smart_material", "Save a folder (or fill layer) as a reusable .pigsmart smart material. Part-agnostic: generator masks, fills, blend modes and opacities are kept; part selections and painted pixels are dropped (see `warnings`).",
          json!({ "layer": layer_ref("folder name, path or index"), "path": { "type": "string", "description": "file to write (.pigsmart added if no extension)" }, "name": { "type": "string" } }), &["layer", "path"]),
        t("apply_smart_material", "Instance a .pigsmart smart material into this project as a folder (below the top paint layer, or inside `parent`). `parts` limits the whole material to those mesh parts through the folder's mask.",
          json!({ "path": { "type": "string" }, "parts": { "type": "array", "items": { "type": "integer", "minimum": 0 } }, "parent": folder_ref("folder to put it in"),
                  "name": { "type": "string" }, "opacity": { "type": "number" }, "visible": { "type": "boolean" }, "blend": { "type": "object" }, "channels": { "type": "object" } }), &["path"]),
        t("list_parts", "The mesh's parts (connected pieces: body, glass panes, buttons...). Use ids in a mask's `parts`. With no arguments: every part as [{id, triangles, center, size}]. With any filter / sort / limit argument: {total_parts, matched, returned, offset, parts: [{id, triangles, center, size, thickness, area, facing}]} (or just ids with ids_only). Sizes are bounding-box sides in metres: thickness <= width <= length; area = width x length; facing = axis of the thinnest side.",
          list_parts_props(), &[]),
        t("pick_parts", "Find part ids either by viewport points (`points` [[x,y],...] in 0..1 for a camera view yaw/pitch/zoom; render the same view first) -> {parts: [id or null per point]}, or by a shape query (`shape`, same filters as list_parts, e.g. thin flat parts bigger than 1 m2: {max_thickness: 0.02, min_area: 1}) -> {parts: [ids], count}.",
          {
              let mut p = camera.clone();
              p["points"] = json!({ "type": "array", "items": { "type": "array", "items": { "type": "number" } }, "description": "viewport points [[x, y], ...] in 0..1, y down" });
              p["shape"] = json!({ "type": "object", "properties": list_parts_props(), "additionalProperties": false, "description": "shape query instead of points (see list_parts)" });
              p
          }, &[]),
        t("bake", "Re-bake AO and curvature.", json!({ "ao_samples": { "type": "integer" }, "ao_distance": { "type": "number" }, "curvature_radius": { "type": "number" }, "curvature_strength": { "type": "number" } }), &[]),
        t("paint_stroke", "Paint a brush stroke projected from a camera view onto the model.", paint_props, &["points"]),
        t("project_decal", "Project an image (PNG with alpha: sign, logo, label, poster, graffiti) onto the model like a sticker. Ways to place it: `rect` over a camera view; `part` alone (fit to the part's outward face); a world-space `box` (+ `facing`); or precisely with `anchor` [u,v] on a part's `face` (or `position` + `normal`) plus `size` in metres and `rotation`. Anchored decals can be torn / faded (`wear`, `fade`) and stacked with `overlap_order`. Colour comes from the image times `tint`; optional emission, height, opacity / transmission (`values` + `channels`). Every decal on a paint layer is recorded for export_variants (`name`, `variant`, `enabled`). Lands on the top paint layer unless `layer` / `overlap_order` is given. One undo step.",
          {
              let mut p = json!({ "image": { "type": "string" }, "rect": { "type": "array", "items": { "type": "number" }, "description": "[x0, y0, x1, y1] viewport area in 0..1 (y down)" },
                  "part": { "type": "integer", "description": "instead of rect + camera: put the image on this mesh part's outward face (see list_parts)" },
                  "fit": { "type": "string", "enum": ["contain", "fill"], "description": "with `part`: keep the image's aspect (contain, default) or stretch (fill)" },
                  "margin": { "type": "number", "description": "with `part`: border as a fraction (default 0.05)" },
                  "box": { "type": "object", "description": "instead of rect/part: a world-space box {min: [x,y,z], max: [x,y,z]} or {center, size}; the image goes on the surface seen through its broad face (for areas of big walls)" },
                  "facing": { "type": "string", "enum": ["+x", "-x", "+y", "-y", "+z", "-z"], "description": "with part/box: look at this side (default: the thinnest axis, away from the model centre)" },
                  "yaw": { "type": "number" }, "pitch": { "type": "number" }, "zoom": { "type": "number" }, "width": { "type": "integer" }, "height": { "type": "integer" },
                  "target": { "type": "array", "items": { "type": "number" }, "maxItems": 3, "description": "orbit centre [x, y, z] in world metres (with rect + camera)" },
                  "tint": { "type": "array", "items": { "type": "number" }, "description": "multiplies the image colour, sRGB 0..1" }, "material": { "type": "string", "description": "preset for roughness/metallic (default plain paint)" },
                  "emissive_strength": { "type": "number" }, "height": { "type": "number" }, "opacity": { "type": "number" },
                  "layer": layer_ref("target layer (default: top paint layer)"), "mask": { "type": "boolean", "description": "project into the layer's mask instead" },
                  "mask_value": { "type": "string", "enum": ["white", "black"], "description": "with mask: true" },
                  "alpha_from_luminance": { "type": "boolean" }, "values": brush_values,
                  "channels": { "type": "array", "items": { "type": "string" }, "description": "channels to write (default base_color, roughness, metallic; + emissive / height when set; e.g. [\"opacity\"] with values {opacity: 0} punches holes in the image's shape)" },
                  "name": { "type": "string", "description": "decal name for export_variants (default: image file stem)" },
                  "variant": { "type": "string", "description": "variant group tag" },
                  "enabled": { "type": "boolean", "description": "false = record it for variants but don't paint it in the authored look" } });
              for (k, v) in anchored.as_object().unwrap().iter().chain(wear_props.as_object().unwrap()) {
                  p[k] = v.clone();
              }
              p["distance"] = json!({ "type": "number", "minimum": 0, "description": "with rect + camera: camera distance from `target`, metres" });
              p["part"] = json!({ "type": "integer", "minimum": 0, "description": "put the image on this mesh part's outward face (see list_parts); with `anchor`, the part to place on" });
              p
          }, &["image"]),
        t("scatter_decals", "Scatter images randomly over a mesh (or `parts` / a layer `mask` / a `region`) with a seed: e.g. torn posters at street level. Constraints: `height` band above the ground, `size` range, `rotation_jitter`, `min_spacing`, walls only (`facing`), and `fit` (never hanging off a wall). Per-decal tear / fade wear. Each placed decal is recorded for export_variants like an anchored project_decal. Returns where each landed. One undo step.",
          scatter_props, &["images"]),
        t("render", "Render the model with its current material (PBR image-based lighting, bloom, ACES). Choose lighting (studio / night / overcast or an hdri), exposure and bloom. With `views` it returns one contact sheet of front/back/left/right/top views. Returns the image.", render_props, &[]),
        t("render_turntable", "Render `frames` views evenly around the model (at `pitch`) as one labelled contact-sheet PNG: see the whole asset in one call. Takes the same lighting / bloom / view args as render.", sheet_props, &[]),
        t("export_lighting", "Write a built-in lighting preset as an equirectangular .hdr (e.g. to light a Blender world exactly like Pigment's viewport).",
          json!({ "lighting": { "type": "string", "enum": ["studio", "night", "overcast"] }, "path": { "type": "string" }, "width": { "type": "integer", "description": "default 2048" } }), &["path"]),
        t("export_textures", "Export PNG texture maps. Presets: unreal, unity, godot, separate (glTF/Blender: BaseColor, Roughness, Metallic, AO, Normal_OpenGL, Height, Emissive, plus Opacity / Transmission when the material has any). unreal/unity/godot put opacity in the base colour's alpha (RGBA) when it isn't solid.",
          json!({ "dir": { "type": "string" }, "preset": { "type": "string", "enum": pigment_core::export::presets().iter().map(|p| p.id).collect::<Vec<_>>(), "description": "default separate" }, "name": { "type": "string", "description": "file name prefix (default: the mesh name)" },
                  "compression": { "type": "string", "enum": ["none", "fastest", "fast", "balanced", "best"], "description": "PNG compression effort (default fast). fastest/none write quickest but bigger files; maps are encoded in parallel either way" } }), &["dir"]),
        t("export_variants", "Export N texture sets from this project without re-running the script: one folder per variant, <dir>/<name>__<variant>/<name>_<map>.png. Each variant starts from the authored stack, sets `seed` (random part subsets such as lit windows, and generator noise), switches off `disable` then on `enable` (layer names, decal names, variant groups, or \"*\" = everything tagged), and swaps decal images (decals on changed layers are replayed). Definitions are stored in the project (save_project to keep them); omit `variants` to reuse the stored ones.",
          json!({ "dir": { "type": "string" }, "name": { "type": "string", "description": "file/folder name (default: mesh name)" },
                  "preset": { "type": "string", "description": "export preset (default separate)" },
                  "variants": { "type": "array", "items": { "type": "object", "properties": {
                      "name": { "type": "string" }, "seed": { "type": "integer" },
                      "enable": { "type": "array", "items": { "type": "string" } }, "disable": { "type": "array", "items": { "type": "string" } },
                      "swaps": { "type": "object", "description": "decal / group / layer name -> image path, or {image, tint, emissive_strength, opacity, ...}" } }, "required": ["name"] } },
                  "only": { "type": "array", "items": { "type": "string" }, "description": "export just these variants" },
                  "folder": { "type": "string", "description": "folder pattern (default \"{name}__{variant}\")" },
                  "preview": { "type": "object", "description": "render args (yaw, pitch, zoom, width, height, view, lighting, hdri, exposure, env_rotation, bloom, background, dir): also save a preview PNG per variant to <dir>/<name>__<variant>.png. Previews start from the default look (studio, bloom on, exposure 0), not from the last render; the session look is restored afterwards." },
                  "dry_run": { "type": "boolean", "description": "validate + store, report what each variant shows, export nothing" } }), &[]),
        t("send_to_blender", "Export everything Blender needs into `dir`: the texture maps (preset, default 'separate'), a material.json sidecar (channels and files, emissive_scale, normal convention, resolution, project path) and the painted mesh with tangents (<name>.glb). The Pigment Bridge add-on (tools/blender_addon/pigment_bridge) links objects to this folder and live-reloads it. For random per-object variants in Blender, export each variant to a folder named <asset>__<variant>.",
          json!({ "dir": { "type": "string" }, "name": { "type": "string", "description": "base file name (default: mesh name)" },
                  "preset": { "type": "string", "description": "export preset (default separate)" },
                  "mesh": { "type": "boolean", "description": "also export the mesh (default true)" },
                  "mesh_format": { "type": "string", "enum": ["glb", "obj"], "description": "glb (default, with tangents) or obj (no tangents)" },
                  "project": { "type": "string", "description": "save the project here first, so the sidecar links to it" } }), &["dir"]),
        t("export_mesh", "Write the loaded mesh exactly as Pigment paints it (world transforms applied, UVs, normals, and in .glb the tangents the normal map was baked with).",
          json!({ "path": { "type": "string", "description": ".glb or .obj (no extension: .glb)" }, "format": { "type": "string", "enum": ["glb", "obj"] } }), &["path"]),
        t("get_project_info", "Overview of the session in one call: mesh (name, source, triangles, bounds), texture resolution, parts count, layers, bake status, project folder, last export timing.", json!({}), &[]),
        t("batch", "Run several tool calls in one request, in order: {calls: [{tool, args}, ...]}. Returns {ok, failed, results: [{index, tool, ok, ms, result | error}]}. Stops at the first error unless stop_on_error is false. Images from render are saved to disk (path in the result) rather than returned.",
          json!({ "calls": { "type": "array", "items": { "type": "object", "properties": { "tool": { "type": "string" }, "args": { "type": "object" } }, "required": ["tool"], "additionalProperties": false } },
                  "stop_on_error": { "type": "boolean", "description": "default true" } }), &["calls"]),
        t("undo", "Undo the last action.", json!({}), &[]),
        t("redo", "Redo.", json!({}), &[]),
    ])
}

/// Schema of a layer `mask` argument.
fn mask_schema() -> Value {
    let mut gens: Vec<&str> = pigment_core::GeneratorKind::ALL.iter().map(|g| g.id()).collect();
    // aliases GeneratorKind::from_id accepts (bricks / square / hex also pick the tile variant)
    gens.extend(["drips", "leak", "wetness", "wet", "puddle", "grime_accumulation", "lichen", "bricks", "brick", "tile", "square", "hex", "windows", "window_lights"]);
    let mut gen_fields = json!({
        "generator": { "type": "string", "enum": gens, "description": "procedural mask" },
        "amount": { "type": "number" }, "softness": { "type": "number" }, "scale": { "type": "number" }, "breakup": { "type": "number" },
        "seed": { "type": "integer", "minimum": 0 }, "ao_influence": { "type": "number" }, "curvature_weight": { "type": "number" },
        // weathering generators: named slots (see docs/agents/generators/NOTES.md)
        "drip_length": { "type": "number", "description": "leaks: metres a streak runs (= curvature_weight, default 2.5)" },
        "variant": { "type": ["string", "integer"], "description": "tiles: bricks | square | hex (or 0 / 1 / 2)" },
        "aspect": { "type": "number", "description": "tiles / window_grid: cell width / height (= curvature_weight)" },
        "mortar": { "type": "number", "description": "tiles: mortar width as a fraction of a row (= ao_influence)" },
        "frame": { "type": "number", "description": "window_grid: frame width as a fraction of the cell (= ao_influence)" },
        "cell_size": { "type": "number", "description": "window_grid: cell (storey) height in metres (= scale)" },
        "fill": { "type": "number", "description": "window_grid: lit fraction 0..1 (= amount)" }
    });
    let mut effect = gen_fields.clone();
    effect["op"] = json!({ "type": "string", "enum": ["multiply", "add", "subtract", "max", "min"], "description": "how it combines with the mask so far (default multiply)" });
    gen_fields["invert"] = json!({ "type": "boolean" });
    gen_fields["parts"] = json!({ "type": "array", "items": { "type": "integer", "minimum": 0 },
        "description": "part ids from list_parts / pick_parts: limit the layer to those mesh pieces ([] = whole model)" });
    gen_fields["parts_where"] = json!({ "type": "object", "properties": list_parts_props(), "additionalProperties": false,
        "description": "select parts by shape instead of ids (same filters as list_parts, e.g. {\"max_thickness\": 0.02, \"min_area\": 0.5}); resolved to ids when set; combined with `parts` as a union" });
    gen_fields["effects"] = json!({ "type": "array", "maxItems": 2, "description": "up to 2 more generators combined in order",
        "items": { "type": "object", "properties": effect, "required": ["generator"], "additionalProperties": false } });
    json!({ "type": ["string", "object", "null"], "properties": gen_fields, "additionalProperties": false,
            "description": "\"white\" | \"black\" (painted mask) | null (remove the mask) | {generator, amount, ..., invert, parts, effects}" })
}

/// Filters / sorting / paging shared by list_parts and pick_parts `shape`.
fn list_parts_props() -> Value {
    let n = |d: &str| json!({ "type": "number", "description": d });
    json!({
        "min_triangles": { "type": "integer", "minimum": 0 }, "max_triangles": { "type": "integer", "minimum": 0 },
        "min_thickness": n("thinnest bounding-box side, metres"), "max_thickness": n("e.g. 0.02 for glass panes / signs"),
        "min_width": n("middle side"), "max_width": n("middle side"),
        "min_length": n("longest side"), "max_length": n("longest side"),
        "min_size": n("alias of min_length"), "max_size": n("alias of max_length"),
        "min_area": n("width x length, m2 (the broad face)"), "max_area": n("width x length, m2"),
        "min_volume": n("bounding-box volume, m3"), "max_volume": n("bounding-box volume, m3"),
        "facing": { "type": "string", "enum": ["x", "y", "z"], "description": "axis of the thinnest side (y = horizontal slabs: roofs, floors, awnings)" },
        "inside": { "type": "array", "description": "part centre inside the box [[x0, y0, z0], [x1, y1, z1]]; null components = unbounded, e.g. [[null, 10, null], [null, null, null]] = above y 10",
                    "items": { "type": "array", "items": { "type": ["number", "null"] } } },
        "ids": { "type": "array", "items": { "type": "integer", "minimum": 0 }, "description": "only among these ids" },
        "sort": { "type": "string", "enum": ["id", "triangles", "size", "area", "thickness", "volume"], "description": "default id" },
        "order": { "type": "string", "enum": ["asc", "desc"], "description": "default desc (biggest first), asc for sort id" },
        "limit": { "type": "integer", "minimum": 0 }, "offset": { "type": "integer", "minimum": 0 },
        "ids_only": { "type": "boolean", "description": "return just the ids" }
    })
}

fn schemas() -> &'static HashMap<String, Value> {
    static S: OnceLock<HashMap<String, Value>> = OnceLock::new();
    S.get_or_init(|| tools().as_array().unwrap().iter().map(|t| (t["name"].as_str().unwrap().to_string(), t["inputSchema"].clone())).collect())
}

/// Validate a call against the tool's schema (no GPU needed).
fn check_args(name: &str, args: &Value) -> Result<(), String> {
    let Some(schema) = schemas().get(name) else {
        let mut names: Vec<&str> = schemas().keys().map(String::as_str).collect();
        names.sort_unstable();
        let hint = names.iter().find(|n| n.contains(name) || (name.len() > 3 && name.contains(*n))).map(|n| format!(" (did you mean `{n}`?)")).unwrap_or_default();
        return Err(format!("unknown tool `{name}`{hint}; tools: {}", names.join(", ")));
    };
    // "white" / "black" are the only strings a mask accepts
    if let Some(Value::String(m)) = args.get("mask").filter(|_| schema["properties"]["mask"]["properties"].get("effects").is_some()) {
        if m != "white" && m != "black" {
            return Err(format!("{name}: `mask` = \"{m}\": a mask string must be \"white\" or \"black\" (or null / an object)"));
        }
    }
    pigment_engine::mcp_args::validate(name, schema, args)
}

/// Turn a tool's MCP content into plain JSON for batch results.
fn content_json(content: &[Value]) -> Value {
    let items: Vec<Value> = content
        .iter()
        .map(|c| match c["type"].as_str() {
            Some("text") => {
                let t = c["text"].as_str().unwrap_or("");
                serde_json::from_str(t).unwrap_or_else(|_| Value::String(t.to_string()))
            }
            Some(k) => json!({ "omitted": k }),
            None => c.clone(),
        })
        .filter(|v| v.get("omitted").is_none())
        .collect();
    if items.len() == 1 {
        items.into_iter().next().unwrap()
    } else {
        Value::Array(items)
    }
}

/// The `batch` tool: run calls in order, collecting results and timings.
fn batch(session: &mut Option<Session>, args: &Value) -> Result<Vec<Value>, String> {
    let calls = args["calls"].as_array().ok_or("batch: `calls` must be an array of {tool, args}")?;
    let stop = args.get("stop_on_error").and_then(Value::as_bool).unwrap_or(true);
    let (mut ok, mut failed) = (0usize, 0usize);
    let mut results = Vec::new();
    let t_all = Instant::now();
    for (i, c) in calls.iter().enumerate() {
        let tool = c["tool"].as_str().unwrap_or("");
        let a = c.get("args").cloned().unwrap_or(json!({}));
        let t0 = Instant::now();
        let r = if tool == "batch" { Err("batch: `calls` can't contain another batch".to_string()) } else { call(session, tool, &a) };
        if let Some(s) = session.as_ref() {
            let _ = s.rs.device.poll(eframe::egui_wgpu::wgpu::PollType::Wait { submission_index: None, timeout: None });
        }
        let ms = (t0.elapsed().as_secs_f64() * 10000.0).round() / 10.0;
        match r {
            Ok(content) => {
                ok += 1;
                results.push(json!({ "index": i, "tool": tool, "ok": true, "ms": ms, "result": content_json(&content) }));
            }
            Err(e) => {
                failed += 1;
                results.push(json!({ "index": i, "tool": tool, "ok": false, "ms": ms, "error": e }));
                if stop {
                    break;
                }
            }
        }
    }
    let summary = json!({ "ok": ok, "failed": failed, "skipped": calls.len() - ok - failed, "total_ms": (t_all.elapsed().as_secs_f64() * 10000.0).round() / 10.0, "results": results });
    let text = serde_json::to_string_pretty(&summary).unwrap();
    if failed > 0 {
        Err(text)
    } else {
        Ok(vec![json!({ "type": "text", "text": text })])
    }
}

/// Run one tool. Returns MCP `content` items.
fn call(session: &mut Option<Session>, name: &str, args: &Value) -> Result<Vec<Value>, String> {
    check_args(name, args)?;
    if name == "batch" {
        return batch(session, args);
    }
    if session.is_none() {
        *session = Some(Session::new()?);
    }
    let s = session.as_mut().unwrap();
    let text = |v: Value| Ok(vec![json!({ "type": "text", "text": serde_json::to_string_pretty(&v).unwrap() })]);
    match name {
        "new_project" => text(s.new_project(args)?),
        "open_project" => text(s.open_project(args)?),
        "save_project" => text(s.save_project(args)?),
        "list_library" => text(s.library()),
        "list_layers" => text(s.list_layers(args)),
        "save_smart_material" => text(s.save_smart_material(args)?),
        "apply_smart_material" => text(s.apply_smart_material(args)?),
        "list_parts" => text(s.list_parts_query(args)?),
        "get_project_info" => text(s.project_info()),
        "pick_parts" => text(s.pick_parts(args)?),
        "add_smart_material" => text(s.add_smart_material(args)?),
        "add_layer" => text(s.add_layer(args)?),
        "update_layer" => text(s.update_layer(args)?),
        "delete_layer" => text(s.delete_layer(args)?),
        "bake" => text(s.bake(args)?),
        "paint_stroke" => text(s.paint_stroke(args)?),
        "project_decal" => text(s.project_decal(args)?),
        "scatter_decals" => text(s.scatter_decals(args)?),
        "export_textures" => text(s.export_textures(args)?),
        "export_variants" => text(s.export_variants(args)?),
        "send_to_blender" => text(s.send_to_blender(args)?),
        "export_mesh" => text(s.export_mesh(args)?),
        "undo" => text(s.undo(false)?),
        "redo" => text(s.undo(true)?),
        "render" => {
            let img = s.render(args)?;
            Ok(vec![
                json!({ "type": "image", "data": base64::engine::general_purpose::STANDARD.encode(&img.png), "mimeType": "image/png" }),
                json!({ "type": "text", "text": format!("saved {}", img.path.display()) }),
            ])
        }
        "render_turntable" => {
            let img = s.render_turntable(args)?;
            Ok(vec![
                json!({ "type": "image", "data": base64::engine::general_purpose::STANDARD.encode(&img.png), "mimeType": "image/png" }),
                json!({ "type": "text", "text": format!("saved {}", img.path.display()) }),
            ])
        }
        "export_lighting" => text(s.export_lighting(args)?),
        other => Err(format!("unknown tool `{other}`")),
    }
}

fn handle(session: &mut Option<Session>, msg: &Value) -> Option<Value> {
    let id = msg.get("id").cloned();
    let method = msg.get("method").and_then(Value::as_str).unwrap_or("");
    let params = msg.get("params").cloned().unwrap_or(Value::Null);
    let result = match method {
        "initialize" => Ok(json!({
            "protocolVersion": params.get("protocolVersion").and_then(Value::as_str).unwrap_or(PROTOCOL),
            "capabilities": { "tools": {} },
            "serverInfo": { "name": "pigment", "version": env!("CARGO_PKG_VERSION") },
            "instructions": "Pigment textures 3D meshes with PBR materials. Typical flow: new_project(mesh) -> add_smart_material / add_layer with generator masks -> render to check -> export_textures(preset 'separate' for Blender/glTF) -> save_project."
        })),
        "ping" => Ok(json!({})),
        "tools/list" => Ok(json!({ "tools": tools() })),
        "tools/call" => {
            let name = params.get("name").and_then(Value::as_str).unwrap_or("");
            let args = params.get("arguments").cloned().unwrap_or(json!({}));
            Ok(match call(session, name, &args) {
                Ok(content) => json!({ "content": content, "isError": false }),
                Err(e) => json!({ "content": [{ "type": "text", "text": e }], "isError": true }),
            })
        }
        m if m.starts_with("notifications/") => return None,
        m => Err(json!({ "code": -32601, "message": format!("method not found: {m}") })),
    };
    let id = id?;
    Some(match result {
        Ok(r) => json!({ "jsonrpc": "2.0", "id": id, "result": r }),
        Err(e) => json!({ "jsonrpc": "2.0", "id": id, "error": e }),
    })
}

/// `--script`: run (or with `check_only`, just validate) a JSONL script.
/// Returns the process exit code.
fn run_script(session: &mut Option<Session>, path: &str, keep_going: bool, check_only: bool) -> i32 {
    let text = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("can't read script {path}: {e}");
            return 2;
        }
    };
    let t_all = Instant::now();
    let (mut steps, mut failed) = (0usize, 0usize);
    let mut timings: Vec<(f64, usize, String)> = Vec::new();
    for (n, line) in text.lines().enumerate().filter(|(_, l)| !l.trim().is_empty() && !l.trim_start().starts_with("//")) {
        let n = n + 1;
        steps += 1;
        let parsed = serde_json::from_str::<Value>(line).map_err(|e| format!("invalid JSON: {e}")).and_then(|v| {
            let tool = v.get("tool").and_then(Value::as_str).ok_or("each line needs \"tool\": \"<name>\"")?.to_string();
            if let Some(k) = v.as_object().and_then(|o| o.keys().find(|k| *k != "tool" && *k != "args")) {
                return Err(format!("unknown key `{k}` (a line is {{\"tool\": ..., \"args\": {{...}}}})"));
            }
            Ok((tool, v.get("args").cloned().unwrap_or(json!({}))))
        });
        let (tool, a) = match parsed {
            Ok(x) => x,
            Err(e) => {
                eprintln!("[line {n}] ERROR: {e}");
                failed += 1;
                if keep_going || check_only {
                    continue;
                }
                break;
            }
        };
        if check_only {
            match check_args(&tool, &a) {
                Ok(()) => eprintln!("[line {n}] {tool}: ok"),
                Err(e) => {
                    eprintln!("[line {n}] {tool}: ERROR: {e}");
                    failed += 1;
                }
            }
            continue;
        }
        let t0 = Instant::now();
        let r = call(session, &tool, &a);
        // wait for the step's GPU work so its time isn't billed to the next step
        if let Some(s) = session.as_ref() {
            let _ = s.rs.device.poll(eframe::egui_wgpu::wgpu::PollType::Wait { submission_index: None, timeout: None });
        }
        let ms = t0.elapsed().as_secs_f64() * 1000.0;
        match r {
            Ok(content) => {
                for c in content {
                    if c["type"] == "text" {
                        println!("[{tool}] {}", c["text"].as_str().unwrap_or(""));
                    }
                }
                eprintln!("[line {n}] {tool}: {ms:.0} ms");
            }
            Err(e) => {
                eprintln!("[{tool}] ERROR (line {n}, {ms:.0} ms): {e}");
                failed += 1;
            }
        }
        let _ = std::io::stdout().flush();
        timings.push((ms, n, tool));
        if failed > 0 && !keep_going {
            break;
        }
    }
    if check_only {
        eprintln!("script check: {steps} steps, {failed} invalid");
    } else {
        let total = t_all.elapsed().as_secs_f64();
        let mut by_tool: Vec<(String, f64, usize)> = Vec::new();
        for (ms, _, t) in &timings {
            match by_tool.iter_mut().find(|(n, ..)| n == t) {
                Some(e) => {
                    e.1 += ms;
                    e.2 += 1;
                }
                None => by_tool.push((t.clone(), *ms, 1)),
            }
        }
        by_tool.sort_by(|a, b| b.1.total_cmp(&a.1));
        let mut slow = timings.clone();
        slow.sort_by(|a, b| b.0.total_cmp(&a.0));
        eprintln!("script: {} of {steps} steps run, {failed} failed, {total:.1} s total", timings.len());
        eprintln!("  by tool: {}", by_tool.iter().map(|(t, ms, k)| format!("{t} x{k} {:.1} s", ms / 1000.0)).collect::<Vec<_>>().join(", "));
        eprintln!("  slowest: {}", slow.iter().take(3).map(|(ms, n, t)| format!("line {n} {t} {:.1} s", ms / 1000.0)).collect::<Vec<_>>().join(", "));
    }
    if failed > 0 {
        1
    } else {
        0
    }
}

fn main() {
    // logs go to stderr; stdout is the protocol
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("warn,wgpu_hal=error")).target(env_logger::Target::Stderr).init();
    let mut session: Option<Session> = None;
    let args: Vec<String> = std::env::args().collect();
    if let Some(i) = args.iter().position(|a| a == "--export-for-blender") {
        std::process::exit(export_for_blender(&mut session, &args[i + 1..]));
    }
    if let Some(i) = args.iter().position(|a| a == "--script") {
        // scripted mode: {"tool": "...", "args": {...}} per line; prints results
        let Some(path) = args.get(i + 1) else {
            eprintln!("usage: pigment-mcp --script <file.jsonl> [--keep-going] [--check]");
            std::process::exit(2);
        };
        let keep_going = args.iter().any(|a| a == "--keep-going" || a == "--continue");
        let check_only = args.iter().any(|a| a == "--check");
        std::process::exit(run_script(&mut session, path, keep_going, check_only));
    }
    let stdin = std::io::stdin();
    let mut out = std::io::stdout().lock();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let reply = match serde_json::from_str::<Value>(&line) {
            Ok(Value::Array(batch)) => {
                let r: Vec<Value> = batch.iter().filter_map(|m| handle(&mut session, m)).collect();
                (!r.is_empty()).then(|| Value::Array(r))
            }
            Ok(msg) => handle(&mut session, &msg),
            Err(e) => Some(json!({ "jsonrpc": "2.0", "id": null, "error": { "code": -32700, "message": e.to_string() } })),
        };
        if let Some(r) = reply {
            let _ = writeln!(out, "{r}");
            let _ = out.flush();
        }
    }
}

/// `--export-for-blender <project.pigment | mesh> <dir> [--name N] [--preset P] [--no-mesh] [--mesh-format glb|obj]`.
/// Used by the Blender add-on to (re)export a linked Pigment project.
fn export_for_blender(session: &mut Option<Session>, rest: &[String]) -> i32 {
    let usage = "usage: pigment-mcp --export-for-blender <project.pigment | mesh.glb> <dir> [--name N] [--preset P] [--no-mesh] [--mesh-format glb|obj]";
    let valued = ["--name", "--preset", "--mesh-format"];
    let pos: Vec<&String> = rest.iter().enumerate().filter(|(i, a)| !a.starts_with("--") && (*i == 0 || !valued.contains(&rest[i - 1].as_str()))).map(|(_, a)| a).collect();
    let (Some(src), Some(dir)) = (pos.first(), pos.get(1)) else {
        eprintln!("{usage}");
        return 2;
    };
    let opt = |k: &str| rest.iter().position(|a| a == k).and_then(|i| rest.get(i + 1)).cloned();
    let src_path = std::path::Path::new(src.as_str());
    let open = if src_path.join("project.json").exists() || src_path.file_name().is_some_and(|f| f == "project.json") {
        call(session, "open_project", &json!({ "path": src }))
    } else {
        call(session, "new_project", &json!({ "mesh": src }))
    };
    if let Err(e) = open {
        eprintln!("[export-for-blender] ERROR: {e}");
        return 1;
    }
    let mut a = json!({ "dir": dir, "mesh": !rest.iter().any(|x| x == "--no-mesh") });
    for (flag, key) in [("--name", "name"), ("--preset", "preset"), ("--mesh-format", "mesh_format")] {
        if let Some(v) = opt(flag) {
            a[key] = json!(v);
        }
    }
    match call(session, "send_to_blender", &a) {
        Ok(content) => {
            for c in content {
                println!("{}", c["text"].as_str().unwrap_or(""));
            }
            0
        }
        Err(e) => {
            eprintln!("[export-for-blender] ERROR: {e}");
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    /// Every tool's schema is well-formed: an object schema that rejects
    /// unknown keys, every required key is a declared property, and every
    /// property says what type it takes.
    #[test]
    fn tool_schemas_are_complete() {
        fn typed(path: &str, p: &Value) {
            assert!(p.get("type").is_some(), "{path}: property without a type: {p}");
            if let Some(props) = p.get("properties").and_then(Value::as_object) {
                for (k, v) in props {
                    typed(&format!("{path}.{k}"), v);
                }
            }
            if let Some(items) = p.get("items") {
                typed(&format!("{path}[]"), items);
            }
        }
        let tools = tools();
        let mut names = std::collections::HashSet::new();
        for t in tools.as_array().unwrap() {
            let name = t["name"].as_str().unwrap();
            assert!(names.insert(name), "duplicate tool {name}");
            assert!(t["description"].as_str().is_some_and(|d| d.len() > 4), "{name}: describe the tool");
            let s = &t["inputSchema"];
            assert_eq!(s["type"], "object", "{name}");
            assert_eq!(s["additionalProperties"], false, "{name}");
            let props = s["properties"].as_object().unwrap();
            for r in s["required"].as_array().unwrap() {
                assert!(props.contains_key(r.as_str().unwrap()), "{name}: required `{r}` is not a property");
            }
            for (k, v) in props {
                typed(&format!("{name}.{k}"), v);
            }
        }
        for t in ["get_project_info", "batch", "list_parts", "pick_parts", "export_textures"] {
            assert!(names.contains(t), "missing tool {t}");
        }
    }

    /// The checked-in scripts all pass argument validation.
    #[test]
    fn every_repo_script_matches_the_tool_schemas() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let mut checked = 0;
        for dir in ["scenes/town/scripts", "scenes/cyberpunk"] {
            for e in std::fs::read_dir(root.join(dir)).unwrap() {
                let p = e.unwrap().path();
                if p.extension().is_some_and(|x| x == "jsonl") {
                    for (n, line) in std::fs::read_to_string(&p).unwrap().lines().enumerate() {
                        if line.trim().is_empty() || line.trim_start().starts_with("//") {
                            continue;
                        }
                        let v: Value = serde_json::from_str(line).unwrap();
                        let args = v.get("args").cloned().unwrap_or(json!({}));
                        check_args(v["tool"].as_str().unwrap(), &args).unwrap_or_else(|e| panic!("{}:{}: {e}", p.display(), n + 1));
                        checked += 1;
                    }
                }
            }
        }
        assert!(checked > 50, "only {checked} lines checked");
    }

    #[test]
    fn bad_calls_name_the_bad_argument() {
        let e = check_args("add_layer", &json!({ "name": "x", "materail": "Steel" })).unwrap_err();
        assert!(e.contains("unknown argument `materail` (did you mean `material`?)"), "{e}");
        let e = check_args("add_layer", &json!({ "mask": "grey" })).unwrap_err();
        assert!(e.contains("`mask` = \"grey\""), "{e}");
        let e = check_args("add_layer", &json!({ "mask": { "generator": "rust" } })).unwrap_err();
        assert!(e.contains("`mask.generator` = \"rust\" is not one of: edge_wear"), "{e}");
        let e = check_args("add_layer", &json!({ "mask": { "parts": [3, "7"] } })).unwrap_err();
        assert!(e.contains("`mask.parts[1]` must be integer"), "{e}");
        let e = check_args("add_layer", &json!({ "mask": { "effects": [{ "generator": "dirt" }, { "generator": "dirt" }, { "generator": "dirt" }] } })).unwrap_err();
        assert!(e.contains("at most 2"), "{e}");
        let e = check_args("export_textures", &json!({ "dir": "x", "compression": "max" })).unwrap_err();
        assert!(e.contains("`compression` = \"max\" is not one of: none, fastest, fast, balanced, best"), "{e}");
        let e = check_args("export_textures", &json!({})).unwrap_err();
        assert!(e.contains("missing required argument `dir`"), "{e}");
        let e = check_args("list_part", &json!({})).unwrap_err();
        assert!(e.contains("unknown tool `list_part` (did you mean `list_parts`?)"), "{e}");
        let e = check_args("pick_parts", &json!({ "shape": { "max_thicknes": 0.1 } })).unwrap_err();
        assert!(e.contains("unknown argument `shape.max_thicknes` (did you mean `max_thickness`?)"), "{e}");
        check_args("pick_parts", &json!({ "shape": { "max_thickness": 0.02, "min_area": 1, "facing": "z", "inside": [[null, 1.0, null], [null, null, null]] } })).unwrap();
        check_args("update_layer", &json!({ "layer": 2, "mask": null })).unwrap();
        check_args("batch", &json!({ "calls": [{ "tool": "list_layers" }, { "tool": "render", "args": { "yaw": 10 } }] })).unwrap();
        let e = check_args("batch", &json!({ "calls": [{ "tool": "list_layers", "arg": {} }] })).unwrap_err();
        assert!(e.contains("unknown argument `calls[0].arg` (did you mean `args`?)"), "{e}");
    }

    #[test]
    fn batch_results_unwrap_tool_json() {
        let c = vec![json!({ "type": "image", "data": "...", "mimeType": "image/png" }), json!({ "type": "text", "text": "saved C:/x.png" })];
        assert_eq!(content_json(&c), json!("saved C:/x.png"));
        let c = vec![json!({ "type": "text", "text": "{\"layers\": [1, 2]}" })];
        assert_eq!(content_json(&c)["layers"][1], 2);
    }
}
