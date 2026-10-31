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
        "mask": { "description": "\"white\" | \"black\" | null (remove) | {generator: edge_wear|dirt|grunge|streaks|stripes|spots|scratches|panel_lines, amount, softness, scale, breakup, seed, ao_influence, curvature_weight, invert}" }
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
        t("bake", "Re-bake AO and curvature.", json!({ "ao_samples": { "type": "integer" }, "ao_distance": { "type": "number" }, "curvature_radius": { "type": "number" }, "curvature_strength": { "type": "number" } }), &[]),
        t("paint_stroke", "Paint a brush stroke projected from a camera view onto the model.", paint_props, &["points"]),
        t("render", "Render the model with its current material (PBR, studio lighting). Returns the image.", render_props, &[]),
        t("export_textures", "Export PNG texture maps. Presets: unreal, unity, godot, separate (glTF/Blender: BaseColor, Roughness, Metallic, AO, Normal_OpenGL, Height).",
          json!({ "dir": { "type": "string" }, "preset": { "type": "string" }, "name": { "type": "string" } }), &["dir"]),
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
        "add_smart_material" => text(s.add_smart_material(args)?),
        "add_layer" => text(s.add_layer(args)?),
        "update_layer" => text(s.update_layer(args)?),
        "delete_layer" => text(s.delete_layer(args)?),
        "bake" => text(s.bake(args)?),
        "paint_stroke" => text(s.paint_stroke(args)?),
        "export_textures" => text(s.export_textures(args)?),
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
