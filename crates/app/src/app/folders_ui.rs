//! Layer folder and saved smart material actions shared by the layer panel
//! and the automation session.

use super::*;
use pigment_core::folders::MAX_FOLDER_DEPTH;
use pigment_core::smart::{SmartMaterial, SMART_EXTENSION};

impl PigmentApp {
    pub(super) fn insert_layer(&mut self, mut l: Layer) {
        let at = self.selected.and_then(|id| self.doc.index_of(id)).map(|i| i + 1).unwrap_or(self.doc.layers.len());
        let id = l.id;
        // lands next to the selection, in the same folder
        l.parent = self.selected.and_then(|s| self.doc.layer(s)).and_then(|s| s.parent);
        self.doc.layers.insert(at, l);
        self.doc.normalize_folders();
        self.select(Some(id), false);
    }

    pub(super) fn duplicate_selected(&mut self, rs: &RenderState) {
        let Some(i) = self.selected.and_then(|id| self.doc.index_of(id)) else { return };
        if self.doc.layers[i].is_folder() {
            let id = self.doc.layers[i].id;
            self.duplicate_tree(rs, id);
            return;
        }
        let mut l = self.doc.layers[i].clone();
        l.id = self.doc.mint();
        l.name = format!("{} copy", l.name);
        if let LayerKind::Paint { res } = &mut l.kind {
            let new = self.doc.mint();
            self.ts.duplicate_layer(&rs.device, &rs.queue, *res, new);
            *res = new;
        }
        if let Some(m) = &mut l.mask {
            let new = self.doc.mint();
            self.ts.duplicate_mask(&rs.device, &rs.queue, m.res, new);
            m.res = new;
        }
        let id = l.id;
        self.doc.layers.insert(i + 1, l);
        self.select(Some(id), false);
    }

    /// A new folder above the selection (in the same folder as it).
    pub(super) fn add_folder(&mut self) {
        let n = self.doc.layers.iter().filter(|l| l.is_folder()).count() + 1;
        let f = self.doc.new_folder(&format!("Folder {n}"));
        self.insert_layer(f);
    }

    /// Wrap the selected layer (or folder) in a new folder.
    pub(super) fn group_selected(&mut self) {
        let Some(id) = self.selected else { return };
        if self.doc.layer(id).is_some_and(Layer::is_folder) && self.doc.depth(id) + 1 >= MAX_FOLDER_DEPTH {
            self.status = Some((format!("Folders nest at most {MAX_FOLDER_DEPTH} levels deep"), true));
            return;
        }
        let n = self.doc.layers.iter().filter(|l| l.is_folder()).count() + 1;
        if let Ok(f) = self.doc.group_into_folder(&format!("Folder {n}"), &[id]) {
            self.select(Some(f), false);
        }
    }

    /// Move the selection one step up (+1) or down (-1) among its siblings.
    pub(super) fn nudge_selected(&mut self, dir: i32) {
        let Some(id) = self.selected else { return };
        let Some(l) = self.doc.layer(id) else { return };
        let parent = l.parent;
        let sibs: Vec<LayerId> = self.doc.children_of(parent).into_iter().map(|i| self.doc.layers[i].id).collect();
        let Some(k) = sibs.iter().position(|s| *s == id) else { return };
        let to = k as i32 + dir;
        if to < 0 || to as usize >= sibs.len() {
            return;
        }
        let _ = self.doc.move_layer(id, parent, Some(to as usize));
    }

    pub(super) fn can_nudge(&self, dir: i32) -> bool {
        let Some(l) = self.selected.and_then(|id| self.doc.layer(id)) else { return false };
        let sibs = self.doc.children_of(l.parent);
        let k = sibs.iter().position(|i| self.doc.layers[*i].id == l.id).unwrap_or(0) as i32 + dir;
        k >= 0 && (k as usize) < sibs.len()
    }

    /// Move the selection out of its folder, just above that folder.
    pub(super) fn move_selected_out(&mut self) {
        let Some(id) = self.selected else { return };
        let Some(p) = self.doc.layer(id).and_then(|l| l.parent) else { return };
        let grand = self.doc.layer(p).and_then(|f| f.parent);
        let sibs: Vec<LayerId> = self.doc.children_of(grand).into_iter().map(|i| self.doc.layers[i].id).collect();
        let pos = sibs.iter().position(|s| *s == p).map(|k| k + 1);
        if let Err(e) = self.doc.move_layer(id, grand, pos) {
            self.status = Some((e, true));
        }
    }

    /// Move the selection into folder `fid` (on top of its contents).
    pub(super) fn move_selected_into(&mut self, fid: LayerId) {
        let Some(id) = self.selected else { return };
        if let Err(e) = self.doc.move_layer(id, Some(fid), None) {
            self.status = Some((e, true));
        }
    }

    /// Folders the selection could move into: (id, "A/B" path).
    pub(super) fn folder_targets(&self) -> Vec<(LayerId, String)> {
        let sel = self.selected;
        self.doc
            .layers
            .iter()
            .rev()
            .filter(|f| f.is_folder() && Some(f.id) != sel && sel.is_none_or(|s| !self.doc.is_inside(f.id, s)))
            .filter(|f| sel.and_then(|s| self.doc.layer(s)).is_none_or(|l| l.parent != Some(f.id)))
            .map(|f| (f.id, self.doc.layer_path(f.id)))
            .collect()
    }

    /// Delete the selection (a folder goes with its contents).
    pub(super) fn delete_selected(&mut self) {
        let Some(id) = self.selected else { return };
        let Some(i) = self.doc.index_of(id) else { return };
        self.doc.remove_layer_tree(id);
        let next = self.doc.layers.get(i.min(self.doc.layers.len().saturating_sub(1))).map(|l| l.id);
        self.select(next, false);
    }

    pub(super) fn save_smart_dialog(&mut self) {
        let Some(id) = self.selected else { return };
        let name = self.doc.layer(id).map(|l| l.name.clone()).unwrap_or_default();
        let Some(mut p) = rfd::FileDialog::new().set_title("Save smart material").set_file_name(format!("{name}.{SMART_EXTENSION}")).add_filter("Smart material", &[SMART_EXTENSION]).save_file() else {
            return;
        };
        if p.extension().is_none_or(|e| e != SMART_EXTENSION) {
            p.set_extension(SMART_EXTENSION);
        }
        match self.save_smart(id, &name, &p) {
            Ok(sm) => {
                let extra = if sm.warnings.is_empty() { String::new() } else { format!(" ({})", sm.warnings.join("; ")) };
                self.status = Some((format!("Saved smart material {}{extra}", p.display()), false));
            }
            Err(e) => self.status = Some((e, true)),
        }
    }

    pub(super) fn load_smart_dialog(&mut self) {
        let Some(p) = rfd::FileDialog::new().set_title("Apply smart material").add_filter("Smart material", &[SMART_EXTENSION]).pick_file() else { return };
        match self.apply_smart(&p, &[], None) {
            Ok(id) => {
                self.select(Some(id), false);
                self.status = Some((format!("Applied smart material {}", p.display()), false));
            }
            Err(e) => self.status = Some((e, true)),
        }
    }

    pub(crate) fn save_smart(&self, id: LayerId, name: &str, path: &Path) -> Result<SmartMaterial, String> {
        let sm = self.doc.extract_smart(id, name)?;
        sm.save(path).map_err(|e| format!("{e:#}"))?;
        Ok(sm)
    }

    /// Instance a `.pigsmart` file. Goes inside folder `parent` (on top), or
    /// at the top level above the selection's top-level layer, else below the
    /// topmost paint layer. Returns the new root's id.
    pub(crate) fn apply_smart(&mut self, path: &Path, parts: &[u32], parent: Option<LayerId>) -> Result<LayerId, String> {
        let sm = SmartMaterial::load(path).map_err(|e| format!("{e:#}"))?;
        let layers = self.doc.instantiate_smart(&sm, parts);
        let root = layers.last().map(|l| l.id).ok_or("empty smart material")?;
        let at = match parent {
            Some(_) => None,
            None => Some(self.doc.layers.iter().rposition(|l| l.is_paint() && l.parent.is_none()).unwrap_or(self.doc.layers.len())),
        };
        self.doc.insert_tree(parent, at, layers);
        Ok(root)
    }

    /// Duplicate a folder with everything inside it (fresh ids and pixels).
    pub(super) fn duplicate_tree(&mut self, rs: &RenderState, id: LayerId) {
        let members = self.doc.subtree(id);
        let src: Vec<Layer> = self.doc.layers.iter().filter(|l| members.contains(&l.id)).cloned().collect();
        let mut map = std::collections::HashMap::new();
        let mut out = Vec::new();
        for mut l in src {
            let new = self.doc.mint();
            map.insert(l.id, new);
            l.id = new;
            if let LayerKind::Paint { res } = &mut l.kind {
                let r = self.doc.mint();
                self.ts.duplicate_layer(&rs.device, &rs.queue, *res, r);
                *res = r;
            }
            if let Some(m) = &mut l.mask {
                let r = self.doc.mint();
                self.ts.duplicate_mask(&rs.device, &rs.queue, m.res, r);
                m.res = r;
            }
            out.push(l);
        }
        let parent = self.doc.layer(id).and_then(|l| l.parent);
        for l in &mut out {
            l.parent = l.parent.and_then(|p| map.get(&p).copied());
        }
        let root = map[&id];
        if let Some(r) = out.iter_mut().find(|l| l.id == root) {
            r.name = format!("{} copy", r.name);
        }
        let at = self.doc.index_of(id).map(|i| i + 1);
        match parent {
            // inside a folder: insert_tree puts it on top of that folder; then
            // move it to just above the original
            Some(p) => {
                self.doc.insert_tree(Some(p), None, out);
                let sibs: Vec<LayerId> = self.doc.children_of(Some(p)).into_iter().map(|i| self.doc.layers[i].id).collect();
                let pos = sibs.iter().position(|s| *s == id).map(|k| k + 1);
                let _ = self.doc.move_layer(root, Some(p), pos);
            }
            None => self.doc.insert_tree(None, at, out),
        }
        self.select(Some(root), false);
    }
}
