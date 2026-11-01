//! MCP: brush engine arguments of `paint_stroke` (tip, pressure, jitter,
//! flow, angle, spacing, lazy mouse, pressure curves, symmetry, stencil,
//! tool: paint | clone | smudge) and `list_library` brush tips.

use super::*;
use pigment_core::brush::{BrushDynamics, Jitter, PressureCurve, Symmetry};

fn curve(a: &Value, k: &str, default: PressureCurve) -> Res<PressureCurve> {
    match a.get(k) {
        None => Ok(default),
        Some(Value::Bool(b)) => Ok(PressureCurve { enabled: *b, ..default }),
        Some(v) if v.is_object() => Ok(PressureCurve {
            enabled: v.get("enabled").and_then(Value::as_bool).unwrap_or(true),
            min: f(v, "min").unwrap_or(default.min).clamp(0.0, 1.0),
            gamma: f(v, "gamma").unwrap_or(default.gamma).clamp(0.05, 20.0),
        }),
        Some(v) => Err(format!("`{k}` must be true / false or {{min, gamma}}, got {v}")),
    }
}

/// Apply the brush engine arguments of a `paint_stroke` call (everything not
/// given goes back to its default). Returns the pressure for each point.
pub(super) fn configure_brush(app: &mut PigmentApp, rs: &RenderState, a: &Value, npts: usize, viewport_px: Vec2) -> Res<Vec<f32>> {
    let b = &mut app.brush;
    let mut d = BrushDynamics::default();
    if let Some(x) = f(a, "flow") {
        d.flow = x.clamp(0.01, 1.0);
    }
    if let Some(x) = f(a, "angle") {
        d.angle = x;
    }
    d.follow_angle = a.get("follow_angle").and_then(Value::as_bool).unwrap_or(false);
    if let Some(x) = f(a, "lazy") {
        d.lazy = x.max(0.0);
    }
    if let Some(x) = a.get("seed").and_then(Value::as_u64) {
        d.seed = x as u32;
    }
    if let Some(j) = a.get("jitter") {
        let n = |k: &str| f(j, k).unwrap_or(0.0).max(0.0);
        d.jitter = Jitter { size: n("size").min(1.0), angle: n("angle"), position: n("position"), flow: n("flow").min(1.0) };
    }
    d.pressure_size = curve(a, "pressure_size", PressureCurve::on())?;
    d.pressure_flow = curve(a, "pressure_flow", PressureCurve::off())?;
    d.pressure_opacity = curve(a, "pressure_opacity", PressureCurve::off())?;
    b.dynamics = d;
    // tip
    b.tip = match a.get("tip") {
        None | Some(Value::Null) => None,
        Some(Value::String(t)) if t == "round" && !b.tips.iter().any(|(id, _)| id == "round") => None,
        Some(Value::String(t)) => {
            if !b.tips.iter().any(|(id, _)| id == t) {
                return Err(format!("`tip` = \"{t}\": unknown brush tip (tips: {})", b.tips.iter().map(|(id, _)| id.as_str()).collect::<Vec<_>>().join(", ")));
            }
            Some(t.clone())
        }
        Some(v) => return Err(format!("`tip` must be a tip id (see list_library brush_tips), got {v}")),
    };
    // tool
    b.tool = match s(a, "tool").unwrap_or("paint") {
        "paint" => BrushTool::Paint,
        "clone" => BrushTool::Clone,
        "smudge" => BrushTool::Smudge,
        t => return Err(format!("`tool` = \"{t}\": one of paint, clone, smudge")),
    };
    if b.tool != BrushTool::Clone {
        b.clone_source = None;
        b.clone_offset = None;
    }
    b.smudge = f(a, "smudge").unwrap_or(0.5).clamp(0.01, 8.0);
    // symmetry
    b.symmetry = match a.get("symmetry") {
        None | Some(Value::Null) => Symmetry::default(),
        Some(v) => {
            let on = |k: &str| v.get(k).and_then(Value::as_bool).unwrap_or(false);
            let axis = match v.get("axis") {
                None => 1,
                Some(Value::String(s)) => match s.as_str() {
                    "x" => 0,
                    "y" => 1,
                    "z" => 2,
                    _ => return Err(format!("`symmetry.axis` = \"{s}\": x, y or z")),
                },
                Some(x) => x.as_u64().unwrap_or(1).min(2) as u32,
            };
            let center = match v.get("center").and_then(Value::as_array) {
                Some(c) if c.len() == 3 => Some([0, 1, 2].map(|k| c[k].as_f64().unwrap_or(0.0) as f32)),
                Some(_) => return Err("`symmetry.center` must be [x, y, z]".into()),
                None => None,
            };
            Symmetry { x: on("x"), y: on("y"), z: on("z"), radial: v.get("radial").and_then(Value::as_u64).unwrap_or(0) as u32, axis, center }
        }
    };
    // stencil
    let stencil = match a.get("stencil") {
        None | Some(Value::Null) => None,
        Some(v) => {
            let path = PathBuf::from(s(v, "image").ok_or("`stencil` needs `image` (a PNG / JPG path)")?);
            let size = image::image_dimensions(&path).map_err(|e| format!("`stencil.image` {}: {e}", path.display()))?;
            let c = v.get("center").and_then(Value::as_array).map(|c| Vec2::new(c.first().and_then(Value::as_f64).unwrap_or(0.5) as f32, c.get(1).and_then(Value::as_f64).unwrap_or(0.5) as f32)).unwrap_or(Vec2::splat(0.5));
            Some(StencilState {
                path,
                center: c,
                rotation: f(v, "rotation").unwrap_or(0.0),
                scale: f(v, "scale").unwrap_or(1.0).max(0.01),
                opacity: f(v, "opacity").unwrap_or(1.0).clamp(0.0, 1.0),
                invert: v.get("invert").and_then(Value::as_bool).unwrap_or(false),
                size: [size.0, size.1],
            })
        }
    };
    app.set_stencil(rs, stencil)?;
    let _ = viewport_px;
    // pressure per point (a number = every point)
    let pressures = match a.get("pressure") {
        None => vec![1.0; npts],
        Some(Value::Number(n)) => vec![(n.as_f64().unwrap_or(1.0) as f32).clamp(0.0, 1.0); npts],
        Some(Value::Array(v)) => {
            if v.len() != npts {
                return Err(format!("`pressure` has {} values for {npts} points (give one per point, or a single number)", v.len()));
            }
            v.iter().map(|x| (x.as_f64().unwrap_or(1.0) as f32).clamp(0.0, 1.0)).collect()
        }
        Some(v) => return Err(format!("`pressure` must be a number or an array (one per point), got {v}")),
    };
    Ok(pressures)
}

impl Session {
    /// Brush tips for list_library.
    pub(super) fn brush_tips(&self) -> Value {
        Value::Array(self.app.brush.tips.iter().map(|(id, label)| json!({ "id": id, "label": label })).collect())
    }
}

#[cfg(test)]
mod tests {
    use super::super::gpu_lock;
    use super::*;

    const TOP: [(&str, f64); 3] = [("yaw", 0.0), ("pitch", 0.0), ("zoom", 1.0)];

    /// A flat quad facing the front camera (UV 0.1..0.9).
    fn session() -> Option<Session> {
        let mut s = Session::new().ok()?;
        let dir = std::env::temp_dir().join(format!("pigment-brush-{}", std::process::id()));
        std::fs::create_dir_all(&dir).ok()?;
        let obj = dir.join("quad.obj");
        pigment_core::Mesh::tile_grid(1).write_obj(&obj).ok()?;
        s.new_project(&json!({ "mesh": obj, "resolution": 512, "material": "Concrete" })).unwrap();
        Some(s)
    }
    fn stroke(s: &mut Session, extra: Value) -> Res<Value> {
        let mut a = json!({ "points": [[0.3, 0.5], [0.45, 0.5]], "size": 30, "values": { "base_color": [0.0, 0.0, 1.0] }, "width": 512, "height": 512 });
        for (k, v) in TOP {
            a[k] = json!(v);
        }
        for (k, v) in extra.as_object().unwrap() {
            a[k] = v.clone();
        }
        s.paint_stroke(&a)
    }
    fn material(s: &mut Session) -> pigment_core::export::MaterialImages {
        s.app.commit_doc_changes();
        s.app.ensure_composited(&s.rs);
        crate::render::io::read_material(&s.rs.device, &s.rs.queue, &s.app.ts)
    }
    /// Blue texels in the u range [u0, u1).
    fn blue(m: &pigment_core::export::MaterialImages, u0: f32, u1: f32) -> usize {
        let n = m.size as usize;
        (0..n * n).filter(|i| {
            let u = (i % n) as f32 / n as f32;
            let p = &m.color[i * 4..];
            u >= u0 && u < u1 && p[2] as i32 > p[0] as i32 + 40
        }).count()
    }
    fn total(m: &pigment_core::export::MaterialImages) -> usize {
        blue(m, 0.0, 1.0)
    }
    fn reset(s: &mut Session) {
        s.undo(false).unwrap();
    }

    #[test]
    fn pressure_tips_flow_and_jitter() {
        let _g = gpu_lock();
        let Some(mut s) = session() else { return };
        stroke(&mut s, json!({})).unwrap();
        let full = total(&material(&mut s));
        assert!(full > 500, "plain stroke paints ({full})");
        reset(&mut s);
        stroke(&mut s, json!({ "pressure": [0.2, 0.2] })).unwrap();
        let light = total(&material(&mut s));
        assert!(light * 3 < full, "light pressure = thin stroke ({light} vs {full})");
        reset(&mut s);
        // pressure ramp: thin at the start, full at the end
        stroke(&mut s, json!({ "pressure": [0.1, 1.0] })).unwrap();
        let ramp = total(&material(&mut s));
        assert!(ramp > light && ramp < full, "ramp in between ({ramp})");
        reset(&mut s);
        // a square tip covers more than the round falloff
        stroke(&mut s, json!({ "points": [[0.4, 0.5]], "tip": "square", "hardness": 1.0 })).unwrap();
        let square = total(&material(&mut s));
        reset(&mut s);
        stroke(&mut s, json!({ "points": [[0.4, 0.5]], "hardness": 1.0 })).unwrap();
        let round = total(&material(&mut s));
        reset(&mut s);
        assert!(square as f32 > round as f32 * 1.1, "square tip {square} vs round {round}");
        stroke(&mut s, json!({ "points": [[0.4, 0.5]], "tip": "cracks" })).unwrap();
        let cracks = total(&material(&mut s));
        reset(&mut s);
        assert!(cracks * 3 < round && cracks > 20, "a cracks tip paints thin lines ({cracks} vs {round})");
        assert!(stroke(&mut s, json!({ "tip": "nope" })).unwrap_err().contains("unknown brush tip"));
        // low flow builds up less than full flow along one pass
        let peak = |m: &pigment_core::export::MaterialImages| m.color.chunks_exact(4).map(|p| p[2] as i32 - p[0] as i32).max().unwrap_or(0);
        stroke(&mut s, json!({ "flow": 0.05, "spacing": 0.5 })).unwrap();
        let weak = peak(&material(&mut s));
        reset(&mut s);
        stroke(&mut s, json!({})).unwrap();
        let strong = peak(&material(&mut s));
        reset(&mut s);
        assert!(weak + 40 < strong, "flow 0.05 is fainter ({weak} vs {strong})");
        // position jitter scatters dabs: more ground covered than the plain stroke's band
        stroke(&mut s, json!({ "jitter": { "position": 1.5, "size": 0.5 }, "spacing": 0.3 })).unwrap();
        let m = material(&mut s);
        let n = m.size as usize;
        let rows = (0..n).filter(|y| (0..n).any(|x| { let p = &m.color[(y * n + x) * 4..]; p[2] as i32 > p[0] as i32 + 40 })).count();
        reset(&mut s);
        stroke(&mut s, json!({})).unwrap();
        let m = material(&mut s);
        let rows0 = (0..n).filter(|y| (0..n).any(|x| { let p = &m.color[(y * n + x) * 4..]; p[2] as i32 > p[0] as i32 + 40 })).count();
        assert!(rows > rows0 + 10, "jittered stroke spans more rows ({rows} vs {rows0})");
    }

    #[test]
    fn symmetry_stencil_clone_and_smudge() {
        let _g = gpu_lock();
        let Some(mut s) = session() else { return };
        assert!(stroke(&mut s, json!({ "tool": "clone" })).unwrap_err().contains("clone_source"));
        // symmetry x: the left-half stroke also lands on the right half
        stroke(&mut s, json!({ "points": [[0.2, 0.5], [0.3, 0.5]] })).unwrap();
        let m = material(&mut s);
        let (l, r) = (blue(&m, 0.0, 0.5), blue(&m, 0.5, 1.0));
        assert!(r * 4 < l || l * 4 < r, "mostly one side without symmetry ({l}, {r})");
        reset(&mut s);
        stroke(&mut s, json!({ "points": [[0.2, 0.5], [0.3, 0.5]], "symmetry": { "x": true } })).unwrap();
        let m = material(&mut s);
        let (l2, r2) = (blue(&m, 0.0, 0.5), blue(&m, 0.5, 1.0));
        assert!(l2.min(r2) * 2 > l2.max(r2), "mirrored to the other side ({l2}, {r2})");
        reset(&mut s);
        // stencil: left half of the view black, right half white -> paint only on one side
        let dir = std::env::temp_dir().join(format!("pigment-stencil-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let img = image::RgbaImage::from_fn(64, 64, |x, _| if x < 32 { image::Rgba([0, 0, 0, 255]) } else { image::Rgba([255, 255, 255, 255]) });
        let path = dir.join("half.png");
        img.save(&path).unwrap();
        stroke(&mut s, json!({ "points": [[0.1, 0.5], [0.9, 0.5]], "stencil": { "image": path, "scale": 1.0 } })).unwrap();
        // check on screen (same camera): the view spans more than one tile period
        let shot = s.render(&json!({ "yaw": 0.0, "pitch": 0.0, "zoom": 1.0, "width": 512, "height": 512, "view": "base color" })).unwrap();
        let img = image::load_from_memory(&shot.png).unwrap().to_rgb8();
        let side = |x0: u32, x1: u32| img.enumerate_pixels().filter(|(x, _, p)| *x >= x0 && *x < x1 && p.0[2] as i32 > p.0[0] as i32 + 40).count();
        let (l3, r3) = (side(40, 236), side(276, 472));
        assert!(r3 > 1000 && l3 * 20 < r3, "the stencil lets paint through its white half only ({l3}, {r3})");
        reset(&mut s);
        std::fs::remove_dir_all(dir).ok();
        // clone: a blue dot at A, copied to B
        stroke(&mut s, json!({ "points": [[0.25, 0.3]] })).unwrap();
        let a = total(&material(&mut s));
        stroke(&mut s, json!({ "points": [[0.7, 0.7]], "tool": "clone", "clone_source": [0.25, 0.3], "channels": ["base_color"] })).unwrap();
        let b = total(&material(&mut s));
        assert!(b as f32 > a as f32 * 1.6, "the clone copies the dot ({a} -> {b})");
        reset(&mut s);
        reset(&mut s);
        // smudge: dragging right across a blue line carries blue into the band right of it
        let band = |m: &pigment_core::export::MaterialImages| -> i64 {
            let n = m.size as usize;
            (0..n * n)
                .filter(|i| {
                    let (u, v) = ((i % n) as f32 / n as f32, (i / n) as f32 / n as f32);
                    (0.53..0.6).contains(&u) && (0.45..0.55).contains(&v)
                })
                .map(|i| (m.color[i * 4 + 2] as i64 - m.color[i * 4] as i64).max(0))
                .sum()
        };
        stroke(&mut s, json!({ "points": [[0.5, 0.2], [0.5, 0.8]], "size": 12 })).unwrap();
        let before = band(&material(&mut s));
        stroke(&mut s, json!({ "points": [[0.47, 0.5], [0.65, 0.5]], "size": 50, "tool": "smudge", "smudge": 0.6, "channels": ["base_color"] })).unwrap();
        let after = band(&material(&mut s));
        assert!(after > before + 2000, "smudge drags blue along ({before} -> {after})");
    }
}
