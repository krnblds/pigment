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
use crate::app::automation::Session;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::sync::OnceLock;
use std::time::Instant;

const PROTOCOL: &str = "2025-06-18";

/// Every tool, plus `texture_set` on the tools that work on one set's layers.
pub(crate) fn tools() -> Value {
    let mut v = tools_base();
    for t in v.as_array_mut().unwrap() {
        if crate::app::automation::set_tools::SET_TOOLS.contains(&t["name"].as_str().unwrap_or("")) {
            t["inputSchema"]["properties"]["texture_set"] = json!({ "type": ["string", "integer"],
                "description": "texture set to work on (name or index, see list_texture_sets; default: the active one); \"*\" = every set (paint_stroke paints across sets on its own)" });
        }
    }
    v
}

fn tools_base() -> Value {
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
        "filters": { "type": "array", "items": filter_schema(false), "description": "replace the layer's filter stack (run in order on the stack right after this layer, inside its mask; on a filter layer: on the stack below). [] removes them" },
        "anchor": { "type": ["string", "null"], "description": "make this layer an anchor point with this name (null removes): generators above can read its height / mask / colour (mask.input)" },
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
        "transmission": { "type": "number", "description": "0..1, 1 = clear glass (refracts; pair with low roughness and opacity < 1 for see-through windows)" },
        "coat": { "type": "number", "description": "clearcoat weight 0..1: a glossy dielectric varnish over the base (car paint, lacquer). Giving it (even 0, e.g. on a dirt/rust layer) turns the coat channel on" },
        "coat_roughness": { "type": "number", "description": "clearcoat roughness 0..1 (default 0.03 = fresh lacquer; 0.2-0.4 = hazy, weathered coat)" },
        "flake": { "type": "number", "description": "metallic flake amount 0..1 in the base under the coat (sparkle); pair with metallic 0.3-0.7 and coat 1" }
    });
    for (k, v) in value_extras.as_object().unwrap() {
        layer_fields["values"]["properties"][k] = v.clone();
    }
    let brush_values = json!({ "type": "object", "description": "brush material values (same keys as a fill's values: base_color, roughness, metallic, height, emissive, emissive_strength, opacity, transmission, coat, coat_roughness, flake); opacity/transmission/coat/coat_roughness/flake given here are painted too", "properties": layer_fields["values"]["properties"].clone() });
    let camera = json!({
        "yaw": { "type": "number", "description": "degrees around the model (default 35)" },
        "pitch": { "type": "number", "description": "degrees above (default 20)" },
        "zoom": { "type": "number", "description": "1 = framed, 2 = twice as close" },
        "width": { "type": "integer" }, "height": { "type": "integer" },
        "target": { "type": "array", "items": { "type": "number" }, "maxItems": 3, "description": "orbit centre [x, y, z] in world metres (default: the model's centre); combine with zoom or distance for close-ups" },
        "distance": { "type": "number", "minimum": 0, "description": "camera distance from the target in metres (overrides zoom's framing)" }
    });
    ground_layer_fields(&mut layer_fields);
    let mut add_props = layer_fields.clone();
    let layer_ref = |d: &str| json!({ "type": ["string", "integer"], "description": d });
    let folder_ref = |d: &str| json!({ "type": ["string", "integer", "null"], "description": d });
    add_props["kind"] = json!({ "type": "string", "enum": ["fill", "paint", "folder", "filter", "decal", "foliage"], "description": "decal = a decal layer: project_decal / scatter_decals / place_decal on it make editable decal objects (list_decals, update_decal, delete_decal; the layer re-composites). filter = an adjustment layer: its `filters` run on the whole stack below, inside its mask and opacity (default position: top). folder = a group with its own opacity, blend, mask and visibility; its mask multiplies its children's. foliage = cards on the model (see scatter_foliage / paint_foliage / grow_ivy)" });
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
    // brush engine (pigment_core::brush): every call starts from the defaults
    let curve = |d: &str| json!({ "type": ["boolean", "object"], "additionalProperties": false, "description": d,
        "properties": { "enabled": { "type": "boolean" }, "min": { "type": "number", "description": "value at zero pressure, 0..1 (default 0.1)" }, "gamma": { "type": "number", "description": "response curve: > 1 needs more pressure (default 1)" } } });
    for (k, v) in [
        ("tip", json!({ "type": ["string", "null"], "description": "brush tip (alpha) from the library (list_library brush_tips: round, square, chalk, spray, splatter, cracks, scratches, grunge_1, grunge_2, leaves, dots); default: round falloff with `hardness`" })),
        ("pressure", json!({ "type": ["number", "array"], "items": { "type": "number" }, "description": "pen pressure 0..1: one number for the whole stroke or one per point (interpolated between points). Drives size (pressure_size, on by default), flow and opacity curves" })),
        ("pressure_size", curve("pressure -> size (default on, min 0.1)")),
        ("pressure_flow", curve("pressure -> flow (default off)")),
        ("pressure_opacity", curve("pressure -> opacity (default off)")),
        ("spacing", json!({ "type": "number", "description": "distance between dabs as a fraction of the diameter (default 0.1)" })),
        ("flow", json!({ "type": "number", "description": "per-dab strength 0..1 (default 1 = a stroke never exceeds `opacity`; lower = dabs build up towards it)" })),
        ("angle", json!({ "type": "number", "description": "tip angle, degrees" })),
        ("follow_angle", json!({ "type": "boolean", "description": "the tip turns with the stroke direction (+ angle)" })),
        ("jitter", json!({ "type": "object", "additionalProperties": false, "description": "random variation per dab",
            "properties": { "size": { "type": "number", "description": "0..1 fraction" }, "angle": { "type": "number", "description": "degrees either way" }, "position": { "type": "number", "description": "scatter, in diameters" }, "flow": { "type": "number", "description": "0..1 fraction" } } })),
        ("lazy", json!({ "type": "number", "description": "lazy mouse: the brush trails the points by this many pixels (smooths the path)" })),
        ("seed", json!({ "type": "integer", "minimum": 0, "description": "jitter seed" })),
        ("symmetry", json!({ "type": ["object", "null"], "additionalProperties": false, "description": "object-space symmetry: mirror planes through `center` (default: the mesh centre) and/or radial copies around an axis",
            "properties": { "x": { "type": "boolean" }, "y": { "type": "boolean" }, "z": { "type": "boolean" }, "radial": { "type": "integer", "minimum": 0, "description": "copies around the axis" },
                            "axis": { "type": ["string", "integer"], "description": "radial axis x | y | z (default y)" }, "center": { "type": "array", "items": { "type": "number" }, "description": "[x, y, z]" } } })),
        ("stencil", json!({ "type": ["object", "null"], "additionalProperties": false, "required": ["image"], "description": "paint through an image laid over the view (luminance x alpha = how much paint gets through)",
            "properties": { "image": { "type": "string" }, "center": { "type": "array", "items": { "type": "number" }, "description": "[x, y] in 0..1 of the view (default centre)" },
                            "rotation": { "type": "number", "description": "degrees" }, "scale": { "type": "number", "description": "image height as a fraction of the view height (default 1)" },
                            "opacity": { "type": "number", "description": "0 = no effect, 1 = full (default)" }, "invert": { "type": "boolean" } } })),
        ("tool", json!({ "type": "string", "enum": ["paint", "clone", "smudge"], "description": "paint (default); clone copies the layer from `clone_source` keeping the offset to the stroke start; smudge drags the existing pixels along the stroke" })),
        ("clone_source", json!({ "type": "array", "items": { "type": "number" }, "description": "clone: [x, y] viewport point (0..1, this call's camera) to copy from" })),
        ("smudge", json!({ "type": "number", "description": "smudge drag length in brush diameters (default 0.5)" })),
    ] {
        paint_props[k] = v;
    }
    let mut render_props = camera.clone();
    render_props["view"] = json!({ "type": "string", "description": "material (default), base color, roughness, metallic, height, normal, ambient occlusion, curvature, world normal, uv checker, emission, opacity, transmission, coat, coat roughness, flake" });
    render_props["path"] = json!({ "type": "string", "description": "where to save the PNG (default: temp)" });
    render_props["exposure"] = json!({ "type": "number" });
    render_props["background"] = json!({ "type": "boolean" });
    // lighting / post (persist across renders until changed)
    render_props["lighting"] = json!({ "type": "string", "enum": ["studio", "night", "overcast", "lightbox", "lightbox_dark", "night_rain", "night_moon", "dusk", "predawn"], "description": "built-in lighting: studio (neutral softboxes), night (dark blue city night, cyan + magenta neon rim lights, sodium lamp), overcast (soft daylight), lightbox (white seamless studio cove under the model with soft contact shadows and reflections, big softboxes and long rim strips: product / car beauty shots), lightbox_dark (black glossy cove lit by strip lights, car-commercial reflection lines); or a game sky baked by tools/sky/make_sky.py (assets/sky/<id>_2k.hdr, the same HDR the Blender town and the Godot game use): night_rain (default game sky: low overcast lit orange/magenta by the city), night_moon, dusk, predawn. The skies are dark night radiance: use exposure 2-4 to judge albedo, 0-1 for the in-game look" });
    render_props["hdri"] = json!({ "type": "string", "description": "light with an equirectangular .hdr / .exr instead (overrides lighting)" });
    render_props["stage"] = json!({ "type": "boolean", "description": "lightbox lighting: show the studio cove floor / contact shadow / floor reflection under the model (default true; persists)" });
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
        let mut p = json!({ "projection": { "type": "string", "enum": ["box", "triplanar", "wrap"], "description": "decal layers: box (planar, default), triplanar (wraps over corners in the decal frame) or wrap (conforms: the surface is unfolded from the decal centre)" },
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
        t("inspect_project", "Inspect a project or mesh and validate referenced assets without a GPU.", json!({"path":{"type":"string"}}), &["path"]),
        t("verify_export", "Decode exported textures and mesh references and check the material sidecar for a target. Does not run an external engine.", json!({"dir":{"type":"string"},"target":{"type":"string","enum":["separate","blender","godot","unity","unreal"]}}), &["dir"]),
        t("render_feedback", "Save a multi-view preview and labelled material-channel contact sheet for the current project. Returns artifact paths.", json!({"dir":{"type":"string"}}), &["dir"]),
        t("doctor", "Check GPU availability, optional sky assets, project integrity and export destination write access.", json!({"project":{"type":"string"},"export_dir":{"type":"string"},"no_gpu":{"type":"boolean"}}), &[]),
        t("new_project", "Start a project from a mesh (.glb/.gltf/.obj with UVs), or a flat sheet with `tile` instead of `mesh`: a seamless tile (size_m; strokes, decals, generator noise and normals wrap across the edges), a trim sheet (strips stacked in V, wrapping along U; one part + folder per strip) or a decal atlas (cells packed with padding; one part + folder per cell, transparent base). The sheet lies in world XZ (y up, metres; u -> +x, v -> +z). export_textures then also writes <name>_layout.json (strip/cell UV rects) and, for atlases, <name>_BaseColorAlpha.png. Bakes AO + curvature. Optionally starts from a smart material or a base material; a paint layer goes on top.",
          json!({ "mesh": { "type": "string" }, "resolution": { "type": "integer", "enum": [512, 1024, 2048, 4096] }, "smart_material": { "type": "string" }, "material": { "type": "string" },
                  "texture_sets": { "type": ["string", "array"], "description": "several texture sets, each with its own resolution and layer stack: \"materials\" (one per mesh material), \"udim\" (one per UDIM tile), or [{name, materials: [ids or names], udim, resolution}]. Each starts with a copy of the initial stack",
                      "items": { "type": "object", "additionalProperties": false, "required": ["name"], "properties": { "name": { "type": "string" }, "materials": { "type": "array", "items": { "type": ["integer", "string"] } }, "udim": { "type": "integer" }, "resolution": { "type": "integer", "enum": [512, 1024, 2048, 4096] } } } },
                  "udim": { "type": "boolean", "description": "one texture set per UDIM tile the mesh's UVs use (UVs beyond 0..1 -> tiles 1001+)" },
                  "udim_tiles": { "type": "array", "description": "move part of the mesh to its own UDIM tile, its UVs repacked to fill the tile (more texel density there); then one texture set per tile unless texture_sets says otherwise",
                      "items": { "type": "object", "additionalProperties": false, "required": ["tile"], "properties": { "tile": { "type": "integer", "description": "1002..1100" }, "below_y": { "type": "number", "description": "triangles whose centre is below this height (m)" }, "above_y": { "type": "number" },
                          "parts": { "type": "array", "items": { "type": "integer" } }, "parts_where": { "type": "object", "description": "a part shape query as in list_parts" }, "margin": { "type": "number", "description": "UV margin in the tile (default 0.01)" } } } },
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
                            } },
                  "foliage_atlas": { "type": "object", "additionalProperties": false,
                            "description": "a foliage card atlas instead of a mesh: cells (leaf, twig, needle spray, blossom, grass tuft, ivy sprig, moss) drawn by the leaf generators into a generated layer, one folder per cell for extra layers. export_textures also writes Translucency / Thickness (+ backlight for godot, SubsurfaceColor for unreal) and <name>_foliage.json for foliage layers",
                            "properties": {
                                "cells": { "type": "array", "items": { "type": "object", "properties": foliage_cell_props(), "additionalProperties": false } },
                                "padding_px": { "type": "integer", "minimum": 0, "description": "texels between cells (default 16)" },
                                "folders": { "type": "boolean", "description": "a folder masked to each cell (default true)" },
                                "name": { "type": "string", "description": "export name (default FoliageAtlas)" }
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
        t("bake", "Re-bake AO and curvature from the project mesh. With `high_mesh` (and/or `maps`): high-to-low bake onto the project mesh's UVs (CPU BVH; rays from a cage along the low normal, both ways): normal (tangent, OpenGL), normal_object, position, thickness, ao, curvature, height (displacement), color_id (the high mesh's materials or vertex colours), material_id (the project mesh's own materials, no high mesh needed). Maps are written as PNGs to `dir` (default <project>/bakes); AO + curvature replace the mesh bakes generators read, the tangent normal becomes a 'Baked normal' fill layer, and the color / material ID map feeds mask.id_color.",
          json!({ "ao_samples": { "type": "integer", "description": "AO rays (mesh bake: directions; high bake: per texel, default 48)" }, "ao_distance": { "type": "number" }, "curvature_radius": { "type": "number" }, "curvature_strength": { "type": "number" },
                  "high_mesh": { "type": "string", "description": "high-poly mesh (.obj / .gltf / .glb) to bake from" },
                  "cage": { "type": ["number", "string", "null"], "description": "max distance between the low and high surfaces in metres, or \"auto\" (default: measured from the meshes)" },
                  "maps": { "type": "array", "items": { "type": "string", "enum": pigment_core::hibake::BakeMap::ALL.iter().map(|m| m.id()).collect::<Vec<_>>() }, "description": "default with high_mesh: normal, ao, curvature, height, color_id; without: material_id" },
                  "id_source": { "type": "string", "enum": ["material", "vertex_color"], "description": "color_id from the high mesh's materials (default) or its vertex colours" },
                  "dir": { "type": "string", "description": "where to write the maps" },
                  "normal_layer": { "type": "boolean", "description": "add / update the 'Baked normal' fill layer (default true)" } }), &[]),
        t("paint_stroke", "Paint a brush stroke projected from a camera view onto the model. Brush engine: tip (alphas), per-point pen pressure with size / flow / opacity curves, spacing, flow, angle (or follow_angle), jitter, lazy mouse, object-space symmetry (mirror x/y/z, radial), a screen-space stencil, and tools clone (clone_source) and smudge. `points` is a polyline (line / path tool).", paint_props, &["points"]),
        t("project_decal", "Project an image (PNG with alpha: sign, logo, label, poster, graffiti) onto the model like a sticker. Ways to place it: `rect` over a camera view; `part` alone (fit to the part's outward face); a world-space `box` (+ `facing`); or precisely with `anchor` [u,v] on a part's `face` (or `position` + `normal`) plus `size` in metres and `rotation`. Anchored decals can be torn / faded (`wear`, `fade`) and stacked with `overlap_order`. Colour comes from the image times `tint`; optional emission, height, opacity / transmission (`values` + `channels`). Every decal on a paint layer is recorded for export_variants (`name`, `variant`, `enabled`). Lands on the top paint layer unless `layer` / `overlap_order` is given. One undo step.",
          {
              let mut p = json!({ "projection": { "type": "string", "enum": ["box", "triplanar", "wrap"], "description": "decal layers: box (planar, default), triplanar (wraps over corners in the decal frame) or wrap (conforms: the surface is unfolded from the decal centre)" }, "image": { "type": "string" }, "rect": { "type": "array", "items": { "type": "number" }, "description": "[x0, y0, x1, y1] viewport area in 0..1 (y down)" },
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
        t("render", "Render the model with its current material (PBR image-based lighting, bloom, ACES). Choose lighting (studio / night / overcast / lightbox / lightbox_dark, a game sky night_rain / night_moon / dusk / predawn, or an hdri), exposure and bloom. With `views` it returns one contact sheet of front/back/left/right/top views. Returns the image.", render_props, &[]),
        t("render_turntable", "Render `frames` views evenly around the model (at `pitch`) as one labelled contact-sheet PNG: see the whole asset in one call. Takes the same lighting / bloom / view args as render.", sheet_props, &[]),
        t("export_lighting", "Write a built-in lighting preset as an equirectangular .hdr (e.g. to light a Blender world exactly like Pigment's viewport).",
          json!({ "lighting": { "type": "string", "enum": ["studio", "night", "overcast", "lightbox", "lightbox_dark", "night_rain", "night_moon", "dusk", "predawn"] }, "path": { "type": "string" }, "width": { "type": "integer", "description": "default 2048" } }), &["path"]),
        t("add_foliage_cell", "Foliage atlas projects: add a cell (leaf, twig, needle spray, blossom, grass tuft, ivy sprig, moss...) drawn by the leaf generators. The atlas is repacked: fills and folders stay, painted pixels are cleared. Returns the new layout.",
          foliage_cell_props(), &["name"]),
        t("update_foliage_cell", "Foliage atlas projects: change a cell's generator parameters (shape, arrangement, venation, serration, colours, autumn, dry edges, holes, bites, translucency...) or its preset; only that cell is redrawn (a new size_m repacks the atlas). One undo step.",
          { let mut p = foliage_cell_props(); p["cell"] = json!({ "type": ["string", "integer"], "description": "cell name or index" }); p["rename"] = json!({ "type": "string" }); p }, &["cell"]),
        t("add_bark", "Seamless tile projects: a generated bark layer (tiles on both axes) with colour, height (-> normal) and roughness. Styles: fissured (oak, old pine), plated (Japanese black pine), lenticels (smooth cherry with horizontal lenticels), peeling (birch / crape myrtle). Call again with the same name to change it.",
          json!({ "style": { "type": "string", "enum": ["fissured", "plated", "lenticels", "peeling", "smooth", "cherry", "pine", "oak", "birch"] },
                  "scale": { "type": "number", "description": "features per metre across" }, "stretch": { "type": "number", "description": "elongation along the trunk (v)" },
                  "depth": { "type": "number", "description": "0..1 relief" }, "roughness_variation": { "type": "number" },
                  "color": { "type": "array", "items": { "type": "number" } }, "crack_color": { "type": "array", "items": { "type": "number" } }, "accent_color": { "type": "array", "items": { "type": "number" } },
                  "roughness": { "type": "number" }, "lichen": { "type": "number", "description": "0..1 lichen specks" }, "seed": { "type": "integer", "minimum": 0 },
                  "name": { "type": "string", "description": "layer name (default `Bark (generated)`)" } }), &[]),
        t("scatter_foliage", "Scatter foliage cards over the model into a foliage layer: moss tufts in crevices, grass on the ground, weeds on roofs, fallen leaves, ivy leaves on walls. Choose `cells`, `count` or `density` (cards per m2), surfaces by normal (`facing`), `parts` / `region`, a `mask` (a layer such as Moss or Puddles, or an inline generator) and/or `ao` (crevices), `scale`, `align`, `min_spacing`, `seed`. Cards render in the viewport (alpha-tested, back-lit) and export with export_foliage. One undo step.",
          { let mut p = foliage_place_props();
            p["cells"] = json!({ "type": ["array", "string"], "items": { "type": ["string", "object"] }, "description": "cell names (or {cell, weight}) from the layer's atlas, e.g. [\"moss\", \"moss_patch\"]" });
            p["count"] = json!({ "type": "integer", "minimum": 0 }); p["density"] = json!({ "type": "number", "description": "cards per m2 of the allowed surface (instead of count)" });
            p["min_spacing"] = json!({ "type": "number", "description": "metres between card bases (also from existing cards)" });
            p["rotation_jitter"] = json!({ "type": "number", "description": "flat / wall cards: +- degrees around the normal (default 180)" });
            p["mount"] = json!({ "type": "string", "enum": ["upright", "flat", "wall", "hanging"], "description": "override the cells' mount" });
            p }, &[]),
        t("paint_foliage", "Paint foliage with a brush: a camera stroke (`points` in 0..1 + yaw / pitch / zoom / target / distance, like paint_stroke) or `world_points`; each dab scatters cards within `radius` metres at `density` per m2, spaced so scrubbing fills gaps instead of piling up. `erase: true` removes cards (optionally only `cells`). One undo step.",
          { let mut p = foliage_place_props();
            for (k, v) in camera.as_object().unwrap() { p[k] = v.clone(); }
            p["points"] = json!({ "type": "array", "items": { "type": "array", "items": { "type": "number" } }, "description": "stroke in viewport coords 0..1, y down" });
            p["world_points"] = json!({ "type": "array", "items": { "type": "array", "items": { "type": "number" } }, "description": "stroke as world points [[x, y, z], ...] (snapped to the surface)" });
            p["cells"] = json!({ "type": ["array", "string"], "items": { "type": ["string", "object"] }, "description": "cell names to paint (picked at random)" });
            p["mount"] = json!({ "type": "string", "enum": ["upright", "flat", "wall", "hanging"], "description": "override the cells' mount" });
            p["radius"] = json!({ "type": "number", "description": "brush radius in metres (default 0.3)" });
            p["density"] = json!({ "type": "number", "description": "cards per m2 (default 40)" });
            p["erase"] = json!({ "type": "boolean" });
            p }, &[]),
        t("grow_ivy", "Grow ivy along the surface from start points: a growth walk that climbs (up_bias), wanders, wraps round corners and branches, laying stem cards and leaf cards (ivy_leaf / ivy_stem from the builtin atlas, or `leaf` / `stem` cells). Start with `start` world points or a camera stroke `points`. One undo step.",
          { let mut p = foliage_place_props();
            for (k, v) in camera.as_object().unwrap() { p[k] = v.clone(); }
            p["start"] = json!({ "type": "array", "items": { "type": "array", "items": { "type": "number" } }, "description": "world start points [[x, y, z], ...] (snapped to the surface)" });
            p["points"] = json!({ "type": "array", "items": { "type": "array", "items": { "type": "number" } }, "description": "or start points from a camera view, 0..1" });
            p["length"] = json!({ "type": "number", "description": "metres of main strand per start (default 2.5)" });
            p["branching"] = json!({ "type": "number", "description": "side branches per metre (default 1.2)" });
            p["max_strands"] = json!({ "type": "integer", "minimum": 1 });
            p["step"] = json!({ "type": "number", "description": "walk step, metres (default 0.04)" });
            p["up_bias"] = json!({ "type": "number", "description": "pull upwards 0..1 (default 0.7)" });
            p["wander"] = json!({ "type": "number", "description": "random wander 0..1 (default 0.35)" });
            p["leaf_spacing"] = json!({ "type": "number", "description": "metres between leaves (default 0.06)" });
            p["leaf_scale"] = json!({ "type": ["number", "array"], "items": { "type": "number" } });
            p["stem_width"] = json!({ "type": "number", "description": "metres (default 0.012)" });
            p["leaf"] = json!({ "type": "string", "description": "leaf cell (default ivy_leaf)" });
            p["stem"] = json!({ "type": ["string", "null"], "description": "stem cell (default ivy_stem, null = no stems)" });
            p }, &[]),
        t("export_foliage", "Export the foliage layers: <name>_foliage.glb (every card as geometry, atlas UVs), <name>_foliage_instances.json (per cell: UV rect, card mesh, Godot Transform3D list for a MultiMesh), the atlas maps (BaseColorAlpha, Normal_OpenGL, Roughness, Translucency, Thickness) and a material.json entry (kind foliage: alpha clip, two-sided, translucency) for the Blender add-on. send_to_blender includes it.",
          json!({ "dir": { "type": "string" }, "name": { "type": "string", "description": "file prefix (default: mesh name)" }, "layer": { "type": ["string", "integer"], "description": "only this foliage layer (default: every visible one)" } }), &["dir"]),
        t("export_textures", "Export PNG texture maps. Presets: unreal, unity, godot, separate (glTF/Blender: BaseColor, Roughness, Metallic, AO, Normal_OpenGL, Height, Emissive, plus Opacity / Transmission when the material has any). unreal/unity/godot put opacity in the base colour's alpha (RGBA) when it isn't solid.",
          json!({ "dir": { "type": "string" }, "preset": { "type": "string", "enum": pigment_core::export::presets().iter().map(|p| p.id).collect::<Vec<_>>(), "description": "default separate" }, "name": { "type": "string", "description": "file name prefix (default: the mesh name)" },
                  "compression": { "type": "string", "enum": ["none", "fastest", "fast", "balanced", "best"], "description": "PNG compression effort (default fast). fastest/none write quickest but bigger files; maps are encoded in parallel either way" },
                  "template": { "type": ["string", "object"], "description": "an export template id (list_export_templates: unreal, unity, godot, separate, orm, unreal_packed, unity_hdrp, godot_orm, gltf, arnold, or a saved one) or an inline template {id, outputs: [...]}; overrides `preset`. Supports 8/16-bit PNG, TGA, f16/f32 EXR (HDR height and emission)" } }), &["dir"]),
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
        t("send_to_blender", "Export everything Blender needs into `dir`: the texture maps (preset, default 'separate'), a material.json sidecar (channels and files, emissive_scale, normal convention, resolution, project path) and the painted mesh with tangents (<name>.glb). The Pigment Bridge add-on (tools/blender_addon/pigment_bridge) links objects to this folder and live-reloads it. For random per-object variants in Blender, export each variant to a folder named <asset>__<variant>. Foliage layers are included (<name>_foliage.glb + instances + atlas maps, sidecar entry kind \"foliage\"). With several texture sets: every set in the preset as <name>_<set>_<map>.<udim>.png, one sidecar entry per set (its glTF materials and UDIM tile) listed under <name>.texture_sets, and the whole mesh with one glTF material per source material; the add-on gives each face its set's material.",
          json!({ "dir": { "type": "string" }, "name": { "type": "string", "description": "base file name (default: mesh name)" },
                  "preset": { "type": "string", "description": "export preset (default separate)" },
                  "mesh": { "type": "boolean", "description": "also export the mesh (default true)" },
                  "mesh_format": { "type": "string", "enum": ["glb", "obj"], "description": "glb (default, with tangents) or obj (no tangents)" },
                  "project": { "type": "string", "description": "save the project here first, so the sidecar links to it" },
                  "foliage": { "type": "boolean", "description": "also export the foliage layers (export_foliage; default true when there are any)" } }), &["dir"]),
        t("export_mesh", "Write the loaded mesh exactly as Pigment paints it (world transforms applied, UVs, normals, and in .glb the tangents the normal map was baked with).",
          json!({ "path": { "type": "string", "description": ".glb or .obj (no extension: .glb)" }, "format": { "type": "string", "enum": ["glb", "obj"] } }), &["path"]),
        t("export_window_map", "Interior mapping (parallax windows): write a window map of the mesh for the given glass parts. <dir>/<name>_WindowMap.png is a UV-space grey map (glTF UVs, row 0 = v 0) whose texels hold pane index + 1 (0 = not a pane; 16-bit if over 255 panes); panes grow `pad` texels into empty gutter, never over other parts. <dir>/<name>_panes.json lists every pane's frame: part id, centre, outward normal, right / up (as seen from outside), size [w, h] in metres and centre UV. A shader looks the pane up from the fragment UV and ray-casts into a room behind it (see pack_interiors).",
          json!({ "dir": { "type": "string" }, "name": { "type": "string", "description": "file prefix (default: mesh name)" },
                  "parts": { "type": ["array", "object"], "description": "pane part ids, or a shape query as in list_parts (e.g. {max_thickness: 0.02, min_area: 0.3})" },
                  "resolution": { "type": "integer", "description": "map size (default: the project resolution); nearest-sampled, so it can be lower" },
                  "pad": { "type": "integer", "description": "texels to grow panes into the empty atlas gutter (default 4)" },
                  "outward_from": { "type": "array", "items": { "type": "number" }, "description": "normals point away from this point (default: the mesh bounds centre)" },
                  "up": { "type": "array", "items": { "type": "number" }, "description": "world up for the panes' vertical axis (default [0, 1, 0])" } }), &["dir", "parts"]),
        t("pack_interiors", "Interior mapping: pack rooms into one texture-array strip (<dir>/<name>_atlas.png: cell x (cell * 2 * rooms), RGBA8, layers lit / off per room) plus <dir>/<name>.json. Format 'pre-projected': a room is a box size [w, h, d] metres behind the window plane, imaged by a pinhole camera `eye` metres in front of the window (default d) whose frustum passes through the front rectangle; alpha = depth of the surface seen (0 window plane .. 1 back wall) so shaders can ray-march furniture with parallax. Give each room `lit` (+ optional `off`, `depth`) rendered images, or the classic `faces` {back, left, right, floor, ceiling}, which are reprojected (analytic depth). Colour grade per room (`grade`, `off_grade`) on top of the pack-wide `grade`. Needs no project or GPU.",
          json!({ "dir": { "type": "string" }, "name": { "type": "string", "description": "default interiors" },
                  "cell": { "type": "integer", "description": "layer size in pixels (default 512)" },
                  "base_dir": { "type": "string", "description": "relative image paths are resolved against this folder" },
                  "grade": { "type": "object", "description": "pack-wide grade: exposure (stops), contrast, saturation, tint [r,g,b], lift [r,g,b], vignette" },
                  "rooms": { "type": "array", "items": { "type": "object", "properties": {
                      "name": { "type": "string" }, "size": { "type": "array", "items": { "type": "number" }, "description": "[width, height, depth] m (default [4, 3, 4])" },
                      "eye": { "type": "number" }, "lit": { "type": "string" }, "off": { "type": "string", "description": "lights-off render (default: lit at 3 %)" },
                      "depth": { "type": "string", "description": "grey depth image, 0 window .. 1 back wall (default: the empty box)" },
                      "faces": { "type": "object", "description": "{back, left, right, floor, ceiling} images instead of lit" },
                      "grade": { "type": "object" }, "off_grade": { "type": "object" }, "tags": { "type": "array", "items": { "type": "string" } } },
                      "required": ["name"], "additionalProperties": false } } }), &["dir", "rooms"]),
        t("get_project_info", "Overview of the session in one call: mesh (name, source, triangles, bounds), texture resolution, parts count, layers, bake status, project folder, last export timing.", json!({}), &[]),
        t("batch", "Run several tool calls in one request, in order: {calls: [{tool, args}, ...]}. Returns {ok, failed, results: [{index, tool, ok, ms, result | error}]}. Stops at the first error unless stop_on_error is false. Images from render are saved to disk (path in the result) rather than returned.",
          json!({ "calls": { "type": "array", "items": { "type": "object", "properties": { "tool": { "type": "string" }, "args": { "type": "object" } }, "required": ["tool"], "additionalProperties": false } },
                  "stop_on_error": { "type": "boolean", "description": "default true" } }), &["calls"]),
        t("add_filter", "Add a filter to a layer's filter stack. target \"layer\" (default): runs on the composited stack right after the layer, inside its mask (for a filter layer: on the stack below, gated by its mask and opacity); target \"mask\": runs on the layer's evaluated mask. Spatial filters are seam-aware (taps stay on their UV island). Filters run in order; `index` inserts (0 = first).",
          { let mut p = filter_schema(true)["properties"].clone();
            p["layer"] = json!({ "type": ["string", "integer"], "description": "layer name, path or index" });
            p["target"] = json!({ "type": "string", "enum": ["layer", "mask"], "description": "default layer" });
            p["index"] = json!({ "type": "integer", "minimum": 0, "description": "position in the stack (default: last)" });
            p }, &["layer", "kind"]),
        t("update_filter", "Change, toggle or reorder filter `index` of a layer's (or its mask's) filter stack. Giving a different `kind` resets its parameters.",
          { let mut p = filter_schema(true)["properties"].clone();
            p["layer"] = json!({ "type": ["string", "integer"], "description": "layer name, path or index" });
            p["target"] = json!({ "type": "string", "enum": ["layer", "mask"], "description": "default layer" });
            p["index"] = json!({ "type": "integer", "minimum": 0, "description": "which filter (0 = runs first)" });
            p["move_to"] = json!({ "type": "integer", "minimum": 0, "description": "new position in the stack" });
            p }, &["layer", "index"]),
        t("remove_filter", "Remove filter `index` from a layer's (or its mask's) filter stack.",
          json!({ "layer": { "type": ["string", "integer"], "description": "layer name, path or index" }, "target": { "type": "string", "enum": ["layer", "mask"], "description": "default layer" }, "index": { "type": "integer", "minimum": 0 } }), &["layer", "index"]),
        t("set_anchor", "Make a layer or folder an anchor point: the stack as composited right after it (height, the layer's mask x coverage, colour luminance) can be read by generators of layers above through mask.input {anchor, channel}, e.g. edge wear on painted scratches or dirt in painted dents; the `anchor` generator uses a channel directly as a mask.",
          json!({ "layer": { "type": ["string", "integer"], "description": "layer name, path or index" }, "anchor": { "type": ["string", "null"], "description": "anchor name (default: the layer name); null removes it" } }), &["layer"]),
        t("list_export_templates", "Export templates: built-in (the presets, ORM, Unreal packed, Unity HDRP mask map, Godot ORM, glTF, Arnold EXR), user (prefs) and project ones, with their outputs (file pattern, channel sources, format, bit depth, colour space, padding).", json!({}), &[]),
        t("save_export_template", "Save a custom export template: outputs -> file name pattern ({name}, {set}, {udim}) -> per-channel sources (base_color.r/g/b, opacity, roughness, smoothness, metallic, ao, height, normal.x/y/z, normal_dx.x/y/z, emissive.r/g/b, transmission, coat, coat_roughness, flake, const:<v>, '1-' prefix inverts) with format png | tga | exr, bit depth u8 | u16 | f16 | f32, colour space srgb | linear and padding dilate | none. Use it with export_textures {template: id}.",
          json!({ "template": template_schema(), "scope": { "type": "string", "enum": ["project", "user"], "description": "save with the project (default) or in the user preferences" } }), &["template"]),
        t("list_decals", "Decal objects on decal layers (add_layer kind \"decal\"): id, name, group, layer, image, centre, normal, size, rotation, depth, projection, wear, enabled. Bottom to top per layer.",
          json!({ "layer": { "type": ["string", "integer"], "description": "only this layer" } }), &[]),
        t("update_decal", "Edit a decal object non-destructively (the layer re-composites): move (position snapped to the surface, or `move` [dx, dy] metres in its plane), rotate, scale / size, projection, image, tint, opacity, wear, fade, enable / hide, rename, re-order (move_to), align upright / vertical, snap to the centre or nearest edge of the flat window-free area it sits on.",
          json!({ "decal": { "type": ["string", "integer"], "description": "decal id or name (list_decals)" }, "layer": { "type": ["string", "integer"], "description": "the decal's layer (default: search every decal layer)" },
                  "position": { "type": "array", "items": { "type": "number" }, "description": "[x, y, z] world point, snapped onto the surface along the normal" },
                  "normal": { "type": "array", "items": { "type": "number" } },
                  "move": { "type": "array", "items": { "type": "number" }, "description": "[dx, dy] metres along the decal's right / up" },
                  "size": { "type": ["number", "array"], "items": { "type": "number" }, "description": "width (keeps the aspect) or [w, h] metres" },
                  "scale": { "type": "number" }, "rotation": { "type": "number", "description": "degrees" }, "rotate": { "type": "number", "description": "add degrees" },
                  "depth": { "type": "number" }, "projection": { "type": "string", "enum": ["box", "triplanar", "wrap"] }, "image": { "type": "string" },
                  "tint": { "type": "array", "items": { "type": "number" } }, "opacity": { "type": "number" }, "wear": { "type": "number" }, "fade": { "type": "number" },
                  "wear_scale": { "type": "number" }, "wear_seed": { "type": "number" }, "paper_rim": { "type": "number" },
                  "enabled": { "type": "boolean" }, "name": { "type": "string" }, "variant": { "type": "string", "description": "variant group" },
                  "move_to": { "type": "integer", "minimum": 0, "description": "new position in the layer's decal order (0 = bottom)" },
                  "align": { "type": "string", "enum": ["upright", "vertical"] }, "snap": { "type": "string", "enum": ["center", "edge"] }, "margin": { "type": "number", "description": "snap edge margin (m)" } }), &["decal"]),
        t("delete_decal", "Delete a decal object.", json!({ "decal": { "type": ["string", "integer"], "description": "decal id or name (list_decals)" }, "layer": { "type": ["string", "integer"] } }), &["decal"]),
        t("place_decal", "Place decal objects in the largest flat, window-free wall area: `region: \"auto\"` (optionally limited by parts / parts_where / height band / facing, `pick` the n-th largest) or {min, max} (the largest area inside a world box). One image fitted into it, or a `grid` {rows, cols, gap} of `images` (a poster wall). Goes on a decal layer (`layer`, `overlap_order`, or the top decal layer / a new one).",
          json!({ "image": { "type": "string" }, "images": { "type": "array", "items": { "type": "string" }, "description": "for a grid: cycled over the cells" },
                  "region": { "type": ["string", "object"], "description": "\"auto\" or {min: [x,y,z], max: [x,y,z]}" }, "pick": { "type": "integer", "minimum": 0 },
                  "parts": { "type": "array", "items": { "type": "integer" } }, "parts_where": { "type": "object", "description": "part shape query (list_parts)" },
                  "height": { "type": "array", "items": { "type": "number" }, "description": "[min, max] metres above the mesh's lowest point" },
                  "facing": { "type": "string", "enum": ["walls", "any"] }, "margin": { "type": "number", "description": "kept free inside the area (m, default 0.05)" },
                  "fill": { "type": "number", "description": "fraction of the area (or grid cell) the image fills (default 0.9)" },
                  "grid": { "type": "object", "additionalProperties": false, "properties": { "rows": { "type": "integer" }, "cols": { "type": "integer" }, "gap": { "type": "number" } } },
                  "layer": { "type": ["string", "integer"] }, "overlap_order": { "type": "integer" }, "name": { "type": "string" }, "variant": { "type": "string" },
                  "projection": { "type": "string", "enum": ["box", "triplanar", "wrap"] },
                  "tint": { "type": "array", "items": { "type": "number" } }, "material": { "type": "string" }, "emissive_strength": { "type": "number" }, "opacity": { "type": "number" },
                  "wear": { "type": "number" }, "fade": { "type": "number" }, "wear_style": { "type": "string", "enum": ["noise", "grunge"] }, "wear_scale": { "type": "number" }, "wear_seed": { "type": "number" }, "paper_rim": { "type": "number" },
                  "alpha_from_luminance": { "type": "boolean" }, "channels": { "type": "array", "items": { "type": "string" } }, "values": { "type": "object" } }), &[]),
        t("list_texture_sets", "The project's texture sets (one per material / UDIM tile, each with its own resolution and layer stack): name, materials, UDIM tile, resolution, triangles, layer count, which is active; plus the mesh's UDIM tiles.", json!({}), &[]),
        t("undo", "Undo the last action.", json!({}), &[]),
        t("redo", "Redo.", json!({}), &[]),
    ])
}

/// Schema of an export template (`pigment_core::templates`).
fn template_schema() -> Value {
    json!({ "type": "object", "additionalProperties": false, "required": ["id", "outputs"], "description": "an export template",
        "properties": { "id": { "type": "string" }, "label": { "type": "string" },
            "outputs": { "type": "array", "items": { "type": "object", "additionalProperties": false, "required": ["pattern", "channels", "format", "bit_depth"],
                "properties": {
                    "pattern": { "type": "string", "description": "file name without extension, tokens {name} {set} {udim}" },
                    "channels": { "type": "array", "items": { "type": "string" }, "description": "1, 3 or 4 sources, e.g. ao, roughness, metallic" },
                    "format": { "type": "string", "enum": ["png", "tga", "exr"] },
                    "bit_depth": { "type": "string", "enum": ["u8", "u16", "f16", "f32"], "description": "png: u8/u16, tga: u8, exr: f16/f32" },
                    "color_space": { "type": "string", "enum": ["srgb", "linear"], "description": "base colour / emission encoding (default srgb)" },
                    "padding": { "type": "string", "enum": ["dilate", "none"], "description": "dilate: seam padding (default); none: zero outside the UV islands" },
                    "skip_if_neutral": { "type": "boolean", "description": "don't write the file when it holds nothing (opacity / transmission / coat of a material without any)" } } } } } })
}

/// Schema of one filter (`pigment_core::filters`). `top` = tool arguments
/// (the tool marks `kind` required itself).
fn filter_schema(top: bool) -> Value {
    let kinds: Vec<&str> = pigment_core::filters::FilterKind::ALL.iter().map(|k| k.id()).collect();
    let num = |d: &str| json!({ "type": "number", "description": d });
    let lv = |d: &str| json!({ "type": ["number", "array"], "items": { "type": "number" }, "description": d });
    let rgb = |d: &str| json!({ "type": "array", "items": { "type": "number" }, "minItems": 3, "maxItems": 3, "description": d });
    let mut v = json!({ "type": "object", "additionalProperties": false, "properties": {
        "kind": { "type": "string", "enum": kinds, "description": "levels, hsl, color_balance, invert, clamp (point filters); blur, directional_blur, sharpen, warp, slope_blur, edge_detect, height_to_normal (spatial, seam-aware); fill_holes, grow, shrink (masks only); noise_overlay (MatFinish-style world noise)" },
        "enabled": { "type": "boolean" },
        "radius": num("blur / sharpen / grow / shrink / fill_holes / edge radius, warp / slope_blur distance: texels at 2048 (scales with the resolution)"),
        "amount": num("strength: sharpen, warp, slope_blur, noise_overlay, edge gain, height_to_normal"),
        "strength": num("alias of amount"),
        "angle": num("directional_blur: degrees (0 = along +u)"),
        "scale": num("noise frequency per metre (warp, slope_blur, noise_overlay)"),
        "seed": { "type": "integer", "minimum": 0 },
        "levels": { "type": "object", "additionalProperties": false, "description": "each a number (master) or [r, g, b] / [r, g, b, master]",
            "properties": { "in_black": lv("input black"), "in_white": lv("input white"), "gamma": lv("gamma (1 = linear, > 1 brighter)"), "out_black": lv("output black"), "out_white": lv("output white") } },
        "hue": num("hsl: hue shift, degrees"), "saturation": num("hsl: -1..1"), "lightness": num("hsl: -1..1"),
        "shadows": rgb("color_balance: rgb offsets -1..1"), "midtones": rgb("color_balance"), "highlights": rgb("color_balance"),
        "min": num("clamp minimum (0..1)"), "max": num("clamp maximum (0..1)"),
        "use_height": { "type": "boolean", "description": "slope_blur: follow the stack's height instead of noise; height_to_normal: keep the height (adds normal detail on top) instead of converting it" },
        "channels": { "type": "array", "items": { "type": "string", "enum": ["base_color", "roughness", "metallic", "height", "normal", "emissive"] }, "description": "layer filters: channels to change (default per kind: colour filters base_color, spatial ones colour/roughness/metallic/height/emission)" }
    } });
    if !top {
        v["required"] = json!(["kind"]);
    }
    v
}

/// Schema of a layer `mask` argument.
fn mask_schema() -> Value {
    let mut gens: Vec<&str> = pigment_core::GeneratorKind::ALL.iter().map(|g| g.id()).collect();
    // aliases GeneratorKind::from_id accepts (bricks / square / hex also pick the tile variant)
    gens.extend(["drips", "leak", "wetness", "wet", "puddle", "grime_accumulation", "lichen", "bricks", "brick", "tile", "square", "hex", "windows", "window_lights"]);
    // ground generator aliases (cobbles, pebbles, leaves, grass ... also pick a variant)
    gens.extend(["ridged", "cliff"]);
    gens.extend(pigment_core::ground::GROUND_ALIASES.iter().map(|a| a.0));
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
    ground_gen_fields(&mut gen_fields);
    let mut effect = gen_fields.clone();
    effect["op"] = json!({ "type": "string", "enum": ["multiply", "add", "subtract", "max", "min"], "description": "how it combines with the mask so far (default multiply)" });
    gen_fields["invert"] = json!({ "type": "boolean" });
    gen_fields["parts"] = json!({ "type": "array", "items": { "type": "integer", "minimum": 0 },
        "description": "part ids from list_parts / pick_parts: limit the layer to those mesh pieces ([] = whole model)" });
    gen_fields["parts_where"] = json!({ "type": "object", "properties": list_parts_props(), "additionalProperties": false,
        "description": "select parts by shape instead of ids (same filters as list_parts, e.g. {\"max_thickness\": 0.02, \"min_area\": 0.5}); resolved to ids when set; combined with `parts` as a union" });
    gen_fields["input"] = json!({ "type": ["object", "null"], "additionalProperties": false, "required": ["anchor"],
        "description": "generator input: read an anchor below this layer instead of only the mesh bakes. The anchor channel's relief (value minus its local average) is added to the curvature (raised rims = edges, dents = cavities); the `anchor` generator uses the channel directly. null = bakes",
        "properties": { "anchor": { "type": "string", "description": "anchor name (set_anchor)" }, "channel": { "type": "string", "enum": ["height", "mask", "color"], "description": "default height" },
                        "strength": { "type": "number", "description": "relief -> curvature gain (default 4)" }, "radius": { "type": "number", "description": "relief neighbourhood, texels at 2048 (default 6)" } } });
    gen_fields["id_color"] = json!({ "type": ["object", "null"], "additionalProperties": false, "required": ["color"],
        "description": "ID mask: only where the project's ID map (bake color_id / material_id) has this colour; null removes it",
        "properties": { "color": { "type": "array", "items": { "type": "number" }, "minItems": 3, "maxItems": 3, "description": "sRGB 0..1, as in the ID map (pick it from the baked PNG or list_layers id colours)" },
                        "tolerance": { "type": "number", "description": "RGB distance that still matches (default 0.1)" } } });
    gen_fields["filters"] = json!({ "type": "array", "items": filter_schema(false), "description": "replace the mask's filter stack (blur, grow, shrink, fill_holes, warp, levels...), run in order on the evaluated mask. [] removes them" });
    gen_fields["effects"] = json!({ "type": "array", "maxItems": 2, "description": "up to 2 more generators combined in order",
        "items": { "type": "object", "properties": effect, "required": ["generator"], "additionalProperties": false } });
    json!({ "type": ["string", "object", "null"], "properties": gen_fields, "additionalProperties": false,
            "description": "\"white\" | \"black\" (painted mask) | null (remove the mask) | {generator, amount, ..., invert, parts, effects}" })
}

/// Foliage cell fields: leaf generator parameters plus the cell's name,
/// preset, card size, mount and card mesh.
fn foliage_cell_props() -> Value {
    use pigment_core::foliage as fol;
    let n = |d: &str| json!({ "type": "number", "description": d });
    let i = |d: &str| json!({ "type": "integer", "minimum": 0, "description": d });
    let rgb = |d: &str| json!({ "type": "array", "items": { "type": "number" }, "maxItems": 3, "description": d });
    json!({
        "name": { "type": "string", "description": "cell name (unique in the atlas)" },
        "preset": { "type": "string", "enum": fol::PRESETS, "description": "start from a preset (Japanese pagoda tree, maple, ginkgo, cherry blossom, black pine, grass, ivy, moss, weeds, fern, hanging vine, fallen leaves...); other fields override it" },
        "size_m": { "type": ["number", "array"], "items": { "type": "number" }, "description": "card size in metres [width, height] (default from the preset)" },
        "mount": { "type": "string", "enum": ["upright", "flat", "wall", "hanging"], "description": "how the foliage brush sets this card on a surface" },
        "mesh": { "type": "string", "enum": ["quad", "cross", "star"], "description": "card geometry per instance (cross = 2 crossed quads for tufts)" },
        "shape": { "type": "string", "enum": fol::LeafShape::ALL.map(|s| s.id()), "description": "leaf outline (aliases: maple = palmate, fan = ginkgo, heart = cordate, blade = grass)" },
        "arrangement": { "type": "string", "enum": fol::Arrangement::ALL.map(|s| s.id()), "description": "single leaf; twig (alternating on a stem); compound (pinnate leaflets, pagoda tree / fern); tuft (grass); spray (needle fascicles); cluster (blossoms); rosette; clump (moss cushion); scatter (fallen leaves / moss patch); trailing (hanging)" },
        "count": i("leaves / compound leaves / fascicles / flowers / blades"),
        "aspect": n("leaf width / length (0 = shape default)"),
        "lobes": i("lobes (palmate, ivy), leaflet pairs (compound), needles per fascicle (spray), petals (cluster)"),
        "lobe_depth": n("0..1 how deep the lobes are cut (ginkgo: the centre notch)"),
        "spread": n("degrees the lobes / blades / needles fan over (0 = default)"),
        "serration": n("0..1 edge tooth depth"),
        "teeth": i("teeth per side (per lobe for lobed leaves)"),
        "venation": n("0..1 vein strength in colour and height (midrib + secondary veins)"),
        "veins": i("secondary veins per side (ginkgo: radiating veins)"),
        "vein_angle": n("degrees between secondary veins and the midrib"),
        "color": rgb("leaf base colour, sRGB 0..1"),
        "tip_color": rgb("colour towards the tip / rim"),
        "tip_amount": n("0..1 base -> tip gradient strength"),
        "vein_color": rgb("vein colour"),
        "hue_jitter": n("0..1 per-leaf hue variation"),
        "value_jitter": n("0..1 per-leaf brightness variation"),
        "autumn": n("0..1 green -> yellow -> autumn_color"),
        "autumn_jitter": n("per-leaf +- variation of autumn"),
        "autumn_color": rgb("full-autumn colour (maple red, ginkgo gold)"),
        "dry_edges": n("0..1 width of a dry brown rim"),
        "dry_color": rgb("dry rim colour"),
        "holes": n("0..1 holes eaten through the blade"),
        "bites": n("0..1 chance per leaf of insect bites out of the edge"),
        "translucency": n("0..1 light passing through (back-lit glow; exported as the Translucency / backlight / subsurface map)"),
        "translucency_color": { "type": ["array", "null"], "items": { "type": "number" }, "maxItems": 3, "description": "colour of the light coming through (default: derived from the leaf colour)" },
        "roughness": n("0..1"),
        "stem_color": rgb("stems, petioles, twigs"),
        "stem_width": n("stem width relative to the leaf length (0 = no stem)"),
        "bend": n("-1..1 sideways bend of blades / needles"),
        "wave": n("0..1 waviness of the main stem"),
        "leaf_size": n("leaf length relative to the twig / cell (0 = default)"),
        "stamens": { "type": "boolean", "description": "blossoms: stamens in the flower centre" },
        "seed": i("random seed")
    })
}

/// Mask for foliage scatter: a layer (name / index) whose mask is read, or
/// an inline generator mask.
fn foliage_mask_schema() -> Value {
    let full = mask_schema();
    let mut props = full["properties"].clone();
    let o = props.as_object_mut().unwrap();
    o.remove("effects");
    o.remove("parts_where");
    json!({ "type": ["string", "integer", "object", "null"], "properties": props, "additionalProperties": false,
            "description": "where foliage may go: a layer name / index (its mask: generator, painted pixels and parts, e.g. the Moss or Puddles layer) or an inline generator mask {generator: \"moss\", amount, scale, ...}. Cards are kept with probability rising around `mask_threshold`" })
}

/// Placement / surface fields shared by the foliage tools.
fn foliage_place_props() -> Value {
    json!({
        "layer": { "type": ["string", "integer"], "description": "foliage layer (created on top as `Foliage` / the given name if missing)" },
        "atlas": { "type": "string", "description": "card source for the layer: \"builtin\" (default library: moss, moss_patch, grass, weed, ivy_leaf, ivy_stem, ivy, maple_leaf, ginkgo_leaf, cherry_petals, fallen_leaves, fern, hanging_vine, weed_rosette) or a foliage atlas export's <name>_foliage.json" },
        "wind": { "type": "number", "description": "0..1 wind sway in the viewport preview" },
        "facing": { "type": "string", "enum": ["up", "walls", "down", "any"], "description": "surfaces by normal: up (ground, ledges, roofs), walls, down (ceilings, undersides), any" },
        "min_up": { "type": "number", "description": "lowest surface normal y allowed (-1..1, overrides facing)" },
        "max_up": { "type": "number", "description": "highest surface normal y allowed" },
        "parts": { "type": "array", "items": { "type": "integer", "minimum": 0 }, "description": "only these mesh parts" },
        "region": { "type": "object", "additionalProperties": false, "description": "world box", "properties": { "min": { "type": "array", "items": { "type": "number" } }, "max": { "type": "array", "items": { "type": "number" } } } },
        "mask": foliage_mask_schema(),
        "mask_threshold": { "type": "number", "description": "mask value around which cards appear (default 0.5)" },
        "ao": { "type": ["number", "array"], "items": { "type": "number" }, "description": "[min, max] baked AO allowed: e.g. [0, 0.7] = crevices and corners only" },
        "scale": { "type": ["number", "array"], "items": { "type": "number" }, "description": "card scale range [min, max] (x the cell's size_m)" },
        "align": { "type": "number", "description": "upright cards: 0 = along the surface normal, 1 = straight up (gravity); default 0.6" },
        "seed": { "type": "integer", "minimum": 0 }
    })
}

/// Named parameters of the ground generators (docs/agents/ground/NOTES.md).
fn ground_gen_fields(g: &mut Value) {
    let n = |d: &str| json!({ "type": "number", "description": d });
    g["variant"] = json!({ "type": ["string", "integer"], "description": "tiles: bricks | square | hex; cells: dome | f2 | edges | value | plates; scatter: pebble | flake | leaf | twig | shell | clover | chip; rock: height | cracks | ledges | streaks; blades: height | tips | clumps; ripples: height | crests (or the index); planks: the layout, boards | herringbone | chevron | basketweave" });
    let fields = [
        ("warp", "cells / rock: domain warp (= breakup)"),
        ("randomness", "cells: point jitter 0 (grid) .. 1 (= ao_influence)"),
        ("edge_width", "cells: edge / bevel width in metres (= curvature_weight)"),
        ("bevel", "cells: alias of edge_width"),
        ("stretch", "cells: cells per metre along x relative to z (extra[0])"),
        ("height_variation", "cells / scatter: random height per cell / instance 0..1"),
        ("edge_noise", "cells: roughens the cell borders (extra[2])"),
        ("density", "scatter / blades: chance per slot 0..1 (= amount)"),
        ("size_variation", "scatter: 0 all the same .. 1 (= breakup)"),
        ("elongation", "scatter: long axis / short axis, 1 round .. 12 needles (= ao_influence)"),
        ("size", "scatter: radius as a fraction of a cell (= curvature_weight)"),
        ("radius", "scatter: alias of size"),
        ("per_cell", "scatter: instances per cell 1..8 (extra[0])"),
        ("align", "scatter: 0 random rotation .. 1 all along x (extra[1])"),
        ("irregularity", "scatter: irregular outlines (extra[2]); ripples: curving crests (= breakup)"),
        ("strata", "rock: strata ledges strength 0..1 (= ao_influence)"),
        ("cracks", "rock: block-joint crack depth 0..2 (= curvature_weight)"),
        ("bands", "rock: strata bands per metre along the surface's v (extra[0])"),
        ("streaks", "rock: downhill erosion streaks (extra[1])"),
        ("crack_scale", "rock: crack cells per metre (extra[2])"),
        ("clumping", "blades: clump contrast 0..1 (= breakup)"),
        ("lean", "blades: 0 upright .. 1 lying flat (= ao_influence)"),
        ("length", "blades: blade length in metres; planks: plank length / width (= curvature_weight)"),
        ("width", "blades: blade half width at the root in metres (extra[0])"),
        ("swirl", "blades: how much neighbouring blades lean the same way (extra[1])"),
        ("level", "blades tips / clumps: the output value where the mask starts, 0..1 (extra[2]; amount stays the blade density)"),
        ("asymmetry", "ripples: gentle windward / steep lee side 0..1 (= ao_influence)"),
        ("defects", "ripples: forking, ending, fading crests 0..1 (= curvature_weight)"),
        ("angle", "ripples: crest direction in degrees from x (extra[0])"),
        ("sharpness", "ripples: crest sharpness 0..1 (extra[1])"),
        ("waviness", "planks: how much the grain wanders 0..1.5 (= breakup)"),
        ("joint_width", "planks: gap between planks in metres, e.g. 0.001 (= ao_influence)"),
        ("length_ratio", "planks: plank length / width; herringbone and basketweave round it to whole slats (= curvature_weight)"),
        ("rings_per_cm", "planks: growth rings per cm of radius, oak ~2-4 (extra[0])"),
        ("flat_sawn", "planks: 0 quarter-sawn straight stripes .. 1 flat-sawn arches (extra[1])"),
        ("knots", "planks: how many boards have knots 0..1 (extra[2])"),
    ];
    for (k, d) in fields {
        g[k] = n(d);
    }
    g["output"] = json!({ "type": "string", "enum": pigment_core::ground::PLANK_OUTPUTS, "description": "planks: what the mask shows, surface | joints | latewood | pores (extra[3]); the layers of one wood floor share everything else (layout, size, grain)" });
    g["extra"] = json!({ "type": "array", "items": { "type": "number" }, "maxItems": 4, "description": "ground generators: the raw shape parameters (see the named args)" });
}

/// Fill-layer ground options: height profile, height blend, per-instance jitter.
fn ground_layer_fields(l: &mut Value) {
    l["height_profile"] = json!({ "type": "boolean", "description": "fill layers: the height follows the mask generator's shape (a dome per pebble, a blade's rise, the ripple profile) instead of a flat plateau; turns the height channel on" });
    l["height_gain"] = json!({ "type": "number", "description": "fill layers: multiplies the fill's height, 0..8 (relief beyond -1..1: boulders, rock masses, ruts; the stack's height is HDR, normals see all of it, the exported height map clamps to -1..1); turns the height channel on" });
    l["height_blend"] = json!({ "type": ["object", "string", "null"], "additionalProperties": false,
        "description": "fill layers: show only where this layer's level (its height + offset) is above the stack (\"above\": sand between pebbles, water in ruts) or below it (\"below\": moss on the tops). A string sets the mode; null removes.",
        "properties": {
            "mode": { "type": "string", "enum": ["above", "below", "lows", "tops"] },
            "contrast": { "type": "number", "description": "transition width in height units (default 0.05)" },
            "offset": { "type": "number", "description": "added to the layer's level (height units)" } } });
    l["jitter"] = json!({ "type": ["object", "number", "null"], "additionalProperties": false,
        "description": "fill layers: per-instance variation keyed by the mask generator's instance (each pebble, cell, blade, rock block). A number = value range; null removes.",
        "properties": {
            "value": { "type": "number", "description": "brightness +/- (0.2 = x0.8 .. x1.2)" },
            "hue": { "type": "number", "description": "hue rotation +/- in turns (0.03 = +/- 11 degrees)" },
            "saturation": { "type": "number", "description": "saturation +/-" },
            "roughness": { "type": "number", "description": "roughness +/-" } } });
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
pub(crate) fn check_args(name: &str, args: &Value) -> Result<(), String> {
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
    crate::mcp_args::validate(name, schema, args)
}

/// Turn a tool's MCP content into plain JSON for batch results.
pub(crate) fn content_json(content: &[Value]) -> Value {
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
pub(crate) fn call(session: &mut Option<Session>, name: &str, args: &Value) -> Result<Vec<Value>, String> {
    check_args(name, args)?;
    let cpu = match name {
        "inspect_project" => Some(pigment_core::diagnostics::inspect(std::path::Path::new(args["path"].as_str().unwrap()))),
        "verify_export" => Some(pigment_core::diagnostics::verify_export(std::path::Path::new(args["dir"].as_str().unwrap()), args["target"].as_str())),
        "doctor" => Some(Ok(crate::cli::doctor_args(args))),
        _ => None,
    };
    if let Some(result) = cpu {
        let value = result.map_err(|e| format!("{e:#}"))?;
        return Ok(vec![json!({"type":"text","text":value.to_string()})]);
    }
    if name == "batch" {
        return batch(session, args);
    }
    if name == "pack_interiors" {
        let v = crate::app::automation::pack_interiors(args)?;
        return Ok(vec![json!({ "type": "text", "text": serde_json::to_string_pretty(&v).unwrap() })]);
    }
    if session.is_none() {
        *session = Some(Session::new()?);
    }
    // `texture_set`: run the tool on that set ("*": on every set), then go back
    if let Some(ts) = args.get("texture_set").filter(|_| crate::app::automation::set_tools::SET_TOOLS.contains(&name)) {
        let s = session.as_mut().unwrap();
        let mut names = s.texture_set_scope(ts)?;
        if name == "paint_stroke" {
            names.truncate(1); // a stroke already paints across sets
        }
        let prev = s.active_texture_set();
        let mut a = args.clone();
        a.as_object_mut().unwrap().remove("texture_set");
        let mut results = serde_json::Map::new();
        let mut missed = Vec::new();
        for n in &names {
            session.as_mut().unwrap().activate_texture_set(n)?;
            match call(session, name, &a) {
                Ok(content) => {
                    results.insert(n.clone(), content_json(&content));
                }
                // with "*", a decal only lands on the sets it touches
                Err(e) if names.len() > 1 && (name == "project_decal" || name == "scatter_decals") && (e.contains("no surface") || e.contains("no spot") || e.contains("nothing to place") || e.contains("placed 0")) => {
                    missed.push(n.clone());
                }
                Err(e) => {
                    let _ = session.as_mut().unwrap().activate_texture_set(&prev);
                    return Err(format!("texture set `{n}`: {e}"));
                }
            }
        }
        if results.is_empty() && !missed.is_empty() {
            let _ = session.as_mut().unwrap().activate_texture_set(&prev);
            return Err(format!("{name}: touches no surface in any texture set"));
        }
        session.as_mut().unwrap().activate_texture_set(&prev)?;
        let v = if results.len() == 1 { results.into_iter().next().unwrap().1 } else { Value::Object(results) };
        return Ok(vec![json!({ "type": "text", "text": serde_json::to_string_pretty(&v).unwrap() })]);
    }
    let s = session.as_mut().unwrap();
    let text = |v: Value| Ok(vec![json!({ "type": "text", "text": serde_json::to_string_pretty(&v).unwrap() })]);
    match name {
        "render_feedback" => text(crate::cli::feedback(s, std::path::Path::new(args["dir"].as_str().unwrap())).map_err(|e| format!("{e:#}"))?),
        "new_project" => text(s.new_project(args)?),
        "open_project" => text(s.open_project(args)?),
        "save_project" => text(s.save_project(args)?),
        "list_library" => text(s.library()),
        "list_layers" => text(s.list_layers(args)),
        "list_texture_sets" => text(s.list_texture_sets()),
        "list_decals" => text(s.list_decals(args)?),
        "update_decal" => text(s.update_decal(args)?),
        "delete_decal" => text(s.delete_decal(args)?),
        "place_decal" => text(s.place_decal_region(args)?),
        "list_export_templates" => text(s.list_export_templates()),
        "save_export_template" => text(s.save_export_template(args)?),
        "save_smart_material" => text(s.save_smart_material(args)?),
        "apply_smart_material" => text(s.apply_smart_material(args)?),
        "list_parts" => text(s.list_parts_query(args)?),
        "get_project_info" => text(s.project_info()),
        "pick_parts" => text(s.pick_parts(args)?),
        "add_smart_material" => text(s.add_smart_material(args)?),
        "add_layer" => text(s.add_layer(args)?),
        "update_layer" => text(s.update_layer(args)?),
        "add_filter" => text(s.add_filter(args)?),
        "update_filter" => text(s.update_filter(args)?),
        "remove_filter" => text(s.remove_filter(args)?),
        "set_anchor" => text(s.set_anchor(args)?),
        "delete_layer" => text(s.delete_layer(args)?),
        "bake" => text(s.bake(args)?),
        "paint_stroke" => text(s.paint_stroke(args)?),
        "project_decal" => text(s.project_decal(args)?),
        "scatter_decals" => text(s.scatter_decals(args)?),
        "export_textures" => text(s.export_textures(args)?),
        "export_variants" => text(s.export_variants(args)?),
        "send_to_blender" => text(s.send_to_blender(args)?),
        "export_mesh" => text(s.export_mesh(args)?),
        "add_foliage_cell" => text(s.add_foliage_cell(args)?),
        "update_foliage_cell" => text(s.update_foliage_cell(args)?),
        "add_bark" => text(s.add_bark(args)?),
        "scatter_foliage" => text(s.scatter_foliage(args)?),
        "paint_foliage" => text(s.paint_foliage(args)?),
        "grow_ivy" => text(s.grow_ivy(args)?),
        "export_foliage" => text(s.export_foliage(args)?),
        "export_window_map" => text(s.export_window_map(args)?),
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

pub fn serve() {
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
        let mut directories = vec![root.join("scenes")];
        while let Some(dir) = directories.pop() {
            for e in std::fs::read_dir(&dir).unwrap_or_else(|e| panic!("{}: {e}", dir.display())) {
                let entry = e.unwrap();
                let p = entry.path();
                if entry.file_type().unwrap().is_dir() {
                    directories.push(p);
                    continue;
                }
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
