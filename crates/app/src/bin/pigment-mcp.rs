//! Pigment MCP server: drives a headless Pigment session over the Model
//! Context Protocol (JSON-RPC 2.0, one message per line on stdin/stdout).
//!
//!   claude mcp add pigment -- <repo>/target/release/pigment-mcp.exe
//!
//! It can also run a script of tool calls without an MCP client:
//!
//!   pigment-mcp --script calls.jsonl     (one {"tool": ..., "args": {...}} per line)
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
    let layer_fields = json!({
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
        "mask": mask_schema()
    });
    let camera = json!({
        "yaw": { "type": "number", "description": "degrees around the model (default 35)" },
        "pitch": { "type": "number", "description": "degrees above (default 20)" },
        "zoom": { "type": "number", "description": "1 = framed, 2 = twice as close" },
        "width": { "type": "integer" }, "height": { "type": "integer" }
    });
    let mut add_props = layer_fields.clone();
    add_props["kind"] = json!({ "type": "string", "enum": ["fill", "paint"] });
    add_props["index"] = json!({ "type": "integer", "minimum": 0, "description": "stack position (0 = bottom); default: below the top paint layer" });
    let mut upd_props = layer_fields;
    upd_props["layer"] = json!({ "type": ["string", "integer"], "description": "layer name or index (0 = bottom)" });
    upd_props["move_to"] = json!({ "type": "integer", "minimum": 0, "description": "new stack position (0 = bottom)" });
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
    ] {
        paint_props[k] = v;
    }
    let mut render_props = camera.clone();
    render_props["view"] = json!({ "type": "string", "description": "material (default), base color, roughness, metallic, height, normal, ambient occlusion, curvature, world normal, uv checker" });
    render_props["path"] = json!({ "type": "string", "description": "where to save the PNG (default: temp)" });
    render_props["exposure"] = json!({ "type": "number" });
    render_props["background"] = json!({ "type": "boolean" });
    let t = |name: &str, desc: &str, props: Value, req: &[&str]| json!({ "name": name, "description": desc, "inputSchema": { "type": "object", "properties": props, "required": req, "additionalProperties": false } });
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
        t("delete_layer", "Remove a layer.", json!({ "layer": { "type": ["string", "integer"], "description": "layer name or index (0 = bottom)" } }), &["layer"]),
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
        t("project_decal", "Project an image (PNG with alpha: sign, logo, label, graffiti) onto the model from a camera view, like a sticker. Colour comes from the image times `tint`; optional emission (glowing neon signs) and height. Lands on the top paint layer unless `layer` is given.",
          json!({ "image": { "type": "string" }, "rect": { "type": "array", "items": { "type": "number" }, "description": "[x0, y0, x1, y1] viewport area in 0..1 (y down)" },
                  "part": { "type": "integer", "description": "instead of rect + camera: put the image on this mesh part's outward face (see list_parts)" },
                  "fit": { "type": "string", "enum": ["contain", "fill"], "description": "with `part`: keep the image's aspect (contain, default) or stretch (fill)" },
                  "margin": { "type": "number", "description": "with `part`: border as a fraction (default 0.05)" },
                  "yaw": { "type": "number" }, "pitch": { "type": "number" }, "zoom": { "type": "number" }, "width": { "type": "integer" }, "height": { "type": "integer" },
                  "tint": { "type": "array", "items": { "type": "number" }, "description": "multiplies the image colour, sRGB 0..1" }, "material": { "type": "string", "description": "preset for roughness/metallic (default plain paint)" },
                  "channels": { "type": "array", "items": { "type": "string" }, "description": "channels to write (default base_color, roughness, metallic; + emissive / height when set)" },
                  "mask_value": { "type": "string", "enum": ["white", "black"], "description": "with mask: true" },
                  "emissive_strength": { "type": "number" }, "height": { "type": "number" }, "opacity": { "type": "number" },
                  "layer": { "type": ["string", "integer"], "description": "target layer (default: top paint layer)" }, "mask": { "type": "boolean", "description": "project into the layer's mask instead" },
                  "alpha_from_luminance": { "type": "boolean" } }), &["image"]),
        t("render", "Render the model with its current material (PBR, studio lighting). Returns the image.", render_props, &[]),
        t("export_textures", "Export PNG texture maps. Presets: unreal, unity, godot, separate (glTF/Blender: BaseColor, Roughness, Metallic, AO, Normal_OpenGL, Height).",
          json!({ "dir": { "type": "string" }, "preset": { "type": "string", "enum": pigment_core::export::presets().iter().map(|p| p.id).collect::<Vec<_>>(), "description": "default separate" }, "name": { "type": "string", "description": "file name prefix (default: the mesh name)" },
                  "compression": { "type": "string", "enum": ["none", "fastest", "fast", "balanced", "best"], "description": "PNG compression effort (default fast). fastest/none write quickest but bigger files; maps are encoded in parallel either way" } }), &["dir"]),
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
    let gens: Vec<&str> = pigment_core::GeneratorKind::ALL.iter().map(|g| g.id()).collect();
    let mut gen_fields = json!({
        "generator": { "type": "string", "enum": gens, "description": "procedural mask" },
        "amount": { "type": "number" }, "softness": { "type": "number" }, "scale": { "type": "number" }, "breakup": { "type": "number" },
        "seed": { "type": "integer", "minimum": 0 }, "ao_influence": { "type": "number" }, "curvature_weight": { "type": "number" }
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
        "list_layers" => text(s.layers()),
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
