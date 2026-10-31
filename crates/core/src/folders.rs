//! Layer folders (groups), like Substance Painter's.
//!
//! The stack stays a flat `Vec<Layer>` (bottom to top) so every existing
//! code path keeps working; a layer's `parent` names the folder it is in.
//! A folder is a `LayerKind::Folder` layer with its own opacity, per-channel
//! blend, mask and visibility.
//!
//! Canonical order (kept by [`Document::normalize_folders`]): a folder's
//! children sit directly below it in the flat list, so the panel (drawn top
//! first) shows the folder header followed by its contents.
//!
//! Compositing ([`Document::composite_plan`]): a folder is evaluated as a
//! sub-stack. Its children are composited on top of whatever is below the
//! folder (pass-through), giving `C`; the folder then blends `C` onto the
//! stack below (`B`) with its own blend mode, opacity and mask:
//! `out = blend(B, C, folder_opacity * folder_mask)`. With the Normal mode
//! this is exactly "the folder's opacity and mask multiply its children's".

use crate::document::*;

/// Levels of folders the UI and MCP accept (a folder inside a folder inside
/// a folder...). The compositor itself has no limit.
pub const MAX_FOLDER_DEPTH: usize = 4;

/// One step of the compositor's program, in order.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Step {
    /// Composite layer `layers[i]` onto the current stack.
    Layer(usize),
    /// Start a folder: remember the current stack (B); children follow.
    Begin(usize),
    /// End folder `layers[i]`: blend the children's result (C) onto B.
    End(usize),
}

impl Layer {
    pub fn is_folder(&self) -> bool {
        matches!(self.kind, LayerKind::Folder { .. })
    }
    pub fn is_collapsed(&self) -> bool {
        matches!(self.kind, LayerKind::Folder { collapsed: true })
    }
}

/// Blend modes that make sense on a folder. A folder's content is a
/// pass-through composite (it already contains what is below), so only the
/// modes that compare "below" with "below + children" are meaningful.
pub fn folder_blend_modes(c: Channel) -> &'static [BlendMode] {
    use BlendMode::*;
    match c {
        Channel::Normal => &[Normal],
        Channel::Height => &[Normal, Darken, Lighten],
        _ => &[Normal, Multiply, Screen, Overlay, Darken, Lighten],
    }
}

/// The mode a folder actually uses for `m` (unsupported modes act as Normal).
pub fn folder_blend(c: Channel, m: BlendMode) -> BlendMode {
    if folder_blend_modes(c).contains(&m) {
        m
    } else {
        BlendMode::Normal
    }
}

impl Document {
    /// A new, empty folder (all channels on, Normal blend, full opacity).
    pub fn new_folder(&mut self, name: &str) -> Layer {
        let id = self.mint();
        Layer {
            id,
            name: name.into(),
            visible: true,
            opacity: 1.0,
            kind: LayerKind::Folder { collapsed: false },
            channels: Channels::from_fn(|_| ChannelSettings { enabled: true, blend: BlendMode::Normal, opacity: 1.0 }),
            mask: None,
            parent: None,
        }
    }

    /// Indices of the direct children of `parent` (`None` = top level), bottom to top.
    pub fn children_of(&self, parent: Option<LayerId>) -> Vec<usize> {
        self.layers.iter().enumerate().filter(|(_, l)| self.parent_of(l) == parent).map(|(i, _)| i).collect()
    }

    /// The layer's folder, ignoring dangling references (a parent that is
    /// missing or not a folder counts as top level).
    fn parent_of(&self, l: &Layer) -> Option<LayerId> {
        l.parent.filter(|p| *p != l.id && self.layer(*p).is_some_and(Layer::is_folder))
    }

    /// Folders containing `id`, innermost first.
    pub fn ancestors(&self, id: LayerId) -> Vec<LayerId> {
        let mut out = Vec::new();
        let mut cur = self.layer(id).and_then(|l| self.parent_of(l));
        while let Some(p) = cur {
            if out.contains(&p) || p == id {
                break; // cycle in a hand-edited file
            }
            out.push(p);
            cur = self.layer(p).and_then(|l| self.parent_of(l));
        }
        out
    }

    /// How many folders `id` is inside (0 = top level).
    pub fn depth(&self, id: LayerId) -> usize {
        self.ancestors(id).len()
    }

    /// Is `id` inside folder `folder` (at any depth)?
    pub fn is_inside(&self, id: LayerId, folder: LayerId) -> bool {
        self.ancestors(id).contains(&folder)
    }

    /// Visible itself and inside visible folders only.
    pub fn effectively_visible(&self, id: LayerId) -> bool {
        self.layer(id).is_some_and(|l| l.visible) && self.ancestors(id).iter().all(|a| self.layer(*a).is_some_and(|l| l.visible))
    }

    /// Hidden from the panel because a folder above it is collapsed.
    pub fn is_hidden_in_panel(&self, id: LayerId) -> bool {
        self.ancestors(id).iter().any(|a| self.layer(*a).is_some_and(Layer::is_collapsed))
    }

    /// `id` and everything inside it (when it is a folder).
    pub fn subtree(&self, id: LayerId) -> Vec<LayerId> {
        let mut out = vec![id];
        out.extend(self.layers.iter().filter(|l| self.is_inside(l.id, id)).map(|l| l.id));
        out
    }

    /// "Folder/Sub/Layer" for display and MCP lookups.
    pub fn layer_path(&self, id: LayerId) -> String {
        let mut parts: Vec<String> = self.ancestors(id).iter().rev().filter_map(|a| self.layer(*a).map(|l| l.name.clone())).collect();
        if let Some(l) = self.layer(id) {
            parts.push(l.name.clone());
        }
        parts.join("/")
    }

    /// Put the flat list in canonical order (each folder's subtree directly
    /// below the folder, siblings keeping their relative order) and clear
    /// dangling or cyclic parent links. Idempotent.
    pub fn normalize_folders(&mut self) {
        // cut dangling / non-folder / cyclic links, one at a time so that
        // breaking one link of a cycle keeps the rest of it
        loop {
            let bad = self.layers.iter().position(|l| {
                if l.parent.is_some() && self.parent_of(l).is_none() {
                    return true;
                }
                let mut seen = vec![l.id];
                let mut cur = self.parent_of(l);
                while let Some(c) = cur {
                    if seen.contains(&c) {
                        return true;
                    }
                    seen.push(c);
                    cur = self.layer(c).and_then(|x| self.parent_of(x));
                }
                false
            });
            match bad {
                Some(i) => self.layers[i].parent = None,
                None => break,
            }
        }
        let mut order = Vec::with_capacity(self.layers.len());
        self.emit_subtrees(None, &mut order);
        for i in 0..self.layers.len() {
            if !order.contains(&i) {
                order.push(i);
            }
        }
        if order.iter().enumerate().any(|(k, i)| k != *i) {
            let mut old: Vec<Option<Layer>> = std::mem::take(&mut self.layers).into_iter().map(Some).collect();
            self.layers = order.into_iter().filter_map(|i| old[i].take()).collect();
        }
    }

    fn emit_subtrees(&self, parent: Option<LayerId>, order: &mut Vec<usize>) {
        for i in self.children_of(parent) {
            if self.layers[i].is_folder() {
                self.emit_subtrees(Some(self.layers[i].id), order);
            }
            order.push(i);
        }
    }

    /// Move layer `id` into folder `parent` (`None` = top level) at
    /// `position` among that folder's children (0 = bottom, `None` = top).
    /// Moving out of a folder to the top level without a position puts the
    /// layer directly above the top-level folder it came from.
    pub fn move_layer(&mut self, id: LayerId, parent: Option<LayerId>, position: Option<usize>) -> Result<(), String> {
        let Some(i) = self.index_of(id) else { return Err(format!("no layer {id}")) };
        if let Some(p) = parent {
            let Some(f) = self.layer(p) else { return Err(format!("no folder {p}")) };
            if !f.is_folder() {
                return Err(format!("`{}` is not a folder", f.name));
            }
            if p == id || self.is_inside(p, id) {
                return Err("a folder can't go inside itself".into());
            }
            let below = self.subtree_height(id);
            if self.layers[i].is_folder() && self.depth(p) + 1 + below >= MAX_FOLDER_DEPTH {
                return Err(format!("folders nest at most {MAX_FOLDER_DEPTH} levels deep"));
            }
        }
        let siblings: Vec<LayerId> = self.children_of(parent).into_iter().map(|k| self.layers[k].id).filter(|s| *s != id).collect();
        // the sibling it lands just above (None = bottom of the folder)
        let anchor_above: Option<LayerId> = match position {
            Some(0) => None,
            Some(p) => siblings.get(p.min(siblings.len()).saturating_sub(1)).copied(),
            None if parent.is_none() && self.layers[i].parent.is_some() => self.ancestors(id).last().copied(),
            None => siblings.last().copied(),
        };
        let mut l = self.layers.remove(i);
        l.parent = parent;
        let at = match anchor_above.and_then(|a| self.index_of(a)) {
            Some(k) => k + 1,
            None => match parent {
                Some(p) => {
                    let sub = self.subtree(p);
                    self.layers.iter().position(|x| sub.contains(&x.id)).unwrap_or(0)
                }
                None => 0,
            },
        };
        self.layers.insert(at.min(self.layers.len()), l);
        // a moved folder brings its contents along
        self.normalize_folders();
        Ok(())
    }

    /// How many levels of folders are nested inside `id` (0 when none; a
    /// folder holding a folder is 1).
    fn subtree_height(&self, id: LayerId) -> usize {
        self.layers
            .iter()
            .filter(|l| l.is_folder() && self.is_inside(l.id, id))
            .map(|l| self.depth(l.id) - self.depth(id))
            .max()
            .unwrap_or(0)
    }

    /// Delete a layer, or a folder with everything inside it.
    pub fn remove_layer_tree(&mut self, id: LayerId) -> Vec<Layer> {
        let gone = self.subtree(id);
        let (removed, kept): (Vec<Layer>, Vec<Layer>) = std::mem::take(&mut self.layers).into_iter().partition(|l| gone.contains(&l.id));
        self.layers = kept;
        removed
    }

    /// Put `layers` (children before their folder) into the stack: inside
    /// folder `parent` at its top, or at the top level at flat index `at`.
    pub fn insert_tree(&mut self, parent: Option<LayerId>, at: Option<usize>, layers: Vec<Layer>) {
        let ids: Vec<LayerId> = layers.iter().map(|l| l.id).collect();
        let roots: Vec<LayerId> = layers.iter().filter(|l| l.parent.is_none_or(|p| !ids.contains(&p))).map(|l| l.id).collect();
        let at = match parent {
            Some(p) => self.index_of(p).unwrap_or(self.layers.len()),
            None => at.unwrap_or(self.layers.len()).min(self.layers.len()),
        };
        for (k, mut l) in layers.into_iter().enumerate() {
            if roots.contains(&l.id) {
                l.parent = parent;
            }
            self.layers.insert(at + k, l);
        }
        self.normalize_folders();
    }

    /// The compositor's program: visible layers and folders in stack order,
    /// with each non-empty visible folder bracketing its visible contents.
    /// Hidden folders hide everything in them; empty folders are skipped.
    pub fn composite_plan(&self) -> Vec<Step> {
        let mut out = Vec::new();
        self.plan(None, &mut out, 0);
        out
    }

    fn plan(&self, parent: Option<LayerId>, out: &mut Vec<Step>, depth: usize) {
        if depth > 64 {
            return;
        }
        for i in self.children_of(parent) {
            let l = &self.layers[i];
            if !l.visible {
                continue;
            }
            if l.is_folder() {
                let mark = out.len();
                out.push(Step::Begin(i));
                self.plan(Some(l.id), out, depth + 1);
                if out.len() == mark + 1 {
                    out.pop(); // nothing visible inside
                } else {
                    out.push(Step::End(i));
                }
            } else {
                out.push(Step::Layer(i));
            }
        }
    }

    /// Group sibling layers `ids` into a new folder placed where the topmost
    /// of them was. Returns the folder's id.
    pub fn group_into_folder(&mut self, name: &str, ids: &[LayerId]) -> Result<LayerId, String> {
        let first = *ids.first().ok_or("nothing to group")?;
        let parent = self.layer(first).ok_or("no such layer")?.parent;
        if ids.iter().any(|id| self.layer(*id).is_none_or(|l| l.parent != parent)) {
            return Err("only layers in the same folder can be grouped".into());
        }
        let top = ids.iter().filter_map(|id| self.index_of(*id)).max().unwrap();
        let mut folder = self.new_folder(name);
        let fid = folder.id;
        folder.parent = parent;
        self.layers.insert(top + 1, folder);
        for id in ids {
            if let Some(l) = self.layer_mut(*id) {
                l.parent = Some(fid);
            }
        }
        self.normalize_folders();
        Ok(fid)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// base, [Weathering: dirt, [Rust: spots, streaks]], paint
    fn nested() -> (Document, LayerId, LayerId) {
        let mut d = Document::default();
        let base = d.fill_with("Base", "Concrete", None);
        d.layers.push(base);
        let w = d.new_folder("Weathering");
        let wid = w.id;
        d.layers.push(w);
        let dirt = d.fill_with("Dirt", "Grime", Some(Generator::new(GeneratorKind::Dirt)));
        let did = dirt.id;
        d.layers.push(dirt);
        d.move_layer(did, Some(wid), None).unwrap();
        let r = d.new_folder("Rust");
        let rid = r.id;
        d.layers.push(r);
        d.move_layer(rid, Some(wid), None).unwrap();
        for n in ["Spots", "Streaks"] {
            let l = d.fill_with(n, "Rust", None);
            let id = l.id;
            d.layers.push(l);
            d.move_layer(id, Some(rid), None).unwrap();
        }
        let p = d.new_paint_layer("Paint");
        d.layers.push(p);
        (d, wid, rid)
    }

    fn names(d: &Document) -> Vec<&str> {
        d.layers.iter().map(|l| l.name.as_str()).collect()
    }

    #[test]
    fn folders_nest_in_canonical_order() {
        let (d, wid, rid) = nested();
        assert_eq!(names(&d), ["Base", "Dirt", "Spots", "Streaks", "Rust", "Weathering", "Paint"]);
        assert_eq!(d.depth(rid), 1);
        assert_eq!(d.depth(d.layers[2].id), 2);
        assert_eq!(d.layer_path(d.layers[3].id), "Weathering/Rust/Streaks");
        assert_eq!(d.subtree(wid).len(), 5);
        assert_eq!(d.children_of(Some(wid)).len(), 2);
        let mut e = d.clone();
        e.normalize_folders();
        assert_eq!(e, d, "normalize is idempotent");
    }

    #[test]
    fn plan_brackets_folders_and_skips_hidden_or_empty() {
        let (mut d, wid, rid) = nested();
        use Step::*;
        assert_eq!(d.composite_plan(), vec![Layer(0), Begin(5), Layer(1), Begin(4), Layer(2), Layer(3), End(4), End(5), Layer(6)]);
        d.layer_mut(rid).unwrap().visible = false;
        assert_eq!(d.composite_plan(), vec![Layer(0), Begin(5), Layer(1), End(5), Layer(6)]);
        assert!(!d.effectively_visible(d.layers[2].id));
        d.layer_mut(wid).unwrap().visible = false;
        assert_eq!(d.composite_plan(), vec![Layer(0), Layer(6)]);
        let mut e = Document::default();
        let f = e.new_folder("Empty");
        e.layers.push(f);
        assert!(e.composite_plan().is_empty());
    }

    #[test]
    fn moving_in_and_out() {
        let (mut d, wid, rid) = nested();
        let paint = d.layers[6].id;
        d.move_layer(paint, Some(rid), Some(0)).unwrap();
        assert_eq!(names(&d), ["Base", "Dirt", "Paint", "Spots", "Streaks", "Rust", "Weathering"]);
        // out to the top level: lands just above the folder it came from
        d.move_layer(paint, None, None).unwrap();
        assert_eq!(names(&d), ["Base", "Dirt", "Spots", "Streaks", "Rust", "Weathering", "Paint"]);
        // a folder can't go into itself or its children
        assert!(d.move_layer(wid, Some(rid), None).is_err());
        assert!(d.move_layer(wid, Some(wid), None).is_err());
        // moving a folder moves its contents
        d.move_layer(rid, None, Some(0)).unwrap();
        assert_eq!(names(&d), ["Spots", "Streaks", "Rust", "Base", "Dirt", "Weathering", "Paint"]);
        assert_eq!(d.depth(d.layers[0].id), 1);
        // delete a folder with its contents
        let gone = d.remove_layer_tree(rid);
        assert_eq!(gone.len(), 3);
        assert_eq!(names(&d), ["Base", "Dirt", "Weathering", "Paint"]);
    }

    #[test]
    fn nesting_depth_is_limited() {
        let mut d = Document::default();
        let mut parent = None;
        for k in 0..MAX_FOLDER_DEPTH {
            let f = d.new_folder(&format!("F{k}"));
            let id = f.id;
            d.layers.push(f);
            d.move_layer(id, parent, None).unwrap();
            parent = Some(id);
        }
        let l = d.new_fill_layer("deep");
        let id = l.id;
        d.layers.push(l);
        d.move_layer(id, parent, None).unwrap(); // a layer inside the deepest folder is fine
        let f = d.new_folder("too deep");
        let fid = f.id;
        d.layers.push(f);
        assert!(d.move_layer(fid, parent, None).is_err());
    }

    #[test]
    fn dangling_and_cyclic_parents_are_repaired() {
        let (mut d, wid, rid) = nested();
        d.layer_mut(wid).unwrap().parent = Some(rid); // cycle W -> R -> W
        d.layers[0].parent = Some(9999); // dangling
        d.normalize_folders();
        assert!(d.layers.iter().all(|l| d.ancestors(l.id).len() < 3));
        assert_eq!(d.layers.iter().find(|l| l.name == "Base").unwrap().parent, None);
        // the plan still covers every layer exactly once
        let n = d.composite_plan().iter().filter(|s| matches!(s, Step::Layer(_))).count();
        assert_eq!(n, 5);
    }

    #[test]
    fn group_and_old_projects() {
        let mut d = Document::demo();
        let ids: Vec<LayerId> = d.layers[1..3].iter().map(|l| l.id).collect();
        let f = d.group_into_folder("Wear", &ids).unwrap();
        assert_eq!(names(&d), ["Teal paint", "Edge wear", "Dirt", "Wear", "Paint"]);
        assert_eq!(d.children_of(Some(f)).len(), 2);
        // folders survive a save; projects without folders load as before
        let s = serde_json::to_string(&d).unwrap();
        assert_eq!(serde_json::from_str::<Document>(&s).unwrap(), d);
        let old = serde_json::to_string(&Document::demo()).unwrap();
        assert!(!old.contains("parent"), "no new keys for folder-less projects");
        assert!(serde_json::from_str::<Document>(&old).unwrap().layers.iter().all(|l| l.parent.is_none()));
        assert!(s.contains("\"type\":\"folder\""));
    }

    #[test]
    fn folder_blend_falls_back_to_normal() {
        assert_eq!(folder_blend(Channel::Height, BlendMode::Add), BlendMode::Normal);
        assert_eq!(folder_blend(Channel::Normal, BlendMode::NormalCombine), BlendMode::Normal);
        assert_eq!(folder_blend(Channel::BaseColor, BlendMode::Multiply), BlendMode::Multiply);
    }
}
