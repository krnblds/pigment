//! Decal layers (`pigment_core::decal_layer`): the layer's pixels are
//! regenerated from its decal objects whenever they change (moved, rotated,
//! scaled, re-ordered, re-imaged, hidden, deleted, undone). Each object is
//! painted with the box-decal path (planar, triplanar or wrap projection,
//! tear / fade wear), bottom to top, without undo steps: the objects are the
//! document state.

use super::decals::{BoxDecal, DecalLook};
use super::*;
use pigment_core::decal_layer::{DecalObject, DecalSet};
use std::hash::{Hash, Hasher};

fn key(set: &DecalSet, res: ResId, size: u32) -> u64 {
    let mut h = std::collections::hash_map::DefaultHasher::new();
    serde_json::to_string(set).unwrap_or_default().hash(&mut h);
    res.hash(&mut h);
    size.hash(&mut h);
    h.finish()
}

impl PigmentApp {
    /// The image path of a decal object (relative paths: project, mesh folder, working dir).
    pub(crate) fn decal_image_path(&self, o: &DecalObject) -> PathBuf {
        pigment_core::image_fill::resolve_path(&o.image, &self.image_bases()).unwrap_or_else(|| PathBuf::from(&o.image))
    }

    /// Regenerate every decal layer whose objects changed.
    pub(crate) fn sync_decal_layers(&mut self, rs: &RenderState) {
        let todo: Vec<(LayerId, u64)> = self
            .doc
            .layers
            .iter()
            .filter_map(|l| {
                let (set, res) = (l.decals.as_ref()?, l.paint_res()?);
                let k = key(set, res, self.ts.res);
                (self.decal_keys.get(&l.id) != Some(&k) && self.ts.layers.contains_key(&res)).then_some((l.id, k))
            })
            .collect();
        for (id, k) in todo {
            // recorded first: painting composites, which comes back here
            self.decal_keys.insert(id, k);
            if let Err(e) = self.regenerate_decal_layer(rs, id) {
                self.set_status(e, true);
            }
        }
    }

    /// Clear decal layer `id` and paint its enabled objects, bottom to top.
    pub(crate) fn regenerate_decal_layer(&mut self, rs: &RenderState, id: LayerId) -> Result<usize, String> {
        let Some(l) = self.doc.layer(id) else { return Ok(0) };
        let (Some(set), Some(res)) = (l.decals.clone(), l.paint_res()) else { return Ok(0) };
        self.ts.clear_layer(&rs.device, &rs.queue, res);
        if self.stroke.is_some() {
            self.end_stroke(rs);
        }
        // paint with the decal's own values, then put the user's brush and selection back
        let (sel, mask) = (self.selected, self.paint_mask);
        let (values, channels, opacity, erase, tool) = (self.brush.values.clone(), self.brush.channels, self.brush.opacity, self.brush.erase, self.brush.tool);
        self.selected = Some(id);
        self.paint_mask = false;
        self.brush.opacity = 1.0;
        self.brush.erase = false;
        self.brush.tool = BrushTool::Paint;
        self.decal_regen = true;
        let mut landed = 0;
        let mut err = None;
        for o in set.objects.iter().filter(|o| o.enabled) {
            self.brush.values = o.values.clone();
            self.brush.channels = [false; 11];
            for c in &o.channels {
                self.brush.channels[c.index()] = true;
            }
            let w = &o.wear;
            let look = DecalLook { opacity: w.opacity, luminance_alpha: w.alpha_from_luminance, tear: w.tear, fade: w.fade, wear_scale: w.wear_scale, seed: w.seed, grunge: w.grunge, paper_rim: w.paper_rim, ..DecalLook::default() };
            let d = BoxDecal { image: self.decal_image_path(o), placement: o.placement(), look, projection: o.projection };
            match self.project_box_decals(rs, &[d], String::new(), false) {
                Ok(n) => landed += n,
                Err(e) => err = Some(format!("decal `{}`: {e}", o.name)),
            }
        }
        self.decal_regen = false;
        self.selected = sel;
        self.paint_mask = mask;
        (self.brush.values, self.brush.channels, self.brush.opacity, self.brush.erase, self.brush.tool) = (values, channels, opacity, erase, tool);
        self.ts.unsaved.insert(res);
        self.composited = None;
        match err {
            Some(e) => Err(e),
            None => Ok(landed),
        }
    }
}
