//! Export templates in the app: find (project > user > built-in), save,
//! and export every texture set / UDIM tile with one.

use super::*;
use pigment_core::templates::{self, ExportTemplate};

/// Where a template comes from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TemplateScope {
    Builtin,
    User,
    Project,
}

impl TemplateScope {
    pub fn id(self) -> &'static str {
        match self {
            TemplateScope::Builtin => "builtin",
            TemplateScope::User => "user",
            TemplateScope::Project => "project",
        }
    }
}

impl PigmentApp {
    fn user_template_dir(&self) -> Option<PathBuf> {
        self.ui.prefs.dir.clone().or_else(prefs::config_dir)
    }

    /// Every template: built-in, user, project (later ones override by id).
    pub fn all_templates(&self) -> Vec<(ExportTemplate, TemplateScope)> {
        let mut v: Vec<(ExportTemplate, TemplateScope)> = templates::builtin().into_iter().map(|t| (t, TemplateScope::Builtin)).collect();
        let user = self.user_template_dir().map(|d| templates::load_user(&d)).unwrap_or_default();
        for (t, s) in user.into_iter().map(|t| (t, TemplateScope::User)).chain(self.doc.export_templates.iter().cloned().map(|t| (t, TemplateScope::Project))) {
            v.retain(|(x, _)| x.id != t.id);
            v.push((t, s));
        }
        v
    }

    pub fn find_template(&self, id: &str) -> Option<ExportTemplate> {
        self.all_templates().into_iter().find(|(t, _)| t.id.eq_ignore_ascii_case(id)).map(|(t, _)| t)
    }

    /// Save a template with the project or in the user prefs.
    pub fn save_template(&mut self, t: ExportTemplate, scope: TemplateScope) -> Result<PathBuf, String> {
        t.validate()?;
        match scope {
            TemplateScope::Project => {
                self.doc.export_templates.retain(|x| x.id != t.id);
                self.doc.export_templates.push(t);
                Ok(self.project_dir.clone().unwrap_or_default())
            }
            TemplateScope::User => {
                let dir = self.user_template_dir().ok_or("no user preferences folder")?;
                let mut list = templates::load_user(&dir);
                list.retain(|x| x.id != t.id);
                list.push(t);
                templates::save_user(&dir, &list).map_err(|e| format!("saving templates: {e:#}"))?;
                Ok(dir.join(templates::USER_FILE))
            }
            TemplateScope::Builtin => Err("built-in templates can't be overwritten; save under another id".into()),
        }
    }

    /// Export with a template: every texture set and tile (tokens {name},
    /// {set}, {udim}; with several sets a pattern without {set} gets
    /// `_<set>` after the name and `.<udim>` at the end).
    pub fn export_with_template(&mut self, rs: &RenderState, dir: &Path, t: &ExportTemplate, name: &str, compression: export::Compression) -> Result<Vec<PathBuf>, String> {
        t.validate()?;
        let home = self.active_set_name();
        let multi = self.has_sets();
        let mut tt = t.clone();
        if multi {
            for o in &mut tt.outputs {
                if !o.pattern.contains("{set}") {
                    o.pattern = o.pattern.replacen("{name}", "{name}_{set}", 1);
                }
                if !o.pattern.contains("{udim}") {
                    o.pattern.push_str(".{udim}");
                }
            }
        }
        let mut files = Vec::new();
        for set in self.set_names() {
            self.activate_set(rs, &set)?;
            self.ensure_composited(rs);
            let _ = rs.device.poll(eframe::egui_wgpu::wgpu::PollType::Wait { submission_index: None, timeout: None });
            let m = io::read_material(&rs.device, &rs.queue, &self.ts);
            let hdr = tt.needs_hdr().then(|| io::read_hdr_planes(&rs.device, &rs.queue, &self.ts));
            let udim = self.doc.texture_set.as_ref().map(|s| s.tile()).unwrap_or(1001);
            let set_token = if multi { pigment_core::texsets::sanitize(&set) } else { String::new() };
            files.extend(templates::export(dir, &tt, &m, hdr.as_ref(), name, &set_token, udim, compression).map_err(|e| format!("{e:#}"))?);
        }
        self.activate_set(rs, &home)?;
        Ok(files)
    }
}
