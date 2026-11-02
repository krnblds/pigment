//! Filter stacks (layer result, mask, filter layers), anchor points and
//! generator inputs, as editors shown in the Properties and Mask panels.

use super::super::design::{self as ds, font, size, space, Btn, Icon, IconBtn, RichTip};
use super::*;
use pigment_core::filters::{AnchorChannel, Filter, FilterKind, FilterTarget, GenInput};

/// One filter's parameters (only the ones its kind reads).
fn filter_params_ui(ui: &mut egui::Ui, f: &mut Filter, target: FilterTarget, salt: (usize, &str)) {
    let p = &mut f.params;
    let k = f.kind;
    let radius_label = match k {
        FilterKind::Warp | FilterKind::SlopeBlur => "Distance",
        _ => "Radius",
    };
    if k.is_spatial() && k != FilterKind::HeightToNormal {
        ds::slider_row_ex(ui, radius_label, &mut p.radius, 0.0..=128.0, ds::Unit::Suffix(" px", 1), true, Some("Texels at 2048; scales with the texture size"));
    }
    match k {
        FilterKind::Levels => {
            let lv = &mut p.levels;
            ds::slider_row(ui, "In black", &mut lv.in_black[3], 0.0..=1.0, ds::Unit::Plain(2));
            ds::slider_row(ui, "In white", &mut lv.in_white[3], 0.0..=1.0, ds::Unit::Plain(2));
            ds::slider_row_ex(ui, "Gamma", &mut lv.gamma[3], 0.1..=10.0, ds::Unit::Plain(2), true, None);
            ds::slider_row(ui, "Out black", &mut lv.out_black[3], 0.0..=1.0, ds::Unit::Plain(2));
            ds::slider_row(ui, "Out white", &mut lv.out_white[3], 0.0..=1.0, ds::Unit::Plain(2));
            if target == FilterTarget::Layer {
                ds::collapsible(ui, &format!("filters.levels_rgb.{}.{}", salt.0, salt.1), "Per channel (R, G, B)", false, |ui| {
                    for (c, name) in ["R", "G", "B"].iter().enumerate() {
                        ds::slider_row(ui, &format!("{name} gamma"), &mut lv.gamma[c], 0.1..=10.0, ds::Unit::Plain(2));
                        ds::slider_row(ui, &format!("{name} out white"), &mut lv.out_white[c], 0.0..=1.0, ds::Unit::Plain(2));
                    }
                });
            }
        }
        FilterKind::Hsl => {
            ds::slider_row(ui, "Hue", &mut p.hue, -180.0..=180.0, ds::Unit::Suffix("°", 0));
            ds::slider_row(ui, "Saturation", &mut p.saturation, -1.0..=1.0, ds::Unit::Plain(2));
            ds::slider_row(ui, "Lightness", &mut p.lightness, -1.0..=1.0, ds::Unit::Plain(2));
        }
        FilterKind::ColorBalance => {
            for (label, v) in [("Shadows", &mut p.shadows), ("Midtones", &mut p.midtones), ("Highlights", &mut p.highlights)] {
                ui.horizontal(|ui| {
                    ds::prop_label(ui, label, Some("Red, green and blue offsets"));
                    for x in v.iter_mut() {
                        ui.add(egui::DragValue::new(x).range(-1.0..=1.0).speed(0.01));
                    }
                });
            }
        }
        FilterKind::Clamp => {
            ds::slider_row(ui, "Min", &mut p.min, 0.0..=1.0, ds::Unit::Plain(2));
            ds::slider_row(ui, "Max", &mut p.max, 0.0..=1.0, ds::Unit::Plain(2));
        }
        FilterKind::DirectionalBlur => {
            ds::slider_row(ui, "Angle", &mut p.angle, -180.0..=180.0, ds::Unit::Suffix("°", 0));
        }
        FilterKind::Sharpen | FilterKind::EdgeDetect | FilterKind::HeightToNormal => {
            ds::slider_row(ui, "Strength", &mut p.amount, 0.0..=8.0, ds::Unit::Plain(2));
            if k == FilterKind::HeightToNormal {
                ds::toggle(ui, &mut p.use_height, "Keep the height").on_hover_text("On: adds normal detail on top (stronger bumps). Off: converts the height into normal detail and flattens it.");
            }
        }
        FilterKind::Warp | FilterKind::SlopeBlur | FilterKind::NoiseOverlay => {
            ds::slider_row(ui, "Strength", &mut p.amount, 0.0..=2.0, ds::Unit::Plain(2));
            ds::slider_row_ex(ui, "Noise scale /m", &mut p.scale, 0.1..=200.0, ds::Unit::Plain(1), true, None);
            if k == FilterKind::SlopeBlur && target == FilterTarget::Layer {
                ds::toggle(ui, &mut p.use_height, "Follow the stack's height");
            }
            ui.horizontal(|ui| {
                ds::prop_label(ui, "Seed", None);
                ui.add(egui::DragValue::new(&mut p.seed).range(0..=999));
            });
        }
        _ => {}
    }
    if target == FilterTarget::Layer {
        ui.horizontal_wrapped(|ui| {
            ds::prop_label(ui, "Channels", Some("Which channels the filter changes"));
            let mut list = f.channel_list();
            let mut changed = false;
            for c in [Channel::BaseColor, Channel::Roughness, Channel::Metallic, Channel::Height, Channel::Normal, Channel::Emissive] {
                let mut on = list.contains(&c);
                if ui.add(Btn::ghost(c.label()).small().selected(on)).clicked() {
                    on = !on;
                    changed = true;
                    if on {
                        list.push(c);
                    } else {
                        list.retain(|x| *x != c);
                    }
                }
            }
            if changed {
                f.channels = list;
            }
        });
    }
}

/// An ordered filter stack with enable toggles, reorder and remove.
/// Returns the rect of the first filter's enable toggle (UI tests).
pub fn filter_stack_ui(ui: &mut egui::Ui, filters: &mut Vec<Filter>, target: FilterTarget, id: &str) -> Option<egui::Rect> {
    let mut first: Option<egui::Rect> = None;
    let mut action: Option<(usize, i32)> = None; // (index, -1 up / 1 down / 0 remove)
    let n = filters.len();
    if n == 0 {
        ds::hint(ui, match target {
            FilterTarget::Mask => "No mask filters. Blur, grow, shrink, warp or fill holes in the mask.",
            FilterTarget::Layer => "No filters. Levels, HSL, blur, sharpen, warp... applied after this layer, inside its mask.",
        });
    }
    for (k, f) in filters.iter_mut().enumerate() {
        ds::card(ui, |ui| {
            ui.horizontal(|ui| {
                let t = ds::toggle(ui, &mut f.enabled, f.kind.label());
                if k == 0 {
                    first = Some(t.rect);
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.add(IconBtn::new(Icon::Close, "Remove this filter").size(size::CONTROL_H_SM)).clicked() {
                        action = Some((k, 0));
                    }
                    if k + 1 < n && ui.add(IconBtn::new(Icon::ChevronDown, "Move down (runs later)").size(size::CONTROL_H_SM)).clicked() {
                        action = Some((k, 1));
                    }
                    if k > 0 && ui.add(IconBtn::new(Icon::ChevronRight, "Move up (runs earlier)").size(size::CONTROL_H_SM)).clicked() {
                        action = Some((k, -1));
                    }
                });
            });
            ds::hint(ui, f.kind.blurb());
            if f.enabled {
                filter_params_ui(ui, f, target, (k, id));
            }
        });
    }
    match action {
        Some((k, 0)) => {
            filters.remove(k);
        }
        Some((k, -1)) => filters.swap(k, k - 1),
        Some((k, _)) => filters.swap(k, k + 1),
        None => {}
    }
    ui.add_space(space::XS);
    let mut add: Option<FilterKind> = None;
    egui::ComboBox::from_id_salt(("add filter", id)).selected_text("Add filter…").show_ui(ui, |ui| {
        for k in FilterKind::ALL {
            let ok = match target {
                FilterTarget::Mask => k.on_mask(),
                FilterTarget::Layer => k.on_layer(),
            };
            if ok && ui.selectable_label(false, k.label()).on_hover_text(k.blurb()).clicked() {
                add = Some(k);
            }
        }
    });
    if let Some(k) = add {
        filters.push(Filter::new(k));
    }
    first
}

/// Properties panel: the layer's filters and its anchor point.
pub fn layer_filters_ui(app: &mut PigmentApp, ui: &mut egui::Ui, i: usize) {
    let is_filter = matches!(app.doc.layers[i].kind, LayerKind::Filter {});
    if app.doc.layers[i].is_foliage() {
        return;
    }
    ds::section(ui, if is_filter { "Filters (stack below)" } else { "Filters" });
    let l = &mut app.doc.layers[i];
    if let Some(r) = filter_stack_ui(ui, &mut l.filters, FilterTarget::Layer, "layer") {
        app.anchors.insert("layer_filter_0", r);
    }
    let l = &mut app.doc.layers[i];
    ds::section(ui, "Anchor point");
    ds::card(ui, |ui| {
        let mut on = l.anchor.is_some();
        if ds::toggle(ui, &mut on, "Anchor").rich_tip("Anchor point", "Layers above can read the stack as it is right here (height, this layer's mask, colour) in their generators: edge wear on painted scratches, dirt in painted dents.").changed() {
            l.anchor = on.then(|| l.name.clone());
        }
        if let Some(a) = &mut l.anchor {
            ui.horizontal(|ui| {
                ds::prop_label(ui, "Name", Some("Generators refer to the anchor by this name"));
                ui.text_edit_singleline(a);
            });
        }
    });
}

/// Mask panel: the mask's filter stack.
pub fn mask_filters_ui(app: &mut PigmentApp, ui: &mut egui::Ui, i: usize) {
    ds::section(ui, "Mask filters");
    if let Some(m) = app.doc.layers[i].mask.as_mut() {
        if let Some(r) = filter_stack_ui(ui, &mut m.filters, FilterTarget::Mask, "mask") {
            app.anchors.insert("mask_filter_0", r);
        }
    }
}

/// Mask panel: where the generator reads its input (bakes or an anchor).
pub fn generator_input_ui(app: &mut PigmentApp, ui: &mut egui::Ui, i: usize) {
    let anchors = app.doc.anchors_below(i);
    let Some(g) = app.doc.layers[i].mask.as_mut().and_then(|m| m.generator.as_mut()) else { return };
    ds::section(ui, "Input");
    ds::card(ui, |ui| {
        let current = match &g.input {
            None => "Mesh bakes".to_string(),
            Some(inp) => format!("{} · {}", inp.anchor, inp.channel.label()),
        };
        let mut choice: Option<Option<GenInput>> = None;
        ui.horizontal(|ui| {
            ds::prop_label(ui, "Source", Some("Bakes (curvature, AO) or a channel of an anchor below this layer"));
            egui::ComboBox::from_id_salt("gen input").selected_text(current).show_ui(ui, |ui| {
                if ui.selectable_label(g.input.is_none(), "Mesh bakes").clicked() {
                    choice = Some(None);
                }
                for a in &anchors {
                    for c in AnchorChannel::ALL {
                        let sel = g.input.as_ref().is_some_and(|x| &x.anchor == a && x.channel == c);
                        if ui.selectable_label(sel, format!("{a} · {}", c.label())).clicked() {
                            choice = Some(Some(GenInput::new(a, c)));
                        }
                    }
                }
            });
        });
        if let Some(c) = choice {
            g.input = c;
        }
        if anchors.is_empty() {
            ds::hint(ui, "No anchors below this layer. Turn on Anchor in a lower layer's properties.");
        }
        if let Some(inp) = &mut g.input {
            ds::slider_row(ui, "Strength", &mut inp.strength, 0.0..=16.0, ds::Unit::Plain(2));
            ds::slider_row(ui, "Radius", &mut inp.radius, 1.0..=64.0, ds::Unit::Suffix(" px", 0));
        }
        let _ = font::SMALL;
    });
}

/// "Filter layer" entry for the add-layer menu.
pub fn add_filter_layer(app: &mut PigmentApp) {
    let l = app.doc.new_filter_layer("Filter", vec![Filter::new(FilterKind::Levels)]);
    app.insert_layer(l);
}

