//! Brush engine section of the Brush panel: tool (paint / clone / smudge),
//! tip, flow, angle, jitter, pen pressure curves, lazy mouse, line / path
//! tools, symmetry and the stencil.

use super::super::design::{self as ds, font, Btn, Icon, RichTip};
use super::super::{BrushTool, StencilState};
use super::*;
use pigment_core::brush::PressureCurve;

fn curve_ui(ui: &mut egui::Ui, label: &str, c: &mut PressureCurve) {
    ds::toggle(ui, &mut c.enabled, label);
    if c.enabled {
        ds::slider_row(ui, "Minimum", &mut c.min, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row_ex(ui, "Response", &mut c.gamma, 0.25..=4.0, ds::Unit::Plain(2), true, Some("Above 1: needs more pressure. Below 1: responds early."));
    }
}

pub fn brush_engine_ui(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
    ds::section(ui, "Tool");
    ds::segmented(ui, &mut app.brush.tool, &[(BrushTool::Paint, Some(Icon::Brush), "Paint"), (BrushTool::Clone, Some(Icon::Duplicate), "Clone"), (BrushTool::Smudge, Some(Icon::Wand), "Smudge")]);
    match app.brush.tool {
        BrushTool::Clone => {
            let msg = if app.brush.clone_source.is_some() { "Source set. Strokes copy from it, keeping the offset of the first stroke. Alt-click to pick a new source." } else { "Alt-click the model to set the source, then paint." };
            ds::hint(ui, msg);
        }
        BrushTool::Smudge => {
            ds::slider_row(ui, "Drag", &mut app.brush.smudge, 0.05..=2.0, ds::Unit::Plain(2));
            ds::hint(ui, "Drags the existing pixels along the stroke (length in brush diameters).");
        }
        BrushTool::Paint => {}
    }

    ds::section(ui, "Tip");
    ds::card(ui, |ui| {
        let current = app.brush.tip.as_ref().and_then(|t| app.brush.tips.iter().find(|(id, _)| id == t)).map(|(_, l)| l.clone()).unwrap_or_else(|| "Round (hardness)".into());
        let mut pick: Option<Option<String>> = None;
        egui::ComboBox::from_id_salt("brush tip").selected_text(current).show_ui(ui, |ui| {
            if ui.selectable_label(app.brush.tip.is_none(), "Round (hardness)").clicked() {
                pick = Some(None);
            }
            for (id, label) in &app.brush.tips {
                if ui.selectable_label(app.brush.tip.as_deref() == Some(id), label).clicked() {
                    pick = Some(Some(id.clone()));
                }
            }
        });
        if let Some(t) = pick {
            app.brush.tip = t;
        }
        if app.brush.tips.is_empty() {
            ds::hint(ui, "No tip library found (assets/brushes; run tools/make_brush_tips.py).");
        }
        let d = &mut app.brush.dynamics;
        ds::slider_row(ui, "Angle", &mut d.angle, -180.0..=180.0, ds::Unit::Suffix("°", 0));
        ds::toggle(ui, &mut d.follow_angle, "Angle follows the stroke");
    });

    ds::section(ui, "Stroke");
    ds::card(ui, |ui| {
        let d = &mut app.brush.dynamics;
        ds::slider_row_ex(ui, "Flow", &mut d.flow, 0.02..=1.0, ds::Unit::Percent, false, Some("Below 100%: dabs build up towards the strength as you paint over"));
        ds::slider_row_ex(ui, "Lazy mouse", &mut d.lazy, 0.0..=200.0, ds::Unit::Suffix(" px", 0), false, Some("The brush trails the pointer by this distance: smooth, steady lines"));
        ds::collapsible(ui, "brush.jitter", "Jitter", false, |ui| {
            ds::slider_row(ui, "Size", &mut d.jitter.size, 0.0..=1.0, ds::Unit::Percent);
            ds::slider_row(ui, "Angle", &mut d.jitter.angle, 0.0..=180.0, ds::Unit::Suffix("°", 0));
            ds::slider_row(ui, "Position", &mut d.jitter.position, 0.0..=2.0, ds::Unit::Plain(2));
            ds::slider_row(ui, "Flow", &mut d.jitter.flow, 0.0..=1.0, ds::Unit::Percent);
        });
        ds::collapsible(ui, "brush.pressure", "Pen pressure", false, |ui| {
            ds::hint(ui, "Tablet pressure (pen or touch force). A mouse paints at full pressure.");
            curve_ui(ui, "Pressure → size", &mut d.pressure_size);
            curve_ui(ui, "Pressure → flow", &mut d.pressure_flow);
            curve_ui(ui, "Pressure → opacity", &mut d.pressure_opacity);
        });
        ui.horizontal_wrapped(|ui| {
            if ui.add(Btn::secondary(if app.brush.path_mode { "Path: on" } else { "Path tool" }).small().selected(app.brush.path_mode)).rich_tip("Path tool", "Click points on the model, Enter paints along them, Esc clears.").clicked() {
                app.brush.path_mode = !app.brush.path_mode;
                app.brush.path.clear();
            }
        });
        ds::hint(ui, "Shift-click: a straight line from the end of the last stroke.");
    });

    ds::section(ui, "Symmetry");
    ds::card(ui, |ui| {
        let s = &mut app.brush.symmetry;
        ui.horizontal(|ui| {
            ds::toggle(ui, &mut s.x, "X");
            ds::toggle(ui, &mut s.y, "Y");
            ds::toggle(ui, &mut s.z, "Z");
        });
        let mut radial = s.radial as f32;
        if ds::slider_row(ui, "Radial", &mut radial, 1.0..=16.0, ds::Unit::Plain(0)).changed() {
            s.radial = radial.round() as u32;
        }
        if s.radial > 1 {
            ds::segmented(ui, &mut s.axis, &[(0, None, "Around X"), (1, None, "Around Y"), (2, None, "Around Z")]);
        }
        ds::hint(ui, "Mirrors through the model's centre, in object space.");
    });

    ds::section(ui, "Stencil");
    ds::card(ui, |ui| {
        let mut load = false;
        let mut clear = false;
        ui.horizontal_wrapped(|ui| {
            load = ui.add(Btn::secondary(if app.brush.stencil.is_some() { "Change image…" } else { "Load image…" }).icon(Icon::Image).small()).clicked();
            if app.brush.stencil.is_some() {
                clear = ui.add(Btn::ghost("Remove").small()).clicked();
            }
        });
        if let Some(st) = app.brush.stencil.as_mut() {
            ds::slider_row(ui, "Opacity", &mut st.opacity, 0.0..=1.0, ds::Unit::Percent);
            ds::slider_row_ex(ui, "Scale", &mut st.scale, 0.02..=8.0, ds::Unit::Plain(2), true, None);
            ds::slider_row(ui, "Rotation", &mut st.rotation, -180.0..=180.0, ds::Unit::Suffix("°", 0));
            ds::toggle(ui, &mut st.invert, "Invert");
            ds::hint(ui, "Hold S over the viewport: drag moves, Shift+drag rotates, wheel scales.");
        } else {
            ui.label(ds::text("Paint through an image laid over the screen.", font::SMALL));
        }
        if clear {
            let _ = app.set_stencil(rs, None);
        }
        if load {
            if let Some(path) = rfd::FileDialog::new().set_title("Stencil image").add_filter("Image", &["png", "jpg", "jpeg"]).pick_file() {
                let size = image::image_dimensions(&path).map(|(w, h)| [w, h]).unwrap_or([1, 1]);
                let st = StencilState { path, center: Vec2::splat(0.5), rotation: 0.0, scale: 0.6, opacity: 1.0, invert: false, size };
                if let Err(e) = app.set_stencil(rs, Some(st)) {
                    app.set_status(e, true);
                }
            }
        }
    });
}
