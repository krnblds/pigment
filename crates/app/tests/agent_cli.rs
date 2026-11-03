use serde_json::{json, Value};
use std::io::Write;
use std::process::{Command, Stdio};

fn invoke(args: &[&str], input: &str) -> (i32, Value) {
    let mut child = Command::new(env!("CARGO_BIN_EXE_pigment"))
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(input.as_bytes())
        .unwrap();
    let out = child.wait_with_output().unwrap();
    let value = serde_json::from_slice(&out.stdout)
        .unwrap_or_else(|e| panic!("{e}: {}", String::from_utf8_lossy(&out.stdout)));
    (out.status.code().unwrap(), value)
}

#[test]
fn stdin_recipes_preserve_types_and_validate_before_execution() {
    let recipe = json!({"version":1,"parameters":{"resolution":512},"seed":7,"calls":[{"tool":"new_project","args":{"tile":{"size_m":2},"resolution":{"$param":"resolution"}}},{"tool":"add_bark","args":{"name":"Seeded bark"}}]});
    let (code, out) = invoke(
        &["validate", "-", "--params", "{\"resolution\":1024}"],
        &recipe.to_string(),
    );
    assert_eq!(code, 0);
    assert_eq!(out["calls"][0]["args"]["resolution"], 1024);
    assert_eq!(out["calls"][1]["args"]["seed"], 7);
    let (code, out) = invoke(
        &["run", "-"],
        "{\"tool\":\"new_project\",\"args\":{\"mesh\":\"missing.obj\"}}\n{\"tool\":\"typo\"}",
    );
    assert_eq!(code, 2);
    assert!(out["error"].as_str().unwrap().contains("typo"));
}

#[test]
fn cpu_tools_and_diagnostics_have_machine_readable_exit_status() {
    let (code, out) = invoke(&["tools", "verify_export"], "");
    assert_eq!(code, 0);
    assert_eq!(out["name"], "verify_export");
    assert_eq!(invoke(&["doctor", "--no-gpu"], "").0, 0);
    assert_eq!(
        invoke(&["verify-export", "/nonexistent/pigment-test"], "").0,
        1
    );
    assert_eq!(invoke(&["validate", "-"], "{bad").0, 2);
}

#[test]
#[ignore = "requires Blender; set PIGMENT_TEST_BLENDER to its executable"]
fn real_blender_import_of_exported_material_and_mesh() {
    use pigment_core::{bridge, export, Mesh};
    let blender = std::env::var("PIGMENT_TEST_BLENDER").expect("set PIGMENT_TEST_BLENDER");
    let dir = std::env::temp_dir().join(format!("pigment-cli-blender-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let m = export::MaterialImages {
        size: 2,
        color: vec![255; 16],
        orm: vec![128; 16],
        normal: vec![128; 16],
        height: vec![32768; 4],
        emissive: vec![0; 16],
        emissive_scale: 1.0,
        coat: Vec::new(),
    };
    let preset = export::preset("separate").unwrap();
    export::export(&dir, "Test", &preset, &m).unwrap();
    let mesh_path = dir.join("mesh.glb");
    bridge::export_mesh(&Mesh::torus(1.0, 0.25, 12, 8), &mesh_path).unwrap();
    bridge::write_sidecar(
        &dir,
        "Test",
        &preset,
        &m,
        &bridge::SidecarExtra {
            mesh: Some(mesh_path),
            ..Default::default()
        },
    )
    .unwrap();
    let (code, out) = invoke(
        &[
            "verify-export",
            dir.to_str().unwrap(),
            "--target",
            "blender",
            "--blender",
            &blender,
        ],
        "",
    );
    assert_eq!(code, 0, "{out}");
    assert_eq!(out["engine_import_tested"], true);
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
#[ignore = "requires a usable GPU adapter"]
fn gpu_recipe_save_reopen_feedback_and_export() {
    let dir = std::env::temp_dir().join(format!("pigment-cli-gpu-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let project = dir.join("tile.pigment");
    let export = dir.join("export");
    let feedback = dir.join("review");
    let recipe = json!({"version":1,"seed":17,"calls":[
        {"tool":"new_project","args":{"tile":{"size_m":2},"resolution":512}},
        {"tool":"add_bark","args":{"name":"Bark"}},
        {"tool":"save_project","args":{"path":project}},
        {"tool":"open_project","args":{"path":project}},
        {"tool":"export_textures","args":{"dir":export,"preset":"separate"}},
        {"tool":"verify_export","args":{"dir":export,"target":"separate"}}
    ]});
    let (code, out) = invoke(
        &["run", "-", "--feedback", feedback.to_str().unwrap()],
        &recipe.to_string(),
    );
    assert_eq!(code, 0, "{out}");
    assert!(project.join("project.json").exists());
    for name in ["preview.png", "channels.png"] {
        let image = image::open(feedback.join(name)).unwrap();
        assert!(image.width() > 256 && image.height() > 256);
    }
    std::fs::remove_dir_all(dir).unwrap();
}
