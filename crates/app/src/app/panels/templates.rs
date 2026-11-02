//! Export templates in the Export panel: pick one, export with it, or edit
//! a copy (outputs, file patterns, channel sources, format, bit depth,
//! colour space, padding) and save it to the user prefs or the project.

use super::super::design::{self as ds, font, size, Btn, Icon, IconBtn};
use super::super::templates_app::TemplateScope;
use super::*;
use pigment_core::templates::{BitDepth, ColorSpace, ExportTemplate, FileFormat, Padding, TemplateOutput};
use std::cell::RefCell;

/// Channel sources offered in the editor (any `templates::parse_chan` string works over MCP).
const SOURCES: [&str; 30] = [
    "base_color.r", "base_color.g", "base_color.b", "opacity", "roughness", "1-roughness", "smoothness", "metallic", "ao", "height", "normal.x", "normal.y", "normal.z", "normal_dx.x", "normal_dx.y",
    "normal_dx.z", "emissive.r", "emissive.g", "emissive.b", "transmission", "coat", "coat_roughness", "flake", "const:0", "const:0.5", "const:1", "1-metallic", "1-ao", "1-opacity", "1-height",
];

#[derive(Default)]
struct State {
    /// The template the Export button uses.
    current: String,
    /// The copy being edited.
    draft: Option<ExportTemplate>,
    /// Every template (built-in, user, project), refreshed now and then and after a save.
    cache: Option<(std::time::Instant, Vec<(ExportTemplate, TemplateScope)>)>,
}

thread_local! {
    static STATE: RefCell<State> = RefCell::new(State { current: "separate".into(), draft: None, cache: None });
}

fn output_ui(ui: &mut egui::Ui, o: &mut TemplateOutput, k: usize) -> bool {
    let mut remove = false;
    ds::card(ui, |ui| {
        ui.horizontal(|ui| {
            ui.add(egui::TextEdit::singleline(&mut o.pattern).hint_text("{name}_BaseColor").desired_width(ui.available_width() - size::CONTROL_H * 1.5));
            remove = ui.add(IconBtn::new(Icon::Close, "Remove this output").size(size::CONTROL_H_SM)).clicked();
        });
        ui.horizontal_wrapped(|ui| {
            let n = o.channels.len();
            for c in 0..4 {
                let label = if c < n { o.channels[c].clone() } else { "–".into() };
                egui::ComboBox::from_id_salt(("tpl ch", k, c)).selected_text(label).show_ui(ui, |ui| {
                    if c + 1 == n && n > 1 && ui.selectable_label(false, "– (drop)").clicked() {
                        o.channels.pop();
                    }
                    for s in SOURCES {
                        if ui.selectable_label(c < n && o.channels[c] == s, s).clicked() {
                            if c < n {
                                o.channels[c] = s.into();
                            } else {
                                while o.channels.len() < c {
                                    o.channels.push("const:0".into());
                                }
                                o.channels.push(s.into());
                            }
                        }
                    }
                });
            }
        });
        ui.horizontal_wrapped(|ui| {
            egui::ComboBox::from_id_salt(("tpl fmt", k)).selected_text(format!("{:?}", o.format)).show_ui(ui, |ui| {
                for f in [FileFormat::Png, FileFormat::Tga, FileFormat::Exr] {
                    ui.selectable_value(&mut o.format, f, format!("{f:?}"));
                }
            });
            egui::ComboBox::from_id_salt(("tpl depth", k)).selected_text(format!("{:?}", o.bit_depth)).show_ui(ui, |ui| {
                for d in [BitDepth::U8, BitDepth::U16, BitDepth::F16, BitDepth::F32] {
                    ui.selectable_value(&mut o.bit_depth, d, format!("{d:?}"));
                }
            });
            egui::ComboBox::from_id_salt(("tpl cs", k)).selected_text(format!("{:?}", o.color_space)).show_ui(ui, |ui| {
                ui.selectable_value(&mut o.color_space, ColorSpace::Srgb, "sRGB");
                ui.selectable_value(&mut o.color_space, ColorSpace::Linear, "Linear");
            });
            egui::ComboBox::from_id_salt(("tpl pad", k)).selected_text(format!("Padding: {:?}", o.padding)).show_ui(ui, |ui| {
                ui.selectable_value(&mut o.padding, Padding::Dilate, "Dilate (seam padding)");
                ui.selectable_value(&mut o.padding, Padding::None, "None (zero outside islands)");
            });
        });
        ds::toggle(ui, &mut o.skip_if_neutral, "Skip when empty");
        if let Err(e) = o.validate() {
            ui.label(ds::text(e, font::SMALL).color(ds::pal(ui).warn));
        }
    });
    remove
}

pub fn templates_ui(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
    ds::section(ui, "Export template");
    STATE.with(|st| {
        let mut st = st.borrow_mut();
        // reading the user templates file every frame is slow: refresh every 2 s
        if st.cache.as_ref().is_none_or(|(t, _)| t.elapsed().as_secs_f32() > 2.0) {
            st.cache = Some((std::time::Instant::now(), app.all_templates()));
        }
        let all = st.cache.as_ref().map(|c| c.1.clone()).unwrap_or_default();
        ds::card(ui, |ui| {
            let label = all.iter().find(|(t, _)| t.id == st.current).map(|(t, s)| format!("{} ({})", if t.label.is_empty() { &t.id } else { &t.label }, s.id())).unwrap_or_else(|| st.current.clone());
            egui::ComboBox::from_id_salt("export template").selected_text(label).show_ui(ui, |ui| {
                for (t, s) in &all {
                    if ui.selectable_label(st.current == t.id, format!("{} · {}", t.id, s.id())).on_hover_text(&t.label).clicked() {
                        st.current = t.id.clone();
                    }
                }
            });
            ui.horizontal_wrapped(|ui| {
                if ui.add(Btn::secondary("Export with template").icon(Icon::Export).small()).clicked() {
                    if let Some(t) = app.find_template(&st.current) {
                        let dir = app.ui.prefs.export_dir.clone().unwrap_or_else(super::super::jobs::default_export_root).join(app.export_name.trim());
                        let name = app.export_name.clone();
                        match app.export_with_template(rs, &dir, &t, &name, Default::default()) {
                            Ok(f) => app.set_status(format!("Exported {} files with `{}` to {}", f.len(), t.id, dir.display()), false),
                            Err(e) => app.set_status(e, true),
                        }
                    }
                }
                if ui.add(Btn::ghost("Edit a copy").small()).clicked() {
                    if let Some(mut t) = app.find_template(&st.current) {
                        t.id = format!("{}_custom", t.id);
                        t.label = format!("{} (custom)", t.label);
                        st.draft = Some(t);
                    }
                }
            });
        });
        let mut save: Option<TemplateScope> = None;
        let mut close = false;
        if let Some(d) = st.draft.as_mut() {
            ds::section(ui, "Edit template");
            ui.horizontal(|ui| {
                ds::prop_label(ui, "Id", Some("Save under this id; export_textures {template: id}"));
                ui.text_edit_singleline(&mut d.id);
            });
            let mut drop: Option<usize> = None;
            for (k, o) in d.outputs.iter_mut().enumerate() {
                if output_ui(ui, o, k) {
                    drop = Some(k);
                }
            }
            if let Some(k) = drop {
                d.outputs.remove(k);
            }
            ui.horizontal_wrapped(|ui| {
                if ui.add(Btn::ghost("Add output").icon(Icon::Plus).small()).clicked() {
                    d.outputs.push(TemplateOutput { pattern: "{name}_Map".into(), channels: vec!["roughness".into()], format: FileFormat::Png, bit_depth: BitDepth::U8, color_space: ColorSpace::Srgb, padding: Padding::Dilate, skip_if_neutral: false });
                }
                let valid = d.validate();
                if ui.add(Btn::secondary("Save to my templates").icon(Icon::Save).small().enabled(valid.is_ok())).clicked() {
                    save = Some(TemplateScope::User);
                }
                if ui.add(Btn::secondary("Save with project").small().enabled(valid.is_ok())).clicked() {
                    save = Some(TemplateScope::Project);
                }
                close = ui.add(Btn::ghost("Close").small()).clicked();
                if let Err(e) = valid {
                    ui.label(ds::text(e, font::SMALL).color(ds::pal(ui).warn));
                }
            });
        }
        if let (Some(scope), Some(d)) = (save, st.draft.clone()) {
            match app.save_template(d.clone(), scope) {
                Ok(_) => {
                    st.cache = None;
                    st.current = d.id.clone();
                    app.set_status(format!("Saved template `{}` ({})", d.id, scope.id()), false);
                }
                Err(e) => app.set_status(e, true),
            }
        }
        if close {
            st.draft = None;
        }
    });
}

/// UI tests: open the editor on a copy of `id`.
#[cfg(test)]
pub fn edit_copy_for_tests(app: &PigmentApp, id: &str) {
    STATE.with(|st| {
        let mut st = st.borrow_mut();
        st.current = id.into();
        st.draft = app.find_template(id).map(|mut t| {
            t.id = format!("{id}_custom");
            t
        });
    });
}
