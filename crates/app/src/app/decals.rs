//! World-space decals on the GPU: precise placement on a surface and
//! scatters, with tear / fade wear (see `decal_box.wgsl` and
//! `pigment_core::decal`). Several decals placed together are one undo step.

use super::*;
use crate::render::paint::BoxDecalGpu;
use pigment_core::decal::Placement;

/// How a decal looks once stuck on: opacity and weathering.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DecalLook {
    pub opacity: f32,
    pub luminance_alpha: bool,
    /// 0 = intact, 1 = mostly torn away.
    pub tear: f32,
    /// 0 = fresh, 1 = badly sun-bleached and worn through.
    pub fade: f32,
    /// Noise frequency across the decal (higher = smaller rips and patches).
    pub wear_scale: f32,
    pub seed: f32,
    /// Ridged, streaky "grunge" noise instead of soft noise.
    pub grunge: bool,
    /// Width of the bare-paper rim along tears (0 = none).
    pub paper_rim: f32,
    /// Surfaces facing the decal less than this (cosine) are skipped.
    pub min_facing: f32,
}

impl Default for DecalLook {
    fn default() -> Self {
        Self { opacity: 1.0, luminance_alpha: false, tear: 0.0, fade: 0.0, wear_scale: 5.0, seed: 0.0, grunge: false, paper_rim: 0.035, min_facing: 0.2 }
    }
}

/// One decal to stick on.
#[derive(Clone, Debug)]
pub struct BoxDecal {
    pub image: PathBuf,
    pub placement: Placement,
    pub look: DecalLook,
    /// Box (planar), triplanar or wrap (conform) projection.
    pub projection: pigment_core::decal_layer::DecalProjection,
}

impl BoxDecal {
    pub fn gpu(&self) -> BoxDecalGpu {
        let p = &self.placement;
        let l = &self.look;
        let v = |a: glam::Vec3, w: f32| [a.x, a.y, a.z, w];
        BoxDecalGpu {
            center: v(p.center, p.depth),
            right: v(p.right, p.size.x * 0.5),
            up: v(p.up, p.size.y * 0.5),
            normal: v(p.normal, l.opacity),
            params: [l.luminance_alpha as u32 as f32, l.min_facing, self.projection.gpu_id() as f32, 0.0],
            wear: [l.tear.clamp(0.0, 1.0), l.fade.clamp(0.0, 1.0), l.wear_scale.max(0.01), l.seed],
            wear2: [l.grunge as u32 as f32, l.paper_rim.max(0.0), 0.0, 0.0],
        }
    }
}

impl PigmentApp {
    /// Stick decals onto the selected layer (or its mask), in order, so later
    /// ones go over earlier ones. Colour comes from each image tinted by the
    /// brush colour; the brush's other enabled channels are painted where the
    /// decal is opaque. All of them are one undo step. Returns how many landed
    /// on the mesh (a decal whose box touches no surface is skipped).
    /// `record_history: false` (variant replay) paints without an undo step.
    pub(super) fn project_box_decals(&mut self, rs: &RenderState, decals: &[BoxDecal], label: String, record_history: bool) -> Result<usize, String> {
        if self.stroke.is_some() {
            return Err("finish the current stroke first".into());
        }
        for d in decals {
            self.decal_texture(rs, &d.image)?;
        }
        self.auto_mask_for_fill(rs);
        let target = self.paint_target().map_err(String::from)?;
        if self.mesh_gpu.is_none() {
            return Err("no mesh loaded".into());
        }
        self.ensure_composited(rs);
        let mut brush = self.brush_gpu();
        brush.enabled3[1] = 1.0;
        let mut snaps = Vec::new();
        let mut landed = 0;
        use pigment_core::decal_layer::DecalProjection;
        for d in decals {
            let mut tiles = TileSet::default();
            // wrap / triplanar reach past the box footprint: mark a bigger box
            let footprint = match d.projection {
                DecalProjection::Box => d.placement,
                _ => {
                    let mut p = d.placement;
                    p.size *= 3.0;
                    p.depth = p.depth.max(p.size.max_element() * 0.5);
                    p
                }
            };
            if footprint.mark_tiles(self.wrap_mesh.as_ref().unwrap_or(&self.mesh), &mut tiles) == 0 {
                continue;
            }
            let Some(texels) = tiles.texel_bounds(self.ts.res) else { continue };
            let wrap = (d.projection == DecalProjection::Wrap).then(|| {
                use eframe::egui_wgpu::wgpu::util::DeviceExt;
                let reach = d.placement.size.max_element() * 1.5;
                let coords = pigment_core::decal_layer::unfold(&self.mesh, &d.placement, reach);
                rs.device.create_buffer_init(&eframe::egui_wgpu::wgpu::util::BufferInitDescriptor { label: Some("wrap coords"), contents: bytemuck::cast_slice(&coords), usage: eframe::egui_wgpu::wgpu::BufferUsages::VERTEX })
            });
            if !self.painter.begin(&rs.device, &rs.queue, &self.ts, target) {
                return Err("nothing to paint on".into());
            }
            let (mg, tex) = (self.mesh_gpu.as_ref().unwrap(), &self.decals[&d.image]);
            self.painter.box_decal(&rs.device, &rs.queue, &self.ts, mg, tex, &d.gpu(), &brush, texels, wrap.as_ref());
            if let Some(snap) = self.painter.end(&rs.device, &rs.queue, &tiles) {
                snaps.push(snap);
            }
            landed += 1;
        }
        if !record_history {
            if landed > 0 {
                self.ts.unsaved.insert(target.res());
            }
        } else if !snaps.is_empty() {
            self.ts.unsaved.insert(target.res());
            self.counters.strokes += 1;
            self.push_paint_history(label, snaps);
        }
        self.composited = None;
        Ok(landed)
    }
}
