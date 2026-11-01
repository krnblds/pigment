//! The material library (live thumbnails rendered by Pigment), applying a
//! material to the whole model or one part, and the Weathering panel's
//! "How worn?" slider.

use super::super::design::{self as ds, font, size, space, Btn, Icon, RichTip, ToastKind};
use super::super::prefs::Mode;
use super::super::ui::LibItem;
use super::*;
use crate::render::viewport::{ViewSettings, Viewport};
use crate::render::MeshGpu;
use eframe::egui_wgpu::wgpu;
use std::collections::{HashMap, VecDeque};

const THUMB_RES: u32 = 256;
const THUMB_PX: u32 = 160;
/// Bump when thumbnails would look different (invalidates the disk cache).
const THUMB_VERSION: u32 = 3;

/// Material thumbnails, rendered by Pigment's own compositor and viewport on
/// a small crate, a few per frame so the window never stalls, cached in
/// memory and as PNGs under `<config>/thumbs`.
pub struct Thumbs {
    ts: TexSet,
    viewport: Viewport,
    mesh: Mesh,
    mg: MeshGpu,
    camera: OrbitCamera,
    done: HashMap<String, egui::TextureId>,
    handles: Vec<egui::TextureHandle>,
    textures: Vec<wgpu::Texture>,
    wanted: VecDeque<(String, Document)>,
    disk: Option<PathBuf>,
    pub rendered: usize,
}

fn cache_name(key: &str) -> String {
    let mut h: u64 = 1469598103934665603;
    for b in key.bytes() {
        h = (h ^ b as u64).wrapping_mul(1099511628211);
    }
    format!("v{THUMB_VERSION}_{h:016x}.png")
}

impl Thumbs {
    pub fn new(rs: &RenderState, baker: &Baker, disk: Option<PathBuf>) -> Thumbs {
        let (d, q) = (&rs.device, &rs.queue);
        let mesh = Mesh::demo_crate(24);
        let mg = MeshGpu::new(d, &mesh);
        let mut ts = TexSet::new(d, q, THUMB_RES);
        let (c, r) = mesh.bounding_sphere();
        ts.prepare_mesh(d, q, &mg, c, r);
        let bake = Document::default().bake;
        baker.bake(d, q, &mesh, &mg, &mut ts, &bake);
        let mut camera = OrbitCamera::default();
        camera.frame(c, r);
        camera.yaw = 0.62;
        camera.pitch = 0.42;
        camera.distance *= 0.8;
        Thumbs { ts, viewport: Viewport::new(d), mesh, mg, camera, done: HashMap::new(), handles: vec![], textures: vec![], wanted: VecDeque::new(), disk, rendered: 0 }
    }

    /// The thumbnail for `key` if ready; otherwise queue `make()` to render.
    pub fn get(&mut self, ctx: &egui::Context, key: &str, make: impl FnOnce() -> Document) -> Option<egui::TextureId> {
        if let Some(t) = self.done.get(key) {
            return Some(*t);
        }
        if self.wanted.iter().any(|(k, _)| k == key) {
            return None;
        }
        if let Some(path) = self.disk.as_ref().map(|d| d.join(cache_name(key))) {
            if let Ok(img) = image::open(&path) {
                let img = img.to_rgba8();
                let ci = egui::ColorImage::from_rgba_unmultiplied([img.width() as usize, img.height() as usize], img.as_raw());
                let h = ctx.load_texture(key, ci, egui::TextureOptions::LINEAR);
                self.done.insert(key.to_string(), h.id());
                self.handles.push(h);
                return self.done.get(key).copied();
            }
        }
        self.wanted.push_back((key.to_string(), make()));
        None
    }

    pub fn pending(&self) -> usize {
        self.wanted.len()
    }

    /// Render up to `budget` queued thumbnails.
    pub fn pump(&mut self, rs: &RenderState, env: &Environment, budget: usize) {
        let (d, q) = (&rs.device, &rs.queue);
        for _ in 0..budget {
            let Some((key, mut doc)) = self.wanted.pop_front() else { return };
            doc.resolution = THUMB_RES;
            self.ts.ensure_resources(d, q, &doc);
            self.ts.composite(d, q, &doc, None);
            self.viewport.ensure_targets(d, [THUMB_PX, THUMB_PX]);
            let view = ViewSettings { show_env: false, ..Default::default() };
            self.viewport.draw(d, q, &self.camera, &view, Some(&self.mg), env, &self.ts);
            let Some(src) = self.viewport.color() else { return };
            let tex = d.create_texture(&wgpu::TextureDescriptor {
                label: Some("thumbnail"),
                size: wgpu::Extent3d { width: THUMB_PX, height: THUMB_PX, depth_or_array_layers: 1 },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: src.format,
                usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
                view_formats: &[],
            });
            let mut enc = d.create_command_encoder(&Default::default());
            enc.copy_texture_to_texture(src.tex.as_image_copy(), tex.as_image_copy(), wgpu::Extent3d { width: THUMB_PX, height: THUMB_PX, depth_or_array_layers: 1 });
            q.submit([enc.finish()]);
            let view = tex.create_view(&Default::default());
            let id = rs.renderer.write().register_native_texture(d, &view, wgpu::FilterMode::Linear);
            if let Some(dir) = &self.disk {
                let px = crate::render::gpu::readback(d, q, src);
                let _ = std::fs::create_dir_all(dir);
                let _ = image::save_buffer(dir.join(cache_name(&key)), &px, THUMB_PX, THUMB_PX, image::ExtendedColorType::Rgba8);
            }
            self.textures.push(tex);
            self.done.insert(key, id);
            self.rendered += 1;
        }
    }

    #[allow(dead_code)]
    pub fn mesh_triangles(&self) -> usize {
        self.mesh.triangle_count()
    }
}

/// Small image previews (tile sets, decals), loaded lazily and cached.
#[derive(Default)]
pub struct ImageThumbs {
    map: HashMap<PathBuf, Option<egui::TextureHandle>>,
    loads_this_frame: usize,
}

impl ImageThumbs {
    pub fn begin_frame(&mut self) {
        self.loads_this_frame = 0;
    }

    pub fn get(&mut self, ctx: &egui::Context, path: &Path) -> Option<egui::TextureId> {
        if let Some(h) = self.map.get(path) {
            return h.as_ref().map(|h| h.id());
        }
        if self.loads_this_frame >= 4 {
            return None;
        }
        self.loads_this_frame += 1;
        let h = image::open(path).ok().map(|img| {
            let img = img.thumbnail(128, 128).to_rgba8();
            let ci = egui::ColorImage::from_rgba_unmultiplied([img.width() as usize, img.height() as usize], img.as_raw());
            ctx.load_texture(path.to_string_lossy(), ci, egui::TextureOptions::LINEAR)
        });
        let id = h.as_ref().map(|h| h.id());
        self.map.insert(path.to_path_buf(), h);
        id
    }
}

// ------------------------------------------------------------------ catalogue

/// Library categories: (name, items).
pub fn catalogue() -> Vec<(&'static str, Vec<LibItem>)> {
    let smart = |n: &str| LibItem::Smart(n.to_string());
    let preset = |n: &str| LibItem::Preset(n.to_string());
    let featured = vec![
        smart("Worn teal paint metal"),
        smart("Rusty steel"),
        preset("Car paint clearcoat"),
        smart("Grimy concrete"),
        smart("Tech panels"),
        smart("Worn olive drab metal"),
        smart("Scuffed white plastic"),
        smart("Grimy chrome"),
        smart("Hazard stripes"),
        preset("Metallic flake paint"),
        preset("Tinted glass"),
        preset("Neon cyan"),
    ];
    let mut groups: Vec<(&'static str, Vec<LibItem>)> = vec![("Featured", featured), ("Smart materials", smart_material_names().iter().map(|n| smart(n)).collect())];
    let cat = |n: &str| -> &'static str {
        let l = n.to_ascii_lowercase();
        if l.contains("glass") || l == "cut-out" {
            "Glass & cut-outs"
        } else if l.contains("neon") || l.contains("led") || l.contains("screen") {
            "Glow"
        } else if l.contains("car paint") || l.contains("candy") || l.contains("flake") {
            "Car paint"
        } else if ["steel", "iron", "aluminium", "gold", "copper", "gunmetal", "chrome", "rust", "verdigris"].iter().any(|m| l.contains(m)) {
            "Metals"
        } else if ["asphalt", "concrete", "grime", "seam", "chip"].iter().any(|m| l.contains(m)) {
            "Ground & grime"
        } else {
            "Paint & plastic"
        }
    };
    let mut flat: Vec<(&'static str, Vec<LibItem>)> = vec![];
    for (n, _) in material_presets() {
        let c = cat(n);
        match flat.iter_mut().find(|(k, _)| *k == c) {
            Some((_, v)) => v.push(preset(n)),
            None => flat.push((c, vec![preset(n)])),
        }
    }
    let order = ["Metals", "Paint & plastic", "Car paint", "Glass & cut-outs", "Glow", "Ground & grime"];
    flat.sort_by_key(|(k, _)| order.iter().position(|o| o == k).unwrap_or(99));
    groups.extend(flat);
    groups
}

/// Friendlier display names for the beginner library.
pub fn display_name(item: &LibItem) -> String {
    match item {
        LibItem::Smart(n) if n == "Worn teal paint metal" => "Worn painted metal".into(),
        LibItem::Smart(n) if n == "Rusty steel" => "Rusty".into(),
        LibItem::Preset(n) if n == "Car paint clearcoat" => "Car paint".into(),
        LibItem::Smart(n) if n == "Grimy concrete" => "Concrete".into(),
        other => other.name(),
    }
}

pub fn subtitle(item: &LibItem) -> &'static str {
    match item {
        LibItem::Smart(_) => "Smart · wears",
        LibItem::Preset(_) => "Material",
        LibItem::File(_) => "Saved smart",
    }
}

fn thumb_key(item: &LibItem) -> String {
    match item {
        LibItem::Smart(n) => format!("smart:{n}"),
        LibItem::Preset(n) => format!("preset:{n}"),
        LibItem::File(p) => format!("file:{}:{}", p.display(), std::fs::metadata(p).and_then(|m| m.modified()).map(|t| format!("{t:?}")).unwrap_or_default()),
    }
}

/// The layers `item` stands for, as one folder tree (children first, root last).
pub fn item_layers(doc: &mut Document, item: &LibItem, parts: &[u32]) -> Result<Vec<Layer>, String> {
    let (name, layers) = match item {
        LibItem::Smart(n) => (display_name(item), doc.smart_material(n).ok_or_else(|| format!("unknown smart material {n}"))?),
        LibItem::Preset(n) => (display_name(item), vec![doc.fill_with(n, n, None)]),
        LibItem::File(p) => {
            let sm = pigment_core::smart::SmartMaterial::load(p).map_err(|e| format!("{e:#}"))?;
            let ls = doc.instantiate_smart(&sm, parts);
            return Ok(ls);
        }
    };
    let mut folder = doc.new_folder(&name);
    if !parts.is_empty() {
        let res = doc.mint();
        let mut m = Mask::new(res);
        m.parts = parts.to_vec();
        folder.mask = Some(m);
    }
    let mut out: Vec<Layer> = layers
        .into_iter()
        .map(|mut l| {
            l.parent = Some(folder.id);
            l
        })
        .collect();
    out.push(folder);
    Ok(out)
}

/// A preview document for a library item: the item over a neutral base.
fn preview_doc(item: &LibItem) -> Document {
    let mut doc = Document { resolution: THUMB_RES, ..Default::default() };
    if let Ok(layers) = item_layers(&mut doc, item, &[]) {
        doc.layers.extend(layers);
    }
    doc
}

/// A preview of a mask generator: bright where it applies, dark elsewhere.
pub fn generator_doc(kind: GeneratorKind) -> Document {
    let mut doc = Document { resolution: THUMB_RES, ..Default::default() };
    let base = doc.fill_with("Base", "Carbon black", None);
    let mut g = Generator::new(kind);
    if kind == GeneratorKind::WindowGrid {
        g.amount = 0.6;
    }
    let on = doc.fill_with("Generator", "Hazard yellow", Some(g));
    doc.layers.push(base);
    doc.layers.push(on);
    doc
}

/// Generators whose amount the Weathering slider drives.
pub const WEATHER: [GeneratorKind; 9] = [
    GeneratorKind::EdgeWear,
    GeneratorKind::Dirt,
    GeneratorKind::Grunge,
    GeneratorKind::Streaks,
    GeneratorKind::Spots,
    GeneratorKind::Scratches,
    GeneratorKind::Leaks,
    GeneratorKind::Moss,
    GeneratorKind::Puddles,
];

/// The weathering slider's multiplier on authored amounts: 0 = pristine, 0.5 = as authored, 1 = twice.
pub fn wear_factor(w: f32) -> f32 {
    (w * 2.0).clamp(0.0, 2.0)
}

impl PigmentApp {
    pub(in crate::app) fn thumbs(&mut self, rs: &RenderState) -> &mut Thumbs {
        if self.ui.thumbs.is_none() {
            self.ui.thumbs = Some(Thumbs::new(rs, &self.baker, self.ui.prefs.thumb_dir()));
        }
        self.ui.thumbs.as_mut().unwrap()
    }

    /// Weathering layers: (index, base amount at "as authored").
    fn weather_layers(&mut self) -> Vec<(usize, f32)> {
        let w = self.ui.wear;
        let mut out = vec![];
        for (i, l) in self.doc.layers.iter().enumerate() {
            let Some(g) = l.mask.as_ref().and_then(|m| m.generator.as_ref()) else { continue };
            if !WEATHER.contains(&g.kind) {
                continue;
            }
            let base = *self.ui.wear_bases.entry(l.id).or_insert_with(|| if wear_factor(w) > 0.05 { g.amount / wear_factor(w) } else { g.amount });
            out.push((i, base));
        }
        out
    }

    /// Set the weathering level 0..1 (0.5 = as the material was authored).
    pub(in crate::app) fn set_wear(&mut self, w: f32) {
        let layers = self.weather_layers();
        self.ui.wear = w.clamp(0.0, 1.0);
        let k = wear_factor(self.ui.wear);
        for (i, base) in layers {
            if let Some(g) = self.doc.layers[i].mask.as_mut().and_then(|m| m.generator.as_mut()) {
                g.amount = (base * k).clamp(0.0, 1.0);
            }
        }
    }

    pub(in crate::app) fn has_weathering(&self) -> bool {
        self.doc.layers.iter().any(|l| l.mask.as_ref().and_then(|m| m.generator.as_ref()).is_some_and(|g| WEATHER.contains(&g.kind)))
    }

    /// Apply a library item. Simple mode replaces the model's material (or
    /// the part's); Advanced mode adds it above the selection. `part` limits
    /// it to one mesh part.
    pub(in crate::app) fn apply_library(&mut self, _rs: &RenderState, item: &LibItem, part: Option<u32>) {
        let parts: Vec<u32> = part.into_iter().collect();
        let layers = match item_layers(&mut self.doc, item, &parts) {
            Ok(l) => l,
            Err(e) => return self.notify_error("Couldn't apply that material", &e),
        };
        let Some(root) = layers.last().map(|l| l.id) else { return };
        let simple = self.ui.prefs.mode == Mode::Simple;
        let top_paint = |doc: &Document| doc.layers.iter().position(|l| l.is_paint() && l.parent.is_none()).unwrap_or(doc.layers.len());
        let mut replaced = 0;
        let at = if let Some(p) = part {
            // replace the folder already filling exactly this part
            let old = self.doc.layers.iter().find(|l| l.parent.is_none() && l.mask.as_ref().is_some_and(|m| m.parts == [p])).map(|l| l.id);
            match old {
                Some(id) => {
                    let i = self.doc.index_of(id).unwrap();
                    let first = i + 1 - self.doc.subtree(id).len();
                    self.doc.remove_layer_tree(id);
                    replaced += 1;
                    first
                }
                None => top_paint(&self.doc),
            }
        } else if simple {
            // the whole-model material: every top-level fill / folder without a part mask
            let olds: Vec<LayerId> = self.doc.layers.iter().filter(|l| l.parent.is_none() && !l.is_paint() && l.mask.as_ref().is_none_or(|m| m.parts.is_empty())).map(|l| l.id).collect();
            for id in olds {
                self.doc.remove_layer_tree(id);
                replaced += 1;
            }
            0
        } else {
            match self.selected.and_then(|s| self.doc.layer(s)).filter(|l| l.parent.is_none()).and_then(|l| self.doc.index_of(l.id)) {
                Some(i) => i + 1,
                None => top_paint(&self.doc),
            }
        };
        let ids: Vec<LayerId> = layers.iter().map(|l| l.id).collect();
        self.doc.insert_tree(None, Some(at), layers);
        if !self.doc.layers.iter().any(|l| l.is_paint()) {
            let paint = self.doc.new_paint_layer("Paint");
            self.doc.layers.push(paint);
        }
        // new weathering follows the current slider
        let k = wear_factor(self.ui.wear);
        for l in self.doc.layers.iter_mut().filter(|l| ids.contains(&l.id)) {
            if let Some(g) = l.mask.as_mut().and_then(|m| m.generator.as_mut()).filter(|g| WEATHER.contains(&g.kind)) {
                self.ui.wear_bases.insert(l.id, g.amount);
                g.amount = (g.amount * k).clamp(0.0, 1.0);
            }
        }
        if simple {
            let top = self.doc.layers.iter().rev().find(|l| l.is_paint()).map(|l| l.id);
            self.select(top, false);
        } else {
            self.select(Some(root), false);
        }
        self.ui.lib_current = Some(item.clone());
        let name = display_name(item);
        let where_ = match part {
            Some(p) => format!("part {p}"),
            None if simple => "the model".to_string(),
            None => "the layer stack".to_string(),
        };
        let what = if replaced > 0 { "Replaced with" } else { "Applied" };
        self.set_status(format!("{what} {name} on {where_} (Ctrl+Z to undo)"), false);
    }

    /// Save the selected folder as a smart material in the user's library.
    pub(in crate::app) fn save_to_library(&mut self) {
        let Some(id) = self.selected else { return };
        let Some(dir) = self.ui.prefs.dir.as_ref().map(|d| d.join("smart materials")) else {
            self.save_smart_dialog();
            return;
        };
        let name = self.doc.layer(id).map(|l| l.name.clone()).unwrap_or_default();
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join(format!("{}.{}", name.replace(['/', '\\', ':'], "_"), pigment_core::smart::SMART_EXTENSION));
        match self.save_smart(id, &name, &path) {
            Ok(_) => {
                self.ui.toasts.push(ToastKind::Success, "Saved to your library", format!("{name} is under Saved in the Materials panel."));
            }
            Err(e) => self.notify_error("Couldn't save the smart material", &e),
        }
    }

    pub(in crate::app) fn saved_materials(&self) -> Vec<LibItem> {
        let Some(dir) = self.ui.prefs.dir.as_ref().map(|d| d.join("smart materials")) else { return vec![] };
        let mut v: Vec<PathBuf> = std::fs::read_dir(dir).into_iter().flatten().flatten().map(|e| e.path()).filter(|p| p.extension().is_some_and(|e| e == pigment_core::smart::SMART_EXTENSION)).collect();
        v.sort();
        v.into_iter().map(LibItem::File).collect()
    }
}

// ------------------------------------------------------------------ panels

#[derive(Default)]
pub struct LibraryPanel {
    query: String,
    category: Option<&'static str>,
}

impl Panel for LibraryPanel {
    fn id(&self) -> PanelId {
        PanelId::Library
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        let p = ds::pal(ui);
        let simple = app.ui.prefs.mode == Mode::Simple;
        ds::search_field(ui, &mut self.query, "Search materials");
        ui.add_space(space::SM);
        let mut cats = catalogue();
        let saved = app.saved_materials();
        if !saved.is_empty() {
            cats.insert(2, ("Saved", saved));
        }
        // category chips
        ui.horizontal_wrapped(|ui| {
            ui.spacing_mut().item_spacing = egui::vec2(space::XS, space::XS);
            if ui.add(Btn::ghost("All").small().selected(self.category.is_none())).clicked() {
                self.category = None;
            }
            for (c, _) in &cats {
                if ui.add(Btn::ghost(*c).small().selected(self.category == Some(*c))).clicked() {
                    self.category = Some(c);
                }
            }
        });
        ui.add_space(space::XS);
        let target = if app.tool() == super::super::ui::Tool::Fill { "Click a tile, then click a part of the model." } else if simple { "Click a material to put it on the whole model. Use Fill part (G) for one piece." } else { "Click to add a material above the selected layer." };
        ds::hint(ui, target);
        ui.add_space(space::SM);
        let q = self.query.trim().to_lowercase();
        let mut shown_any = false;
        let mut seen = std::collections::HashSet::new();
        let tile = size::TILE;
        let cols = ((ui.available_width() + space::SM) / (tile + space::SM)).floor().max(1.0) as usize;
        let tile_w = ((ui.available_width() - space::SM * (cols as f32 - 1.0)) / cols as f32).floor();
        let mut clicked: Option<LibItem> = None;
        for (cat, items) in cats {
            if self.category.is_some_and(|c| c != cat) {
                continue;
            }
            if self.category.is_none() && cat == "Smart materials" && q.is_empty() {
                // featured already shows the best ones; the rest stays one click away
            }
            let items: Vec<LibItem> = items.into_iter().filter(|i| (q.is_empty() || display_name(i).to_lowercase().contains(&q) || i.name().to_lowercase().contains(&q)) && (self.category.is_some() || seen.insert(thumb_key(i)))).collect();
            if items.is_empty() {
                continue;
            }
            shown_any = true;
            ds::section(ui, cat);
            let grid = egui::Grid::new(("lib", cat)).spacing([space::SM, space::SM]).show(ui, |ui| {
                for (k, item) in items.iter().enumerate() {
                    let key = thumb_key(item);
                    let it = item.clone();
                    let thumb = app.thumbs(rs).get(ui.ctx(), &key, || preview_doc(&it));
                    let v = match item {
                        LibItem::Preset(n) => material_preset(n),
                        _ => MaterialValues::default(),
                    };
                    let selected = app.ui.lib_current.as_ref() == Some(item);
                    let r = ds::asset_tile(
                        ui,
                        tile_w,
                        thumb,
                        |pa, r| {
                            ds::paint_material_swatch(pa, r, v.base_color, v.roughness, v.metallic, v.emissive_strength, v.opacity, ds::radius::MD);
                            ds::icons::spinner(pa, egui::Rect::from_center_size(r.center(), egui::vec2(18.0, 18.0)), p.text_muted, 0.0);
                        },
                        &display_name(item),
                        subtitle(item),
                        selected,
                    );
                    let tip = match item {
                        LibItem::Smart(_) => "A layered material with edge wear and dirt that follow the model's shape.",
                        LibItem::Preset(_) => "One material: colour, roughness, metal and more.",
                        LibItem::File(_) => "A smart material you saved.",
                    };
                    if r.rich_tip(&display_name(item), tip).clicked() {
                        clicked = Some(item.clone());
                    }
                    if (k + 1) % cols == 0 {
                        ui.end_row();
                    }
                }
            });
            if cat == "Featured" || app.anchors.get("presets").is_none() {
                app.anchors.insert("presets", grid.response.rect);
            }
        }
        if !shown_any {
            ds::empty_state(ui, Icon::Search, "No material matches", "Try another word, like metal, paint, glass or rust.", None);
        }
        if let Some(item) = clicked {
            if app.tool() == super::super::ui::Tool::Fill {
                app.ui.lib_current = Some(item.clone());
                app.set_status(format!("{}: now click a part of the model", display_name(&item)), false);
            } else {
                app.apply_library(rs, &item, None);
            }
        }
        if !simple {
            ui.add_space(space::MD);
            ui.horizontal_wrapped(|ui| {
                let folder = app.selected.and_then(|id| app.doc.layer(id)).is_some_and(|l| l.is_folder());
                if ui.add(Btn::secondary("Save folder to library").icon(Icon::Save).small().enabled(folder)).on_disabled_hover_text("Select a folder in Layers first").clicked() {
                    app.save_to_library();
                }
                if ui.add(Btn::ghost("Apply .pigsmart file…").icon(Icon::Open).small()).clicked() {
                    app.load_smart_dialog();
                }
            });
        }
        // render a few queued thumbnails per frame
        if let Some(t) = app.ui.thumbs.as_mut() {
            if t.pending() > 0 {
                t.pump(rs, &app.env, 2);
                ui.ctx().request_repaint();
            }
        }
    }
}

pub struct LookPanel;

impl Panel for LookPanel {
    fn id(&self) -> PanelId {
        PanelId::Look
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        let p = ds::pal(ui);
        ds::section(ui, "How worn?");
        if !app.has_weathering() {
            if ds::empty_state(ui, Icon::Rain, "Nothing to weather yet", "Materials marked \"Smart · wears\" get edge wear, scratches and dirt you can dial in here.", Some("Show smart materials")) {
                app.ui.prefs.layout_mut().open(PanelId::Library);
            }
        } else {
            let mut w = app.ui.wear;
            let r = ds::slider_row_ex(ui, "Weathering", &mut w, 0.0..=1.0, ds::Unit::Percent, false, Some("Scales every edge wear, scratch, rust and dirt layer at once. 50% is how the material was made."));
            app.anchors.insert("wear_slider", r.rect);
            if r.changed() {
                app.set_wear(w);
            }
            ui.horizontal(|ui| {
                for (label, v) in [("Brand new", 0.08), ("Used", 0.35), ("Worn", 0.6), ("Battered", 0.92)] {
                    if ui.add(Btn::ghost(label).small().selected((app.ui.wear - v).abs() < 0.02)).clicked() {
                        app.set_wear(v);
                    }
                }
            });
            ui.label(ds::text("Edge wear and dirt follow the model's shape: they gather on edges and in crevices by themselves.", font::SMALL).color(p.text_muted));
        }
        ui.add_space(space::MD);
        ds::section(ui, "Light it");
        super::misc::lighting_presets(app, ui, rs);
        ui.add_space(space::LG);
        if ui.add(Btn::primary("Export…").icon(Icon::Export).fill().large()).clicked() {
            app.show_export = true;
        }
    }
}
