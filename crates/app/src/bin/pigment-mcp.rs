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

use base64::Engine;
use pigment_engine::app::automation::Session;
use serde_json::{json, Value};
use std::io::{BufRead, Write};

const PROTOCOL: &str = "2025-06-18";

fn tools() -> Value {
    let layer_fields = json!({
        "name": { "type": "string" },
        "material": { "type": "string", "description": "Material preset name (see list_library)" },
        "values": { "type": "object", "description": "Override fill values", "properties": {
            "base_color": { "type": "array", "items": { "type": "number" }, "description": "sRGB 0..1" },
            "roughness": { "type": "number" }, "metallic": { "type": "number" }, "height": { "type": "number", "description": "-1..1, negative = recessed" } } },
        "opacity": { "type": "number" },
        "visible": { "type": "boolean" },
        "channels": { "type": "object", "description": "e.g. {\"height\": false, \"roughness\": true}" },
        "blend": { "type": "object", "description": "per channel, e.g. {\"base_color\": \"multiply\", \"height\": \"add\"}" },
        "mask": { "description": "\"white\" | \"black\" | null (remove) | {generator: edge_wear|dirt|grunge|streaks|stripes|spots|scratches|panel_lines|gradient, amount, softness, scale, breakup, seed, ao_influence, curvature_weight, invert, parts: [part ids from list_parts / pick_parts: limit the layer to those mesh pieces], effects: [{generator, op: multiply|add|subtract|max|min, amount, scale, breakup, ...}] (max 2)}" }
    });
    let camera = json!({
        "yaw": { "type": "number", "description": "degrees around the model (default 35)" },
        "pitch": { "type": "number", "description": "degrees above (default 20)" },
        "zoom": { "type": "number", "description": "1 = framed, 2 = twice as close" },
        "width": { "type": "integer" }, "height": { "type": "integer" }
    });
    let mut add_props = layer_fields.clone();
    add_props["kind"] = json!({ "type": "string", "enum": ["fill", "paint"] });
    add_props["index"] = json!({ "type": "integer", "description": "stack position (0 = bottom); default: below the top paint layer" });
    let mut upd_props = layer_fields;
    upd_props["layer"] = json!({ "description": "layer name or index (0 = bottom)" });
    upd_props["move_to"] = json!({ "type": "integer" });
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
    ] {
        paint_props[k] = v;
    }
    let mut render_props = camera;
    render_props["view"] = json!({ "type": "string", "description": "material (default), base color, roughness, metallic, height, normal, ambient occlusion, curvature, world normal, uv checker" });
    render_props["path"] = json!({ "type": "string", "description": "where to save the PNG (default: temp)" });
    render_props["exposure"] = json!({ "type": "number" });
    render_props["background"] = json!({ "type": "boolean" });
    let t = |name: &str, desc: &str, props: Value, req: &[&str]| json!({ "name": name, "description": desc, "inputSchema": { "type": "object", "properties": props, "required": req } });
    json!([
        t("new_project", "Start a project from a mesh (.glb/.gltf/.obj with UVs). Bakes AO + curvature. Optionally starts from a smart material or a base material; a paint layer goes on top.",
          json!({ "mesh": { "type": "string" }, "resolution": { "type": "integer", "enum": [512, 1024, 2048, 4096] }, "smart_material": { "type": "string" }, "material": { "type": "string" } }), &["mesh"]),
        t("open_project", "Open a .pigment project folder.", json!({ "path": { "type": "string" } }), &["path"]),
        t("save_project", "Save the project folder (git-friendly).", json!({ "path": { "type": "string" } }), &[]),
        t("list_library", "Material presets, smart materials, generators, blend modes, export presets, views.", json!({}), &[]),
        t("list_layers", "The layer stack, bottom to top.", json!({}), &[]),
        t("add_smart_material", "Add a multi-layer smart material (e.g. 'Rusty steel', 'Hazard stripes', 'Tech panels', 'Worn olive drab metal').", json!({ "name": { "type": "string" } }), &["name"]),
        t("add_layer", "Add a fill or paint layer, optionally with a material and a generator mask.", add_props, &[]),
        t("update_layer", "Change a layer: material, values, opacity, visibility, channels, blend modes, mask/generator, position.", upd_props, &["layer"]),
        t("delete_layer", "Remove a layer.", json!({ "layer": {} }), &["layer"]),
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
                  "yaw": { "type": "number" }, "pitch": { "type": "number" }, "zoom": { "type": "number" },
                  "tint": { "type": "array", "items": { "type": "number" } }, "material": { "type": "string", "description": "preset for roughness/metallic (default plain paint)" },
                  "emissive_strength": { "type": "number" }, "height": { "type": "number" }, "opacity": { "type": "number" },
                  "layer": {}, "mask": { "type": "boolean" }, "alpha_from_luminance": { "type": "boolean" } }), &["image"]),
        t("render", "Render the model with its current material (PBR, studio lighting). Returns the image.", render_props, &[]),
        t("export_textures", "Export PNG texture maps. Presets: unreal, unity, godot, separate (glTF/Blender: BaseColor, Roughness, Metallic, AO, Normal_OpenGL, Height).",
          json!({ "dir": { "type": "string" }, "preset": { "type": "string" }, "name": { "type": "string" } }), &["dir"]),
        t("send_to_blender", "Export everything Blender needs into `dir`: the texture maps (preset, default 'separate'), a material.json sidecar (channels and files, emissive_scale, normal convention, resolution, project path) and the painted mesh with tangents (<name>.glb). The Pigment Bridge add-on (tools/blender_addon/pigment_bridge) links objects to this folder and live-reloads it. For random per-object variants in Blender, export each variant to a folder named <asset>__<variant>.",
          json!({ "dir": { "type": "string" }, "name": { "type": "string", "description": "base file name (default: mesh name)" },
                  "preset": { "type": "string", "description": "export preset (default separate)" },
                  "mesh": { "type": "boolean", "description": "also export the mesh (default true)" },
                  "mesh_format": { "type": "string", "enum": ["glb", "obj"], "description": "glb (default, with tangents) or obj (no tangents)" },
                  "project": { "type": "string", "description": "save the project here first, so the sidecar links to it" } }), &["dir"]),
        t("export_mesh", "Write the loaded mesh exactly as Pigment paints it (world transforms applied, UVs, normals, and in .glb the tangents the normal map was baked with).",
          json!({ "path": { "type": "string", "description": ".glb or .obj (no extension: .glb)" }, "format": { "type": "string", "enum": ["glb", "obj"] } }), &["path"]),
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
        "list_layers" => text(s.layers()),
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
    if let Some(i) = args.iter().position(|a| a == "--export-for-blender") {
        std::process::exit(export_for_blender(&mut session, &args[i + 1..]));
    }
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
