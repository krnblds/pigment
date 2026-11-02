//! High-to-low baking in the app (`pigment_core::hibake`): bake a high-poly
//! mesh onto the project mesh, write the maps as PNGs, and apply them:
//! AO + curvature become the mesh bakes generators read, the tangent normal
//! becomes a "Baked normal" fill layer, the color / material ID map feeds ID
//! masks.

use super::*;
use pigment_core::hibake::{self, BakeMap, HighBake};

/// Name of the fill layer that carries the baked normal map.
pub const BAKED_NORMAL_LAYER: &str = "Baked normal";

/// What a high bake did.
pub struct HighBakeReport {
    pub files: Vec<(BakeMap, PathBuf)>,
    pub cage: f32,
    pub hit_rate: f32,
    pub ms: f64,
}

fn file_name(mesh: &str, m: BakeMap) -> String {
    format!("{mesh}_{}.png", m.id())
}

/// Write one baked map as PNG: 16-bit grey (AO, curvature, height,
/// thickness), 16-bit RGB (position), 8-bit RGB (normals, IDs).
fn write_map(path: &Path, m: &hibake::BakedMap) -> Result<(), String> {
    let n = m.size;
    let rgb16 = |f: &dyn Fn(&[f32]) -> [u16; 3]| -> image::ImageBuffer<image::Rgb<u16>, Vec<u16>> {
        image::ImageBuffer::from_fn(n, n, |x, y| {
            let i = ((y * n + x) * 4) as usize;
            image::Rgb(f(&m.rgba[i..i + 4]))
        })
    };
    let q16 = |v: f32| (v.clamp(0.0, 1.0) * 65535.0).round() as u16;
    let q8 = |v: f32| (v.clamp(0.0, 1.0) * 255.0).round() as u8;
    let r = match m.map {
        BakeMap::Ao | BakeMap::Curvature | BakeMap::Height | BakeMap::Thickness => {
            image::ImageBuffer::<image::Luma<u16>, Vec<u16>>::from_fn(n, n, |x, y| image::Luma([q16(m.rgba[((y * n + x) * 4) as usize])])).save(path)
        }
        BakeMap::Position => rgb16(&|p| [q16(p[0]), q16(p[1]), q16(p[2])]).save(path),
        _ => image::RgbImage::from_fn(n, n, |x, y| {
            let i = ((y * n + x) * 4) as usize;
            image::Rgb([q8(m.rgba[i]), q8(m.rgba[i + 1]), q8(m.rgba[i + 2])])
        })
        .save(path),
    };
    r.map_err(|e| format!("writing {}: {e}", path.display()))
}

impl PigmentApp {
    /// Where high bakes go: `<project>/bakes`, else a temp folder per mesh.
    pub(super) fn bake_dir(&self) -> PathBuf {
        match &self.project_dir {
            Some(d) => d.join("bakes"),
            None => std::env::temp_dir().join("pigment-bakes").join(&self.mesh.name),
        }
    }

    fn resolve_bake_dir(&self, hb: &HighBake) -> PathBuf {
        if hb.dir.is_empty() {
            return self.bake_dir();
        }
        let p = PathBuf::from(&hb.dir);
        if p.is_absolute() {
            p
        } else {
            self.project_dir.clone().unwrap_or_default().join(p)
        }
    }

    /// Bake `high` onto the project mesh with `hb`, write the maps and apply
    /// them (AO / curvature, baked normal layer, ID map).
    pub(super) fn bake_high(&mut self, rs: &RenderState, high: Option<&Mesh>, mut hb: HighBake, apply_normal: bool) -> Result<HighBakeReport, String> {
        if high.is_none() && hb.maps.iter().any(|m| m.needs_high()) {
            return Err("these maps need `high_mesh`".into());
        }
        let t0 = Instant::now();
        let res = self.doc.resolution;
        let out = hibake::bake(&self.mesh, high, res, &hb);
        let dir = self.resolve_bake_dir(&hb);
        std::fs::create_dir_all(&dir).map_err(|e| format!("creating {}: {e}", dir.display()))?;
        let mut files = Vec::new();
        for m in &out.maps {
            let p = dir.join(file_name(&self.mesh.name, m.map));
            write_map(&p, m)?;
            files.push((m.map, p));
        }
        // store the folder relative to the project when possible
        hb.dir = match &self.project_dir {
            Some(pd) => dir.strip_prefix(pd).map(|r| r.to_string_lossy().replace('\\', "/")).unwrap_or_else(|_| dir.to_string_lossy().into_owned()),
            None => dir.to_string_lossy().into_owned(),
        };
        if hb.cage.is_none() {
            log::info!("high bake: automatic cage {:.4} m", out.cage);
        }
        // AO / curvature into the mesh bakes
        self.apply_high_maps(rs, &out.maps);
        // ID map: the high mesh's colour ID, else the low material ID
        let id = files.iter().find(|(m, _)| *m == BakeMap::ColorId).or_else(|| files.iter().find(|(m, _)| *m == BakeMap::MaterialId));
        if let Some((_, p)) = id {
            self.doc.id_map = Some(self.project_relative(p));
        }
        // the tangent normal as a fill layer at the bottom of the stack
        if let Some((_, p)) = files.iter().find(|(m, _)| *m == BakeMap::Normal).filter(|_| apply_normal) {
            let path = self.project_relative(p);
            self.ts.tiles.forget(&path);
            let i = match self.doc.layers.iter().position(|l| l.name == BAKED_NORMAL_LAYER) {
                Some(i) => i,
                None => {
                    let mut l = self.doc.new_fill_layer(BAKED_NORMAL_LAYER);
                    for c in Channel::ALL {
                        l.channels.get_mut(c).enabled = c == Channel::Normal;
                    }
                    self.doc.layers.insert(0, l);
                    0
                }
            };
            let mut f = pigment_core::ImageFill::default();
            *f.images.get_mut(pigment_core::ImageChannel::Normal) = Some(path);
            self.doc.layers[i].image = Some(f);
        }
        self.doc.bake.high = Some(hb);
        self.load_id_map(rs);
        self.composited = None;
        Ok(HighBakeReport { files, cage: out.cage, hit_rate: out.hit_rate, ms: t0.elapsed().as_secs_f64() * 1000.0 })
    }

    fn project_relative(&self, p: &Path) -> String {
        match &self.project_dir {
            Some(pd) => p.strip_prefix(pd).map(|r| r.to_string_lossy().replace('\\', "/")).unwrap_or_else(|_| p.to_string_lossy().into_owned()),
            None => p.to_string_lossy().into_owned(),
        }
    }

    fn apply_high_maps(&mut self, rs: &RenderState, maps: &[hibake::BakedMap]) {
        let ao = maps.iter().find(|m| m.map == BakeMap::Ao);
        let cv = maps.iter().find(|m| m.map == BakeMap::Curvature);
        if ao.is_none() && cv.is_none() {
            return;
        }
        let res = ao.or(cv).unwrap().size;
        let n = (res * res) as usize;
        let rg: Vec<[f32; 2]> = (0..n).map(|i| [ao.map(|m| m.rgba[i * 4]).unwrap_or(1.0), cv.map(|m| m.rgba[i * 4]).unwrap_or(0.5)]).collect();
        if res == self.ts.res {
            self.ts.apply_high_bakes(&rs.device, &rs.queue, &rg, res);
        }
    }

    /// Re-apply a stored high bake's AO / curvature files (after the mesh
    /// bake runs again, e.g. on open) and load the ID map.
    pub(super) fn apply_high_bake_files(&mut self, rs: &RenderState) {
        if let Some(hb) = self.doc.bake.high.clone() {
            let dir = self.resolve_bake_dir(&hb);
            let res = self.ts.res;
            let read = |m: BakeMap| -> Option<hibake::BakedMap> {
                let img = image::open(dir.join(file_name(&self.mesh.name, m))).ok()?.to_luma16();
                if img.width() != res {
                    return None;
                }
                Some(hibake::BakedMap { map: m, size: res, rgba: img.pixels().flat_map(|p| [p.0[0] as f32 / 65535.0, 0.0, 0.0, 1.0]).collect() })
            };
            let maps: Vec<hibake::BakedMap> = [BakeMap::Ao, BakeMap::Curvature].into_iter().filter(|m| hb.maps.contains(m)).filter_map(read).collect();
            self.apply_high_maps(rs, &maps);
        }
        self.load_id_map(rs);
    }

    /// Upload the document's ID map (or clear it).
    pub(super) fn load_id_map(&mut self, rs: &RenderState) {
        let img = self.doc.id_map.as_ref().and_then(|p| pigment_core::image_fill::resolve_path(p, &self.image_bases())).and_then(|p| image::open(p).ok()).map(|i| i.to_rgba8());
        match img {
            Some(i) => self.ts.set_id_map(&rs.device, &rs.queue, Some((i.as_raw(), i.width(), i.height()))),
            None => self.ts.set_id_map(&rs.device, &rs.queue, None),
        }
        self.composited = None;
    }
}
