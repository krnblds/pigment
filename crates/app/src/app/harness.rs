//! Offscreen UI harness: runs the real `eframe::App` frame function without a
//! window, feeds it scripted input (pointer, keys, text) and renders the egui
//! output with the app's own wgpu renderer into a texture that can be saved
//! as a PNG. Used by the UI tests and to capture the docs screenshots, so the
//! app never needs an OS window or OS-level input.

use super::*;
use eframe::egui_wgpu::wgpu;
use eframe::App as _;

pub struct Harness {
    pub ctx: egui::Context,
    pub app: PigmentApp,
    pub rs: RenderState,
    frame: eframe::Frame,
    /// Window size in points.
    pub size: egui::Vec2,
    pub ppp: f32,
    events: Vec<egui::Event>,
    time: f64,
    pointer: egui::Pos2,
    last_output: Option<egui::FullOutput>,
    textures: egui::TexturesDelta,
}

impl Drop for Harness {
    fn drop(&mut self) {
        // uploads queued after the last render() have nowhere to go
        self.textures.clear();
    }
}

impl Harness {
    /// A harness with a fresh app. `None` without a GPU adapter.
    pub fn new(size: [f32; 2], ppp: f32) -> Option<Harness> {
        let rs = super::automation::headless_render_state()?;
        let config = std::env::temp_dir().join(format!("pigment-harness-{}-{}", std::process::id(), NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)));
        let _ = std::fs::remove_dir_all(&config);
        let mut app = PigmentApp::create_with(&rs, None, super::prefs::Prefs::in_dir(config));
        app.ui.welcome = false;
        Some(Self::with_app(rs, app, size, ppp))
    }

    pub fn with_app(rs: RenderState, app: PigmentApp, size: [f32; 2], ppp: f32) -> Harness {
        let ctx = egui::Context::default();
        super::design::install(&ctx, &app.ui.prefs);
        let mut frame = eframe::Frame::_new_kittest();
        frame.wgpu_render_state = Some(rs.clone());
        Harness {
            ctx,
            app,
            rs,
            frame,
            size: egui::vec2(size[0], size[1]),
            ppp,
            events: Vec::new(),
            time: 0.0,
            pointer: egui::pos2(-10.0, -10.0),
            last_output: None,
            textures: Default::default(),
        }
    }

    fn raw_input(&mut self) -> egui::RawInput {
        let mut raw = egui::RawInput { screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, self.size)), time: Some(self.time), ..Default::default() };
        raw.viewports.entry(egui::ViewportId::ROOT).or_default().native_pixels_per_point = Some(self.ppp);
        raw.events = std::mem::take(&mut self.events);
        raw.focused = true;
        raw
    }

    /// Run one frame with the queued input.
    pub fn step(&mut self) {
        self.time += 1.0 / 60.0;
        let raw = self.raw_input();
        let (app, frame) = (&mut self.app, &mut self.frame);
        let mut out = self.ctx.run_ui(raw, |ui| app.ui(ui, frame));
        // move (not copy) the delta: epaint asserts that every delta is applied or cleared
        self.textures.append(std::mem::take(&mut out.textures_delta));
        self.last_output = Some(out);
    }

    pub fn run(&mut self, frames: usize) {
        for _ in 0..frames {
            self.step();
        }
    }

    pub fn hover(&mut self, p: egui::Pos2) {
        self.pointer = p;
        self.events.push(egui::Event::PointerMoved(p));
    }

    fn button(&mut self, p: egui::Pos2, button: egui::PointerButton, pressed: bool) {
        self.events.push(egui::Event::PointerButton { pos: p, button, pressed, modifiers: Default::default() });
    }

    /// Move, press and release over a few frames, like a real click.
    pub fn click(&mut self, p: egui::Pos2) {
        self.hover(p);
        self.step();
        self.button(p, egui::PointerButton::Primary, true);
        self.step();
        self.button(p, egui::PointerButton::Primary, false);
        self.step();
        self.step();
    }

    /// Press / release the primary button without moving (for long drags).
    pub fn events_push_press(&mut self, p: egui::Pos2) {
        self.button(p, egui::PointerButton::Primary, true);
    }

    pub fn events_push_release(&mut self, p: egui::Pos2) {
        self.button(p, egui::PointerButton::Primary, false);
    }

    pub fn right_click(&mut self, p: egui::Pos2) {
        self.hover(p);
        self.step();
        self.button(p, egui::PointerButton::Secondary, true);
        self.step();
        self.button(p, egui::PointerButton::Secondary, false);
        self.step();
    }

    /// Click the centre of a UI anchor the app registered this frame.
    pub fn click_anchor(&mut self, name: &str) -> bool {
        match self.app.anchors.get(name).copied() {
            Some(r) => {
                self.click(r.center());
                true
            }
            None => false,
        }
    }

    /// Press at `from`, move in `steps` to `to`, release.
    pub fn drag(&mut self, from: egui::Pos2, to: egui::Pos2, steps: usize) {
        self.hover(from);
        self.step();
        self.button(from, egui::PointerButton::Primary, true);
        self.step();
        for i in 1..=steps.max(1) {
            let p = from + (to - from) * (i as f32 / steps.max(1) as f32);
            self.hover(p);
            self.step();
        }
        self.button(to, egui::PointerButton::Primary, false);
        self.step();
        self.step();
    }

    pub fn key(&mut self, key: egui::Key, modifiers: egui::Modifiers) {
        self.events.push(egui::Event::ModifiersChanged(modifiers));
        self.events.push(egui::Event::Key { key, physical_key: None, pressed: true, repeat: false, modifiers });
        self.step();
        self.events.push(egui::Event::Key { key, physical_key: None, pressed: false, repeat: false, modifiers });
        self.events.push(egui::Event::ModifiersChanged(Default::default()));
        self.step();
    }

    pub fn type_text(&mut self, text: &str) {
        self.events.push(egui::Event::Text(text.to_string()));
        self.step();
    }

    /// Run a frame and render it to RGBA8 pixels (physical size).
    pub fn render(&mut self) -> image::RgbaImage {
        self.step();
        let out = self.last_output.take().expect("a frame ran");
        let w = (self.size.x * self.ppp).round() as u32;
        let h = (self.size.y * self.ppp).round() as u32;
        let (d, q) = (&self.rs.device, &self.rs.queue);
        let format = self.rs.target_format;
        let tex = d.create_texture(&wgpu::TextureDescriptor {
            label: Some("harness"),
            size: wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let view = tex.create_view(&Default::default());
        let jobs = self.ctx.tessellate(out.shapes, out.pixels_per_point);
        let screen = eframe::egui_wgpu::ScreenDescriptor { size_in_pixels: [w, h], pixels_per_point: out.pixels_per_point };
        let textures = std::mem::take(&mut self.textures);
        {
            let mut r = self.rs.renderer.write();
            for (id, deltas) in &textures.set {
                for delta in deltas {
                    r.update_texture(d, q, *id, delta);
                }
            }
            let mut enc = d.create_command_encoder(&Default::default());
            let cmds = r.update_buffers(d, q, &mut enc, &jobs, &screen);
            {
                let pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("harness egui"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &view,
                        resolve_target: None,
                        depth_slice: None,
                        ops: wgpu::Operations { load: wgpu::LoadOp::Clear(wgpu::Color::BLACK), store: wgpu::StoreOp::Store },
                    })],
                    ..Default::default()
                });
                let mut pass = pass.forget_lifetime();
                r.render(&mut pass, &jobs, &screen);
            }
            q.submit(cmds.into_iter().chain([enc.finish()]));
            for id in &textures.free {
                r.free_texture(id);
            }
        }
        let t = crate::render::gpu::Tex { tex, view, size: w, height: h, format, mips: 1 };
        let px = crate::render::gpu::readback(d, q, &t);
        let mut img = image::RgbaImage::from_raw(w, h, px).expect("readback size");
        for p in img.pixels_mut() {
            p[3] = 255;
        }
        img
    }

    pub fn save_png(&mut self, path: &Path) -> image::RgbaImage {
        let img = self.render();
        if let Some(d) = path.parent() {
            let _ = std::fs::create_dir_all(d);
        }
        img.save(path).expect("write screenshot");
        img
    }
}

static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
