//! Pigment MCP server: drives a headless Pigment session over the Model
//! Context Protocol (JSON-RPC 2.0, one message per line on stdin/stdout).
//!
//!   claude mcp add pigment -- <repo>/target/release/pigment-mcp.exe
//!
//! It can also run a script of tool calls without an MCP client:
//!
//!   pigment-mcp --script calls.jsonl     (one {"tool": ..., "args": {...}} per line)

use base64::Engine;
use pigment_engine::app::automation::Session;
use serde_json::{json, Value};
use std::io::{BufRead, Write};

const PROTOCOL: &str = "2025-06-18";

fn tools() -> Value {
    let mut layer_fields = json!({
        "name": { "type": "string" },
        "material": { "type": "string", "description": "Material preset name (see list_library)" },
        "values": { "type": "object", "description": "Override fill values", "properties": {
            "base_color": { "type": "array", "items": { "type": "number" }, "description": "sRGB 0..1" },
            "roughness": { "type": "number" }, "metallic": { "type": "number" }, "height": { "type": "number", "description": "-1..1, negative = recessed" } } },
        "opacity": { "type": "number" },
        "visible": { "type": "boolean" },
        "channels": { "type": "object", "description": "e.g. {\"height\": false, \"roughness\": true}" },
        "blend": { "type": "object", "description": "per channel, e.g. {\"base_color\": \"multiply\", \"height\": \"add\"}" },
        "mask": { "description": "\"white\" | \"black\" | null (remove) | {generator: edge_wear|dirt|grunge|streaks|stripes|spots|scratches|panel_lines|gradient, amount, softness, scale, breakup, seed, ao_influence, curvature_weight, invert, parts: [part ids from list_parts / pick_parts: limit the layer to those mesh pieces], effects: [{generator, op: multiply|add|subtract|max|min, amount, scale, breakup, ...}] (max 2)}" },
        "variant": { "type": ["string", "null"], "description": "variant group tag: export_variants can enable/disable every layer or decal in a group" },
        "part_subset": { "description": "{from, to, salt}: keep only the mask parts whose seeded roll (0..1) is in [from, to). The roll follows the variant seed, so each export_variants variant lights a different set of windows. Layers with the same salt and disjoint ranges get disjoint parts. null removes." }
    });
    layer_fields["image"] = json!({
        "description": "Fill layers: channels from tiling images instead of flat values. A string is a tile set folder (e.g. \"assets/tiles/brick\", see list_library tile_sets); null removes it; an object changes only the fields given. Images: sRGB base colour (x tint), grey roughness (remapped to roughness_range), grey height (0.5 = flat, height = (v - 0.5) * height_scale), OpenGL tangent normal.",
        "properties": {
            "tile_set": { "type": "string", "description": "folder with base_color/roughness/height/normal .png (sets all four)" },
            "base_color": { "type": ["string", "null"], "description": "image path (relative paths resolve from the project/mesh folder and its parents, then the working dir); null = flat value" },
            "roughness": { "type": ["string", "null"] }, "height": { "type": ["string", "null"] }, "normal": { "type": ["string", "null"] },
            "projection": { "type": "string", "enum": ["uv", "triplanar"], "description": "uv: repeats over the UV square; triplanar: world-space box projection, ignores UVs" },
            "tiling": { "description": "uv: repeats across UV 0..1, number or [u, v] (default 1)" },
            "tile_size": { "type": "number", "description": "triplanar: metres per repeat (default 1)" },
            "blend_sharpness": { "type": "number", "description": "triplanar: corner blend, 1 soft .. 16 hard (default 4)" },
            "offset": { "description": "shift in tiles, [u, v]" },
            "rotation": { "type": "number", "description": "degrees" },
            "tint": { "type": "array", "items": { "type": "number" }, "description": "multiplies base colour, sRGB 0..1" },
            "roughness_range": { "type": "array", "items": { "type": "number" }, "description": "[lo, hi] (default [0, 1])" },
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
        "width": { "type": "integer" }, "height": { "type": "integer" }
    });
    let mut add_props = layer_fields.clone();
    add_props["kind"] = json!({ "type": "string", "enum": ["fill", "paint", "folder"], "description": "folder = a group with its own opacity, blend, mask and visibility; its mask multiplies its children's" });
    add_props["index"] = json!({ "type": "integer", "description": "stack position (0 = bottom); default: below the top paint layer. With `parent`: position among the folder's children (default: top)" });
    add_props["parent"] = json!({ "description": "folder to put the new layer in (name, \"Folder/Sub\" path or index); null/omitted = top level" });
    let mut upd_props = layer_fields;
    upd_props["layer"] = json!({ "description": "layer name, \"Folder/Layer\" path, or index (0 = bottom)" });
    upd_props["move_to"] = json!({ "type": "integer", "description": "new position: flat index at the top level, or the position among the siblings inside a folder" });
    upd_props["parent"] = json!({ "description": "move into this folder (name/path/index, on top unless move_to), or null to move out to the top level (just above the folder it was in)" });
    upd_props["collapsed"] = json!({ "type": "boolean", "description": "folders: collapse in the layer panel" });
    let mut paint_props = camera.clone();
    for (k, v) in [
        ("points", json!({ "type": "array", "items": { "type": "array", "items": { "type": "number" } }, "description": "stroke path in viewport coords 0..1, [[x,y],...], y down" })),
        ("material", json!({ "type": "string" })),
        ("size", json!({ "type": "number", "description": "brush diameter in pixels of the width x height view (default 40)" })),
        ("opacity", json!({ "type": "number" })), ("hardness", json!({ "type": "number" })),
        ("height", json!({ "type": "number", "description": "paint height too (-1..1)" })),
        ("channels", json!({ "type": "array", "items": { "type": "string" } })),
        ("layer", json!({ "description": "target layer (default: top paint layer)" })),
        ("mask", json!({ "type": "boolean", "description": "paint the layer's mask instead" })),
        ("mask_value", json!({ "type": "string", "enum": ["white", "black"] })),
        ("erase", json!({ "type": "boolean" })),
        ("values", brush_values.clone()),
    ] {
        paint_props[k] = v;
    }
    let mut render_props = camera;
    render_props["view"] = json!({ "type": "string", "description": "material (default), base color, roughness, metallic, height, normal, ambient occlusion, curvature, world normal, uv checker, emission, opacity, transmission" });
    render_props["path"] = json!({ "type": "string", "description": "where to save the PNG (default: temp)" });
    render_props["exposure"] = json!({ "type": "number" });
    render_props["background"] = json!({ "type": "boolean" });
    // lighting / post (persist across renders until changed)
    render_props["lighting"] = json!({ "type": "string", "enum": ["studio", "night", "overcast"], "description": "built-in lighting: studio (neutral softboxes), night (dark blue city night, cyan + magenta neon rim lights, sodium lamp), overcast (soft daylight)" });
    render_props["hdri"] = json!({ "type": "string", "description": "light with an equirectangular .hdr / .exr instead (overrides lighting)" });
    render_props["env_rotation"] = json!({ "type": "number", "description": "rotate the lighting around the vertical axis, degrees" });
    render_props["bloom"] = json!({ "description": "glow from emissive / HDR highlights: true | false | {threshold (default 1), intensity (0.5), radius (0..1, 0.65)}", "anyOf": [{ "type": "boolean" }, { "type": "object" }] });
    let mut sheet_props = render_props.clone();
    render_props["views"] = json!({ "description": "contact sheet of named views in one PNG: [\"front\",\"back\",\"left\",\"right\",\"top\",\"bottom\"] or \"all\" (width/height are then per tile, default 384)", "anyOf": [{ "type": "array", "items": { "type": "string" } }, { "type": "string" }] });
    render_props["columns"] = json!({ "type": "integer", "description": "with views: tiles per row" });
    sheet_props["frames"] = json!({ "type": "integer", "description": "number of views around the model (default 8)" });
    sheet_props["start_yaw"] = json!({ "type": "number", "description": "yaw of the first frame, degrees (default 0 = front)" });
    sheet_props["columns"] = json!({ "type": "integer", "description": "tiles per row (default 4)" });
    sheet_props["width"] = json!({ "type": "integer", "description": "tile width (default 384)" });
    sheet_props["height"] = json!({ "type": "integer", "description": "tile height (default 384)" });
    let t =|name: &str, desc: &str, props: Value, req: &[&str]| json!({ "name": name, "description": desc, "inputSchema": { "type": "object", "properties": props, "required": req } });
    json!([
        t("new_project", "Start a project from a mesh (.glb/.gltf/.obj with UVs). Bakes AO + curvature. Optionally starts from a smart material or a base material; a paint layer goes on top.",
          json!({ "mesh": { "type": "string" }, "resolution": { "type": "integer", "enum": [512, 1024, 2048, 4096] }, "smart_material": { "type": "string" }, "material": { "type": "string" } }), &["mesh"]),
        t("open_project", "Open a .pigment project folder.", json!({ "path": { "type": "string" } }), &["path"]),
        t("save_project", "Save the project folder (git-friendly).", json!({ "path": { "type": "string" } }), &[]),
        t("list_library", "Material presets, smart materials, generators, blend modes, export presets, views.", json!({}), &[]),
        t("list_layers", "The layer stack, bottom to top. With folders each entry also has id, depth, parent (index of its folder), path; `tree: true` nests folder contents under `layers`.",
          json!({ "tree": { "type": "boolean" } }), &[]),
        t("add_smart_material", "Add a multi-layer smart material (e.g. 'Rusty steel', 'Hazard stripes', 'Tech panels', 'Worn olive drab metal').", json!({ "name": { "type": "string" } }), &["name"]),
        t("add_layer", "Add a fill or paint layer, optionally with a material, tiling images (`image`: brick, concrete... UV or triplanar) and a generator mask.", add_props, &[]),
        t("update_layer", "Change a layer: material, values, image fill, opacity, visibility, channels, blend modes, mask/generator, position.", upd_props, &["layer"]),
        t("delete_layer", "Remove a layer (a folder goes with its contents).", json!({ "layer": {} }), &["layer"]),
        t("save_smart_material", "Save a folder (or fill layer) as a reusable .pigsmart smart material. Part-agnostic: generator masks, fills, blend modes and opacities are kept; part selections and painted pixels are dropped (see `warnings`).",
          json!({ "layer": { "description": "folder name, path or index" }, "path": { "type": "string", "description": "file to write (.pigsmart added if no extension)" }, "name": { "type": "string" } }), &["layer", "path"]),
        t("apply_smart_material", "Instance a .pigsmart smart material into this project as a folder (below the top paint layer, or inside `parent`). `parts` limits the whole material to those mesh parts through the folder's mask.",
          json!({ "path": { "type": "string" }, "parts": { "type": "array", "items": { "type": "integer" } }, "parent": { "description": "folder to put it in" },
                  "name": { "type": "string" }, "opacity": { "type": "number" }, "visible": { "type": "boolean" }, "blend": { "type": "object" }, "channels": { "type": "object" } }), &["path"]),
        t("list_parts", "The mesh's parts (connected pieces: body, glass panes, buttons...) with id, triangle count, centre and size. Use ids in a mask's `parts`.", json!({}), &[]),
        t("pick_parts", "Which parts are under viewport points [[x,y],...] (0..1) for a camera view (yaw/pitch/zoom). Render the same view first to choose points.",
          json!({ "points": { "type": "array" }, "yaw": { "type": "number" }, "pitch": { "type": "number" }, "zoom": { "type": "number" }, "width": { "type": "integer" }, "height": { "type": "integer" } }), &["points"]),
        t("bake", "Re-bake AO and curvature.", json!({ "ao_samples": { "type": "integer" }, "ao_distance": { "type": "number" }, "curvature_radius": { "type": "number" }, "curvature_strength": { "type": "number" } }), &[]),
        t("paint_stroke", "Paint a brush stroke projected from a camera view onto the model.", paint_props, &["points"]),
        t("project_decal", "Project an image (PNG with alpha: sign, logo, label, graffiti) onto the model from a camera view, like a sticker. Colour comes from the image times `tint`; optional emission (glowing neon signs) and height. Lands on the top paint layer unless `layer` is given.",
          json!({ "image": { "type": "string" }, "rect": { "type": "array", "items": { "type": "number" }, "description": "[x0, y0, x1, y1] viewport area in 0..1 (y down)" },
                  "part": { "type": "integer", "description": "instead of rect + camera: put the image on this mesh part's outward face (see list_parts)" },
                  "fit": { "type": "string", "enum": ["contain", "fill"], "description": "with `part`: keep the image's aspect (contain, default) or stretch (fill)" },
                  "margin": { "type": "number", "description": "with `part`: border as a fraction (default 0.05)" },
                  "box": { "type": "object", "description": "instead of rect/part: a world-space box {min: [x,y,z], max: [x,y,z]} or {center, size}; the image goes on the surface seen through its broad face (for areas of big walls)" },
                  "facing": { "type": "string", "enum": ["+x", "-x", "+y", "-y", "+z", "-z"], "description": "with part/box: look at this side (default: the thinnest axis, away from the model centre)" },
                  "yaw": { "type": "number" }, "pitch": { "type": "number" }, "zoom": { "type": "number" },
                  "tint": { "type": "array", "items": { "type": "number" } }, "material": { "type": "string", "description": "preset for roughness/metallic (default plain paint)" },
                  "emissive_strength": { "type": "number" }, "height": { "type": "number" }, "opacity": { "type": "number" },
                  "layer": {}, "mask": { "type": "boolean" }, "alpha_from_luminance": { "type": "boolean" }, "values": brush_values,
                  "channels": { "type": "array", "items": { "type": "string" }, "description": "channels to paint (e.g. [\"opacity\"] with values {opacity: 0} punches holes in the image's shape)" },
                  "name": { "type": "string", "description": "decal name for export_variants (default: image file stem)" },
                  "variant": { "type": "string", "description": "variant group tag" },
                  "enabled": { "type": "boolean", "description": "false = record it for variants but don't paint it in the authored look" } }), &["image"]),
        t("render", "Render the model with its current material (PBR image-based lighting, bloom, ACES). Choose lighting (studio / night / overcast or an hdri), exposure and bloom. With `views` it returns one contact sheet of front/back/left/right/top views. Returns the image.", render_props, &[]),
        t("render_turntable", "Render `frames` views evenly around the model (at `pitch`) as one labelled contact-sheet PNG: see the whole asset in one call. Takes the same lighting / bloom / view args as render.", sheet_props, &[]),
        t("export_lighting", "Write a built-in lighting preset as an equirectangular .hdr (e.g. to light a Blender world exactly like Pigment's viewport).",
          json!({ "lighting": { "type": "string", "enum": ["studio", "night", "overcast"] }, "path": { "type": "string" }, "width": { "type": "integer", "description": "default 2048" } }), &["path"]),
        t("export_textures", "Export PNG texture maps. Presets: unreal, unity, godot, separate (glTF/Blender: BaseColor, Roughness, Metallic, AO, Normal_OpenGL, Height, Emissive, plus Opacity / Transmission when the material has any). unreal/unity/godot put opacity in the base colour's alpha (RGBA) when it isn't solid.",
          json!({ "dir": { "type": "string" }, "preset": { "type": "string" }, "name": { "type": "string" } }), &["dir"]),
        t("export_variants", "Export N texture sets from this project without re-running the script: one folder per variant, <dir>/<name>__<variant>/<name>_<map>.png. Each variant starts from the authored stack, sets `seed` (random part subsets such as lit windows, and generator noise), switches off `disable` then on `enable` (layer names, decal names, variant groups, or \"*\" = everything tagged), and swaps decal images (decals on changed layers are replayed). Definitions are stored in the project (save_project to keep them); omit `variants` to reuse the stored ones.",
          json!({ "dir": { "type": "string" }, "name": { "type": "string", "description": "file/folder name (default: mesh name)" },
                  "preset": { "type": "string", "description": "export preset (default separate)" },
                  "variants": { "type": "array", "items": { "type": "object", "properties": {
                      "name": { "type": "string" }, "seed": { "type": "integer" },
                      "enable": { "type": "array", "items": { "type": "string" } }, "disable": { "type": "array", "items": { "type": "string" } },
                      "swaps": { "type": "object", "description": "decal / group / layer name -> image path, or {image, tint, emissive_strength, opacity, ...}" } }, "required": ["name"] } },
                  "only": { "type": "array", "items": { "type": "string" }, "description": "export just these variants" },
                  "folder": { "type": "string", "description": "folder pattern (default \"{name}__{variant}\")" },
                  "preview": { "type": "object", "description": "render args (yaw, pitch, width, height, exposure, dir): also save a preview PNG per variant to <dir>/<name>__<variant>.png" },
                  "dry_run": { "type": "boolean", "description": "validate + store, report what each variant shows, export nothing" } }), &[]),
        t("undo", "Undo the last action.", json!({}), &[]),
        t("redo", "Redo.", json!({}), &[]),
    ])
}

/// Run one tool. Returns MCP `content` items.
fn call(session: &mut Option<Session>, name: &str, args: &Value) -> Result<Vec<Value>, String> {
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
        "list_parts" => text(s.list_parts()),
        "pick_parts" => text(s.pick_parts(args)?),
        "add_smart_material" => text(s.add_smart_material(args)?),
        "add_layer" => text(s.add_layer(args)?),
        "update_layer" => text(s.update_layer(args)?),
        "delete_layer" => text(s.delete_layer(args)?),
        "bake" => text(s.bake(args)?),
        "paint_stroke" => text(s.paint_stroke(args)?),
        "project_decal" => text(s.project_decal(args)?),
        "export_textures" => text(s.export_textures(args)?),
        "export_variants" => text(s.export_variants(args)?),
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

fn main() {
    // logs go to stderr; stdout is the protocol
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("warn,wgpu_hal=error")).target(env_logger::Target::Stderr).init();
    let mut session: Option<Session> = None;
    let args: Vec<String> = std::env::args().collect();
    if let Some(i) = args.iter().position(|a| a == "--script") {
        // scripted mode: {"tool": "...", "args": {...}} per line; prints results
        let path = args.get(i + 1).expect("--script <file.jsonl>");
        let text = std::fs::read_to_string(path).expect("read script");
        let mut failed = false;
        for (n, line) in text.lines().enumerate().filter(|(_, l)| !l.trim().is_empty() && !l.trim_start().starts_with("//")) {
            let v: Value = serde_json::from_str(line).unwrap_or_else(|e| panic!("line {}: {e}", n + 1));
            let tool = v["tool"].as_str().unwrap_or("");
            match call(&mut session, tool, &v["args"]) {
                Ok(content) => {
                    for c in content {
                        if c["type"] == "text" {
                            println!("[{tool}] {}", c["text"].as_str().unwrap_or(""));
                        }
                    }
                }
                Err(e) => {
                    eprintln!("[{tool}] ERROR: {e}");
                    failed = true;
                    break;
                }
            }
        }
        std::process::exit(if failed { 1 } else { 0 });
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
