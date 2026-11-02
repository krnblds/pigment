//! MCP: export templates (list_export_templates, save_export_template,
//! export_textures {template}).

use super::*;
use crate::app::templates_app::TemplateScope;
use pigment_core::templates::ExportTemplate;

fn parse_template(v: &Value) -> Res<ExportTemplate> {
    let t: ExportTemplate = serde_json::from_value(v.clone()).map_err(|e| format!("`template`: {e}"))?;
    t.validate()?;
    Ok(t)
}

impl Session {
    pub fn list_export_templates(&self) -> Value {
        Value::Array(
            self.app
                .all_templates()
                .into_iter()
                .map(|(t, s)| {
                    let mut v = serde_json::to_value(&t).unwrap_or(Value::Null);
                    v["scope"] = json!(s.id());
                    v
                })
                .collect(),
        )
    }

    pub fn save_export_template(&mut self, a: &Value) -> Res<Value> {
        let raw = a.get("template").ok_or("missing `template`")?;
        if let Some(id) = raw.get("id").and_then(Value::as_str) {
            if pigment_core::templates::builtin().iter().any(|b| b.id == id) {
                return Err(format!("`{id}` is a built-in template id; pick another"));
            }
        }
        let t = parse_template(raw)?;
        let scope = match s(a, "scope").unwrap_or("project") {
            "project" => TemplateScope::Project,
            "user" => TemplateScope::User,
            x => return Err(format!("`scope` = \"{x}\": project or user")),
        };
        let path = self.app.save_template(t.clone(), scope)?;
        self.settle();
        Ok(json!({ "saved": t.id, "scope": scope.id(), "where": path, "outputs": t.outputs.len() }))
    }

    /// export_textures with `template` (an id or an inline template).
    pub(super) fn export_template(&mut self, a: &Value, dir: &Path, compression: export::Compression) -> Res<Value> {
        let t = match a.get("template") {
            Some(Value::String(id)) => self.app.find_template(id).ok_or_else(|| format!("`template` = \"{id}\": no such template (see list_export_templates)"))?,
            Some(v) => parse_template(v)?,
            None => return Err("missing `template`".into()),
        };
        let name = s(a, "name").map(String::from).unwrap_or_else(|| self.app.mesh.name.clone());
        let files = self.app.export_with_template(&self.rs, dir, &t, &name, compression)?;
        Ok(json!({ "template": t.id, "files": files, "texture_sets": self.app.set_names() }))
    }
}

#[cfg(test)]
mod tests {
    use super::super::gpu_lock;
    use super::*;

    #[test]
    fn export_templates_over_mcp() {
        let _g = gpu_lock();
        let Ok(mut s) = Session::new() else { return };
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        s.new_project(&json!({ "mesh": root.join("assets/ammo_box.glb"), "resolution": 512, "material": "Neon pink" })).unwrap();
        let list = s.list_export_templates();
        for id in ["unreal", "separate", "orm", "unreal_packed", "unity_hdrp", "godot_orm", "gltf", "arnold"] {
            assert!(list.as_array().unwrap().iter().any(|t| t["id"] == id), "{id}");
        }
        let dir = std::env::temp_dir().join(format!("pigment-tpl-{}", std::process::id()));
        // built-in HDRP mask map
        let r = s.export_textures(&json!({ "dir": dir, "template": "unity_hdrp", "name": "box" })).unwrap();
        assert!(r["files"].to_string().contains("box_MaskMap.png"), "{r}");
        // Arnold: EXR with HDR emission (the neon is ~6x)
        let r = s.export_textures(&json!({ "dir": dir, "template": "arnold", "name": "box" })).unwrap();
        let emit = image::open(dir.join("box_emission.exr")).unwrap().to_rgb32f();
        let peak = emit.pixels().map(|p| p.0[0]).fold(0.0f32, f32::max);
        assert!(peak > 2.0, "emission keeps its HDR range in EXR (peak {peak}); {r}");
        // a custom template saved with the project, used by id
        let t = json!({ "id": "my_pack", "label": "test", "outputs": [
            { "pattern": "{name}_RMA16", "channels": ["roughness", "metallic", "ao"], "format": "png", "bit_depth": "u16" },
            { "pattern": "{name}_BC_lin", "channels": ["base_color.r", "base_color.g", "base_color.b", "opacity"], "format": "tga", "bit_depth": "u8", "color_space": "linear" },
            { "pattern": "{name}_H", "channels": ["height"], "format": "exr", "bit_depth": "f32", "padding": "none" } ] });
        s.save_export_template(&json!({ "template": t })).unwrap();
        assert!(s.list_export_templates().to_string().contains("\"my_pack\""));
        assert!(s.save_export_template(&json!({ "template": { "id": "unreal", "outputs": [] } })).is_err());
        let bad = json!({ "template": { "id": "bad", "outputs": [{ "pattern": "x", "channels": ["nope"], "format": "png", "bit_depth": "u8" }] } });
        assert!(s.save_export_template(&bad).unwrap_err().contains("unknown source"));
        let r = s.export_textures(&json!({ "dir": dir, "template": "my_pack", "name": "box" })).unwrap();
        assert_eq!(r["files"].as_array().unwrap().len(), 3, "{r}");
        let rma = image::open(dir.join("box_RMA16.png")).unwrap();
        assert!(matches!(rma.color(), image::ColorType::Rgb16));
        // saved in the project: survives save / reopen
        let proj = dir.join("p.pigment");
        s.save_project(&json!({ "path": proj })).unwrap();
        s.open_project(&json!({ "path": proj })).unwrap();
        assert!(s.app.find_template("my_pack").is_some());
        // inline template
        let inline = json!({ "id": "inline", "outputs": [{ "pattern": "{name}_ao", "channels": ["ao"], "format": "png", "bit_depth": "u8" }] });
        let r = s.export_textures(&json!({ "dir": dir, "name": "inl", "template": inline })).unwrap();
        assert!(r["files"].to_string().contains("inl_ao.png"));
        std::fs::remove_dir_all(dir).ok();
    }
}
