//! Foliage in the app: generated layers (foliage atlas cells, bark), card
//! atlases for foliage layers (built-in or exported), the viewport batches,
//! and the operations shared by the UI brush and the MCP tools (paint,
//! scatter, grow ivy, erase, export).

use super::*;
use crate::render::foliage::GpuCard;
use eframe::egui_wgpu::wgpu;
use glam::Vec3;
use pigment_core::decal::SurfaceTri;
use pigment_core::foliage::{self, BarkSpec, CellImage, FoliageCell, Mount};
use pigment_core::foliage_set::{self as fs, FoliageSet, IvyOpts, PlaceOpts, ScatterOpts, SurfaceFilter, BUILTIN_ATLAS};
use std::collections::HashMap;
use std::sync::Arc;

/// Resolution of the built-in card atlas.
pub const BUILTIN_RES: u32 = 2048;

/// Cards a foliage layer can use: cell definitions, their UV rects and the
/// atlas pixels.
pub struct AtlasMeta {
    pub key: String,
    pub cells: Vec<FoliageCell>,
    pub uvs: Vec<[f32; 4]>,
    pub size: u32,
    /// RGBA8 sRGB colour, alpha = coverage.
    pub color: Vec<u8>,
    /// RGBA8 sRGB translucency colour.
    pub trans: Vec<u8>,
    /// The full CPU maps (built-in atlas only), for export.
    pub image: Option<CellImage>,
    /// Folder of an exported atlas (its maps are copied on export).
    pub dir: Option<PathBuf>,
    /// Files of an exported atlas: (role, file name).
    pub files: Vec<(String, String)>,
}

impl AtlasMeta {
    pub fn index(&self, name: &str) -> Option<usize> {
        let n = foliage::builtin_alias(name);
        self.cells.iter().position(|c| c.name == n || c.name == name)
    }
    pub fn names(&self) -> Vec<String> {
        self.cells.iter().map(|c| c.name.clone()).collect()
    }
}

fn to_rgba8(img: &CellImage) -> (Vec<u8>, Vec<u8>) {
    let q = |v: f32| (v.clamp(0.0, 1.0) * 255.0).round() as u8;
    let mut c = Vec::with_capacity(img.color.len() * 4);
    let mut t = Vec::with_capacity(img.color.len() * 4);
    for k in 0..img.color.len() {
        let a = img.alpha[k];
        c.extend_from_slice(&[q(img.color[k][0]), q(img.color[k][1]), q(img.color[k][2]), q(a)]);
        let tr = img.translucency[k];
        t.extend_from_slice(&[q(tr[0]), q(tr[1]), q(tr[2]), 255]);
    }
    (c, t)
}

/// The built-in card library as an atlas.
pub fn builtin_atlas() -> AtlasMeta {
    let cells = foliage::builtin_cells();
    let list: Vec<(String, [f32; 2])> = cells.iter().map(|c| (c.name.clone(), c.size_m)).collect();
    let spec = pigment_core::tile::TileSpec::atlas(&list, BUILTIN_RES, 12).expect("builtin atlas packs");
    let uvs: Vec<[f32; 4]> = spec.cells.iter().map(|c| c.uv).collect();
    let img = foliage::render_atlas(&cells, &uvs, BUILTIN_RES);
    let (color, trans) = to_rgba8(&img);
    AtlasMeta { key: BUILTIN_ATLAS.into(), cells, uvs, size: BUILTIN_RES, color, trans, image: Some(img), dir: None, files: vec![] }
}

/// Load an exported foliage atlas from its `<name>_foliage.json`.
pub fn load_atlas(path: &Path, key: &str) -> Result<AtlasMeta, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("couldn't read foliage atlas {}: {e}", path.display()))?;
    let j: serde_json::Value = serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
    let cells: Vec<FoliageCell> = serde_json::from_value(j["cells"].clone()).map_err(|e| format!("{}: `cells`: {e}", path.display()))?;
    let uvs: Vec<[f32; 4]> = serde_json::from_value(j["uvs"].clone()).map_err(|e| format!("{}: `uvs`: {e}", path.display()))?;
    let dir = path.parent().map(Path::to_path_buf).unwrap_or_default();
    let mut files = vec![];
    if let Some(m) = j["maps"].as_object() {
        for (k, v) in m {
            if let Some(f) = v.as_str() {
                files.push((k.clone(), f.to_string()));
            }
        }
    }
    let file = |role: &str| files.iter().find(|(k, _)| k == role).map(|(_, f)| dir.join(f));
    let cpath = file("base_color_alpha").ok_or("foliage atlas has no base_color_alpha map")?;
    let cimg = image::open(&cpath).map_err(|e| format!("{}: {e}", cpath.display()))?.to_rgba8();
    let size = cimg.width().next_power_of_two();
    let cimg = if cimg.width() != size || cimg.height() != size { image::imageops::resize(&cimg, size, size, image::imageops::FilterType::Triangle) } else { cimg };
    let trans = match file("translucency").and_then(|p| image::open(p).ok()) {
        Some(t) => image::imageops::resize(&t.to_rgba8(), size, size, image::imageops::FilterType::Triangle).into_raw(),
        None => vec![0u8; (size * size * 4) as usize],
    };
    Ok(AtlasMeta { key: key.into(), cells, uvs, size, color: cimg.into_raw(), trans, image: None, dir: Some(dir), files })
}

/// Foliage brush settings (UI tool and MCP `paint_foliage`).
#[derive(Clone, Debug)]
pub struct FoliageBrush {
    /// Cells painted (names in the layer's atlas), picked at random.
    pub cells: Vec<String>,
    /// Brush radius in metres.
    pub radius: f32,
    /// Cards per square metre.
    pub density: f32,
    pub scale: (f32, f32),
    /// Upright cards: 0 = along the normal, 1 = straight up.
    pub align: f32,
    pub facing: String,
    pub erase: bool,
    pub seed: u64,
}

impl Default for FoliageBrush {
    fn default() -> Self {
        FoliageBrush { cells: vec!["grass".into()], radius: 0.4, density: 40.0, scale: (0.8, 1.2), align: 0.6, facing: "any".into(), erase: false, seed: 1 }
    }
}

/// Where a mask for scatter comes from.
#[derive(Clone, Debug)]
pub enum MaskSource {
    /// The mask (generator, painted pixels, parts) of a layer.
    Layer(LayerId),
    /// A mask given inline (same shape as a layer's).
    Mask(Box<Mask>),
}

/// A mask read back into texture space: values 0..1 by UV.
pub struct MaskImage {
    pub size: u32,
    pub v: Vec<f32>,
}

impl MaskImage {
    pub fn at(&self, uv: [f32; 2]) -> f32 {
        let n = self.size as f32;
        let x = ((uv[0].rem_euclid(1.0) * n) as u32).min(self.size - 1);
        let y = ((uv[1].rem_euclid(1.0) * n) as u32).min(self.size - 1);
        self.v[(y * self.size + x) as usize]
    }
}

#[derive(Default)]
pub struct FoliageState {
    /// What each generated layer was last drawn from.
    pub generated: HashMap<LayerId, Generated>,
    pub atlases: HashMap<String, Arc<AtlasMeta>>,
    /// The foliage layers the viewport batches were built from.
    synced: Option<Vec<(LayerId, FoliageSet)>>,
    pub brush: FoliageBrush,
    /// Foliage cell editor: the cell being edited (atlas projects).
    pub edit_cell: usize,
    /// Last brush hit (for the UI ring).
    pub hover: Option<(Vec3, Vec3)>,
    /// Time base for the wind preview.
    pub t0: Option<std::time::Instant>,
    /// The foliage tool is active (V).
    pub active: bool,
    /// Where the current stroke last dabbed.
    pub last_dab: Option<Vec3>,
    /// Dabs so far (varies the seed).
    pub dabs: u64,
}

impl FoliageState {
    pub fn mark_generated(&mut self, doc: &Document) {
        self.generated = doc.layers.iter().filter_map(|l| l.generated.clone().map(|g| (l.id, g))).collect();
        self.synced = None;
    }
}

/// Write a CPU image region into a paint layer's channel textures:
/// colour (+coverage), roughness, height and opacity.
fn upload_region(queue: &wgpu::Queue, lt: &crate::render::texset::LayerTex, img: &CellImage, x0: u32, y0: u32, opacity: bool) {
    let (w, h) = (img.w, img.h);
    if w == 0 || h == 0 {
        return;
    }
    let q = |v: f32| (v.clamp(0.0, 1.0) * 255.0).round() as u8;
    let n = (w * h) as usize;
    let mut col = Vec::with_capacity(n * 4);
    let mut rough = Vec::with_capacity(n * 2);
    let mut height: Vec<u16> = Vec::with_capacity(n * 2);
    let mut op = Vec::with_capacity(n * 2);
    for k in 0..n {
        let c = img.color[k];
        col.extend_from_slice(&[q(c[0]), q(c[1]), q(c[2]), 255]);
        rough.extend_from_slice(&[q(img.roughness[k]), 255]);
        height.extend_from_slice(&[half::f16::from_f32(img.height[k] * img.alpha[k].max(0.0).min(1.0)).to_bits(), half::f16::from_f32(1.0).to_bits()]);
        op.extend_from_slice(&[q(img.alpha[k]), 255]);
    }
    let write = |t: &crate::render::gpu::Tex, data: &[u8], bpp: u32| {
        queue.write_texture(
            wgpu::TexelCopyTextureInfo { texture: &t.tex, mip_level: 0, origin: wgpu::Origin3d { x: x0, y: y0, z: 0 }, aspect: wgpu::TextureAspect::All },
            data,
            wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(w * bpp), rows_per_image: Some(h) },
            wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
        );
    };
    write(&lt.ch[Channel::BaseColor.index()], &col, 4);
    write(&lt.ch[Channel::Roughness.index()], &rough, 2);
    write(&lt.ch[Channel::Height.index()], bytemuck::cast_slice(&height), 4);
    if opacity {
        write(&lt.ch[Channel::Opacity.index()], &op, 2);
    }
}

/// CPU height -> OpenGL tangent normal (RGB8), `strength` = slope scale.
pub fn height_to_normal(img: &CellImage, strength: f32) -> Vec<u8> {
    let (w, h) = (img.w as i64, img.h as i64);
    let at = |x: i64, y: i64| img.height[(y.clamp(0, h - 1) * w + x.clamp(0, w - 1)) as usize] * img.alpha[(y.clamp(0, h - 1) * w + x.clamp(0, w - 1)) as usize];
    let mut out = Vec::with_capacity((w * h * 3) as usize);
    for y in 0..h {
        for x in 0..w {
            let dx = (at(x + 1, y) - at(x - 1, y)) * strength;
            let dy = (at(x, y - 1) - at(x, y + 1)) * strength; // +y up the image
            let n = Vec3::new(-dx, -dy, 1.0).normalize();
            out.extend_from_slice(&[((n.x * 0.5 + 0.5) * 255.0) as u8, ((n.y * 0.5 + 0.5) * 255.0) as u8, ((n.z * 0.5 + 0.5) * 255.0) as u8]);
        }
    }
    out
}

impl PigmentApp {
    /// Redraw generated paint layers whose generator changed (including
    /// after undo / redo, which restore the old generator).
    pub(super) fn sync_generated(&mut self, rs: &RenderState) {
        let res = self.ts.res;
        let mut changed = false;
        for l in &self.doc.layers {
            let (Some(g), Some(r)) = (&l.generated, l.paint_res()) else { continue };
            let prev = self.foliage.generated.get(&l.id);
            if prev == Some(g) {
                continue;
            }
            let Some(lt) = self.ts.layers.get(&r) else { continue };
            match g {
                Generated::FoliageCells { cells } => {
                    let Some(tile) = &self.doc.tile else { continue };
                    let old = match prev {
                        Some(Generated::FoliageCells { cells }) => Some(cells),
                        _ => None,
                    };
                    for (i, (c, sc)) in cells.iter().zip(&tile.cells).enumerate() {
                        if old.and_then(|o| o.get(i)) == Some(c) {
                            continue;
                        }
                        let rc = foliage::cell_rect(sc.uv, res);
                        let img = foliage::render_cell(c, rc[2] - rc[0], rc[3] - rc[1]);
                        upload_region(&rs.queue, lt, &img, rc[0], rc[1], true);
                    }
                }
                Generated::Bark { bark } => {
                    let size = self.doc.tile.as_ref().map(|t| t.size_m).unwrap_or([1.0, 1.0]);
                    let img = foliage::render_bark(bark, size, res, res);
                    upload_region(&rs.queue, lt, &img, 0, 0, false);
                }
            }
            self.ts.unsaved.insert(r);
            self.foliage.generated.insert(l.id, g.clone());
            changed = true;
        }
        if changed {
            self.composited = None;
        }
    }

    /// The atlas a foliage set uses (loaded / generated once).
    pub(super) fn foliage_atlas(&mut self, key: &str) -> Result<Arc<AtlasMeta>, String> {
        if let Some(a) = self.foliage.atlases.get(key) {
            return Ok(a.clone());
        }
        let meta = if key == BUILTIN_ATLAS {
            builtin_atlas()
        } else {
            let p = Path::new(key);
            let p = if p.is_relative() {
                self.image_bases().iter().flat_map(|b| b.ancestors().map(|a| a.join(p)).collect::<Vec<_>>()).find(|c| c.exists()).unwrap_or_else(|| p.to_path_buf())
            } else {
                p.to_path_buf()
            };
            load_atlas(&p, key)?
        };
        let a = Arc::new(meta);
        self.foliage.atlases.insert(key.to_string(), a.clone());
        Ok(a)
    }

    /// Rebuild the viewport's card batches when the foliage layers changed.
    pub(super) fn sync_foliage_gpu(&mut self, rs: &RenderState) {
        let now: Vec<(LayerId, FoliageSet)> = self
            .doc
            .layers
            .iter()
            .filter(|l| self.doc.effectively_visible(l.id))
            .filter_map(|l| l.foliage().map(|f| (l.id, f.clone())))
            .collect();
        if self.foliage.synced.as_ref() == Some(&now) {
            return;
        }
        let mut batches: HashMap<String, Vec<GpuCard>> = HashMap::new();
        for (_, set) in &now {
            if set.instances.is_empty() {
                continue;
            }
            let meta = match self.foliage_atlas(&set.atlas) {
                Ok(m) => m,
                Err(e) => {
                    log::error!("{e}");
                    continue;
                }
            };
            if !self.viewport.foliage.has_atlas(&meta.key) {
                self.viewport.foliage.upload_atlas(&rs.device, &rs.queue, &meta.key, &meta.color, &meta.trans, meta.size);
            }
            let idx: Vec<Option<usize>> = set.cells.iter().map(|c| meta.index(c)).collect();
            let list = batches.entry(meta.key.clone()).or_default();
            for (k, inst) in set.instances.iter().enumerate() {
                let Some(Some(ci)) = idx.get(inst.c as usize) else { continue };
                let uv = meta.uvs[*ci];
                let mount = match inst.mount {
                    Mount::Upright => 0.0,
                    Mount::Flat => 1.0,
                    Mount::Wall => 2.0,
                    Mount::Hanging => 3.0,
                };
                let phase = (k as f32 * 2.399).rem_euclid(6.283);
                for x in inst.quad_x() {
                    list.push(GpuCard { p: inst.p, x: x.into(), y: inst.y, uv, misc: [mount, set.wind, phase, 0.0] });
                }
            }
        }
        self.viewport.foliage.set_batches(&rs.device, batches.into_iter().collect());
        self.foliage.synced = Some(now);
    }

    /// Topmost foliage layer named `name` (or any), created on top if missing.
    pub(super) fn foliage_layer(&mut self, name: Option<&str>, create: bool) -> Result<usize, String> {
        let found = match name {
            Some(n) => self.doc.layers.iter().rposition(|l| l.is_foliage() && l.name.eq_ignore_ascii_case(n)),
            None => self.doc.layers.iter().rposition(|l| l.is_foliage()),
        };
        if let Some(i) = found {
            return Ok(i);
        }
        if let Some(n) = name {
            if self.doc.layers.iter().any(|l| l.name.eq_ignore_ascii_case(n)) {
                return Err(format!("`layer` = \"{n}\" is not a foliage layer"));
            }
        }
        if !create {
            return Err("no foliage layer (paint or scatter some foliage first)".into());
        }
        let l = self.doc.new_foliage_layer(name.unwrap_or("Foliage"));
        self.doc.layers.push(l);
        Ok(self.doc.layers.len() - 1)
    }

    /// Cell names -> (palette index, weight) in the layer's set, checking the atlas.
    pub(super) fn foliage_cells(&mut self, i: usize, names: &[(String, f32)]) -> Result<(Vec<(u16, f32)>, Vec<FoliageCell>), String> {
        let key = self.doc.layers[i].foliage().map(|f| f.atlas.clone()).unwrap_or_else(|| BUILTIN_ATLAS.into());
        let meta = self.foliage_atlas(&key)?;
        let set = self.doc.layers[i].foliage_mut().ok_or("not a foliage layer")?;
        let mut out = vec![];
        for (n, w) in names {
            let ci = meta.index(n).ok_or_else(|| format!("unknown foliage cell `{n}` (atlas `{key}` has: {})", meta.names().join(", ")))?;
            out.push((set.cell_index(&meta.cells[ci].name), *w));
        }
        // definitions indexed like the palette
        let defs: Vec<FoliageCell> = set.cells.iter().map(|c| meta.index(c).map(|k| meta.cells[k].clone()).unwrap_or_else(|| meta.cells[0].clone())).collect();
        Ok((out, defs))
    }

    /// Read a mask back into texture space by compositing it alone (white
    /// through the mask over black), then restore the real composite.
    pub(super) fn mask_image(&mut self, rs: &RenderState, src: &MaskSource) -> Result<MaskImage, String> {
        let mask = match src {
            MaskSource::Layer(id) => self.doc.layer(*id).and_then(|l| l.mask.clone()).ok_or("that layer has no mask")?,
            MaskSource::Mask(m) => (**m).clone(),
        };
        let mut tmp = Document { layers: vec![], tile: self.doc.tile.clone(), variants: self.doc.variants.clone(), ..Document::default() };
        tmp.next_id = self.doc.next_id + 10;
        let mut black = tmp.fill_with("black", "Matte black", None);
        if let LayerKind::Fill { values } = &mut black.kind {
            values.base_color = [0.0; 3];
        }
        let mut white = tmp.fill_with("white", "White plastic", None);
        if let LayerKind::Fill { values } = &mut white.kind {
            values.base_color = [1.0; 3];
        }
        white.mask = Some(mask);
        tmp.layers = vec![black, white];
        self.ts.ensure_resources(&rs.device, &rs.queue, &self.doc);
        self.ts.composite(&rs.device, &rs.queue, &tmp, None);
        let px = crate::render::gpu::readback(&rs.device, &rs.queue, &self.ts.material[0]);
        self.composited = None;
        self.ensure_composited(rs);
        let v = px.chunks_exact(4).map(|c| pigment_core::blend::srgb_to_linear(c[0] as f32 / 255.0)).collect();
        Ok(MaskImage { size: self.ts.res, v })
    }

    /// Baked AO (bakes.r) by UV.
    pub(super) fn ao_image(&mut self, rs: &RenderState) -> MaskImage {
        let raw = crate::render::gpu::readback(&rs.device, &rs.queue, &self.ts.bakes);
        let v = raw.chunks_exact(8).map(|c| half::f16::from_bits(u16::from_le_bytes([c[0], c[1]])).to_f32()).collect();
        MaskImage { size: self.ts.bakes.size, v }
    }

    /// Paint foliage at surface points (brush dabs) on layer `i`. Returns
    /// cards added (or removed when erasing).
    pub(super) fn foliage_paint(&mut self, i: usize, hits: &[(Vec3, Vec3)], b: &FoliageBrush, extra: &dyn Fn(&SurfaceTri, Vec3, Vec3) -> f32, filter: SurfaceFilter) -> Result<usize, String> {
        if b.erase {
            let only: Option<Vec<u16>> = if b.cells.is_empty() {
                None
            } else {
                let set = self.doc.layers[i].foliage().ok_or("not a foliage layer")?;
                Some(set.cells.iter().enumerate().filter(|(_, c)| b.cells.iter().any(|n| foliage::builtin_alias(n) == c.as_str() || n == *c)).map(|(k, _)| k as u16).collect())
            };
            let pts: Vec<Vec3> = hits.iter().map(|h| h.0).collect();
            let set = self.doc.layers[i].foliage_mut().ok_or("not a foliage layer")?;
            return Ok(set.erase(&pts, b.radius, if b.cells.is_empty() { None } else { only.as_deref() }));
        }
        let names: Vec<(String, f32)> = b.cells.iter().map(|c| (c.clone(), 1.0)).collect();
        let (cells, defs) = self.foliage_cells(i, &names)?;
        let spacing = (1.0 / b.density.max(0.01)).sqrt() * 0.6;
        let area = std::f32::consts::PI * b.radius * b.radius;
        let per_dab = ((b.density * area * 0.6).ceil() as usize).max(1);
        let mut added = 0;
        for (k, (p, _)) in hits.iter().enumerate() {
            let o = ScatterOpts {
                cells: cells.clone(),
                defs: &defs,
                count: per_dab,
                seed: b.seed.wrapping_mul(1_000_003).wrapping_add(k as u64 * 7919 + self.doc.layers[i].foliage().map(|f| f.instances.len()).unwrap_or(0) as u64),
                filter: filter.clone(),
                min_spacing: spacing,
                place: PlaceOpts { scale: b.scale, align: b.align, ..Default::default() },
            };
            let existing = self.doc.layers[i].foliage().map(|f| f.instances.clone()).unwrap_or_default();
            let new = fs::paint_dab(&self.mesh, &self.parts, *p, b.radius, &o, &existing, extra);
            added += new.len();
            self.doc.layers[i].foliage_mut().unwrap().instances.extend(new);
        }
        Ok(added)
    }

    /// Grow ivy on layer `i` from surface points.
    pub(super) fn foliage_ivy(&mut self, i: usize, starts: &[(Vec3, Vec3)], leaf: &str, stem: Option<&str>, o: &IvyOpts, filter: &SurfaceFilter) -> Result<fs::IvyResult, String> {
        let mut names = vec![(leaf.to_string(), 1.0)];
        if let Some(s) = stem {
            names.push((s.to_string(), 1.0));
        }
        let (cells, defs) = self.foliage_cells(i, &names)?;
        let grid = fs::TriGrid::new(&self.mesh, &self.parts, filter, (o.step * 4.0).max(0.15));
        let leaf_def = defs[cells[0].0 as usize].clone();
        let stem_def = stem.map(|_| defs[cells[1].0 as usize].clone());
        let r = fs::grow_ivy(&grid, starts, (cells[0].0, &leaf_def), stem_def.as_ref().map(|d| (cells[1].0, d)), o);
        self.doc.layers[i].foliage_mut().unwrap().instances.extend(r.instances.iter().copied());
        Ok(r)
    }

    /// Write every visible foliage layer: per atlas a card glb, an instance
    /// list (Godot MultiMesh) and the atlas maps, plus a `material.json`
    /// entry for the Blender add-on. Returns the files written.
    pub(super) fn export_foliage_to(&mut self, dir: &Path, name: &str, only: Option<LayerId>) -> Result<(Vec<PathBuf>, serde_json::Value), String> {
        std::fs::create_dir_all(dir).map_err(|e| format!("couldn't create {}: {e}", dir.display()))?;
        // merge visible layers by atlas
        let mut by_atlas: Vec<(String, FoliageSet)> = Vec::new();
        for l in &self.doc.layers {
            let Some(set) = l.foliage() else { continue };
            if only.is_some_and(|o| o != l.id) || (only.is_none() && !self.doc.effectively_visible(l.id)) || set.instances.is_empty() {
                continue;
            }
            let pos = match by_atlas.iter().position(|(k, _)| *k == set.atlas) {
                Some(p) => p,
                None => {
                    by_atlas.push((set.atlas.clone(), FoliageSet { atlas: set.atlas.clone(), ..Default::default() }));
                    by_atlas.len() - 1
                }
            };
            let merged = &mut by_atlas[pos].1;
            merged.wind = merged.wind.max(set.wind);
            for inst in &set.instances {
                let mut i2 = *inst;
                i2.c = merged.cell_index(&set.cells[inst.c as usize]);
                merged.instances.push(i2);
            }
        }
        if by_atlas.is_empty() {
            return Err("nothing to export: no visible foliage layer has cards".into());
        }
        let mut files = vec![];
        let mut summary = vec![];
        let multi = by_atlas.len() > 1;
        for (k, (key, set)) in by_atlas.iter().enumerate() {
            let meta = self.foliage_atlas(key)?;
            let base = if multi { format!("{name}_foliage{k}") } else { format!("{name}_foliage") };
            let uvs: Vec<Option<[f32; 4]>> = set.cells.iter().map(|c| meta.index(c).map(|i| meta.uvs[i])).collect();
            let defs: Vec<Option<&FoliageCell>> = set.cells.iter().map(|c| meta.index(c).map(|i| &meta.cells[i])).collect();
            // atlas maps
            let mut maps = serde_json::Map::new();
            let save = |img: image::DynamicImage, suffix: &str, files: &mut Vec<PathBuf>| -> Result<String, String> {
                let f = format!("{base}_{suffix}.png");
                let p = dir.join(&f);
                img.save(&p).map_err(|e| format!("couldn't write {}: {e}", p.display()))?;
                files.push(p);
                Ok(f)
            };
            if let Some(img) = &meta.image {
                let s = img.w;
                let q = |v: f32| (v.clamp(0.0, 1.0) * 255.0).round() as u8;
                let c = image::RgbaImage::from_raw(s, s, meta.color.clone()).ok_or("atlas size")?;
                maps.insert("base_color_alpha".into(), save(c.into(), "BaseColorAlpha", &mut files)?.into());
                let t = image::RgbImage::from_raw(s, s, meta.trans.chunks_exact(4).flat_map(|p| [p[0], p[1], p[2]]).collect()).ok_or("atlas size")?;
                maps.insert("translucency".into(), save(t.into(), "Translucency", &mut files)?.into());
                let n = image::RgbImage::from_raw(s, s, height_to_normal(img, s as f32 / 64.0)).ok_or("atlas size")?;
                maps.insert("normal".into(), save(n.into(), "Normal_OpenGL", &mut files)?.into());
                let r = image::GrayImage::from_raw(s, s, img.roughness.iter().map(|v| q(*v)).collect()).ok_or("atlas size")?;
                maps.insert("roughness".into(), save(r.into(), "Roughness", &mut files)?.into());
                let th = image::GrayImage::from_raw(s, s, img.thickness.iter().map(|v| q(*v)).collect()).ok_or("atlas size")?;
                maps.insert("thickness".into(), save(th.into(), "Thickness", &mut files)?.into());
            } else if let Some(src) = &meta.dir {
                for (role, f) in &meta.files {
                    let from = src.join(f);
                    let suffix = f.rsplit_once('_').map(|(_, s)| s.trim_end_matches(".png").to_string()).unwrap_or_else(|| role.clone());
                    let out = format!("{base}_{suffix}.png");
                    std::fs::copy(&from, dir.join(&out)).map_err(|e| format!("couldn't copy {}: {e}", from.display()))?;
                    files.push(dir.join(&out));
                    maps.insert(role.clone(), out.into());
                }
            }
            let mesh = fs::card_mesh(set, &uvs, &base);
            let glb = dir.join(format!("{base}.glb"));
            pigment_core::bridge::write_glb(&mesh, &glb).map_err(|e| format!("couldn't write {}: {e:#}", glb.display()))?;
            files.push(glb.clone());
            let mut j = fs::instances_json(set, &uvs, &defs);
            j["maps"] = serde_json::Value::Object(maps.clone());
            j["glb"] = json_str(&format!("{base}.glb"));
            j["wind"] = serde_json::json!(set.wind);
            let jp = dir.join(format!("{base}_instances.json"));
            std::fs::write(&jp, serde_json::to_string(&j).unwrap()).map_err(|e| format!("couldn't write {}: {e}", jp.display()))?;
            files.push(jp);
            // Blender add-on: a foliage material entry (alpha clip, two-sided, translucency)
            let entry = serde_json::json!({
                "name": base, "kind": "foliage", "preset": "foliage",
                "mesh": format!("{base}.glb"), "instances": format!("{base}_instances.json"),
                "maps": maps, "alpha_clip": 0.5, "two_sided": true,
                "translucency": maps.contains_key("translucency"),
                "normal_convention": "opengl", "cards": set.instances.len(),
            });
            pigment_core::bridge::update_sidecar(dir, &base, &entry).map_err(|e| format!("{e:#}"))?;
            summary.push(serde_json::json!({ "name": base, "atlas": key, "cards": set.instances.len(), "quads": mesh.indices.len() / 6, "cells": set.cells, "counts": set.counts() }));
        }
        Ok((files, serde_json::Value::Array(summary)))
    }

    /// Foliage atlas projects: translucency and thickness maps (CPU, from the
    /// cell generators) and `<name>_foliage.json` for foliage layers on other
    /// projects. `alpha` is the exported opacity (so holes painted on top
    /// count). Returns the files written.
    pub(super) fn export_foliage_atlas_extras(&mut self, dir: &Path, name: &str, alpha: &[u8], targets: &[&str]) -> Result<Vec<PathBuf>, String> {
        let Some(cells) = self.doc.layers.iter().find_map(|l| match &l.generated {
            Some(Generated::FoliageCells { cells }) => Some(cells.clone()),
            _ => None,
        }) else {
            return Ok(vec![]);
        };
        let Some(tile) = self.doc.tile.clone() else { return Ok(vec![]) };
        let res = self.doc.resolution;
        let uvs: Vec<[f32; 4]> = tile.cells.iter().map(|c| c.uv).collect();
        let img = foliage::render_atlas(&cells, &uvs, res);
        let mut files = vec![];
        let q = |v: f32| (v.clamp(0.0, 1.0) * 255.0).round() as u8;
        let n = (res * res) as usize;
        let a = |k: usize| alpha.get(k * 4 + 3).copied().unwrap_or(255) as f32 / 255.0;
        let trans: Vec<u8> = (0..n).flat_map(|k| img.translucency[k].map(|v| q(v * a(k)))).collect();
        let thick: Vec<u8> = (0..n).map(|k| q(img.thickness[k])).collect();
        let w = |f: String, im: image::DynamicImage, files: &mut Vec<PathBuf>| -> Result<(), String> {
            let p = dir.join(&f);
            im.save(&p).map_err(|e| format!("couldn't write {}: {e}", p.display()))?;
            files.push(p);
            Ok(())
        };
        let ti = image::RgbImage::from_raw(res, res, trans).ok_or("size")?;
        w(format!("{name}_Translucency.png"), ti.clone().into(), &mut files)?;
        w(format!("{name}_Thickness.png"), image::GrayImage::from_raw(res, res, thick).ok_or("size")?.into(), &mut files)?;
        // engine packs
        for t in targets {
            match *t {
                "godot" => w(format!("{name}_backlight.png"), ti.clone().into(), &mut files)?,
                "unreal" => w(format!("{name}_SubsurfaceColor.png"), ti.clone().into(), &mut files)?,
                _ => {}
            }
        }
        let meta = serde_json::json!({
            "format": "pigment-foliage-atlas", "version": 1, "name": name, "resolution": res,
            "cells": cells, "uvs": uvs,
            "maps": {
                "base_color_alpha": format!("{name}_BaseColorAlpha.png"),
                "translucency": format!("{name}_Translucency.png"),
                "thickness": format!("{name}_Thickness.png"),
            },
        });
        let mp = dir.join(format!("{name}_foliage.json"));
        std::fs::write(&mp, serde_json::to_string_pretty(&meta).unwrap()).map_err(|e| format!("couldn't write {}: {e}", mp.display()))?;
        files.push(mp);
        Ok(files)
    }
}

impl PigmentApp {
    /// One click plants: "moss", "ivy", "grass" or "leaves" on the whole
    /// model, each into its own foliage layer. Returns the cards added.
    pub(super) fn quick_foliage(&mut self, rs: &RenderState, kind: &str) -> Result<usize, String> {
        self.commit_doc_changes();
        let (lo, hi) = self.mesh.bounds();
        let height = (hi.y - lo.y).max(0.1);
        let ao = if self.ts.baked { Some(self.ao_image(rs)) } else { None };
        let uvs: Vec<[f32; 2]> = self.mesh.vertices.iter().map(|v| v.uv).collect();
        let idx = self.mesh.indices.clone();
        let ao_max = match kind {
            "grass" | "leaves" => 0.95,
            _ => 1.0,
        };
        let accept = move |st: &SurfaceTri, bary: Vec3, _p: Vec3| -> f32 {
            let Some(img) = &ao else { return 1.0 };
            let t = &idx[st.tri * 3..st.tri * 3 + 3];
            let uv = [0, 1, 2].iter().fold([0.0f32; 2], |a, &k| [a[0] + uvs[t[k] as usize][0] * bary[k], a[1] + uvs[t[k] as usize][1] * bary[k]]);
            // crevices (low AO) are likelier
            let v = img.at(uv);
            if v > ao_max {
                0.0
            } else {
                (1.15 - v).clamp(0.2, 1.0)
            }
        };
        let (cells, facing, scale) = quick_cells(kind);
        let name = match kind {
            "moss" => "Moss",
            "grass" => "Grass",
            "leaves" => "Fallen leaves",
            _ => "Ivy",
        };
        let i = self.foliage_layer(Some(name), true)?;
        let before = self.doc.layers[i].foliage().map(|f| f.instances.len()).unwrap_or(0);
        if kind == "ivy" {
            // start along the bottom of the walls
            let sampler = pigment_core::decal::SurfaceSampler::new(&self.mesh, |_, v, n| n.y.abs() < 0.3 && v.iter().any(|p| p.y < lo.y + 0.4));
            let mut rng = pigment_core::decal::Rng::new(self.foliage.dabs + 17);
            let mut starts: Vec<(Vec3, Vec3)> = vec![];
            for _ in 0..400 {
                if starts.len() >= 4 {
                    break;
                }
                let Some((st, p, _)) = sampler.sample(&mut rng) else { break };
                if p.y < lo.y + 0.4 && starts.iter().all(|s| s.0.distance(p) > 1.5) {
                    starts.push((p, st.n));
                }
            }
            if starts.is_empty() {
                return Err("no wall meets the ground on this model".into());
            }
            let o = IvyOpts { length: (height * 0.5).clamp(1.0, 8.0), seed: self.foliage.dabs + 3, ..Default::default() };
            self.foliage.dabs += 1;
            self.foliage_ivy(i, &starts, "ivy_leaf", Some("ivy_stem"), &o, &SurfaceFilter::default())?;
        } else {
            let names: Vec<(String, f32)> = cells.iter().map(|c| (c.to_string(), 1.0)).collect();
            let (cells, defs) = self.foliage_cells(i, &names)?;
            let mut filter = SurfaceFilter { up: SurfaceFilter::facing(facing).unwrap_or((-1.0, 1.0)), ..Default::default() };
            if kind == "grass" || kind == "leaves" {
                // the ground and the lowest ledges
                filter.region = Some((lo - Vec3::splat(1.0), Vec3::new(hi.x + 1.0, lo.y + height.min(1.5), hi.z + 1.0)));
            }
            let area = fs::surface_area(&self.mesh, &self.parts, &filter);
            let per_m2 = match kind {
                "moss" => 18.0,
                "grass" => 30.0,
                _ => 6.0,
            };
            let count = ((area * per_m2) as usize).clamp(50, 20000);
            let o = ScatterOpts { cells, defs: &defs, count, seed: self.foliage.dabs + 5, filter, min_spacing: 0.0, place: PlaceOpts { scale, ..Default::default() } };
            self.foliage.dabs += 1;
            let existing = self.doc.layers[i].foliage().map(|f| f.instances.clone()).unwrap_or_default();
            let got = fs::scatter(&self.mesh, &self.parts, &o, &existing, &accept);
            self.doc.layers[i].foliage_mut().unwrap().instances.extend(got);
        }
        let after = self.doc.layers[i].foliage().map(|f| f.instances.len()).unwrap_or(0);
        let label = format!("Add {name}");
        if self.doc != self.committed {
            let before_doc = Box::new(std::mem::replace(&mut self.committed, self.doc.clone()));
            self.push_history(label, Edit::Doc { before: before_doc, after: Box::new(self.doc.clone()) });
        }
        Ok(after - before)
    }
}

fn json_str(s: &str) -> serde_json::Value {
    serde_json::Value::String(s.to_string())
}

/// Default cell per quick action ("Add moss / ivy / grass").
pub fn quick_cells(kind: &str) -> (&'static [&'static str], &'static str, (f32, f32)) {
    match kind {
        "moss" => (&["moss", "moss_patch"], "up", (0.7, 1.0)),
        "grass" => (&["grass", "weed"], "up", (0.85, 1.0)),
        "leaves" => (&["fallen_leaves", "maple_leaf", "ginkgo_leaf"], "up", (0.75, 1.0)),
        _ => (&["ivy_leaf"], "walls", (-0.35, 0.35)),
    }
}

pub fn bark_spec(style: &str) -> Option<BarkSpec> {
    foliage::BarkStyle::from_id(style).map(BarkSpec::for_style)
}
