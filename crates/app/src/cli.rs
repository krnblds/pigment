//! Agent CLI. JSON on stdout, logs on stderr; all calls validate before execution.
use crate::{app::automation::Session, mcp};
use anyhow::{bail, Context, Result};
use pigment_core::{
    diagnostics,
    recipe::{Call, Recipe},
};
use serde_json::{json, Map, Value};
use std::{io::Read, path::Path};

const HELP: &str = "Pigment agent CLI (JSON output)\n\
  pigment tools [NAME]\n\
  pigment inspect PATH\n\
  pigment doctor [--project PATH] [--export-dir DIR] [--no-gpu]\n\
  pigment validate FILE|- [--params JSON] [--seed N]\n\
  pigment run FILE|- [--params JSON] [--seed N] [--keep-going] [--feedback DIR]\n\
  pigment feedback PROJECT DIR\n\
  pigment verify-export DIR [--target separate|blender|godot|unity|unreal] [--blender EXE]\n\
  pigment recover PROJECT\n\
Scripts are JSONL; recipes are versioned JSON objects with calls and parameters.\n\
--json is accepted on every command. Exit codes: 0 success, 1 check/execution\n\
failure, 2 input/usage error. With no command (or a mesh/project path), open GUI.";

#[derive(Default)]
struct Options {
    positional: Vec<String>,
    values: Map<String, Value>,
    flags: Vec<String>,
}
impl Options {
    fn parse(args: &[String], values: &[&str], flags: &[&str]) -> Result<Self> {
        let mut out = Self::default();
        let mut i = 0;
        while i < args.len() {
            let a = &args[i];
            if a == "--json" {
                i += 1;
                continue;
            }
            if values.contains(&a.as_str()) {
                i += 1;
                let v = args
                    .get(i)
                    .filter(|v| !v.starts_with("--"))
                    .with_context(|| format!("{a} needs a value"))?;
                if out.values.insert(a.clone(), json!(v)).is_some() {
                    bail!("duplicate option {a}");
                }
            } else if flags.contains(&a.as_str()) {
                out.flags.push(a.clone());
            } else if a.starts_with("--") {
                bail!("unknown option {a}");
            } else {
                out.positional.push(a.clone());
            }
            i += 1;
        }
        Ok(out)
    }
    fn value(&self, key: &str) -> Option<&str> {
        self.values.get(key).and_then(Value::as_str)
    }
    fn flag(&self, key: &str) -> bool {
        self.flags.iter().any(|s| s == key)
    }
    fn count(&self, count: usize) -> Result<()> {
        if self.positional.len() != count {
            bail!("expected {count} positional arguments; see pigment --help");
        }
        Ok(())
    }
}

pub fn dispatch(args: Vec<String>) -> Option<i32> {
    let command = args.first()?.as_str();
    if matches!(command, "--help" | "-h" | "help") {
        println!("{HELP}");
        return Some(0);
    }
    if matches!(command, "--version" | "-V") {
        println!("{}", json!({"version":env!("CARGO_PKG_VERSION")}));
        return Some(0);
    }
    if ![
        "tools",
        "inspect",
        "doctor",
        "validate",
        "run",
        "feedback",
        "verify-export",
        "recover",
    ]
    .contains(&command)
    {
        if command.starts_with('-') && command != "--design-gallery" {
            println!(
                "{}",
                json!({"ok":false,"error":format!("unknown option {command}")})
            );
            return Some(2);
        }
        // Preserve desktop file-opening, but catch misspelled agent commands.
        if Path::new(command).exists()
            || command.contains(['/', '\\', '.'])
            || command == "--design-gallery"
        {
            return None;
        }
        println!(
            "{}",
            json!({"ok":false,"error":format!("unknown command {command}; see pigment --help")})
        );
        return Some(2);
    }
    let result = execute(command, &args[1..]);
    Some(match result {
        Ok((value, code)) => {
            println!("{value}");
            code
        }
        Err(e) => {
            println!("{}", json!({"ok":false,"error":format!("{e:#}")}));
            2
        }
    })
}

fn read_input(path: &str) -> Result<String> {
    if path == "-" {
        let mut text = String::new();
        std::io::stdin().read_to_string(&mut text)?;
        Ok(text)
    } else {
        std::fs::read_to_string(path).with_context(|| format!("reading {path}"))
    }
}

fn calls(text: &str, params: Map<String, Value>, seed: Option<u64>) -> Result<Vec<Call>> {
    let recipe = serde_json::from_str::<Value>(text)
        .ok()
        .is_some_and(|v| v.get("version").is_some() || v.get("calls").is_some());
    let mut effective_seed = seed;
    let mut calls = if recipe {
        let recipe: Recipe = serde_json::from_str(text)?;
        effective_seed = Some(seed.unwrap_or(recipe.seed));
        recipe.expand(params, seed)?
    } else {
        if !params.is_empty() {
            bail!("--params requires a recipe");
        }
        pigment_core::recipe::parse_jsonl(text)?
    };
    let schemas = mcp::tools();
    for c in &mut calls {
        if let Some(seed) = effective_seed {
            if schemas.as_array().unwrap().iter().any(|s| {
                s["name"] == c.tool && s["inputSchema"]["properties"].get("seed").is_some()
            }) {
                let args = c
                    .args
                    .as_object_mut()
                    .context("tool args must be an object")?;
                args.entry("seed").or_insert(json!(seed));
            }
        }
        mcp::check_args(&c.tool, &c.args)
            .map_err(anyhow::Error::msg)
            .with_context(|| format!("tool {}", c.tool))?;
        if c.tool == "batch" {
            for nested in c.args["calls"].as_array().context("batch calls missing")? {
                let name = nested["tool"].as_str().context("batch tool missing")?;
                if name == "batch" {
                    bail!("nested batches are unsupported");
                }
                mcp::check_args(name, nested.get("args").unwrap_or(&json!({})))
                    .map_err(anyhow::Error::msg)?;
            }
        }
    }
    if calls.is_empty() {
        bail!("script contains no calls");
    }
    Ok(calls)
}

fn execute(command: &str, args: &[String]) -> Result<(Value, i32)> {
    match command {
        "tools" => {
            let o = Options::parse(args, &[], &[])?;
            if o.positional.len() > 1 {
                bail!("tools accepts at most one name");
            }
            let tools = mcp::tools();
            let out = if let Some(name) = o.positional.first() {
                tools
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|t| t["name"] == *name)
                    .cloned()
                    .context("unknown tool")?
            } else {
                tools
            };
            Ok((out, 0))
        }
        "inspect" | "recover" | "verify-export" => {
            let o = Options::parse(
                args,
                if command == "verify-export" {
                    &["--target", "--blender"]
                } else {
                    &[]
                },
                &[],
            )?;
            o.count(1)?;
            let path = Path::new(&o.positional[0]);
            if let Some(target) = o.value("--target") {
                if !["separate", "blender", "godot", "unity", "unreal"].contains(&target) {
                    bail!("unknown target {target}");
                }
            }
            let result = match command {
                "inspect" => diagnostics::inspect(path),
                "recover" => pigment_core::transaction::recover(path)
                    .map(|recovered| json!({"ok":true,"recovered":recovered,"path":path})),
                _ => diagnostics::verify_export(path, o.value("--target")).and_then(|mut value| {
                    if let Some(exe) = o.value("--blender") {
                        blender_import(exe, path)?;
                        value["engine_import_tested"] = json!(true);
                        value["import_engine"] = json!("blender");
                    }
                    Ok(value)
                }),
            };
            Ok(report(result))
        }
        "doctor" => {
            let o = Options::parse(args, &["--project", "--export-dir"], &["--no-gpu"])?;
            o.count(0)?;
            Ok(doctor(&o))
        }
        "run" | "validate" => {
            let o = Options::parse(
                args,
                &["--params", "--seed", "--feedback"],
                &["--keep-going"],
            )?;
            o.count(1)?;
            let params: Map<String, Value> =
                serde_json::from_str(o.value("--params").unwrap_or("{}"))?;
            let seed = o.value("--seed").map(str::parse::<u64>).transpose()?;
            let calls = calls(&read_input(&o.positional[0])?, params, seed)?;
            if command == "validate" {
                return Ok((json!({"ok":true,"calls":calls}), 0));
            }
            let mut session = None;
            let mut results = Vec::new();
            let mut failed = false;
            for (index, c) in calls.iter().enumerate() {
                let start = std::time::Instant::now();
                let result = mcp::call(&mut session, &c.tool, &c.args);
                let mut entry =
                    json!({"index":index,"tool":c.tool,"ms":start.elapsed().as_secs_f64()*1000.0});
                match result {
                    Ok(content) => {
                        entry["ok"] = json!(true);
                        entry["result"] = mcp::content_json(&content);
                    }
                    Err(e) => {
                        entry["ok"] = json!(false);
                        entry["error"] = json!(e);
                        failed = true;
                    }
                }
                results.push(entry);
                if failed && !o.flag("--keep-going") {
                    break;
                }
            }
            let feedback = if let Some(dir) = o.value("--feedback") {
                match session
                    .as_mut()
                    .context("no GPU session for feedback")
                    .and_then(|s| feedback(s, Path::new(dir)))
                {
                    Ok(v) => v,
                    Err(e) => {
                        failed = true;
                        json!({"ok":false,"error":format!("{e:#}")})
                    }
                }
            } else {
                Value::Null
            };
            Ok((
                json!({"ok":!failed,"skipped":calls.len()-results.len(),"results":results,"feedback":feedback}),
                i32::from(failed),
            ))
        }
        "feedback" => {
            let o = Options::parse(args, &[], &[])?;
            o.count(2)?;
            let result = (|| {
                let mut session = Session::new().map_err(anyhow::Error::msg)?;
                session
                    .open_project(&json!({"path":o.positional[0]}))
                    .map_err(anyhow::Error::msg)?;
                feedback(&mut session, Path::new(&o.positional[1]))
            })();
            Ok(report(result))
        }
        _ => unreachable!(),
    }
}

fn report(result: Result<Value>) -> (Value, i32) {
    match result {
        Ok(v) => (v, 0),
        Err(e) => (json!({"ok":false,"error":format!("{e:#}")}), 1),
    }
}

pub(crate) fn doctor_args(args: &Value) -> Value {
    let mut o = Options::default();
    for (key, option) in [("project", "--project"), ("export_dir", "--export-dir")] {
        if let Some(value) = args.get(key) {
            o.values.insert(option.into(), value.clone());
        }
    }
    if args["no_gpu"] == true {
        o.flags.push("--no-gpu".into());
    }
    doctor(&o).0
}

fn doctor(o: &Options) -> (Value, i32) {
    let mut checks = Vec::new();
    if !o.flag("--no-gpu") {
        let gpu = crate::app::automation::headless_render_state();
        checks.push(match gpu { Some(rs) => json!({"check":"gpu","ok":true,"adapter":rs.adapter.get_info().name}), None => json!({"check":"gpu","ok":false,"error":"No usable GPU adapter/device; CPU validation and inspection still work"}) });
    }
    for (id, _) in pigment_core::envmath::SKIES {
        let path = pigment_core::envmath::sky_path(id);
        checks.push(json!({"check":"sky","name":id,"ok":path.is_some(),"severity":"warning","path":path,"hint":"Provide baked HDR assets in PIGMENT_SKY_DIR to use this lighting preset"}));
    }
    if let Some(path) = o.value("--project") {
        let (report, code) = report(diagnostics::inspect(Path::new(path)));
        checks.push(json!({"check":"project","ok":code==0,"report":report}));
    }
    if let Some(path) = o.value("--export-dir") {
        let result = writable_destination(Path::new(path));
        checks.push(json!({"check":"export_destination","ok":result.is_ok(),"error":result.err().map(|e|format!("{e:#}"))}));
    }
    let ok = checks
        .iter()
        .all(|c| c["ok"] == true || c["severity"] == "warning");
    (
        json!({"ok":ok,"checks":checks,"gpu_checked":!o.flag("--no-gpu")}),
        i32::from(!ok),
    )
}

fn writable_destination(path: &Path) -> Result<()> {
    let absolute = std::path::absolute(path)?;
    let parent = absolute
        .ancestors()
        .find(|p| p.exists())
        .context("no existing destination ancestor")?;
    if !parent.is_dir() {
        bail!("destination or its ancestor is a file");
    }
    let probe = parent.join(format!(
        ".pigment-write-probe-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_nanos()
    ));
    let f = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&probe)?;
    drop(f);
    std::fs::remove_file(probe)?;
    Ok(())
}

fn blender_import(exe: &str, dir: &Path) -> Result<()> {
    let temp = std::env::temp_dir().join(format!(
        "pigment-import-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_nanos()
    ));
    std::fs::create_dir(&temp)?;
    let result = (|| {
        let script = temp.join("verify.py");
        let bridge = temp.join("bridge.py");
        std::fs::write(
            &script,
            include_str!("../../../tools/verify_blender_export.py"),
        )?;
        std::fs::write(
            &bridge,
            include_str!("../../../tools/blender_addon/pigment_bridge/core.py"),
        )?;
        let output = std::process::Command::new(exe)
            .args([
                "--background",
                "--factory-startup",
                "--python-exit-code",
                "1",
                "--python",
            ])
            .arg(&script)
            .arg("--")
            .arg(std::path::absolute(dir)?)
            .arg(&bridge)
            .output()
            .context("starting Blender import check")?;
        if !output.status.success()
            || !String::from_utf8_lossy(&output.stdout).contains("PIGMENT_IMPORT_OK")
        {
            bail!(
                "Blender import failed: {}\n{}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            );
        }
        Ok(())
    })();
    let _ = std::fs::remove_dir_all(temp);
    result
}

pub(crate) fn feedback(session: &mut Session, dir: &Path) -> Result<Value> {
    std::fs::create_dir_all(dir)?;
    let preview = session
        .render(&json!({"views":"all","width":384,"height":384,"path":dir.join("preview.png")}))
        .map_err(anyhow::Error::msg)?;
    let mut tiles = Vec::new();
    for view in [
        "base color",
        "roughness",
        "metallic",
        "height",
        "normal",
        "emission",
        "opacity",
        "transmission",
        "coat",
        "coat roughness",
        "flake",
    ] {
        let img = session.render(&json!({"view":view,"width":256,"height":256,"yaw":30,"pitch":15,"path":dir.join(format!("{}.png",view.replace(' ',"_")))})).map_err(anyhow::Error::msg)?;
        let rgba = image::load_from_memory(&img.png)?.to_rgba8();
        tiles.push(pigment_core::sheet::Tile {
            w: rgba.width(),
            h: rgba.height(),
            rgba: rgba.into_raw(),
            label: view.to_uppercase(),
        });
    }
    let (rgba, w, h) = pigment_core::sheet::contact_sheet(&tiles, 4);
    let channels = dir.join("channels.png");
    image::save_buffer(&channels, &rgba, w, h, image::ExtendedColorType::Rgba8)?;
    Ok(json!({"ok":true,"preview":preview.path,"channels":channels}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_bad_options_and_prevalidates_entire_script() {
        assert!(Options::parse(&["--typo".into()], &[], &[]).is_err());
        assert!(Options::parse(&["--seed".into()], &["--seed"], &[]).is_err());
        assert!(calls(
            "{\"tool\":\"get_project_info\"}\n{\"tool\":\"not_a_tool\"}",
            Map::new(),
            None
        )
        .is_err());
        assert!(calls(
            "{\"tool\":\"batch\",\"args\":{\"calls\":[{\"tool\":\"not_a_tool\"}]}}",
            Map::new(),
            None
        )
        .is_err());
    }
    #[test]
    fn tools_and_validate_do_not_need_gpu() {
        assert_eq!(execute("tools", &[]).unwrap().1, 0);
        assert_eq!(
            calls("{\"tool\":\"get_project_info\"}", Map::new(), None)
                .unwrap()
                .len(),
            1
        );
    }
}
