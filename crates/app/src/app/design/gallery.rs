//! The design gallery (`pigment --design-gallery`): every token and component
//! in every state, used to review the system and for docs/design/gallery*.png.

use super::*;
use egui::{vec2, Rect, Ui};

pub struct GalleryState {
    pub toggle_a: bool,
    pub toggle_b: bool,
    pub seg: u8,
    pub tab: u8,
    pub slider: f32,
    pub pct: f32,
    pub size_px: f32,
    pub density: Density,
    pub color: [f32; 3],
    pub search: String,
    pub palette: Palette2State,
    pub toasts: Toasts,
    pub seeded: bool,
}

impl Default for GalleryState {
    fn default() -> Self {
        GalleryState {
            toggle_a: true,
            toggle_b: false,
            seg: 0,
            tab: 0,
            slider: 0.35,
            pct: 0.62,
            size_px: 60.0,
            density: Density::Compact,
            color: [0.86, 0.36, 0.08],
            search: "rust".into(),
            palette: Palette2State { open: false, query: "exp".into(), cursor: 0, recent: vec![] },
            toasts: Toasts::default(),
            seeded: false,
        }
    }
}

fn swatch_row(ui: &mut Ui, items: &[(&str, egui::Color32)]) {
    ui.horizontal_wrapped(|ui| {
        for (name, c) in items {
            ui.vertical(|ui| {
                let (r, _) = ui.allocate_exact_size(vec2(56.0, 28.0), egui::Sense::hover());
                ui.painter().rect(r, egui::CornerRadius::same(radius::MD), *c, egui::Stroke::new(1.0, pal(ui).border), egui::StrokeKind::Inside);
                ui.label(text(*name, font::CAPTION).color(pal(ui).text_muted));
            });
        }
    });
}

pub fn show(ui: &mut Ui, st: &mut GalleryState) {
    let p = pal(ui);
    if !st.seeded {
        st.seeded = true;
        st.toasts.push(ToastKind::Success, "Exported 5 maps", "Saved to Documents/Pigment Exports/Crate");
        st.toasts.push(ToastKind::Progress, "Baking AO + curvature", "");
        st.toasts.push(ToastKind::Error, "Couldn't open model", "car.fbx: only OBJ and glTF/GLB are supported.");
    }
    egui::ScrollArea::vertical().show(ui, |ui| {
        ui.label(strong("Pigment design system", font::DISPLAY));
        ui.label(muted(ui, "Dark, compact, keyboard-first. Tokens and components in every state: theme, type, icons, controls, surfaces, feedback."));
        ui.horizontal(|ui| {
            ui.label(text("Density", font::SMALL).color(p.text_secondary));
            if segmented(ui, &mut st.density, &[(Density::Compact, None, "Compact"), (Density::Comfortable, None, "Comfortable")]) {
                set_density(ui.ctx(), st.density);
            }
        });
        ui.add_space(space::MD);
        ui.columns(2, |cols| {
            let ui = &mut cols[0];
            section(ui, "Colour roles");
            swatch_row(ui, &[("bg", p.bg), ("surface", p.surface), ("raised", p.surface_raised), ("hover", p.surface_hover), ("well", p.well), ("overlay", p.overlay)]);
            swatch_row(ui, &[("text", p.text), ("secondary", p.text_secondary), ("muted", p.text_muted), ("disabled", p.text_disabled), ("border", p.border), ("strong", p.border_strong)]);
            swatch_row(ui, &[("accent", p.accent), ("hover", p.accent_hover), ("pressed", p.accent_pressed), ("subtle", p.accent_subtle), ("success", p.success), ("warn", p.warn)]);
            swatch_row(ui, &[("danger", p.danger), ("info", p.info), ("focus", p.focus), ("selection", p.selection)]);
            section(ui, "Type scale (Inter, JetBrains Mono)");
            ui.label(strong("Display 24", font::DISPLAY));
            ui.label(strong("Heading 15 semibold", font::HEADING));
            ui.label(strong("Title 13.5 semibold", font::TITLE));
            ui.label(text("Body 12.5: paint PBR textures onto 3D models.", font::BODY));
            ui.label(text("Small 12: secondary information", font::SMALL).color(p.text_secondary));
            ui.label(caption(ui, "Caption 11 upper case, tracked"));
            ui.label(mono("Mono 11.5  0.62  2048 px  -0.35"));
            section(ui, "Spacing, radii, elevation");
            ui.horizontal(|ui| {
                for s in [space::XXS, space::XS, space::SM, space::MD, space::LG, space::XL, space::XXL, space::XXXL] {
                    let (r, _) = ui.allocate_exact_size(vec2(s, 14.0), egui::Sense::hover());
                    ui.painter().rect_filled(r, egui::CornerRadius::ZERO, p.accent);
                }
            });
            ui.horizontal(|ui| {
                for (lvl, rad) in [(0u8, radius::SM), (1, radius::MD), (2, radius::LG), (3, radius::XL)] {
                    egui::Frame::new().fill(p.surface_raised).corner_radius(egui::CornerRadius::same(rad)).shadow(elevation(lvl, &p)).inner_margin(egui::Margin::same(space::LG as i8)).show(ui, |ui| {
                        ui.label(text(format!("e{lvl} r{rad}"), font::SMALL));
                    });
                    ui.add_space(space::MD);
                }
            });
            section(ui, "Icons (18 pt grid, 1.6 stroke)");
            ui.horizontal_wrapped(|ui| {
                for i in Icon::ALL {
                    let (r, resp) = ui.allocate_exact_size(vec2(icon::LG + space::MD, icon::LG + space::MD), egui::Sense::hover());
                    i.paint(ui.painter(), Rect::from_center_size(r.center(), vec2(icon::LG, icon::LG)), p.text_secondary);
                    resp.on_hover_text(i.name());
                }
            });
            section(ui, "Buttons: rest / selected / disabled");
            for kind in [BtnKind::Primary, BtnKind::Secondary, BtnKind::Ghost, BtnKind::Danger] {
                ui.horizontal(|ui| {
                    ui.add(Btn::new(kind, format!("{kind:?}")).icon(Icon::Export));
                    ui.add(Btn::new(kind, "Selected").selected(true));
                    ui.add(Btn::new(kind, "Disabled").enabled(false));
                    ui.add(Btn::new(kind, "Small").small());
                    ui.add(Btn::new(kind, "Shortcut").shortcut("Ctrl+E"));
                });
            }
            ui.horizontal(|ui| {
                ui.add(Btn::primary("Large primary").icon(Icon::Sparkle).large());
                ui.add(IconBtn::new(Icon::Undo, "Undo").shortcut("Ctrl+Z"));
                ui.add(IconBtn::new(Icon::Redo, "Redo").selected(true));
                ui.add(IconBtn::new(Icon::Trash, "Delete").enabled(false));
            });

            let ui = &mut cols[1];
            section(ui, "Drag fields: drag, Shift fine, Ctrl snap, double-click to type");
            ui.add(DragField::new(&mut st.size_px, 2.0..=800.0).suffix(" px").decimals(0).logarithmic(true).label("Size"));
            ui.add(DragField::new(&mut st.pct, 0.0..=1.0).percent().label("Strength"));
            slider_row(ui, "Roughness", &mut st.slider, 0.0..=1.0, Unit::Plain(2));
            slider_row(ui, "How worn?", &mut st.pct, 0.0..=1.0, Unit::Percent);
            collapsible(ui, "gallery.more", "Collapsible section (open)", true, |ui| {
                slider_row(ui, "Threshold", &mut st.slider, 0.0..=1.0, Unit::Plain(2));
            });
            collapsible(ui, "gallery.closed", "Collapsed section", false, |ui| {
                ui.label("hidden");
            });
            section(ui, "Menu items and status hints");
            egui::Frame::new().fill(p.overlay).stroke(egui::Stroke::new(1.0, p.border_strong)).corner_radius(egui::CornerRadius::same(radius::LG)).inner_margin(egui::Margin::same(space::XS as i8)).show(ui, |ui| {
                ui.set_width(240.0);
                ui.add(MenuItem::new("Rename").icon(Icon::Sliders).shortcut("F2"));
                ui.add(MenuItem::new("Duplicate").icon(Icon::Duplicate).shortcut("Ctrl+D"));
                ui.add(MenuItem::new("Show in viewport").checked(true));
                ui.add(MenuItem::new("Move down").enabled(false));
                ui.add(MenuItem::new("Delete").icon(Icon::Trash).shortcut("Del").danger());
            });
            hint_row(ui, &[hint_mouse(MouseBtn::Left, "Paint"), hint_mouse(MouseBtn::Right, "Orbit"), hint_mouse(MouseBtn::Middle, "Pan"), hint_mouse(MouseBtn::Wheel, "Zoom"), hint_key("F", "Frame")]);
            section(ui, "Toggles, segmented, tabs");
            toggle(ui, &mut st.toggle_a, "Bloom");
            toggle(ui, &mut st.toggle_b, "Show environment");
            segmented(ui, &mut st.seg, &[(0, Some(Icon::Sparkle), "Simple"), (1, Some(Icon::Sliders), "Advanced")]);
            tabs(ui, &mut st.tab, &[(0, "Layer"), (1, "Mask"), (2, "Channels")]);
            section(ui, "Swatches and picker");
            ui.horizontal(|ui| {
                for (k, c) in [p.accent, p.success, p.info, p.danger].into_iter().enumerate() {
                    swatch(ui, c, 24.0, k == 0);
                }
                color_picker(ui, &mut st.color);
            });
            section(ui, "Tool rail and shortcuts");
            ui.horizontal(|ui| {
                tool_button(ui, Icon::Brush, "Paint", "Paint material", "B", true);
                tool_button(ui, Icon::Eraser, "Erase", "Erase", "E", false);
                tool_button(ui, Icon::Bucket, "Fill part", "Click a part to fill it", "G", false);
                tool_button(ui, Icon::Stamp, "Decal", "Stick an image on", "D", false);
                ui.vertical(|ui| {
                    kbd(ui, "Ctrl+K");
                    kbd(ui, "?");
                });
            });
            section(ui, "Card, list rows, drop hints");
            card(ui, |ui| {
                let thumb = |pa: &egui::Painter, r: Rect| paint_material_swatch(pa, r, [0.1, 0.32, 0.35], 0.45, 0.0, 0.0, 1.0, radius::SM);
                let acc = pal(ui).accent;
                let fold = move |pa: &egui::Painter, r: Rect| Icon::Folder.paint(pa, r.shrink(space::XS), acc);
                let rows = [
                    LayerRow { id: egui::Id::NULL.with("g1"), depth: 0, name: "Worn teal paint", subtitle: "Folder · 3 items", visible: true, locked: false, selected: false, shown: true, folder: Some(false), mask: None, opacity: 1.0, thumb: &fold },
                    LayerRow { id: egui::Id::NULL.with("g2"), depth: 1, name: "Edge wear", subtitle: "Fill · edge wear mask", visible: true, locked: false, selected: true, shown: true, folder: None, mask: Some((true, false)), opacity: 1.0, thumb: &thumb },
                    LayerRow { id: egui::Id::NULL.with("g3"), depth: 1, name: "Dirt", subtitle: "Fill · dirt mask", visible: false, locked: true, selected: false, shown: false, folder: None, mask: Some((true, true)), opacity: 0.85, thumb: &thumb },
                ];
                let mut rects = vec![];
                for r in &rows {
                    rects.push(layer_row(ui, r, 0u32).rect);
                }
                paint_drop_hint(ui, rects[2], DropZone::Below);
            });
            section(ui, "Search, property grid");
            search_field(ui, &mut st.search, "Search materials");
            prop_grid(ui, "gallery props", |ui| {
                prop_label(ui, "Roughness", Some("How blurry reflections are"));
                ui.add(DragField::new(&mut st.slider, 0.0..=1.0));
                ui.end_row();
                prop_label(ui, "Base color", None);
                color_picker(ui, &mut st.color);
                ui.end_row();
            });
            section(ui, "Asset tiles, badges");
            ui.horizontal(|ui| {
                for (k, (n, c)) in [("Rusty steel", [0.42, 0.18, 0.08]), ("Car paint", [0.42, 0.04, 0.05]), ("Concrete", [0.55, 0.54, 0.52])].into_iter().enumerate() {
                    asset_tile(ui, size::TILE, None, |pa, r| paint_material_swatch(pa, r, c, 0.5, 0.0, 0.0, 1.0, radius::MD), n, "Smart material", k == 1);
                }
            });
            ui.horizontal(|ui| {
                badge(ui, "NEW", p.accent);
                badge(ui, "4K", p.info);
                badge(ui, "Needs bake", p.warn);
            });
            section(ui, "Progress, empty state");
            progress(ui, Some(0.6), "Exporting 3 of 5 maps");
            progress(ui, None, "Baking AO");
            card(ui, |ui| {
                empty_state(ui, Icon::Stamp, "No decal chosen", "Pick an image below, then click the model to stick it on.", Some("Browse images"));
            });
        });
    });
    let screen = ui.ctx().content_rect();
    st.toasts.show(ui.ctx(), screen);
    let cmds = [
        Command { id: "export".into(), title: "Export textures".into(), group: "File", shortcut: Some("Ctrl+E"), icon: Icon::Export },
        Command { id: "blender".into(), title: "Send to Blender".into(), group: "File", shortcut: None, icon: Icon::Send },
        Command { id: "expand".into(), title: "Expand all folders".into(), group: "Layers", shortcut: None, icon: Icon::Folder },
    ];
    command_palette(ui.ctx(), &mut st.palette, &cmds);
}
