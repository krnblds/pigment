//! Layers (drag to reorder and nest), Properties, Channels and Mask &
//! generators panels.

use super::super::design::{self as ds, font, icon, size, space, Btn, DropZone, Icon, IconBtn, RichTip};
use super::*;

/// Move `dragged` relative to `target`: above / below it among its
/// siblings, or into it (folders). The panel lists the top of the stack first,
/// so "above" means higher in the stack.
pub fn drop_layer(doc: &mut Document, dragged: LayerId, target: LayerId, zone: DropZone) -> Result<(), String> {
    if dragged == target {
        return Ok(());
    }
    if doc.is_inside(target, dragged) {
        return Err("a folder can't go inside itself".into());
    }
    let t = doc.layer(target).ok_or("no target layer")?;
    if zone == DropZone::Into {
        if !t.is_folder() {
            return Err("only folders take layers inside".into());
        }
        return doc.move_layer(dragged, Some(target), None);
    }
    let parent = t.parent;
    let sibs: Vec<LayerId> = doc.children_of(parent).into_iter().map(|i| doc.layers[i].id).filter(|s| *s != dragged).collect();
    let k = sibs.iter().position(|s| *s == target).ok_or("target vanished")?;
    let pos = if zone == DropZone::Above { k + 1 } else { k };
    doc.move_layer(dragged, parent, Some(pos))
}

fn layer_subtitle(doc: &Document, l: &Layer) -> String {
    let kids = doc.children_of(Some(l.id)).len();
    match (&l.kind, &l.mask) {
        (LayerKind::Paint { .. }, None) => "Paint".to_string(),
        (LayerKind::Paint { .. }, Some(_)) => "Paint · masked".to_string(),
        (LayerKind::Fill { .. }, Some(m)) => match &m.generator {
            Some(g) => format!("Fill · {}", g.kind.label().to_lowercase()),
            None if !m.parts.is_empty() => format!("Fill · {} part{}", m.parts.len(), if m.parts.len() == 1 { "" } else { "s" }),
            None => "Fill · painted mask".to_string(),
        },
        (LayerKind::Fill { .. }, None) => if l.image.is_some() { "Image fill · everywhere" } else { "Fill · everywhere" }.to_string(),
        (LayerKind::Filter {}, _) => format!("Filter · {}", l.filters.iter().filter(|f| f.enabled).map(|f| f.kind.label().to_lowercase()).collect::<Vec<_>>().join(", ")),
        (LayerKind::Foliage { foliage }, _) => format!("Foliage · {} card{}", foliage.instances.len(), if foliage.instances.len() == 1 { "" } else { "s" }),
        (LayerKind::Folder { .. }, m) => format!(
            "Folder · {kids} item{}{}",
            if kids == 1 { "" } else { "s" },
            match m {
                Some(m) if !m.parts.is_empty() => format!(" · {} part{}", m.parts.len(), if m.parts.len() == 1 { "" } else { "s" }),
                Some(_) => " · masked".into(),
                None => String::new(),
            }
        ),
    }
}

fn paint_thumb(pa: &egui::Painter, r: egui::Rect, l: &Layer, p: &ds::Palette) {
    match &l.kind {
        LayerKind::Fill { values } => ds::paint_material_swatch(pa, r, values.base_color, values.roughness, values.metallic, values.emissive_strength, values.opacity, ds::radius::SM),
        LayerKind::Paint { .. } => {
            pa.rect_filled(r, egui::CornerRadius::same(ds::radius::SM), p.well);
            Icon::Brush.paint(pa, r.shrink(space::SM), p.text_secondary);
        }
        LayerKind::Folder { .. } => {
            pa.rect_filled(r, egui::CornerRadius::same(ds::radius::SM), p.accent_subtle);
            Icon::Folder.paint(pa, r.shrink(space::SM), p.accent);
        }
        LayerKind::Foliage { .. } => {
            pa.rect_filled(r, egui::CornerRadius::same(ds::radius::SM), p.well);
            Icon::Leaf.paint(pa, r.shrink(space::SM), p.success);
        }
        LayerKind::Filter {} => {
            pa.rect_filled(r, egui::CornerRadius::same(ds::radius::SM), p.well);
            Icon::Sliders.paint(pa, r.shrink(space::SM), p.info);
        }
    }
}

// ------------------------------------------------------------------ layers

#[derive(Default)]
pub struct LayersPanel {
    /// Last drop hint, for tests.
    pub last_drop: Option<(LayerId, DropZone)>,
}

impl Panel for LayersPanel {
    fn id(&self) -> PanelId {
        PanelId::Layers
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        let p = ds::pal(ui);
        super::texsets::set_switcher(app, ui, rs);
        ui.horizontal(|ui| {
            let add = ui.menu_button(ds::strong("+ Add", font::BODY), |ui| add_layer_menu(app, ui, rs));
            app.anchors.insert("add_layer", add.response.rect);
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let sel = app.selected.is_some();
                if ui.add(IconBtn::new(Icon::Trash, "Delete (a folder goes with its contents)").enabled(sel)).clicked() {
                    app.delete_selected();
                }
                if ui.add(IconBtn::new(Icon::Duplicate, "Duplicate").enabled(sel)).clicked() {
                    app.duplicate_selected(rs);
                }
                if ui.add(IconBtn::new(Icon::Folder, "Group the selection into a new folder").enabled(sel)).clicked() {
                    app.group_selected();
                }
            });
        });
        ui.add_space(space::XS);
        if app.doc.layers.is_empty() {
            if ds::empty_state(ui, Icon::Layers, "No layers yet", "Add a material from the library, or a paint layer to paint on.", Some("Add a paint layer")) {
                let l = app.doc.new_paint_layer("Paint");
                app.insert_layer(l);
            }
            return;
        }
        let dragging = egui::DragAndDrop::payload::<LayerId>(ui.ctx()).map(|d| *d);
        let pointer = ui.ctx().pointer_latest_pos();
        let released = ui.input(|i| i.pointer.any_released());
        let mut select: Option<(LayerId, bool)> = None;
        let mut drop: Option<(LayerId, DropZone)> = None;
        let mut toggles: Vec<(LayerId, u64)> = vec![];
        let n = app.doc.layers.len();
        ui.spacing_mut().item_spacing.y = space::XXS;
        for i in (0..n).rev() {
            let l = &app.doc.layers[i];
            let lid = l.id;
            if app.doc.is_hidden_in_panel(lid) {
                continue;
            }
            let selected = app.selected == Some(lid);
            let sub = layer_subtitle(&app.doc, l);
            let thumb = |pa: &egui::Painter, r: egui::Rect| paint_thumb(pa, r, l, &p);
            let row = ds::LayerRow {
                id: egui::Id::NULL.with(("layer row", lid)),
                depth: app.doc.depth(lid),
                name: &l.name,
                subtitle: &sub,
                visible: l.visible,
                locked: app.ui.locked.contains(&lid),
                selected,
                shown: app.doc.effectively_visible(lid),
                folder: match l.kind {
                    LayerKind::Folder { collapsed } => Some(collapsed),
                    _ => None,
                },
                mask: l.mask.as_ref().map(|m| (m.generator.is_some(), selected && app.paint_mask)),
                opacity: l.opacity,
                thumb: &thumb,
            };
            let is_folder = l.is_folder();
            let gen_edge = l.mask.as_ref().and_then(|m| m.generator.as_ref()).is_some_and(|g| g.kind == GeneratorKind::EdgeWear);
            let r = ds::layer_row(ui, &row, lid);
            if gen_edge {
                app.anchors.entry("edge_wear_row").or_insert(r.rect);
            }
            app.ui.dock_rects.push((PanelId::Layers, r.rect));
            if r.clicked {
                select = Some((lid, false));
            }
            if r.mask_clicked {
                select = Some((lid, true));
            }
            if r.toggle_visible {
                toggles.push((lid, 0));
            }
            if r.toggle_lock {
                toggles.push((lid, 1));
            }
            if r.toggle_collapse {
                toggles.push((lid, 2));
            }
            if let Some(c) = r.context {
                c.context_menu(|ui| {
                    if ui.button("Duplicate").clicked() {
                        select = Some((lid, false));
                        toggles.push((lid, 3));
                        ui.close();
                    }
                    if ui.button("Delete").clicked() {
                        toggles.push((lid, 4));
                        ui.close();
                    }
                    if ui.button("Group into folder").clicked() {
                        toggles.push((lid, 5));
                        ui.close();
                    }
                    app.select(Some(lid), app.paint_mask && selected);
                    if ui.add_enabled(app.can_nudge(1), egui::Button::new("Move up")).clicked() {
                        toggles.push((lid, 7));
                        ui.close();
                    }
                    if ui.add_enabled(app.can_nudge(-1), egui::Button::new("Move down")).clicked() {
                        toggles.push((lid, 8));
                        ui.close();
                    }
                    let targets = app.folder_targets();
                    if !targets.is_empty() {
                        ui.menu_button("Into folder", |ui| {
                            for (fid, path) in targets {
                                if ui.button(path).clicked() {
                                    toggles.push((lid, 1000 + fid));
                                    ui.close();
                                }
                            }
                        });
                    }
                    if app.doc.layer(lid).is_some_and(|l| l.parent.is_some()) && ui.button("Move out of folder").clicked() {
                        toggles.push((lid, 6));
                        ui.close();
                    }
                });
            }
            if let (Some(d), Some(pos)) = (dragging, pointer) {
                if d != lid && r.rect.contains(pos) {
                    let z = ds::drop_zone_at(r.rect, pos.y, is_folder);
                    ds::paint_drop_hint(ui, r.rect, z);
                    self.last_drop = Some((lid, z));
                    if released {
                        drop = Some((lid, z));
                    }
                }
            }
        }
        if let Some((id, mask)) = select {
            app.select(Some(id), mask);
        }
        for (id, what) in toggles {
            match what {
                0 => {
                    if let Some(l) = app.doc.layers.iter_mut().find(|l| l.id == id) {
                        l.visible = !l.visible;
                    }
                }
                1 => {
                    if !app.ui.locked.remove(&id) {
                        app.ui.locked.insert(id);
                    }
                }
                2 => {
                    if let Some(LayerKind::Folder { collapsed }) = app.doc.layers.iter_mut().find(|l| l.id == id).map(|l| &mut l.kind) {
                        *collapsed = !*collapsed;
                    }
                }
                3 => {
                    app.select(Some(id), false);
                    app.duplicate_selected(rs);
                }
                4 => {
                    app.select(Some(id), false);
                    app.delete_selected();
                }
                5 => {
                    app.select(Some(id), false);
                    app.group_selected();
                }
                6 => {
                    app.select(Some(id), false);
                    app.move_selected_out();
                }
                7 | 8 => {
                    app.select(Some(id), false);
                    app.nudge_selected(if what == 7 { 1 } else { -1 });
                }
                f => {
                    app.select(Some(id), false);
                    if let Some(fid) = app.folder_targets().into_iter().map(|(f, _)| f).find(|x| 1000 + *x == f) {
                        app.move_selected_into(fid);
                    }
                }
            }
        }
        if let (Some(d), Some((target, zone))) = (dragging, drop) {
            match drop_layer(&mut app.doc, d, target, zone) {
                Ok(()) => app.set_status(format!("Moved {}", app.doc.layer(d).map(|l| l.name.clone()).unwrap_or_default()), false),
                Err(e) => app.set_status(e, true),
            }
            egui::DragAndDrop::clear_payload(ui.ctx());
        }
        if dragging.is_some() {
            ui.ctx().set_cursor_icon(egui::CursorIcon::Grabbing);
        }
        ui.add_space(space::SM);
        ds::hint(ui, "Drag the ⠿ handle to reorder; drop on the middle of a folder to put a layer inside.");
    }
}

pub fn add_layer_menu(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
    let item = |ui: &mut egui::Ui, ic: Icon, label: &str, tip: &str| ui.add(Btn::ghost(label).icon(ic).fill()).on_hover_text(tip).clicked();
    if item(ui, Icon::PaintLayer, "Paint layer", "Paint material directly with the brush") {
        let l = app.doc.new_paint_layer(&format!("Paint {}", app.doc.layers.len() + 1));
        app.insert_layer(l);
        ui.close();
    }
    if item(ui, Icon::FillLayer, "Fill layer", "A flat or image material; paint on it to mask where it shows") {
        let l = app.doc.new_fill_layer(&format!("Fill {}", app.doc.layers.len() + 1));
        app.insert_layer(l);
        ui.close();
    }
    if item(ui, Icon::Folder, "Folder", "Group layers: the folder's opacity and mask apply to everything inside") {
        app.add_folder();
        ui.close();
    }
    if item(ui, Icon::Sliders, "Filter layer", "Levels, HSL, blur, warp... on everything below it (inside its mask)") {
        super::filters::add_filter_layer(app);
        ui.close();
    }
    ui.separator();
    ui.label(ds::caption(ui, "Smart layers"));
    if item(ui, Icon::Sparkle, "Edge wear", "Bare metal on the edges") {
        add_smart(app, rs, "Edge wear", "Steel", GeneratorKind::EdgeWear, 0.55);
        ui.close();
    }
    if item(ui, Icon::Sparkle, "Dirt", "Grime in crevices") {
        add_smart(app, rs, "Dirt", "Grime", GeneratorKind::Dirt, 0.5);
        ui.close();
    }
    if item(ui, Icon::Sparkle, "Rust", "Rust in crevices") {
        add_smart(app, rs, "Rust", "Rust", GeneratorKind::Dirt, 0.4);
        ui.close();
    }
    if item(ui, Icon::Rain, "Leaks", "Drips running down from ledges") {
        add_smart(app, rs, "Leaks", "Grime", GeneratorKind::Leaks, 0.5);
        ui.close();
    }
    if item(ui, Icon::Rain, "Moss", "Growth on ledges and in crevices") {
        add_smart(app, rs, "Moss", "Verdigris", GeneratorKind::Moss, 0.5);
        ui.close();
    }
    ui.separator();
    if item(ui, Icon::Grid, "Smart material…", "Browse the material library") {
        app.ui.prefs.layout_mut().open(PanelId::Library);
        ui.close();
    }
    if item(ui, Icon::Open, "From .pigsmart file…", "Apply a saved smart material file") {
        app.load_smart_dialog();
        ui.close();
    }
}

fn add_smart(app: &mut PigmentApp, rs: &RenderState, name: &str, material: &str, kind: GeneratorKind, amount: f32) {
    let mut l = app.doc.new_fill_layer(name);
    let values = material_preset(material);
    l.channels.metallic.enabled = values.metallic > 0.0 || material == "Steel";
    l.channels.height.enabled = values.height.abs() > 0.01;
    l.channels.normal.enabled = false;
    l.kind = LayerKind::Fill { values };
    let res = app.doc.mint();
    app.ts.new_mask(&rs.device, &rs.queue, res, true);
    let mut g = Generator::new(kind);
    g.amount = amount;
    if kind == GeneratorKind::EdgeWear {
        g.noise_scale = 20.0;
        g.noise_amount = 0.8;
        g.softness = 0.05;
    }
    l.mask = Some(Mask::with_generator(res, g));
    app.insert_layer(l);
}

// ------------------------------------------------------------------ properties

pub struct PropertiesPanel;

fn no_selection(ui: &mut egui::Ui) {
    ds::empty_state(ui, Icon::Layers, "Nothing selected", "Click a layer in the Layers panel to edit it.", None);
}

/// Material values grouped as Surface, Glow, Glass & cut-out, Car paint.
pub fn material_editor(ui: &mut egui::Ui, id: &str, v: &mut MaterialValues, mut en: Option<&mut [bool; 11]>) {
    let mut row = |ui: &mut egui::Ui, k: usize, label: &str, tip: &str| match en.as_deref_mut() {
        Some(e) => {
            ui.checkbox(&mut e[k], ds::text(label, font::SMALL)).on_hover_text(format!("{tip}\nUntick: the brush leaves this channel alone."));
        }
        None => {
            ds::prop_label(ui, label, Some(tip));
        }
    };
    ds::prop_grid(ui, &format!("{id} surface"), |ui| {
        row(ui, 0, "Base color", "The colour under the light");
        ds::color_picker(ui, &mut v.base_color);
        ui.end_row();
        row(ui, 1, "Roughness", "0 = mirror-glossy, 1 = matte");
        ui.add(egui::Slider::new(&mut v.roughness, 0.0..=1.0));
        ui.end_row();
        row(ui, 2, "Metallic", "1 for bare metal, 0 for everything else");
        ui.add(egui::Slider::new(&mut v.metallic, 0.0..=1.0));
        ui.end_row();
        row(ui, 3, "Height", "Raise (+) or engrave (-) the surface");
        ui.add(egui::Slider::new(&mut v.height, -1.0..=1.0));
        ui.end_row();
        row(ui, 4, "Normal tilt", "Bend the surface normal (x, y)");
        ui.horizontal(|ui| {
            ui.add(egui::DragValue::new(&mut v.normal[0]).speed(0.01).range(-0.95..=0.95).prefix("x "));
            ui.add(egui::DragValue::new(&mut v.normal[1]).speed(0.01).range(-0.95..=0.95).prefix("y "));
        });
        ui.end_row();
    });
    egui::CollapsingHeader::new(ds::caption(ui, "Glow")).id_salt((id, "glow")).default_open(v.emissive_strength > 0.0).show(ui, |ui| {
        ds::prop_grid(ui, &format!("{id} glow"), |ui| {
            row(ui, 5, "Emission", "Light the surface gives off (neon, screens, LEDs)");
            ui.horizontal(|ui| {
                ds::color_picker(ui, &mut v.emissive);
                ui.add(egui::DragValue::new(&mut v.emissive_strength).range(0.0..=50.0).speed(0.05).prefix("× "));
            });
            ui.end_row();
        });
    });
    egui::CollapsingHeader::new(ds::caption(ui, "Glass & cut-out")).id_salt((id, "glass")).default_open(v.opacity < 1.0 || v.transmission > 0.0).show(ui, |ui| {
        ds::prop_grid(ui, &format!("{id} glass"), |ui| {
            row(ui, 6, "Opacity", "1 = solid, 0 = a hole (cut-out)");
            ui.add(egui::Slider::new(&mut v.opacity, 0.0..=1.0));
            ui.end_row();
            row(ui, 7, "Transmission", "Glass: light passes through instead of scattering");
            ui.add(egui::Slider::new(&mut v.transmission, 0.0..=1.0));
            ui.end_row();
        });
    });
    egui::CollapsingHeader::new(ds::caption(ui, "Car paint (coat & flake)")).id_salt((id, "coat")).default_open(v.coat > 0.0 || v.flake > 0.0).show(ui, |ui| {
        ds::prop_grid(ui, &format!("{id} coat"), |ui| {
            row(ui, 8, "Clearcoat", "A glossy varnish over the base (car paint, lacquer)");
            ui.add(egui::Slider::new(&mut v.coat, 0.0..=1.0));
            ui.end_row();
            row(ui, 9, "Coat rough", "Roughness of the clearcoat");
            ui.add(egui::Slider::new(&mut v.coat_roughness, 0.0..=1.0));
            ui.end_row();
            row(ui, 10, "Flake", "Metallic flake sparkle under the coat");
            ui.add(egui::Slider::new(&mut v.flake, 0.0..=1.0));
            ui.end_row();
        });
    });
}

impl Panel for PropertiesPanel {
    fn id(&self) -> PanelId {
        PanelId::Properties
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, _rs: &RenderState) {
        let Some(i) = app.selected.and_then(|id| app.doc.index_of(id)) else { return no_selection(ui) };
        let id = app.doc.layers[i].id;
        let mut name = match &app.renaming {
            Some((rid, n)) if *rid == id => n.clone(),
            _ => app.doc.layers[i].name.clone(),
        };
        let r = ui.add(egui::TextEdit::singleline(&mut name).desired_width(f32::INFINITY).font(ds::fonts::semibold(font::HEADING)));
        if r.changed() {
            app.renaming = Some((id, name.clone()));
        }
        if r.lost_focus() {
            if let Some((_, n)) = app.renaming.take() {
                if !n.trim().is_empty() {
                    app.doc.layers[i].name = n.trim().to_string();
                }
            }
        }
        ui.add_space(space::SM);
        let mut paint_mask = app.paint_mask;
        let has_mask = app.doc.layers[i].mask.is_some();
        if ds::tabs(ui, &mut paint_mask, &[(false, "Layer"), (true, if has_mask { "Mask" } else { "Mask (none)" })]) {
            if paint_mask {
                app.ui.prefs.layout_mut().open(PanelId::Mask);
            }
        }
        app.paint_mask = paint_mask;
        ui.add_space(space::SM);
        let image_bases = app.image_bases();
        let tile_sets = app.cached_list("tile sets", || {
            let root = super::decals::asset_dir("tiles");
            root.as_ref().map(|r| pigment_core::image_fill::list_tile_sets(r).into_iter().map(|s| r.join(s)).collect()).unwrap_or_default()
        });
        let mut save_smart = false;
        let mut save_lib = false;
        let l = &mut app.doc.layers[i];
        ds::slider_row(ui, "Opacity", &mut l.opacity, 0.0..=1.0, ds::Unit::Percent);
        match &mut l.kind {
            LayerKind::Fill { values } => {
                ds::section(ui, "Material");
                ds::card(ui, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        ui.spacing_mut().item_spacing = egui::vec2(space::XS, space::XS);
                        for (name, v) in material_presets() {
                            let (r, resp) = ui.allocate_exact_size(egui::vec2(20.0, 20.0), egui::Sense::click());
                            ds::paint_material_swatch(ui.painter(), r, v.base_color, v.roughness, v.metallic, v.emissive_strength, v.opacity, ds::radius::SM);
                            if resp.on_hover_text(name).clicked() {
                                *values = v;
                            }
                        }
                    });
                    ui.add_space(space::SM);
                    material_editor(ui, "fill", values, None);
                });
                ds::section(ui, "Image fill");
                ds::card(ui, |ui| image_fill_editor(ui, &mut l.image, &mut l.channels, &image_bases, &tile_sets, &mut app.ui.image_thumbs));
                ds::section(ui, "Ground");
                ds::card(ui, |ui| ground_editor(ui, l));
            }
            LayerKind::Paint { .. } => {
                ds::card(ui, |ui| {
                    ui.label(ds::strong("Paint layer", font::BODY));
                    ds::hint(ui, "Holds whatever you paint. Pick the brush material in the Brush panel.");
                });
            }
            LayerKind::Foliage { foliage } => {
                ds::card(ui, |ui| {
                    ui.label(ds::strong("Foliage layer", font::BODY));
                    ds::hint(ui, "Cards placed on the model: moss, grass, ivy, fallen leaves. Paint them with the Foliage brush (V); they are not part of the textures and export with Export foliage.");
                    let t = ds::muted(ui, format!("{} cards · atlas: {}", foliage.instances.len(), foliage.atlas));
                    ui.label(t);
                    ds::slider_row(ui, "Wind (preview)", &mut foliage.wind, 0.0..=1.0, ds::Unit::Percent);
                });
            }
            LayerKind::Filter {} => {
                ds::card(ui, |ui| {
                    ui.label(ds::strong("Filter layer", font::BODY));
                    ds::hint(ui, "Filters the whole stack below it, inside its mask and opacity (levels, blur, warp...).");
                });
            }
            LayerKind::Folder { .. } => {
                ds::card(ui, |ui| {
                    ui.label(ds::strong("Folder", font::BODY));
                    ds::hint(ui, "Its contents are blended as a group, then onto the layers below with the folder's opacity, channels and mask.");
                    ui.horizontal_wrapped(|ui| {
                        save_lib = ui.add(Btn::secondary("Save to library").icon(Icon::Save).small()).rich_tip("Save to library", "Reuse this stack on other models: it appears under Saved in Materials.").clicked();
                        save_smart = ui.add(Btn::ghost("Save as file…").small()).clicked();
                    });
                });
            }
        }
        super::filters::layer_filters_ui(app, ui, i);
        if save_smart {
            app.save_smart_dialog();
        }
        if save_lib {
            app.save_to_library();
        }
    }
}

/// Tiling images for a fill layer: tile set browser with previews,
/// projection, transform and one image per channel.
fn image_fill_editor(ui: &mut egui::Ui, image: &mut Option<ImageFill>, channels: &mut Channels<ChannelSettings>, bases: &[PathBuf], sets: &[PathBuf], thumbs: &mut library::ImageThumbs) {
    use pigment_core::image_fill::ImageChannel;
    let p = ds::pal(ui);
    let mut pick: Option<String> = None;
    thumbs.begin_frame();
    let root = sets.first().and_then(|s| s.parent()).map(Path::to_path_buf);
    if sets.is_empty() {
        ds::hint(ui, "No tile sets found in assets/tiles.");
    }
    ui.horizontal_wrapped(|ui| {
        ui.spacing_mut().item_spacing = egui::vec2(space::SM, space::SM);
        for dir in sets {
            let s = dir.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
            let dir = dir.clone();
            let img = ["base_color.png", "base_color.jpg", "basecolor.png", "albedo.png"].iter().map(|f| dir.join(f)).find(|f| f.exists()).or_else(|| std::fs::read_dir(&dir).ok()?.flatten().map(|e| e.path()).find(|p| p.to_string_lossy().to_lowercase().contains("color")));
            let tex = img.and_then(|i| thumbs.get(ui.ctx(), &i));
            let on = image.as_ref().is_some_and(|f| f.images.iter().any(|(_, path)| path.contains(s.as_str())));
            let r = ds::asset_tile(ui, 76.0, tex, |pa, r| Icon::Image.paint(pa, r.shrink(space::LG), p.text_muted), &s, "", on);
            if r.clicked() {
                pick = Some(format!("assets/tiles/{s}"));
            }
        }
    });
    ui.horizontal(|ui| {
        if ui.add(Btn::ghost("Browse folder…").icon(Icon::Open).small()).clicked() {
            if let Some(d) = rfd::FileDialog::new().set_title("Tile set folder (base_color, roughness, height, normal)").pick_folder() {
                pick = Some(d.to_string_lossy().to_string());
            }
        }
        if image.is_some() && ui.add(Btn::ghost("Remove images").icon(Icon::Close).small()).on_hover_text("Back to the flat values").clicked() {
            *image = None;
        }
    });
    if let Some(dir) = pick {
        let mut bases = bases.to_vec();
        if let Some(r) = root.as_ref().and_then(|r| r.parent()).and_then(|r| r.parent()) {
            bases.push(r.to_path_buf());
        }
        match ImageFill::from_tile_set(&dir, &bases) {
            Ok(imgs) => {
                let f = image.get_or_insert_with(ImageFill::default);
                f.images = imgs;
                for (c, _) in f.images.iter() {
                    channels.get_mut(c.channel()).enabled = true;
                }
            }
            Err(e) => log::warn!("{e}"),
        }
    }
    let Some(f) = image else {
        ds::hint(ui, "Drive colour, roughness, height and normal from tiling photos (brick, concrete...) instead of flat values.");
        return;
    };
    ui.horizontal(|ui| {
        ds::prop_label(ui, "Projection", Some("UV follows the model's unwrap; Triplanar ignores UVs and sizes the tiles in metres"));
        ds::segmented(ui, &mut f.projection, &[(Projection::Uv, None, "UV"), (Projection::Triplanar, None, "Triplanar")]);
    });
    ds::prop_grid(ui, "image fill", |ui| {
        match f.projection {
            Projection::Uv => {
                ds::prop_label(ui, "Tiling", None);
                ui.horizontal(|ui| {
                    ui.add(egui::DragValue::new(&mut f.tiling[0]).speed(0.05).range(0.01..=512.0).prefix("u "));
                    ui.add(egui::DragValue::new(&mut f.tiling[1]).speed(0.05).range(0.01..=512.0).prefix("v "));
                });
                ui.end_row();
            }
            Projection::Triplanar => {
                ds::prop_label(ui, "Tile size", None);
                ui.add(egui::DragValue::new(&mut f.tile_size).speed(0.01).range(0.01..=100.0).suffix(" m"));
                ui.end_row();
                ds::prop_label(ui, "Blend sharpness", None);
                ui.add(egui::Slider::new(&mut f.blend_sharpness, 1.0..=16.0));
                ui.end_row();
            }
        }
        ds::prop_label(ui, "Offset", None);
        ui.horizontal(|ui| {
            ui.add(egui::DragValue::new(&mut f.offset[0]).speed(0.01).prefix("u "));
            ui.add(egui::DragValue::new(&mut f.offset[1]).speed(0.01).prefix("v "));
        });
        ui.end_row();
        ds::prop_label(ui, "Rotation", None);
        ui.add(egui::Slider::new(&mut f.rotation, -180.0..=180.0).suffix("°"));
        ui.end_row();
        ds::prop_label(ui, "Tint", None);
        ds::color_picker(ui, &mut f.tint);
        ui.end_row();
        ds::prop_label(ui, "Roughness range", None);
        ui.horizontal(|ui| {
            ui.add(egui::DragValue::new(&mut f.roughness_range[0]).speed(0.01).range(0.0..=1.0));
            ui.add(egui::DragValue::new(&mut f.roughness_range[1]).speed(0.01).range(0.0..=1.0));
        });
        ui.end_row();
        ds::prop_label(ui, "Height scale", None);
        ui.add(egui::DragValue::new(&mut f.height_scale).speed(0.01).range(-4.0..=4.0));
        ui.end_row();
        ds::prop_label(ui, "Normal strength", None);
        ui.add(egui::Slider::new(&mut f.normal_strength, 0.0..=3.0));
        ui.end_row();
    });
    ds::prop_grid(ui, "image fill channels", |ui| {
        for c in ImageChannel::ALL {
            ds::prop_label(ui, c.label(), None);
            let slot = f.images.get_mut(c);
            let name = slot.as_deref().map(|p| Path::new(p).iter().rev().take(2).collect::<Vec<_>>().into_iter().rev().map(|s| s.to_string_lossy()).collect::<Vec<_>>().join("/"));
            ui.horizontal(|ui| {
                ui.label(ds::text(name.clone().unwrap_or_else(|| "flat value".into()), font::SMALL).color(if name.is_some() { p.text } else { p.text_muted })).on_hover_text(slot.clone().unwrap_or_default());
                if ui.add(IconBtn::new(Icon::Open, "Choose image").size(size::CONTROL_H_SM)).clicked() {
                    if let Some(pth) = rfd::FileDialog::new().add_filter("Images", &["png", "jpg", "jpeg", "exr", "hdr"]).pick_file() {
                        *slot = Some(pth.to_string_lossy().to_string());
                        channels.get_mut(c.channel()).enabled = true;
                    }
                }
                if slot.is_some() && ui.add(IconBtn::new(Icon::Close, "Use the flat value").size(size::CONTROL_H_SM)).clicked() {
                    *slot = None;
                }
            });
            ui.end_row();
        }
    });
    let missing = f.missing(bases);
    if !missing.is_empty() {
        ui.label(ds::text(format!("Not found: {}", missing.join(", ")), font::SMALL).color(p.warn));
    }
}

// ------------------------------------------------------------------ channels

pub struct ChannelsPanel;

impl Panel for ChannelsPanel {
    fn id(&self) -> PanelId {
        PanelId::Channels
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, _rs: &RenderState) {
        let Some(i) = app.selected.and_then(|id| app.doc.index_of(id)) else { return no_selection(ui) };
        let l = &mut app.doc.layers[i];
        let is_folder = l.is_folder();
        ui.label(ds::strong(&l.name, font::TITLE));
        ds::hint(ui, "Which channels this layer changes, and how it blends onto the layers below.");
        ui.add_space(space::SM);
        egui::Grid::new("channels").num_columns(3).spacing([space::MD, space::SM]).show(ui, |ui| {
            for c in Channel::ALL {
                let s = l.channels.get_mut(c);
                ui.checkbox(&mut s.enabled, ds::text(c.label(), font::SMALL));
                egui::ComboBox::from_id_salt(("blend", c.index())).width(120.0).selected_text(s.blend.label()).show_ui(ui, |ui| {
                    let modes = if is_folder { pigment_core::folders::folder_blend_modes(c) } else { c.blend_modes() };
                    for m in modes {
                        ui.selectable_value(&mut s.blend, *m, m.label());
                    }
                });
                ui.add(egui::DragValue::new(&mut s.opacity).range(0.0..=1.0).speed(0.01).custom_formatter(|v, _| format!("{:.0}%", v * 100.0)));
                ui.end_row();
            }
        });
    }
}

// ------------------------------------------------------------------ mask

pub struct MaskPanel;

fn generator_blurb(k: GeneratorKind) -> &'static str {
    match k {
        GeneratorKind::EdgeWear => "Finds convex edges (curvature), breaks them up with noise, avoids occluded areas.",
        GeneratorKind::Dirt => "Finds crevices and occluded areas (AO + concave curvature), broken up with noise.",
        GeneratorKind::Grunge => "Blotchy multi-scale noise: discolouration, damp patches, roughness breakup.",
        GeneratorKind::Streaks => "Vertical streaks along world up, heavier under overhangs: rain, leaks, rust runs.",
        GeneratorKind::Stripes => "Diagonal hazard stripes. Amount = stripe width, Scale = stripes per metre.",
        GeneratorKind::Spots => "Warped blobs: rust spots, paint splotches, stains.",
        GeneratorKind::Scratches => "Thin sharp lines: scratches and scuffs.",
        GeneratorKind::PanelLines => "A grid of seams on every face. Use a dark, negative-height fill for engraved panels.",
        GeneratorKind::Gradient => "Rises from the bottom of the model: grime and splash near the ground. Amount = how high.",
        GeneratorKind::Leaks => "Drip streaks running down walls from under sills and ledges (drip bake).",
        GeneratorKind::Puddles => "Standing water on flat, rain-exposed ground. Use low roughness + a darker colour.",
        GeneratorKind::Moss => "Moss and grime on up-facing ledges and in crevices.",
        GeneratorKind::Tiles => "Bricks, square tiles or hexagons with per-cell jitter. Invert for mortar.",
        GeneratorKind::WindowGrid => "A grid of windows on walls; Amount = fraction lit. Use with an emissive fill.",
        GeneratorKind::Cells => "Voronoi cells: domes, edges (cracks), a value per cell or bevelled plates (cobbles, flagstones, cracked mud).",
        GeneratorKind::Scatter => "Scattered pebbles, flakes, leaves, twigs or shells, each with a rounded height. Amount = density.",
        GeneratorKind::Rock => "Ridged, warped rock with strata ledges, block-joint cracks and downhill streaks.",
        GeneratorKind::Blades => "A dense field of grass blades in clumps, leaning; Amount = density. Tips variant for dry tips.",
        GeneratorKind::Ripples => "Wind ripples in sand: asymmetric crests that curve, fork and fade.",
        GeneratorKind::Anchor => "Uses an anchor's channel (painted height, an anchor layer's mask or colour) directly as the mask. Pick the anchor under Input.",
    }
}

/// Slider labels for generators that reuse the generic parameter slots.
type SliderLabels = (Option<&'static str>, Option<&'static str>, std::ops::RangeInclusive<f32>, Option<&'static str>, std::ops::RangeInclusive<f32>);
fn weather_slider_labels(kind: GeneratorKind) -> SliderLabels {
    match kind {
        GeneratorKind::Leaks => (Some("Streaks per metre"), Some("Damp under overhangs"), 0.0..=1.5, Some("Drip length (m)"), 0.1..=8.0),
        GeneratorKind::Puddles => (Some("Puddles per metre"), Some("Pooling in corners"), 0.0..=1.5, Some("Pooling in cavities"), 0.0..=2.0),
        GeneratorKind::Moss => (Some("Clump scale"), Some("Growth in crevices"), 0.0..=1.5, Some("Growth in cavities"), 0.0..=2.0),
        GeneratorKind::Tiles => (Some("Rows per metre"), Some("Mortar width"), 0.0..=0.5, Some("Cell aspect (w/h)"), 0.25..=6.0),
        GeneratorKind::WindowGrid => (Some("Cell height (m)"), Some("Frame width"), 0.0..=0.45, Some("Cell aspect (w/h)"), 0.1..=4.0),
        GeneratorKind::Cells => (Some("Cells per metre"), Some("Randomness"), 0.0..=1.0, Some("Edge width (m)"), 0.001..=0.25),
        GeneratorKind::Scatter => (Some("Cells per metre"), Some("Elongation"), 1.0..=16.0, Some("Radius (cells)"), 0.05..=1.5),
        GeneratorKind::Rock => (Some("Features per metre"), Some("Strata"), 0.0..=1.0, Some("Cracks"), 0.0..=2.0),
        GeneratorKind::Blades => (Some("Blades per metre"), Some("Lean"), 0.0..=1.0, Some("Blade length (m)"), 0.005..=0.3),
        GeneratorKind::Ripples => (Some("Ripples per metre"), Some("Asymmetry"), 0.0..=1.0, Some("Defects"), 0.0..=1.0),
        _ => (None, None, 0.0..=1.5, None, 0.0..=2.0),
    }
}

/// Labels / ranges of the ground generators' extra shape parameters and of
/// their breakup slot.
fn ground_extra_labels(kind: GeneratorKind) -> (&'static str, [Option<(&'static str, std::ops::RangeInclusive<f32>)>; 4]) {
    match kind {
        GeneratorKind::Cells => ("Warp", [Some(("Stretch x", 0.2..=5.0)), Some(("Height variation", 0.0..=1.0)), Some(("Edge noise", 0.0..=1.5)), None]),
        GeneratorKind::Scatter => ("Size variation", [Some(("Per cell", 1.0..=8.0)), Some(("Alignment", 0.0..=1.0)), Some(("Irregular outline", 0.0..=1.5)), Some(("Height variation", 0.0..=1.0))]),
        GeneratorKind::Rock => ("Warp", [Some(("Strata bands /m", 0.2..=12.0)), Some(("Downhill streaks", 0.0..=1.5)), Some(("Crack cells /m", 0.1..=8.0)), None]),
        GeneratorKind::Blades => ("Clumping", [Some(("Blade width (m)", 0.0005..=0.02)), Some(("Swirl", 0.0..=1.0)), Some(("Tips / clumps level", 0.0..=1.0)), None]),
        GeneratorKind::Ripples => ("Irregularity", [Some(("Direction (deg)", -90.0..=90.0)), Some(("Crest sharpness", 0.0..=1.0)), None, None]),
        _ => ("Breakup", [None, None, None, None]),
    }
}

/// The generator picker: a grid of rendered previews. Returns the new choice.
fn generator_picker(app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState, current: Option<GeneratorKind>) -> Option<Option<GeneratorKind>> {
    let p = ds::pal(ui);
    let mut out = None;
    let cols = ((ui.available_width() + space::SM) / (76.0 + space::SM)).floor().max(1.0) as usize;
    let w = ((ui.available_width() - space::SM * (cols as f32 - 1.0)) / cols as f32).floor();
    let grid = egui::Grid::new("generator picker").spacing([space::SM, space::SM]).show(ui, |ui| {
        let r = ds::asset_tile(ui, w, None, |pa, r| Icon::Brush.paint(pa, r.shrink(space::XL), p.text_muted), "Hand-painted", "", current.is_none());
        if r.on_hover_text("No generator: paint the mask yourself").clicked() {
            out = Some(None);
        }
        for (k, g) in GeneratorKind::ALL.into_iter().enumerate() {
            let tex = app.thumbs(rs).get(ui.ctx(), &format!("gen:{}", g.id()), || library::generator_doc(g));
            let r = ds::asset_tile(ui, w, tex, |pa, r| Icon::Wand.paint(pa, r.shrink(space::XL), p.text_muted), g.label(), "", current == Some(g));
            if r.rich_tip(g.label(), generator_blurb(g)).clicked() {
                out = Some(Some(g));
            }
            if (k + 2) % cols == 0 {
                ui.end_row();
            }
        }
    });
    app.anchors.insert("generator_picker", grid.response.rect);
    if let Some(t) = app.ui.thumbs.as_mut() {
        if t.pending() > 0 {
            t.pump(rs, &app.env, 2);
            ui.ctx().request_repaint();
        }
    }
    out
}

impl Panel for MaskPanel {
    fn id(&self) -> PanelId {
        PanelId::Mask
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        let Some(i) = app.selected.and_then(|id| app.doc.index_of(id)) else { return no_selection(ui) };
        ui.label(ds::strong(format!("Mask of {}", app.doc.layers[i].name), font::TITLE));
        let baked = app.ts.baked;
        if app.doc.layers[i].mask.is_none() {
            let mut add: Option<(bool, Option<GeneratorKind>)> = None;
            ds::card(ui, |ui| {
                ds::empty_state(ui, Icon::Mask, "No mask: the layer shows everywhere", "A mask decides where this layer appears. Paint it by hand, or let a generator find edges, crevices or patterns.", None);
                ui.horizontal_wrapped(|ui| {
                    if ui.add(Btn::secondary("Black mask").small()).on_hover_text("Hidden everywhere: paint white to reveal").clicked() {
                        add = Some((false, None));
                    }
                    if ui.add(Btn::secondary("White mask").small()).on_hover_text("Shown everywhere: paint black to hide").clicked() {
                        add = Some((true, None));
                    }
                    if ui.add(Btn::secondary("Edge wear").icon(Icon::Sparkle).small()).clicked() {
                        add = Some((true, Some(GeneratorKind::EdgeWear)));
                    }
                    if ui.add(Btn::secondary("Dirt").icon(Icon::Sparkle).small()).clicked() {
                        add = Some((true, Some(GeneratorKind::Dirt)));
                    }
                });
            });
            if let Some((white, generator)) = add {
                let res = app.doc.mint();
                app.ts.new_mask(&rs.device, &rs.queue, res, white);
                let mut m = Mask::new(res);
                m.generator = generator.map(Generator::new);
                app.doc.layers[i].mask = Some(m);
                app.brush.mask_white = !white;
                app.paint_mask = true;
            }
            return;
        }
        let mut removed = false;
        {
            let m = app.doc.layers[i].mask.as_mut().unwrap();
            ui.horizontal(|ui| {
                ds::toggle(ui, &mut m.enabled, "Enabled");
                ds::toggle(ui, &mut m.invert, "Invert");
            });
        }
        ds::hint(ui, "Selecting the mask makes the brush paint it: white reveals, black hides (X swaps).");
        if !app.paint_mask && ui.add(Btn::secondary("Paint this mask").icon(Icon::Brush).small()).clicked() {
            app.paint_mask = true;
        }
        ds::section(ui, "Generator");
        let top = ui.cursor().min;
        let current = app.doc.layers[i].mask.as_ref().unwrap().generator.as_ref().map(|g| g.kind);
        if let Some(choice) = generator_picker(app, ui, rs, current) {
            app.doc.layers[i].mask.as_mut().unwrap().generator = choice.map(Generator::new);
        }
        let m = app.doc.layers[i].mask.as_mut().unwrap();
        if let Some(g) = &mut m.generator {
            ds::card(ui, |ui| {
                ui.label(ds::strong(g.kind.label(), font::BODY));
                ds::hint(ui, generator_blurb(g.kind));
                if !baked && g.kind.uses_bakes() {
                    ui.label(ds::text("Bake mesh maps first (Texture set & bake).", font::SMALL).color(ds::pal(ui).warn));
                }
                let (scale_label, aux_label, aux_range, shape_label, shape_range) = weather_slider_labels(g.kind);
                let pattern = !matches!(g.kind, GeneratorKind::EdgeWear | GeneratorKind::Dirt);
                ds::slider_row_ex(ui, "Amount", &mut g.amount, 0.0..=1.0, ds::Unit::Percent, false, Some("How much of the surface it covers"));
                let mut sharp = 1.0 - g.softness / 0.5;
                if ds::slider_row(ui, "Sharpness", &mut sharp, 0.0..=1.0, ds::Unit::Percent).changed() {
                    g.softness = (1.0 - sharp) * 0.5;
                }
                ds::slider_row_ex(ui, scale_label.unwrap_or(if pattern { "Scale /m" } else { "Breakup scale" }), &mut g.noise_scale, 0.2..=64.0, ds::Unit::Plain(1), true, None);
                if let Some(label) = shape_label {
                    ds::slider_row(ui, label, &mut g.curvature_weight, shape_range, ds::Unit::Plain(2));
                }
                if let Some(label) = aux_label {
                    ds::slider_row(ui, label, &mut g.ao_influence, aux_range, ds::Unit::Plain(2));
                }
                if g.kind == GeneratorKind::Tiles {
                    ui.horizontal(|ui| {
                        ds::prop_label(ui, "Pattern", None);
                        egui::ComboBox::from_id_salt("tile variant").selected_text(GeneratorKind::TILE_VARIANTS[(g.variant as usize).min(2)]).show_ui(ui, |ui| {
                            for (i, v) in GeneratorKind::TILE_VARIANTS.iter().enumerate() {
                                ui.selectable_value(&mut g.variant, i as u32, *v);
                            }
                        });
                    });
                }
                if g.kind.is_ground() {
                    let names = g.kind.variant_names();
                    ui.horizontal(|ui| {
                        ds::prop_label(ui, "Output", Some("Which shape / output of the generator"));
                        egui::ComboBox::from_id_salt("ground variant").selected_text(names[(g.variant as usize).min(names.len() - 1)]).show_ui(ui, |ui| {
                            for (i, v) in names.iter().enumerate() {
                                ui.selectable_value(&mut g.variant, i as u32, *v);
                            }
                        });
                    });
                    let (_, extra) = ground_extra_labels(g.kind);
                    for (k, e) in extra.into_iter().enumerate() {
                        if let Some((label, range)) = e {
                            ds::slider_row(ui, label, &mut g.extra[k], range, ds::Unit::Plain(3));
                        }
                    }
                }
                ds::slider_row(ui, ground_extra_labels(g.kind).0, &mut g.noise_amount, 0.0..=1.5, ds::Unit::Plain(2));
                if !pattern && shape_label.is_none() {
                    ds::slider_row(ui, "Curvature weight", &mut g.curvature_weight, 0.0..=2.0, ds::Unit::Plain(2));
                }
                if g.kind.uses_bakes() && aux_label.is_none() {
                    ds::slider_row(ui, "AO influence", &mut g.ao_influence, 0.0..=1.5, ds::Unit::Plain(2));
                }
                ui.horizontal(|ui| {
                    ds::prop_label(ui, "Seed", Some("A different random pattern"));
                    ui.add(egui::DragValue::new(&mut g.seed).range(0..=999));
                    if ui.add(IconBtn::new(Icon::Dice, "New random seed").size(size::CONTROL_H_SM)).clicked() {
                        g.seed = (g.seed * 7919 + 17) % 1000;
                    }
                });
            });
        }
        super::filters::generator_input_ui(app, ui, i);
        let gen_rect = egui::Rect::from_min_max(top, egui::pos2(ui.max_rect().right(), ui.cursor().min.y));
        if gen_rect.height() > 10.0 {
            app.anchors.insert("generator", gen_rect);
        }
        let m = app.doc.layers[i].mask.as_mut().unwrap();
        if m.generator.is_some() {
            ds::section(ui, "Combine with");
            ds::card(ui, |ui| {
                ds::hint(ui, "Mix more generators in, e.g. dirt × ground gradient = grime only low down.");
                let mut drop: Option<usize> = None;
                for (k, e) in m.effects.iter_mut().enumerate() {
                    ui.horizontal(|ui| {
                        egui::ComboBox::from_id_salt(("eff op", k)).width(100.0).selected_text(e.op.label()).show_ui(ui, |ui| {
                            for o in MaskOp::ALL {
                                ui.selectable_value(&mut e.op, o, o.label());
                            }
                        });
                        let mut kind = e.generator.kind;
                        egui::ComboBox::from_id_salt(("eff kind", k)).width(110.0).selected_text(kind.label()).show_ui(ui, |ui| {
                            for g in GeneratorKind::ALL {
                                ui.selectable_value(&mut kind, g, g.label());
                            }
                        });
                        if kind != e.generator.kind {
                            e.generator = Generator::new(kind);
                        }
                        if ui.add(IconBtn::new(Icon::Close, "Remove this effect").size(size::CONTROL_H_SM)).clicked() {
                            drop = Some(k);
                        }
                    });
                    ds::slider_row(ui, "Amount", &mut e.generator.amount, 0.0..=1.0, ds::Unit::Percent);
                    ds::slider_row_ex(ui, "Scale", &mut e.generator.noise_scale, 0.2..=64.0, ds::Unit::Plain(1), true, None);
                    ds::slider_row(ui, "Breakup", &mut e.generator.noise_amount, 0.0..=1.5, ds::Unit::Plain(2));
                }
                if let Some(k) = drop {
                    m.effects.remove(k);
                }
                if m.effects.len() < MAX_MASK_EFFECTS && ui.add(Btn::ghost("Add effect").icon(Icon::Plus).small()).clicked() {
                    m.effects.push(MaskEffect { generator: Generator::new(GeneratorKind::Gradient), op: MaskOp::Multiply });
                }
            });
        }
        super::filters::mask_filters_ui(app, ui, i);
        super::hibake::id_mask_ui(app, ui, i);
        let m = app.doc.layers[i].mask.as_mut().unwrap();
        ds::section(ui, "Parts");
        let n = m.parts.len();
        ds::card(ui, |ui| {
            ds::hint(ui, if n == 0 { "Whole model. Limit this layer to chosen pieces (glass, frame, buttons...).".to_string() } else { format!("Only {n} selected part{}.", if n == 1 { "" } else { "s" }) });
            ui.horizontal(|ui| {
                if ui.add(Btn::secondary(if app.part_pick { "Done picking" } else { "Pick parts" }).icon(Icon::Target).small().selected(app.part_pick)).clicked() {
                    let t = if app.part_pick { super::super::ui::Tool::Paint } else { super::super::ui::Tool::Pick };
                    app.set_tool(t);
                }
                if n > 0 && ui.add(Btn::ghost("Whole model").small()).clicked() {
                    if let Some(m) = app.doc.layers[i].mask.as_mut() {
                        m.parts.clear();
                    }
                }
            });
        });
        ui.add_space(space::SM);
        if ui.add(Btn::danger("Remove mask").icon(Icon::Trash).small()).clicked() {
            removed = true;
        }
        if removed {
            app.doc.layers[i].mask = None;
            app.paint_mask = false;
        }
        let _ = icon::SM;
    }
}

/// Ground options of a fill layer (`pigment_core::ground`): height follows
/// the generator's shape, height blend against the stack, per-instance jitter.
fn ground_editor(ui: &mut egui::Ui, l: &mut Layer) {
    use pigment_core::ground::{HeightBlend, HeightBlendMode, InstanceJitter};
    ds::toggle(ui, &mut l.height_profile, "Height follows the generator shape")
        .on_hover_text("A dome per pebble, a blade's rise to its tip... instead of a flat plateau under the mask");
    ds::slider_row(ui, "Height gain", &mut l.height_gain, 0.0..=8.0, ds::Unit::Plain(2));
    let mut on = l.height_blend.is_some();
    if ds::toggle(ui, &mut on, "Blend by height").on_hover_text("Show only where this layer's height is above (fills the lows) or below (the tops) the layers under it").changed() {
        l.height_blend = on.then(HeightBlend::default);
    }
    if let Some(hb) = l.height_blend.as_mut() {
        ui.horizontal(|ui| {
            ds::prop_label(ui, "Where", None);
            egui::ComboBox::from_id_salt("height blend mode").selected_text(hb.mode.label()).show_ui(ui, |ui| {
                for m in HeightBlendMode::ALL {
                    ui.selectable_value(&mut hb.mode, m, m.label());
                }
            });
        });
        ds::slider_row(ui, "Level offset", &mut hb.offset, -1.0..=1.0, ds::Unit::Plain(2));
        ds::slider_row(ui, "Contrast", &mut hb.contrast, 0.0..=0.5, ds::Unit::Plain(3));
    }
    let mut jon = l.jitter.is_some();
    if ds::toggle(ui, &mut jon, "Per-instance variation").on_hover_text("Each pebble, cell, blade or rock block gets its own tone (needs a ground generator mask)").changed() {
        l.jitter = jon.then(|| InstanceJitter { value: 0.2, hue: 0.02, saturation: 0.1, roughness: 0.1 });
    }
    if let Some(j) = l.jitter.as_mut() {
        ds::slider_row(ui, "Value", &mut j.value, 0.0..=1.0, ds::Unit::Plain(2));
        ds::slider_row(ui, "Hue", &mut j.hue, 0.0..=0.25, ds::Unit::Plain(3));
        ds::slider_row(ui, "Saturation", &mut j.saturation, 0.0..=1.0, ds::Unit::Plain(2));
        ds::slider_row(ui, "Roughness", &mut j.roughness, 0.0..=0.5, ds::Unit::Plain(2));
    }
}
