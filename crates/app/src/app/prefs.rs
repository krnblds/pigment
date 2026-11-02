//! User preferences, remembered between sessions in `<config>/pigment/prefs.json`:
//! theme, UI scale, Simple / Advanced mode, the dock layout of each mode and
//! named custom layouts, recent files, window size and the autosave folder.

use super::dock::DockLayout;
use crate::app::design::{Density, ThemeKind};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default, Serialize, Deserialize)]
pub enum Mode {
    /// Big material library, a few tools, one weathering slider, Export.
    #[default]
    Simple,
    /// The full layer stack, masks, generators, channels, variants...
    Advanced,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Prefs {
    #[serde(skip)]
    pub dir: Option<PathBuf>,
    pub theme: ThemeKind,
    pub ui_scale: f32,
    pub mode: Mode,
    pub layout_simple: DockLayout,
    pub layout_advanced: DockLayout,
    pub custom_layouts: Vec<(String, DockLayout)>,
    /// Most recent first: projects (.pigment folders) and models.
    pub recent: Vec<PathBuf>,
    /// Inner window size in points.
    pub window: Option<[f32; 2]>,
    pub show_welcome: bool,
    pub tour_done: bool,
    /// Minutes between autosaves (0 = off).
    pub autosave_minutes: f32,
    pub export_dir: Option<PathBuf>,
    pub export_target: String,
    /// Compact (default) or Comfortable spacing.
    pub density: Density,
    /// Collapsible panel sections the user opened or closed, by id.
    pub sections: std::collections::BTreeMap<String, bool>,
    /// Command palette: most recently run command ids, newest first.
    pub recent_commands: Vec<String>,
}

impl Default for Prefs {
    fn default() -> Self {
        Prefs {
            dir: None,
            theme: ThemeKind::Dark,
            ui_scale: 1.0,
            mode: Mode::Simple,
            layout_simple: DockLayout::beginner(),
            layout_advanced: DockLayout::texturing(),
            custom_layouts: Vec::new(),
            recent: Vec::new(),
            window: None,
            show_welcome: true,
            tour_done: false,
            autosave_minutes: 3.0,
            export_dir: None,
            export_target: "blender".into(),
            density: Density::Compact,
            sections: Default::default(),
            recent_commands: Vec::new(),
        }
    }
}

/// `%APPDATA%/pigment` (Windows), `$XDG_CONFIG_HOME/pigment` or `~/.config/pigment`.
pub fn config_dir() -> Option<PathBuf> {
    let base = std::env::var_os("APPDATA").or_else(|| std::env::var_os("XDG_CONFIG_HOME")).map(PathBuf::from).or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("pigment"))
}

impl Prefs {
    /// Preferences stored in `dir` (tests and the harness use a temp dir).
    pub fn in_dir(dir: PathBuf) -> Prefs {
        let mut p = std::fs::read_to_string(dir.join("prefs.json")).ok().and_then(|s| serde_json::from_str::<Prefs>(&s).ok()).unwrap_or_default();
        p.dir = Some(dir);
        p.sanitize();
        p
    }

    /// The user's preferences (defaults when there are none yet).
    pub fn load() -> Prefs {
        match config_dir() {
            Some(d) => {
                let mut p = Prefs::in_dir(d);
                // the old quick-start marker counts as having seen the tour
                if p.dir.as_ref().is_some_and(|d| d.join("quick_start_done").exists()) {
                    p.tour_done = true;
                }
                p
            }
            None => Prefs::default(),
        }
    }

    fn sanitize(&mut self) {
        if !(0.5..=3.0).contains(&self.ui_scale) {
            self.ui_scale = 1.0;
        }
        for l in [&mut self.layout_simple, &mut self.layout_advanced] {
            l.repair();
        }
        self.recent.retain(|p| p.exists());
        self.recent.truncate(12);
    }

    pub fn save(&self) -> Result<(), String> {
        let Some(dir) = &self.dir else { return Ok(()) };
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        let s = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        let tmp = dir.join("prefs.json.tmp");
        std::fs::write(&tmp, s).map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, dir.join("prefs.json")).map_err(|e| e.to_string())
    }

    pub fn add_recent(&mut self, p: &Path) {
        let p = p.to_path_buf();
        self.recent.retain(|r| r != &p);
        self.recent.insert(0, p);
        self.recent.truncate(12);
    }

    pub fn layout(&self) -> &DockLayout {
        match self.mode {
            Mode::Simple => &self.layout_simple,
            Mode::Advanced => &self.layout_advanced,
        }
    }

    pub fn layout_mut(&mut self) -> &mut DockLayout {
        match self.mode {
            Mode::Simple => &mut self.layout_simple,
            Mode::Advanced => &mut self.layout_advanced,
        }
    }

    pub fn autosave_dir(&self) -> Option<PathBuf> {
        self.dir.as_ref().map(|d| d.join("autosave"))
    }

    pub fn thumb_dir(&self) -> Option<PathBuf> {
        self.dir.as_ref().map(|d| d.join("thumbs"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prefs_round_trip_through_disk() {
        let dir = std::env::temp_dir().join(format!("pigment-prefs-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let mut p = Prefs::in_dir(dir.clone());
        assert_eq!(p.mode, Mode::Simple);
        p.mode = Mode::Advanced;
        p.theme = ThemeKind::Light;
        p.density = Density::Comfortable;
        p.sections.insert("props.glow".into(), true);
        p.ui_scale = 1.25;
        p.layout_advanced = DockLayout::compact();
        p.custom_layouts.push(("Mine".into(), DockLayout::painting()));
        p.save().unwrap();
        let q = Prefs::in_dir(dir.clone());
        assert_eq!(q.mode, Mode::Advanced);
        assert_eq!(q.theme, ThemeKind::Light);
        assert_eq!(q.ui_scale, 1.25);
        assert_eq!(q.density, Density::Comfortable);
        assert_eq!(q.sections.get("props.glow"), Some(&true));
        assert_eq!(q.layout_advanced, DockLayout::compact());
        assert_eq!(q.custom_layouts, p.custom_layouts);
        // a corrupt file falls back to defaults instead of failing
        std::fs::write(dir.join("prefs.json"), "{ not json").unwrap();
        assert_eq!(Prefs::in_dir(dir.clone()).mode, Mode::Simple);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
