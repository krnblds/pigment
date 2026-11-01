//! The decal tool: an image browser for `assets/decals`, four placement
//! modes (stamp on the surface, camera box, fit to a part, scatter) and
//! wear (tear, fade, grunge) - the same engine paths as the MCP tools.

use super::super::decals::{BoxDecal, DecalLook};
use super::super::design::{self as ds, font, space, Btn, Icon};
use super::super::ui::DecalMode;
use super::*;
use pigment_core::decal::{face_point, raycast_parts, Face, Placement, Scatter};

/// `assets/<sub>` near the working directory, the executable or the source tree.
pub fn asset_dir(sub: &str) -> Option<PathBuf> {
    let mut roots: Vec<PathBuf> = vec![];
    if let Ok(c) = std::env::current_dir() {
        roots.extend(c.ancestors().map(Path::to_path_buf));
    }
    if let Ok(e) = std::env::current_exe() {
        roots.extend(e.ancestors().skip(1).map(Path::to_path_buf));
    }
    roots.push(Path::new(env!("CARGO_MANIFEST_DIR")).join("../.."));
    roots.into_iter().map(|r| r.join("assets").join(sub)).find(|p| p.is_dir())
}

/// Decal images under `assets/decals` (one level of subfolders).
pub fn decal_images() -> Vec<PathBuf> {
    let Some(root) = asset_dir("decals") else { return vec![] };
    let mut out = vec![];
    let mut dirs = vec![root];
    let mut depth = 0;
    while let Some(d) = dirs.pop() {
        for e in std::fs::read_dir(&d).into_iter().flatten().flatten() {
            let p = e.path();
            if p.is_dir() && depth < 8 {
                dirs.push(p);
            } else if p.extension().is_some_and(|x| x.eq_ignore_ascii_case("png")) {
                out.push(p);
            }
        }
        depth += 1;
    }
    out.sort();
    out
}

fn aspect(image: &Path) -> f32 {
    image::image_dimensions(image).map(|(w, h)| w as f32 / h.max(1) as f32).unwrap_or(1.0)
}

#[derive(Default)]
pub struct DecalsPanel {
    images: Option<Vec<PathBuf>>,
    thumbs: library::ImageThumbs,
    folder: Option<String>,
}

impl Panel for DecalsPanel {
    fn id(&self) -> PanelId {
        PanelId::Decals
    }

    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        let p = ds::pal(ui);
        let images = self.images.get_or_insert_with(decal_images).clone();
        self.thumbs.begin_frame();
        let active = app.tool() == super::super::ui::Tool::Decal;
        if !active {
            ui.horizontal(|ui| {
                if ui.add(Btn::primary("Use the decal tool").icon(Icon::Stamp)).clicked() {
                    app.set_tool(super::super::ui::Tool::Decal);
                }
                ui.label(ds::text("D", font::SMALL).color(p.text_muted));
            });
            ui.add_space(space::SM);
        }
        ds::section(ui, "Placement");
        ds::segmented(ui, &mut app.ui.decal.mode, &[(DecalMode::Stamp, Some(Icon::Stamp), "Stamp"), (DecalMode::Box, Some(Icon::Frame), "Box"), (DecalMode::Part, Some(Icon::Parts), "Part"), (DecalMode::Scatter, Some(Icon::Scatter), "Scatter")]);
        ds::hint(
            ui,
            match app.ui.decal.mode {
                DecalMode::Stamp => "Click the model: the image sticks flat on the surface there, at its real size in metres.",
                DecalMode::Box => "Drag a box over the model: the image is projected from the camera.",
                DecalMode::Part => "Click a part: the image is fitted to the face of that part you clicked.",
                DecalMode::Scatter => "Scatter copies of the chosen images over the model (or the picked parts) with random wear.",
            },
        );
        ds::section(ui, "Look");
        let d = &mut app.ui.decal;
        if d.mode != DecalMode::Box {
            ds::slider_row_ex(ui, "Size", &mut d.size, 0.02..=4.0, ds::Unit::Suffix(" m", 2), true, Some("Width in metres; the height follows the image"));
        }
        if matches!(d.mode, DecalMode::Stamp) {
            ds::slider_row(ui, "Rotation", &mut d.rotation, -180.0..=180.0, ds::Unit::Suffix("°", 0));
        }
        ds::slider_row(ui, "Opacity", &mut d.opacity, 0.0..=1.0, ds::Unit::Percent);
        ds::slider_row_ex(ui, "Wear", &mut d.wear, 0.0..=1.0, ds::Unit::Percent, false, Some("Tear it with noise, biased to the edges, leaving a rim of bare paper"));
        ds::slider_row_ex(ui, "Fade", &mut d.fade, 0.0..=1.0, ds::Unit::Percent, false, Some("Patchy sun-bleaching and wear-through"));
        ds::toggle(ui, &mut d.grunge, "Grungy, streaked wear");
        if d.mode == DecalMode::Scatter {
            ds::section(ui, "Scatter");
            let mut c = d.count as f32;
            ds::slider_row(ui, "Count", &mut c, 1.0..=60.0, ds::Unit::Plain(0));
            d.count = c.round() as u32;
            ds::slider_row(ui, "Smallest", &mut d.size_range.0, 0.05..=2.0, ds::Unit::Suffix(" m", 2));
            ds::slider_row(ui, "Largest", &mut d.size_range.1, 0.05..=3.0, ds::Unit::Suffix(" m", 2));
            ds::toggle(ui, &mut d.walls_only, "Walls only (vertical surfaces)");
            ui.horizontal(|ui| {
                if ui.add(Btn::primary("Scatter").icon(Icon::Scatter)).clicked() {
                    let imgs: Vec<PathBuf> = app.ui.decal.image.iter().cloned().collect();
                    app.scatter_decals_ui(rs, &imgs);
                }
                if ui.add(Btn::ghost("New seed").icon(Icon::Dice).small()).clicked() {
                    app.ui.decal.seed = app.ui.decal.seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407) % 100000;
                }
            });
        }
        ds::section_with(ui, "Image", |ui| {
            if ui.add(Btn::ghost("Browse…").icon(Icon::Open).small()).clicked() {
                let start = asset_dir("decals").unwrap_or_default();
                if let Some(pth) = rfd::FileDialog::new().set_directory(start).add_filter("Images", &["png", "jpg", "jpeg"]).pick_file() {
                    app.ui.decal.image = Some(pth.clone());
                    app.decal_tool = Some((pth, None));
                }
            }
        });
        if images.is_empty() {
            ds::empty_state(ui, Icon::Image, "No decal images found", "Browse for a PNG with transparency (a sign, a logo, a sticker).", None);
            return;
        }
        let root = asset_dir("decals");
        let folders: Vec<String> = {
            let mut f: Vec<String> = images.iter().filter_map(|i| i.parent().and_then(|d| root.as_ref().and_then(|r| d.strip_prefix(r).ok())).map(|r| r.to_string_lossy().to_string())).collect();
            f.sort();
            f.dedup();
            f
        };
        ui.horizontal_wrapped(|ui| {
            ui.spacing_mut().item_spacing = egui::vec2(space::XS, space::XS);
            for f in &folders {
                let label = if f.is_empty() { "General" } else { f.as_str() };
                if ui.add(Btn::ghost(label).small().selected(self.folder.as_deref() == Some(f.as_str()) || (self.folder.is_none() && f.is_empty()))).clicked() {
                    self.folder = Some(f.clone());
                }
            }
        });
        let sel_folder = self.folder.clone().unwrap_or_default();
        let w = 72.0;
        ui.horizontal_wrapped(|ui| {
            ui.spacing_mut().item_spacing = egui::vec2(space::SM, space::SM);
            for img in images.iter().filter(|i| i.parent().and_then(|d| root.as_ref().and_then(|r| d.strip_prefix(r).ok())).map(|r| r.to_string_lossy().to_string()).unwrap_or_default() == sel_folder) {
                let tex = self.thumbs.get(ui.ctx(), img);
                let name = img.file_stem().map(|s| s.to_string_lossy().replace('_', " ")).unwrap_or_default();
                let on = app.ui.decal.image.as_deref() == Some(img.as_path());
                let r = ds::asset_tile(ui, w, tex, |pa, r| Icon::Image.paint(pa, r.shrink(space::LG), p.text_muted), &name, "", on);
                if r.clicked() {
                    app.ui.decal.image = Some(img.clone());
                    app.decal_tool = Some((img.clone(), None));
                    app.part_pick = false;
                    app.ui.fill_tool = false;
                }
            }
        });
        if self.thumbs_pending(&images) {
            ui.ctx().request_repaint();
        }
    }
}

impl DecalsPanel {
    fn thumbs_pending(&self, _images: &[PathBuf]) -> bool {
        false
    }
}

impl PigmentApp {
    fn decal_look(&self) -> DecalLook {
        let d = &self.ui.decal;
        DecalLook { opacity: d.opacity, tear: d.wear, fade: d.fade, grunge: d.grunge, seed: d.seed as f32, ..Default::default() }
    }

    /// The paint layer decals go on: the selected paint layer, else the top
    /// paint layer, else a new "Decals" layer.
    fn decal_target(&mut self) {
        let ok = self.selected.and_then(|id| self.doc.layer(id)).is_some_and(|l| l.is_paint() || l.mask.is_some());
        if ok && !self.paint_mask {
            return;
        }
        let top = self.doc.layers.iter().rev().find(|l| l.is_paint()).map(|l| l.id);
        match top {
            Some(id) => self.select(Some(id), false),
            None => {
                let l = self.doc.new_paint_layer("Decals");
                let id = l.id;
                self.doc.layers.push(l);
                self.select(Some(id), false);
            }
        }
    }

    /// The brush values decals paint with: the image's colour, matte.
    fn decal_brush(&mut self) -> (MaterialValues, [bool; 11]) {
        let saved = (self.brush.values.clone(), self.brush.channels);
        self.brush.values = MaterialValues { base_color: [1.0; 3], roughness: 0.55, ..Default::default() };
        self.brush.channels = [true, true, true, false, false, false, false, false, false, false, false];
        saved
    }

    /// World-space surface hit under a viewport pixel: (point, normal, part).
    pub(in crate::app) fn surface_at(&self, px: Vec2, viewport_px: Vec2) -> Option<(glam::Vec3, glam::Vec3, u32)> {
        let vp = self.camera.view_proj(viewport_px.x / viewport_px.y.max(1.0));
        let ndc = Vec2::new(px.x / viewport_px.x * 2.0 - 1.0, 1.0 - px.y / viewport_px.y * 2.0);
        let far = vp.inverse().project_point3(glam::Vec3::new(ndc.x, ndc.y, 1.0));
        let eye = self.camera.eye();
        let dir = (far - eye).normalize();
        let (t, dist) = self.mesh.raycast(eye, dir)?;
        let tri = &self.mesh.indices[t * 3..t * 3 + 3];
        let [a, b, c] = [0, 1, 2].map(|k| glam::Vec3::from(self.mesh.vertices[tri[k] as usize].position));
        let mut n = (b - a).cross(c - a).normalize_or_zero();
        if n.dot(dir) > 0.0 {
            n = -n;
        }
        Some((eye + dir * dist, n, self.parts.triangle_part.get(t).copied().unwrap_or(0)))
    }

    fn place_box_decals(&mut self, rs: &RenderState, decals: Vec<BoxDecal>, label: String) -> Result<usize, String> {
        self.commit_doc_changes();
        self.decal_target();
        let saved = self.decal_brush();
        let r = self.project_box_decals(rs, &decals, label, true);
        (self.brush.values, self.brush.channels) = saved;
        r
    }

    /// Stamp mode: one decal flat on the surface at the clicked point.
    pub(in crate::app) fn stamp_decal(&mut self, rs: &RenderState, image: &Path, px: Vec2, viewport_px: Vec2) -> Result<usize, String> {
        let (pt, n, _) = self.surface_at(px, viewport_px).ok_or("Click on the model to place the decal")?;
        let size = glam::Vec2::new(self.ui.decal.size, self.ui.decal.size / aspect(image).max(0.05));
        let placement = Placement::new(pt, n, size, self.ui.decal.rotation, Placement::default_depth(size));
        let name = image.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        self.place_box_decals(rs, vec![BoxDecal { image: image.to_path_buf(), placement, look: self.decal_look() }], format!("Decal {name}"))
    }

    /// Part mode: fit the image to the face of the clicked part.
    pub(in crate::app) fn fit_decal_to_part(&mut self, rs: &RenderState, image: &Path, px: Vec2, viewport_px: Vec2) -> Result<usize, String> {
        let (_, n, part) = self.surface_at(px, viewport_px).ok_or("Click on a part of the model")?;
        let info = *self.parts.info.get(part as usize).ok_or("no such part")?;
        let (lo, hi) = (glam::Vec3::from(info.min), glam::Vec3::from(info.max));
        let (mc, _) = self.mesh.bounding_sphere();
        let face = [Face::Front, Face::Back, Face::Left, Face::Right, Face::Top, Face::Bottom].into_iter().max_by(|a, b| a.normal(lo, hi, mc).dot(n).total_cmp(&b.normal(lo, hi, mc).dot(n))).unwrap_or(Face::Auto);
        let fnrm = face.normal(lo, hi, mc);
        let (pt, extent) = face_point(lo, hi, fnrm, glam::Vec2::new(0.5, 0.5));
        let (center, normal) = match raycast_parts(&self.mesh, &self.parts.triangle_part, Some(&[part]), pt + fnrm * 0.05, -fnrm) {
            Some((_, d, hn)) => (pt + fnrm * 0.05 - fnrm * d, if hn.dot(fnrm) > 0.5 { hn } else { fnrm }),
            None => (pt, fnrm),
        };
        let a = aspect(image).max(0.05);
        let fit = (extent * 0.9).max(glam::Vec2::splat(0.01));
        let size = if fit.x / a <= fit.y { glam::Vec2::new(fit.x, fit.x / a) } else { glam::Vec2::new(fit.y * a, fit.y) };
        let placement = Placement::new(center, normal, size, 0.0, Placement::default_depth(size));
        let name = image.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        self.place_box_decals(rs, vec![BoxDecal { image: image.to_path_buf(), placement, look: self.decal_look() }], format!("Decal {name} on part {part}"))
    }

    /// Scatter mode: copies over the picked parts (or the whole model).
    pub(in crate::app) fn scatter_decals_ui(&mut self, rs: &RenderState, images: &[PathBuf]) {
        if images.is_empty() {
            self.ui.toasts.push(ds::ToastKind::Info, "Choose an image first", "Click a decal in the Decals panel.");
            return;
        }
        let d = &self.ui.decal;
        let parts = self.selected.and_then(|id| self.doc.layer(id)).and_then(|l| l.mask.as_ref()).map(|m| m.parts.clone()).filter(|p| !p.is_empty());
        let size = (d.size_range.0.min(d.size_range.1), d.size_range.0.max(d.size_range.1));
        let p = Scatter {
            count: d.count as usize,
            seed: d.seed,
            parts,
            region: None,
            height: None,
            ground: self.mesh.bounds().0.y,
            size,
            rotation: 0.0,
            rotation_jitter: 6.0,
            min_spacing: size.1 * 0.9,
            max_tilt: d.walls_only.then_some(20.0),
            fit: true,
            aspects: images.iter().map(|i| aspect(i)).collect(),
            depth: None,
        };
        let placed = pigment_core::decal::scatter(&self.mesh, &self.parts, &p);
        if placed.is_empty() {
            self.ui.toasts.push(ds::ToastKind::Warn, "No room for decals", "Try smaller sizes, fewer copies, or turn off Walls only.");
            return;
        }
        let base = self.decal_look();
        let mut rng = pigment_core::decal::Rng::new(p.seed.wrapping_mul(31).wrapping_add(17));
        let decals: Vec<BoxDecal> = placed
            .iter()
            .map(|s| {
                let mut look = base;
                if look.tear > 0.0 {
                    look.tear = (look.tear + rng.range(-0.15, 0.15)).clamp(0.0, 1.0);
                }
                if look.fade > 0.0 {
                    look.fade = (look.fade + rng.range(-0.15, 0.15)).clamp(0.0, 1.0);
                }
                look.seed = base.seed + rng.range(0.0, 100.0);
                BoxDecal { image: images[s.image].clone(), placement: s.placement, look }
            })
            .collect();
        let n = decals.len();
        match self.place_box_decals(rs, decals, format!("Scatter {n} decals")) {
            Ok(k) => self.set_status(format!("Scattered {k} decals (Ctrl+Z undoes all of them)"), false),
            Err(e) => self.notify_error("Couldn't scatter decals", &e),
        }
    }

    /// Viewport input while the decal tool is active.
    pub(in crate::app) fn decal_input(&mut self, ui: &mut egui::Ui, rs: &RenderState, response: &egui::Response, rect: egui::Rect, viewport_px: Vec2, click: bool, released: bool) {
        let ppp = self.ppp;
        let to_px = |p: egui::Pos2| Vec2::new((p.x - rect.min.x) * ppp, (p.y - rect.min.y) * ppp);
        let p = ds::pal(ui);
        let Some((path, start)) = self.decal_tool.clone() else { return };
        let latest = ui.input(|i| i.pointer.latest_pos());
        match self.ui.decal.mode {
            super::super::ui::DecalMode::Box => {
                if click {
                    self.decal_tool = Some((path.clone(), latest));
                }
                if let (Some(a), Some(b)) = (start, latest) {
                    let r = egui::Rect::from_two_pos(a, b);
                    ui.painter().rect_stroke(r, egui::CornerRadius::ZERO, egui::Stroke::new(1.5, p.accent), egui::StrokeKind::Middle);
                    ui.painter().text(r.left_top() - egui::vec2(0.0, space::XS), egui::Align2::LEFT_BOTTOM, path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default(), ds::fonts::regular(font::SMALL), p.accent);
                    if released {
                        if r.width() > 4.0 && r.height() > 4.0 {
                            let (p0, p1) = (to_px(r.min), to_px(r.max));
                            self.decal_target();
                            let saved = self.decal_brush();
                            let res = self.project_decal(rs, &path, [p0.x, p0.y, p1.x, p1.y], viewport_px, false);
                            (self.brush.values, self.brush.channels) = saved;
                            match res {
                                Ok(()) => self.set_status("Decal placed (Ctrl+Z to undo, Esc to stop)", false),
                                Err(e) => self.set_status(e, true),
                            }
                        }
                        self.decal_tool = Some((path, None));
                    }
                }
            }
            super::super::ui::DecalMode::Stamp | super::super::ui::DecalMode::Part => {
                // ghost outline under the cursor
                if let Some(h) = response.hover_pos() {
                    let moved = self.ui.hover_part.as_ref().is_none_or(|(at, _)| at.distance(h) > 0.5);
                    if moved {
                        let hit = self.surface_at(to_px(h), viewport_px).map(|(pt, n, _)| (pt, n));
                        self.ui.hover_part = Some((h, hit));
                    }
                    if let Some((_, Some((pt, n)))) = self.ui.hover_part {
                        let a = aspect(&path).max(0.05);
                        let size = glam::Vec2::new(self.ui.decal.size, self.ui.decal.size / a);
                        let pl = Placement::new(pt, n, size, self.ui.decal.rotation, 0.01);
                        let vp = self.camera.view_proj(viewport_px.x / viewport_px.y.max(1.0));
                        let o = pl.outline();
                        let proj = |w: glam::Vec3| {
                            let c = vp.project_point3(w);
                            egui::pos2(rect.left() + (c.x * 0.5 + 0.5) * rect.width(), rect.top() + (0.5 - c.y * 0.5) * rect.height())
                        };
                        if self.ui.decal.mode == super::super::ui::DecalMode::Stamp {
                            let pts: Vec<egui::Pos2> = [o[1], o[2], o[3], o[4]].into_iter().map(proj).collect();
                            ui.painter().add(egui::Shape::closed_line(pts, egui::Stroke::new(1.5, p.accent)));
                        }
                        ui.painter().circle_filled(proj(pt), 3.0, p.accent);
                    }
                }
                if click {
                    if let Some(h) = latest {
                        let r = if self.ui.decal.mode == super::super::ui::DecalMode::Stamp { self.stamp_decal(rs, &path, to_px(h), viewport_px) } else { self.fit_decal_to_part(rs, &path, to_px(h), viewport_px) };
                        match r {
                            Ok(0) => self.set_status("The decal didn't touch the surface: try another spot", true),
                            Ok(_) => self.set_status("Decal placed (Ctrl+Z to undo, Esc to stop)", false),
                            Err(e) => self.set_status(e, true),
                        }
                    }
                }
            }
            super::super::ui::DecalMode::Scatter => {}
        }
    }
}
