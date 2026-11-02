//! A small docking system (egui_dock has no release for egui 0.37): the
//! window is a tree of splits whose leaves hold tabbed panels. Drag a tab
//! onto another leaf's centre to tab it there or onto an edge to split; drag
//! it off the dock (or use the tab menu) to float it as a window; close it
//! and reopen it from the Window menu. Layouts serialise to JSON (prefs).

use super::design::{self, fonts, font, icon, radius, size, space, Icon};
use eframe::egui;
use egui::{pos2, vec2, Align2, CornerRadius, Rect, Sense, Stroke, StrokeKind, Ui};
use serde::{Deserialize, Serialize};

/// Every panel the app can show, registered by id.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize, PartialOrd, Ord)]
pub enum PanelId {
    Viewport,
    Library,
    Look,
    Brush,
    Layers,
    Properties,
    Channels,
    Mask,
    Decals,
    Parts,
    Variants,
    Lighting,
    History,
    Export,
    TextureSet,
    FoliageLibrary,
    FoliageBrush,
    FoliageCells,
}

impl PanelId {
    pub const ALL: [PanelId; 18] = [
        PanelId::Viewport,
        PanelId::Library,
        PanelId::Look,
        PanelId::Brush,
        PanelId::Layers,
        PanelId::Properties,
        PanelId::Channels,
        PanelId::Mask,
        PanelId::Decals,
        PanelId::Parts,
        PanelId::Variants,
        PanelId::Lighting,
        PanelId::History,
        PanelId::Export,
        PanelId::TextureSet,
        PanelId::FoliageLibrary,
        PanelId::FoliageBrush,
        PanelId::FoliageCells,
    ];

    pub fn title(self) -> &'static str {
        match self {
            PanelId::Viewport => "Viewport",
            PanelId::Library => "Materials",
            PanelId::Look => "Weathering",
            PanelId::Brush => "Brush",
            PanelId::Layers => "Layers",
            PanelId::Properties => "Properties",
            PanelId::Channels => "Channels",
            PanelId::Mask => "Mask & generators",
            PanelId::Decals => "Decals",
            PanelId::Parts => "Parts",
            PanelId::Variants => "Variants",
            PanelId::Lighting => "Lighting",
            PanelId::History => "History",
            PanelId::Export => "Export",
            PanelId::TextureSet => "Texture set & bake",
            PanelId::FoliageLibrary => "Foliage library",
            PanelId::FoliageBrush => "Foliage brush",
            PanelId::FoliageCells => "Foliage cell editor",
        }
    }

    pub fn icon(self) -> Icon {
        match self {
            PanelId::Viewport => Icon::Cube,
            PanelId::Library => Icon::Grid,
            PanelId::Look => Icon::Rain,
            PanelId::Brush => Icon::Brush,
            PanelId::Layers => Icon::Layers,
            PanelId::Properties => Icon::Sliders,
            PanelId::Channels => Icon::Palette,
            PanelId::Mask => Icon::Wand,
            PanelId::Decals => Icon::Stamp,
            PanelId::Parts => Icon::Parts,
            PanelId::Variants => Icon::Dice,
            PanelId::Lighting => Icon::Sun,
            PanelId::History => Icon::History,
            PanelId::Export => Icon::Export,
            PanelId::TextureSet => Icon::Tile,
            PanelId::FoliageLibrary | PanelId::FoliageBrush | PanelId::FoliageCells => Icon::Leaf,
        }
    }

    pub fn closable(self) -> bool {
        self != PanelId::Viewport
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Zone {
    Center,
    Left,
    Right,
    Top,
    Bottom,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum Node {
    Leaf { tabs: Vec<PanelId>, active: usize },
    /// `vertical`: `a` above `b`; otherwise `a` left of `b`. `ratio` = a's share.
    Split { vertical: bool, ratio: f32, a: Box<Node>, b: Box<Node> },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Floating {
    pub panel: PanelId,
    pub pos: [f32; 2],
    pub size: [f32; 2],
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DockLayout {
    pub root: Node,
    #[serde(default)]
    pub floating: Vec<Floating>,
}

fn leaf(tabs: &[PanelId]) -> Node {
    Node::Leaf { tabs: tabs.to_vec(), active: 0 }
}
fn h(ratio: f32, a: Node, b: Node) -> Node {
    Node::Split { vertical: false, ratio, a: Box::new(a), b: Box::new(b) }
}
fn v(ratio: f32, a: Node, b: Node) -> Node {
    Node::Split { vertical: true, ratio, a: Box::new(a), b: Box::new(b) }
}

/// Built-in layout presets.
pub const PRESETS: [&str; 4] = ["Beginner", "Painting", "Texturing", "Compact"];

impl Default for DockLayout {
    fn default() -> Self {
        DockLayout::texturing()
    }
}

impl DockLayout {
    pub fn preset(name: &str) -> Option<DockLayout> {
        Some(match name {
            "Beginner" => DockLayout::beginner(),
            "Painting" => DockLayout::painting(),
            "Texturing" | "Advanced" => DockLayout::texturing(),
            "Compact" => DockLayout::compact(),
            _ => return None,
        })
    }

    /// Simple mode: the model, a big material library, weathering + lighting.
    pub fn beginner() -> DockLayout {
        use PanelId::*;
        DockLayout { root: h(0.70, leaf(&[Viewport]), v(0.64, leaf(&[Library]), leaf(&[Look, Lighting, Export]))), floating: vec![] }
    }

    /// Hand painting: brush on the left, layers on the right.
    pub fn painting() -> DockLayout {
        use PanelId::*;
        DockLayout { root: h(0.2, v(0.6, leaf(&[Brush]), leaf(&[Library, Decals])), h(0.76, leaf(&[Viewport]), v(0.5, leaf(&[Layers, History]), leaf(&[Properties, Mask])))), floating: vec![] }
    }

    /// Advanced texturing: everything one click away.
    pub fn texturing() -> DockLayout {
        use PanelId::*;
        DockLayout {
            root: h(
                0.2,
                v(0.55, leaf(&[Library, Brush]), leaf(&[Decals, Parts, Lighting, TextureSet])),
                h(0.74, v(0.78, leaf(&[Viewport]), leaf(&[History, Variants, Export])), v(0.42, leaf(&[Layers]), leaf(&[Properties, Mask, Channels]))),
            ),
            floating: vec![],
        }
    }

    /// Small screens: one side column of tabs.
    pub fn compact() -> DockLayout {
        use PanelId::*;
        DockLayout { root: h(0.72, leaf(&[Viewport]), leaf(&[Layers, Library, Properties, Mask, Brush, Decals, Lighting, Export])), floating: vec![] }
    }

    pub fn contains(&self, p: PanelId) -> bool {
        self.root.contains(p) || self.floating.iter().any(|f| f.panel == p)
    }

    /// Every panel in the layout, in tree order (floating last).
    pub fn panels(&self) -> Vec<PanelId> {
        let mut out = vec![];
        self.root.collect(&mut out);
        out.extend(self.floating.iter().map(|f| f.panel));
        out
    }

    /// Take a panel out (from a leaf or a window). Empty leaves collapse.
    pub fn remove(&mut self, p: PanelId) {
        self.floating.retain(|f| f.panel != p);
        self.root.remove(p);
        self.root.collapse();
    }

    /// Dock `p` at leaf `path` (0 = first child, 1 = second) in `zone`.
    pub fn dock(&mut self, p: PanelId, path: &[u8], zone: Zone) {
        let target_tabs = self.root.at(path).and_then(|n| if let Node::Leaf { tabs, .. } = n { Some(tabs.clone()) } else { None });
        if zone == Zone::Center && target_tabs.as_ref().is_some_and(|t| t.contains(&p)) {
            return;
        }
        if zone != Zone::Center && target_tabs.as_ref().is_some_and(|t| t.len() == 1 && t[0] == p) {
            return;
        }
        // remove first, but keep the target's path valid: mark the target leaf
        let marker = PanelId::Viewport;
        let _ = marker;
        let mut tree = self.root.clone();
        let mut target = tree.at_mut(path).map(|n| std::mem::replace(n, Node::Leaf { tabs: vec![], active: usize::MAX }));
        if let Some(Node::Leaf { tabs, .. }) = &mut target {
            tabs.retain(|t| *t != p);
        }
        tree.remove(p);
        self.floating.retain(|f| f.panel != p);
        let new = match target {
            Some(Node::Leaf { mut tabs, active }) => {
                let active = active.min(tabs.len().saturating_sub(1));
                match zone {
                    Zone::Center => {
                        tabs.push(p);
                        let n = tabs.len() - 1;
                        Node::Leaf { tabs, active: n }
                    }
                    _ => {
                        let me = leaf(&[p]);
                        let other = Node::Leaf { tabs, active };
                        match zone {
                            Zone::Left => h(0.3, me, other),
                            Zone::Right => h(0.7, other, me),
                            Zone::Top => v(0.35, me, other),
                            _ => v(0.65, other, me),
                        }
                    }
                }
            }
            _ => leaf(&[p]),
        };
        if !tree.replace_placeholder(new.clone()) {
            // the target vanished: put it next to the root
            tree = h(0.75, tree, new);
        }
        tree.collapse();
        self.root = tree;
    }

    pub fn float(&mut self, p: PanelId, pos: egui::Pos2) {
        self.remove(p);
        self.floating.push(Floating { panel: p, pos: [pos.x, pos.y], size: [320.0, 420.0] });
    }

    /// Show a closed panel: as a tab next to the panel it usually sits with,
    /// else in the first side leaf.
    pub fn open(&mut self, p: PanelId) {
        if self.contains(p) {
            self.focus(p);
            return;
        }
        let buddies: &[PanelId] = match p {
            PanelId::Properties | PanelId::Mask | PanelId::Channels => &[PanelId::Properties, PanelId::Mask, PanelId::Channels, PanelId::Layers],
            PanelId::Library | PanelId::Brush => &[PanelId::Library, PanelId::Brush],
            _ => &[PanelId::Layers, PanelId::Library, PanelId::Properties, PanelId::Look],
        };
        for b in buddies {
            if let Some(path) = self.root.path_of(*b) {
                self.dock(p, &path, Zone::Center);
                return;
            }
        }
        match self.root.first_non_viewport_leaf() {
            Some(path) => self.dock(p, &path, Zone::Center),
            None => self.dock(p, &[], Zone::Right),
        }
    }

    /// Make the panel the active tab of its leaf.
    pub fn focus(&mut self, p: PanelId) {
        if let Some(path) = self.root.path_of(p) {
            if let Some(Node::Leaf { tabs, active }) = self.root.at_mut(&path) {
                *active = tabs.iter().position(|t| *t == p).unwrap_or(0);
            }
        }
    }

    pub fn is_visible_tab(&self, p: PanelId) -> bool {
        self.floating.iter().any(|f| f.panel == p) || self.root.active_tabs().contains(&p)
    }

    /// Fix layouts from older versions / hand edits: the viewport must exist
    /// exactly once, no duplicates, no empty leaves.
    pub fn repair(&mut self) {
        let mut seen = std::collections::HashSet::new();
        self.root.dedupe(&mut seen);
        self.floating.retain(|f| seen.insert(f.panel));
        self.root.collapse();
        if !self.root.contains(PanelId::Viewport) {
            self.floating.retain(|f| f.panel != PanelId::Viewport);
            let old = std::mem::replace(&mut self.root, leaf(&[]));
            self.root = if old.is_empty() { leaf(&[PanelId::Viewport]) } else { h(0.72, leaf(&[PanelId::Viewport]), old) };
        }
    }
}

impl Node {
    fn contains(&self, p: PanelId) -> bool {
        match self {
            Node::Leaf { tabs, .. } => tabs.contains(&p),
            Node::Split { a, b, .. } => a.contains(p) || b.contains(p),
        }
    }
    fn is_empty(&self) -> bool {
        matches!(self, Node::Leaf { tabs, .. } if tabs.is_empty())
    }
    fn collect(&self, out: &mut Vec<PanelId>) {
        match self {
            Node::Leaf { tabs, .. } => out.extend(tabs.iter().copied()),
            Node::Split { a, b, .. } => {
                a.collect(out);
                b.collect(out);
            }
        }
    }
    fn active_tabs(&self) -> Vec<PanelId> {
        match self {
            Node::Leaf { tabs, active } => tabs.get(*active).or(tabs.first()).copied().into_iter().collect(),
            Node::Split { a, b, .. } => {
                let mut v = a.active_tabs();
                v.extend(b.active_tabs());
                v
            }
        }
    }
    fn remove(&mut self, p: PanelId) {
        match self {
            Node::Leaf { tabs, active } => {
                if let Some(k) = tabs.iter().position(|t| *t == p) {
                    tabs.remove(k);
                    if *active != usize::MAX && *active >= k && *active > 0 {
                        *active -= 1;
                    }
                }
            }
            Node::Split { a, b, .. } => {
                a.remove(p);
                b.remove(p);
            }
        }
    }
    fn dedupe(&mut self, seen: &mut std::collections::HashSet<PanelId>) {
        match self {
            Node::Leaf { tabs, active } => {
                tabs.retain(|t| seen.insert(*t));
                *active = (*active).min(tabs.len().saturating_sub(1));
            }
            Node::Split { a, b, ratio, .. } => {
                *ratio = ratio.clamp(0.05, 0.95);
                a.dedupe(seen);
                b.dedupe(seen);
            }
        }
    }
    /// Replace splits that have an empty side by the other side. The
    /// placeholder leaf (active = MAX) is never collapsed away.
    fn collapse(&mut self) {
        if let Node::Split { a, b, .. } = self {
            a.collapse();
            b.collapse();
            let empty = |n: &Node| matches!(n, Node::Leaf { tabs, active } if tabs.is_empty() && *active != usize::MAX);
            if empty(a) {
                *self = std::mem::replace(b.as_mut(), leaf(&[]));
            } else if empty(b) {
                *self = std::mem::replace(a.as_mut(), leaf(&[]));
            }
        }
    }
    fn replace_placeholder(&mut self, with: Node) -> bool {
        match self {
            Node::Leaf { active, .. } if *active == usize::MAX => {
                *self = with;
                true
            }
            Node::Leaf { .. } => false,
            Node::Split { a, b, .. } => a.replace_placeholder(with.clone()) || b.replace_placeholder(with),
        }
    }
    pub fn at(&self, path: &[u8]) -> Option<&Node> {
        match (path.first(), self) {
            (None, n) => Some(n),
            (Some(0), Node::Split { a, .. }) => a.at(&path[1..]),
            (Some(_), Node::Split { b, .. }) => b.at(&path[1..]),
            _ => None,
        }
    }
    fn at_mut(&mut self, path: &[u8]) -> Option<&mut Node> {
        match (path.first(), self) {
            (None, n) => Some(n),
            (Some(0), Node::Split { a, .. }) => a.at_mut(&path[1..]),
            (Some(_), Node::Split { b, .. }) => b.at_mut(&path[1..]),
            _ => None,
        }
    }
    pub fn path_of(&self, p: PanelId) -> Option<Vec<u8>> {
        match self {
            Node::Leaf { tabs, .. } => tabs.contains(&p).then(Vec::new),
            Node::Split { a, b, .. } => a.path_of(p).map(|mut v| {
                v.insert(0, 0);
                v
            }).or_else(|| b.path_of(p).map(|mut v| {
                v.insert(0, 1);
                v
            })),
        }
    }
    fn first_non_viewport_leaf(&self) -> Option<Vec<u8>> {
        match self {
            Node::Leaf { tabs, .. } => (!tabs.contains(&PanelId::Viewport)).then(Vec::new),
            Node::Split { a, b, .. } => b.first_non_viewport_leaf().map(|mut v| {
                v.insert(0, 1);
                v
            }).or_else(|| a.first_non_viewport_leaf().map(|mut v| {
                v.insert(0, 0);
                v
            })),
        }
    }
}

// ------------------------------------------------------------------ drawing

/// A tab being dragged.
#[derive(Clone, Copy)]
struct TabDrag(PanelId);

/// Leaf rects computed for a frame: (path, content rect incl. tab bar).
fn layout_rects(node: &Node, rect: Rect, path: &mut Vec<u8>, out: &mut Vec<(Vec<u8>, Rect)>, splits: &mut Vec<(Vec<u8>, Rect, bool, Rect)>) {
    match node {
        Node::Leaf { .. } => out.push((path.clone(), rect)),
        Node::Split { vertical, ratio, a, b } => {
            let gap = size::SPLITTER;
            let (ra, rb, bar) = if *vertical {
                let y = rect.top() + (rect.height() - gap) * ratio;
                (Rect::from_min_max(rect.min, pos2(rect.right(), y)), Rect::from_min_max(pos2(rect.left(), y + gap), rect.max), Rect::from_min_max(pos2(rect.left(), y), pos2(rect.right(), y + gap)))
            } else {
                let x = rect.left() + (rect.width() - gap) * ratio;
                (Rect::from_min_max(rect.min, pos2(x, rect.bottom())), Rect::from_min_max(pos2(x + gap, rect.top()), rect.max), Rect::from_min_max(pos2(x, rect.top()), pos2(x + gap, rect.bottom())))
            };
            splits.push((path.clone(), bar, *vertical, rect));
            path.push(0);
            layout_rects(a, ra, path, out, splits);
            path.pop();
            path.push(1);
            layout_rects(b, rb, path, out, splits);
            path.pop();
        }
    }
}

fn zone_at(rect: Rect, p: egui::Pos2) -> Zone {
    let u = (p.x - rect.left()) / rect.width().max(1.0);
    let w = (p.y - rect.top()) / rect.height().max(1.0);
    let edge = 0.22;
    let d = [(u, Zone::Left), (1.0 - u, Zone::Right), (w, Zone::Top), (1.0 - w, Zone::Bottom)];
    let (m, z) = d.iter().copied().fold((1.0f32, Zone::Center), |acc, (x, z)| if x < acc.0 { (x, z) } else { acc });
    if m < edge {
        z
    } else {
        Zone::Center
    }
}

fn zone_rect(rect: Rect, z: Zone) -> Rect {
    match z {
        Zone::Center => rect.shrink(space::MD),
        Zone::Left => Rect::from_min_max(rect.min, pos2(rect.left() + rect.width() * 0.4, rect.bottom())),
        Zone::Right => Rect::from_min_max(pos2(rect.right() - rect.width() * 0.4, rect.top()), rect.max),
        Zone::Top => Rect::from_min_max(rect.min, pos2(rect.right(), rect.top() + rect.height() * 0.4)),
        Zone::Bottom => Rect::from_min_max(pos2(rect.left(), rect.bottom() - rect.height() * 0.4), rect.max),
    }
}

/// What happened in the dock this frame.
#[derive(Default)]
pub struct DockOutput {
    /// Panel rects drawn this frame (for anchors / tests).
    pub rects: Vec<(PanelId, Rect)>,
}

/// Draw the layout in `rect`, calling `panel` for each visible panel.
pub fn show(ui: &mut Ui, layout: &mut DockLayout, mut panel: impl FnMut(&mut Ui, PanelId)) -> DockOutput {
    let p = design::pal(ui);
    let rect = ui.available_rect_before_wrap();
    ui.painter().rect_filled(rect, CornerRadius::ZERO, p.bg);
    let mut leaves = vec![];
    let mut splits = vec![];
    layout_rects(&layout.root, rect, &mut vec![], &mut leaves, &mut splits);
    let mut out = DockOutput::default();
    let mut actions: Vec<Box<dyn FnOnce(&mut DockLayout)>> = vec![];

    // splitters
    for (path, bar, vertical, parent) in &splits {
        let id = ui.scope_id().with(("dock split", path));
        let r = ui.interact(bar.expand(2.0), id, Sense::drag());
        let hot = r.hovered() || r.dragged();
        if hot {
            ui.ctx().set_cursor_icon(if *vertical { egui::CursorIcon::ResizeVertical } else { egui::CursorIcon::ResizeHorizontal });
            ui.painter().rect_filled(*bar, CornerRadius::ZERO, if r.dragged() { p.accent.gamma_multiply(0.7) } else { p.border_strong });
        }
        if r.dragged() {
            if let Some(pos) = r.interact_pointer_pos() {
                let ratio = if *vertical { (pos.y - parent.top()) / parent.height() } else { (pos.x - parent.left()) / parent.width() };
                let path = path.clone();
                actions.push(Box::new(move |l: &mut DockLayout| {
                    if let Some(Node::Split { ratio: rr, .. }) = l.root.at_mut(&path) {
                        *rr = ratio.clamp(0.08, 0.92);
                    }
                }));
            }
        }
    }

    let dragging = egui::DragAndDrop::payload::<TabDrag>(ui.ctx()).map(|d| d.0);
    let pointer = ui.ctx().pointer_latest_pos();
    let released = ui.input(|i| i.pointer.any_released());

    let m = design::metrics(ui);
    for (path, lrect) in &leaves {
        let Some(Node::Leaf { tabs, active }) = layout.root.at(path).cloned() else { continue };
        if tabs.is_empty() {
            continue;
        }
        let active = active.min(tabs.len() - 1);
        let only_viewport = tabs.len() == 1 && tabs[0] == PanelId::Viewport;
        let lrect = lrect.shrink(0.5);
        let content = if only_viewport { lrect } else { Rect::from_min_max(pos2(lrect.left(), lrect.top() + m.tab_h), lrect.max) };
        if !only_viewport {
            // the tab strip sits on the darker background; the active tab joins the panel below
            let bar = Rect::from_min_max(lrect.min, pos2(lrect.right(), lrect.top() + m.tab_h));
            ui.painter().rect_filled(bar, CornerRadius { nw: radius::LG, ne: radius::LG, sw: 0, se: 0 }, p.bg.lerp_to_gamma(p.surface, 0.45));
            let mut x = bar.left();
            let isz = icon::SM - 1.0;
            for (k, t) in tabs.iter().enumerate() {
                let on = k == active;
                let g = ui.painter().layout_no_wrap(t.title().to_string(), fonts::regular(font::SMALL), p.text);
                let w = g.size().x + isz + space::SM + space::MD * 2.0 + if t.closable() { isz + space::XXS } else { 0.0 };
                let w = w.min(bar.right() - x).max(0.0);
                if w < 24.0 {
                    break;
                }
                let tr = Rect::from_min_size(pos2(x, bar.top()), vec2(w, m.tab_h));
                let id = ui.scope_id().with(("dock tab", *t));
                let r = ui.interact(tr, id, Sense::click_and_drag());
                let bg = if on { p.surface } else if r.hovered() { p.surface_raised } else { egui::Color32::TRANSPARENT };
                ui.painter().rect_filled(tr, CornerRadius { nw: radius::LG, ne: radius::LG, sw: 0, se: 0 }, bg);
                let fg = if on { p.text } else if r.hovered() { p.text_secondary } else { p.text_muted };
                let painter = ui.painter().with_clip_rect(tr);
                t.icon().paint(&painter, Rect::from_min_size(pos2(tr.left() + space::MD, tr.center().y - isz / 2.0), vec2(isz, isz)), if on { p.text_secondary } else { fg });
                painter.galley(pos2(tr.left() + space::MD + isz + space::SM, tr.center().y - g.size().y / 2.0), g, fg);
                if t.closable() && r.hovered() {
                    let cr = Rect::from_center_size(pos2(tr.right() - space::SM - isz / 2.0 + 2.0, tr.center().y), vec2(isz - 3.0, isz - 3.0));
                    let c = ui.interact(cr.expand(2.0), id.with("close"), Sense::click());
                    Icon::Close.paint(ui.painter(), cr, if c.hovered() { p.danger } else { p.text_muted });
                    if c.on_hover_text("Close panel (reopen it from the Window menu)").clicked() {
                        let t = *t;
                        actions.push(Box::new(move |l: &mut DockLayout| l.remove(t)));
                    }
                }
                if r.clicked() {
                    let (path, k) = (path.clone(), k);
                    actions.push(Box::new(move |l: &mut DockLayout| {
                        if let Some(Node::Leaf { active, .. }) = l.root.at_mut(&path) {
                            *active = k;
                        }
                    }));
                }
                if r.drag_started() {
                    egui::DragAndDrop::set_payload(ui.ctx(), TabDrag(*t));
                }
                let t2 = *t;
                r.context_menu(|ui| {
                    if ui.button("Float as window").clicked() {
                        let pos = tr.left_bottom() + vec2(20.0, 20.0);
                        actions.push(Box::new(move |l: &mut DockLayout| l.float(t2, pos)));
                        ui.close();
                    }
                    if t2.closable() && ui.button("Close").clicked() {
                        actions.push(Box::new(move |l: &mut DockLayout| l.remove(t2)));
                        ui.close();
                    }
                });
                out.rects.push((*t, tr));
                x += w + 1.0;
            }
        }
        let t = tabs[active];
        ui.painter().rect_filled(content, CornerRadius { nw: 0, ne: 0, sw: radius::LG, se: radius::LG }, if t == PanelId::Viewport { p.bg } else { p.surface });
        let mut child = ui.new_child(egui::UiBuilder::new().max_rect(content).id_salt(("dock panel", t)).layout(egui::Layout::top_down(egui::Align::Min)));
        child.set_clip_rect(content.intersect(ui.clip_rect()));
        if t == PanelId::Viewport {
            panel(&mut child, t);
        } else {
            egui::ScrollArea::vertical().id_salt(("panel scroll", t)).auto_shrink([false, false]).show(&mut child, |ui| {
                egui::Frame::new().inner_margin(egui::Margin::same(m.pad as i8)).show(ui, |ui| {
                    ui.set_width(ui.available_width());
                    panel(ui, t)
                });
            });
        }
        out.rects.push((t, content));

        // drop target highlight
        if let (Some(d), Some(pos)) = (dragging, pointer) {
            if lrect.contains(pos) {
                let z = zone_at(content, pos);
                let painter = ui.ctx().layer_painter(egui::LayerId::new(egui::Order::Foreground, egui::Id::NULL.with("dock drop")));
                let zr = zone_rect(content, z);
                painter.rect(zr, CornerRadius::same(radius::LG), p.accent.gamma_multiply(0.14), Stroke::new(1.5, p.accent), StrokeKind::Inside);
                painter.text(zr.center(), Align2::CENTER_CENTER, if z == Zone::Center { format!("Add {} here", d.title()) } else { format!("Split: {}", d.title()) }, fonts::semibold(font::BODY), p.text);
                if released {
                    let path = path.clone();
                    actions.push(Box::new(move |l: &mut DockLayout| l.dock(d, &path, z)));
                }
            }
        }
    }
    // dropped outside every leaf: float it
    if let (Some(d), Some(pos), true) = (dragging, pointer, released) {
        if !rect.contains(pos) && d.closable() {
            actions.push(Box::new(move |l: &mut DockLayout| l.float(d, pos)));
        }
    }
    if released {
        egui::DragAndDrop::clear_payload(ui.ctx());
    }

    // floating windows
    let mut floats = layout.floating.clone();
    for f in &mut floats {
        let mut open = true;
        let mut dock_back = false;
        let w = egui::Window::new(egui::RichText::new(f.panel.title()).font(fonts::semibold(font::BODY)))
            .id(egui::Id::NULL.with(("float", f.panel)))
            .open(&mut open)
            .default_pos(pos2(f.pos[0], f.pos[1]))
            .default_size(vec2(f.size[0], f.size[1]))
            .resizable(true)
            .collapsible(true)
            .frame(design::overlay_frame(&p).inner_margin(egui::Margin::same(space::MD as i8)))
            .show(ui.ctx(), |ui| {
                if ui.add(design::Btn::ghost("Dock").icon(Icon::Window).small()).on_hover_text("Put this panel back into the window").clicked() {
                    dock_back = true;
                }
                egui::ScrollArea::vertical().id_salt(("float scroll", f.panel)).show(ui, |ui| panel(ui, f.panel));
            });
        if let Some(r) = w {
            f.pos = [r.response.rect.left(), r.response.rect.top()];
            f.size = [r.response.rect.width(), r.response.rect.height()];
            out.rects.push((f.panel, r.response.rect));
        }
        let fp = f.panel;
        if !open {
            actions.push(Box::new(move |l: &mut DockLayout| l.remove(fp)));
        } else if dock_back {
            actions.push(Box::new(move |l: &mut DockLayout| {
                l.remove(fp);
                l.open(fp);
            }));
        }
    }
    for (a, b) in layout.floating.iter_mut().zip(floats) {
        if a.panel == b.panel {
            *a = b;
        }
    }
    for a in actions {
        a(layout);
    }
    ui.allocate_rect(rect, Sense::hover());
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn layouts_round_trip_through_json() {
        for name in PRESETS {
            let l = DockLayout::preset(name).unwrap();
            let s = serde_json::to_string(&l).unwrap();
            let back: DockLayout = serde_json::from_str(&s).unwrap();
            assert_eq!(back, l, "{name}");
            assert!(l.contains(PanelId::Viewport), "{name} has the viewport");
            let mut panels = l.panels();
            let n = panels.len();
            panels.sort();
            panels.dedup();
            assert_eq!(panels.len(), n, "{name}: duplicate panels");
        }
    }

    #[test]
    fn docking_moves_splits_floats_and_reopens() {
        let mut l = DockLayout::beginner();
        assert!(!l.contains(PanelId::Layers));
        l.open(PanelId::Layers);
        assert!(l.contains(PanelId::Layers));
        // move Library onto the viewport's left edge: a new split
        let vp = l.root.path_of(PanelId::Viewport).unwrap();
        l.dock(PanelId::Library, &vp, Zone::Left);
        let lib = l.root.path_of(PanelId::Library).unwrap();
        let vp2 = l.root.path_of(PanelId::Viewport).unwrap();
        assert_eq!(lib.len(), vp2.len(), "siblings after a split: {:?}", l.root);
        assert_ne!(lib, vp2);
        // tab it next to the viewport instead
        let vp = l.root.path_of(PanelId::Viewport).unwrap();
        l.dock(PanelId::Library, &vp, Zone::Center);
        assert_eq!(l.root.path_of(PanelId::Library), l.root.path_of(PanelId::Viewport));
        // float, then close: gone; reopen: back
        l.float(PanelId::Library, egui::pos2(10.0, 10.0));
        assert!(l.floating.iter().any(|f| f.panel == PanelId::Library));
        assert!(l.root.path_of(PanelId::Library).is_none());
        l.remove(PanelId::Library);
        assert!(!l.contains(PanelId::Library));
        l.open(PanelId::Library);
        assert!(l.contains(PanelId::Library));
        // nothing duplicated or lost
        let mut ps = l.panels();
        let n = ps.len();
        ps.sort();
        ps.dedup();
        assert_eq!(n, ps.len());
        assert!(l.contains(PanelId::Viewport));
    }

    #[test]
    fn repair_restores_a_viewport_and_drops_duplicates() {
        let mut l = DockLayout { root: h(0.5, leaf(&[PanelId::Layers, PanelId::Layers]), leaf(&[])), floating: vec![Floating { panel: PanelId::Layers, pos: [0.0; 2], size: [1.0; 2] }] };
        l.repair();
        assert!(l.contains(PanelId::Viewport));
        assert_eq!(l.panels().iter().filter(|p| **p == PanelId::Layers).count(), 1);
    }
}
