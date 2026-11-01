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
