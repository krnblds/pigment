//! Saved smart materials: a folder (or a single layer) written to a
//! `.pigsmart` JSON file and instanced into any project.
//!
//! Smart materials are part-agnostic. They keep what is procedural (fill
//! values, channel settings, blend modes, opacity, generator masks and mask
//! effects) and drop what belongs to one mesh: mask part selections and
//! painted pixels. Paint layers are skipped and hand-painted masks are saved
//! as plain white masks; [`SmartMaterial::warnings`] says what was dropped.
//! When instancing, `parts` can limit the whole material to some pieces of
//! the new mesh through the root folder's mask.

use crate::document::*;
use serde::{Deserialize, Serialize};
use std::path::Path;

pub const SMART_EXTENSION: &str = "pigsmart";
pub const SMART_FORMAT: u32 = 1;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SmartMaterial {
    /// File format version.
    pub pigsmart: u32,
    pub name: String,
    /// Bottom to top, children before their folder; the last layer is the
    /// root. Ids are local to the file; mask `res` ids are placeholders.
    pub layers: Vec<Layer>,
    /// What couldn't be made part-agnostic when it was saved.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub warnings: Vec<String>,
}

impl SmartMaterial {
    pub fn root(&self) -> Option<&Layer> {
        self.layers.last()
    }

    pub fn save(&self, path: &Path) -> anyhow::Result<()> {
        if let Some(d) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
            std::fs::create_dir_all(d)?;
        }
        let mut s = serde_json::to_string_pretty(self)?;
        s.push('\n');
        std::fs::write(path, s)?;
        Ok(())
    }

    pub fn load(path: &Path) -> anyhow::Result<SmartMaterial> {
        let text = std::fs::read_to_string(path).map_err(|e| anyhow::anyhow!("reading {}: {e}", path.display()))?;
        let sm: SmartMaterial = serde_json::from_str(&text).map_err(|e| anyhow::anyhow!("parsing {}: {e}", path.display()))?;
        if sm.pigsmart > SMART_FORMAT {
            anyhow::bail!("{} was saved by a newer Pigment (smart material format {})", path.display(), sm.pigsmart);
        }
        if sm.layers.is_empty() {
            anyhow::bail!("{} has no layers", path.display());
        }
        Ok(sm)
    }
}

impl Document {
    /// A part-agnostic copy of layer / folder `id` and its contents.
    pub fn extract_smart(&self, id: LayerId, name: &str) -> Result<SmartMaterial, String> {
        let root = self.layer(id).ok_or("no such layer")?;
        if root.is_paint() {
            return Err(format!("`{}` is a paint layer: its pixels belong to this mesh. Save a folder or a fill layer.", root.name));
        }
        let members = self.subtree(id);
        let mut warnings = Vec::new();
        let mut layers = Vec::new();
        // flat order is canonical (children below their folder, root last)
        for l in self.layers.iter().filter(|l| members.contains(&l.id)) {
            if l.is_paint() {
                warnings.push(format!("skipped paint layer `{}` (painted pixels are mesh-specific)", self.layer_path(l.id)));
                continue;
            }
            let mut l = l.clone();
            if l.id == id {
                l.parent = None;
            }
            if let Some(m) = &mut l.mask {
                if !m.parts.is_empty() {
                    warnings.push(format!("dropped the part selection of `{}`", l.name));
                    m.parts.clear();
                }
                if m.generator.is_none() {
                    warnings.push(format!("the mask of `{}` has no generator: saved as a white mask", l.name));
                }
                m.res = 0;
            }
            layers.push(l);
        }
        // the root must be last even if a hand-edited stack isn't canonical
        if let Some(k) = layers.iter().position(|l| l.id == id) {
            let r = layers.remove(k);
            layers.push(r);
        }
        Ok(SmartMaterial { pigsmart: SMART_FORMAT, name: name.to_string(), layers, warnings })
    }

    /// Fresh layers for this document from a smart material (new layer and
    /// mask ids, parent links remapped). Bottom to top, root last, root at the
    /// top level. `parts` (non-empty) limits the root to those mesh parts.
    pub fn instantiate_smart(&mut self, sm: &SmartMaterial, parts: &[u32]) -> Vec<Layer> {
        let mut map = std::collections::HashMap::new();
        let mut out: Vec<Layer> = Vec::with_capacity(sm.layers.len());
        for l in &sm.layers {
            let new = self.mint();
            map.insert(l.id, new);
            let mut l = l.clone();
            l.id = new;
            if let Some(m) = &mut l.mask {
                m.res = self.mint();
            }
            out.push(l);
        }
        for l in &mut out {
            l.parent = l.parent.and_then(|p| map.get(&p).copied());
        }
        if let Some(root) = out.last_mut() {
            root.parent = None;
            if !parts.is_empty() {
                let mut ps: Vec<u32> = parts.iter().copied().filter(|p| *p < MAX_SELECTABLE_PARTS).collect();
                ps.sort_unstable();
                ps.dedup();
                if root.mask.is_none() {
                    root.mask = Some(Mask::new(self.mint()));
                }
                root.mask.as_mut().unwrap().parts = ps;
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn weathering(d: &mut Document) -> LayerId {
        let base = d.fill_with("Base", "Concrete", None);
        d.layers.push(base);
        let mut grime = d.fill_with("Grime", "Grime", Some(Generator::new(GeneratorKind::Dirt)));
        grime.mask.as_mut().unwrap().parts = vec![3, 4];
        let leaks = d.fill_with("Leaks", "Grime", Some(Generator::new(GeneratorKind::Streaks)));
        let paint = d.new_paint_layer("Hand grime");
        let ids = [grime.id, leaks.id, paint.id];
        d.layers.extend([grime, leaks, paint]);
        let f = d.group_into_folder("Weathering", &ids).unwrap();
        d.layer_mut(f).unwrap().opacity = 0.7;
        f
    }

    #[test]
    fn save_is_part_agnostic_and_instancing_remaps_ids() {
        let mut a = Document::default();
        let f = weathering(&mut a);
        let sm = a.extract_smart(f, "Weathering").unwrap();
        assert_eq!(sm.layers.len(), 3, "paint layer skipped");
        assert_eq!(sm.root().unwrap().name, "Weathering");
        assert!(sm.layers.iter().all(|l| l.mask.as_ref().is_none_or(|m| m.parts.is_empty() && m.res == 0)));
        assert_eq!(sm.warnings.len(), 2, "{:?}", sm.warnings);
        // round trip through a file
        let path = std::env::temp_dir().join(format!("pigment-smart-{}.{SMART_EXTENSION}", std::process::id()));
        sm.save(&path).unwrap();
        let back = SmartMaterial::load(&path).unwrap();
        assert_eq!(back, sm);
        std::fs::remove_file(&path).ok();

        // instance into another document twice, the first limited to parts
        let mut b = Document::new_default();
        let before = b.resources();
        let l1 = b.instantiate_smart(&back, &[7, 2, 7]);
        let root1 = l1.last().unwrap().id;
        b.insert_tree(None, Some(1), l1);
        let l2 = b.instantiate_smart(&back, &[]);
        b.insert_tree(None, None, l2);
        assert_eq!(b.layers.len(), 2 + 6);
        let ids: std::collections::HashSet<_> = b.layers.iter().map(|l| l.id).chain(b.resources()).collect();
        assert_eq!(ids.len(), b.layers.len() + b.resources().len(), "unique ids");
        assert!(before.iter().all(|r| b.resources().contains(r)));
        let r1 = b.layer(root1).unwrap();
        assert_eq!(r1.mask.as_ref().unwrap().parts, vec![2, 7]);
        assert_eq!(b.children_of(Some(root1)).len(), 2);
        assert_eq!(b.layers[1].name, "Grime", "first instance sits above the base");
        assert!((r1.opacity - 0.7).abs() < 1e-6);
    }

    #[test]
    fn paint_layers_cant_be_saved_and_newer_files_are_rejected() {
        let mut d = Document::new_default();
        assert!(d.extract_smart(d.layers[1].id, "x").is_err());
        let single = d.extract_smart(d.layers[0].id, "Base").unwrap();
        assert_eq!(single.layers.len(), 1);
        let l = d.instantiate_smart(&single, &[]);
        assert_eq!(l.len(), 1);
        let mut newer = single.clone();
        newer.pigsmart = SMART_FORMAT + 1;
        let path = std::env::temp_dir().join(format!("pigment-smart-new-{}.{SMART_EXTENSION}", std::process::id()));
        newer.save(&path).unwrap();
        assert!(SmartMaterial::load(&path).is_err());
        std::fs::remove_file(&path).ok();
    }
}
