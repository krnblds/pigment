//! Dockable panels. Each is a self-contained widget struct registered by
//! `PanelId`; it keeps its own UI state (search text, filters, previews)
//! between frames, and its scroll position lives in egui memory under the
//! panel's id. New panels plug in by implementing `Panel` and registering in
//! `Panels::new`.

use super::dock::PanelId;
use super::*;
use std::collections::BTreeMap;

pub mod decals;
pub mod layers;
pub mod library;
pub mod misc;

/// A dockable panel.
pub trait Panel {
    fn id(&self) -> PanelId;
    fn ui(&mut self, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState);
}

pub struct Panels {
    map: BTreeMap<PanelId, Box<dyn Panel>>,
}

impl Default for Panels {
    fn default() -> Self {
        Panels::new()
    }
}

impl Panels {
    pub fn new() -> Panels {
        let list: Vec<Box<dyn Panel>> = vec![
            Box::new(misc::ViewportPanel),
            Box::new(library::LibraryPanel::default()),
            Box::new(library::LookPanel),
            Box::new(misc::BrushPanel),
            Box::new(layers::LayersPanel::default()),
            Box::new(layers::PropertiesPanel),
            Box::new(layers::ChannelsPanel),
            Box::new(layers::MaskPanel),
            Box::new(decals::DecalsPanel::default()),
            Box::new(misc::PartsPanel::default()),
            Box::new(misc::VariantsPanel),
            Box::new(misc::LightingPanel),
            Box::new(misc::HistoryPanel),
            Box::new(misc::ExportPanel),
            Box::new(misc::TextureSetPanel),
        ];
        Panels { map: list.into_iter().map(|p| (p.id(), p)).collect() }
    }

    #[cfg_attr(not(test), allow(dead_code))]
    pub fn ids(&self) -> Vec<PanelId> {
        self.map.keys().copied().collect()
    }

    pub fn show(&mut self, id: PanelId, app: &mut PigmentApp, ui: &mut egui::Ui, rs: &RenderState) {
        match self.map.get_mut(&id) {
            Some(p) => p.ui(app, ui, rs),
            None => {
                ui.label(format!("{} is not available", id.title()));
            }
        }
    }
}
