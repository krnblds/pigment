//! Filters and anchors (pigment_core::filters) on the GPU: one flat quad
//! (UV 0.1..0.9), a black base and a white layer masked by a sharp ground
//! gradient, so the mask is visible in the colour map.

use super::*;
use pigment_core::filters::{AnchorChannel, Filter, FilterKind, GenInput};

const R: u32 = 256;

struct Quad {
    g: Gpu,
    ts: TexSet,
}

impl Quad {
    fn new() -> Option<Quad> {
        let g = gpu()?;
        let mesh = Mesh::tile_grid(1);
        let mg = MeshGpu::new(&g.device, &mesh);
        let mut ts = TexSet::new(&g.device, &g.queue, R);
        let (c, r) = mesh.bounding_sphere();
        ts.prepare_mesh(&g.device, &g.queue, &mg, c, r);
        Some(Quad { g, ts })
    }
    fn run(&mut self, doc: &Document, rect: Option<[u32; 4]>) -> pigment_core::export::MaterialImages {
        let (d, q) = (&self.g.device, &self.g.queue);
        self.ts.ensure_resources(d, q, doc);
        self.ts.composite(d, q, doc, rect);
        io::read_material(d, q, &self.ts)
    }
}

/// Black base + white fill shown on the lower half (a hard gradient mask).
fn half_doc() -> Document {
    let mut doc = Document::default();
    let mut base = doc.new_fill_layer("base");
    if let LayerKind::Fill { values } = &mut base.kind {
        values.base_color = [0.0; 3];
    }
    doc.layers.push(base);
    let mut white = doc.new_fill_layer("white");
    if let LayerKind::Fill { values } = &mut white.kind {
        values.base_color = [1.0; 3];
    }
    let mut g = Generator::new(GeneratorKind::Gradient);
    g.amount = 0.5;
    g.softness = 0.0;
    g.noise_amount = 0.0;
    white.mask = Some(Mask::with_generator(doc.mint(), g));
    doc.layers.push(white);
    doc
}

/// Red channel down the middle column, inside the island (rows 30..226).
fn column(m: &pigment_core::export::MaterialImages) -> Vec<u8> {
    (30..226).map(|y| m.color[((y * R + R / 2) * 4) as usize]).collect()
}
fn grey_count(c: &[u8]) -> usize {
    c.iter().filter(|v| **v > 20 && **v < 235).count()
}
fn white_count(c: &[u8]) -> usize {
    c.iter().filter(|v| **v >= 128).count()
}

#[test]
fn mask_filters_blur_grow_and_shrink_the_mask() {
    let Some(mut q) = Quad::new() else { return };
    let doc = half_doc();
    let plain = column(&q.run(&doc, None));
    assert!(grey_count(&plain) <= 3, "the gradient mask should be hard: {plain:?}");
    let w0 = white_count(&plain);
    assert!(w0 > 80 && w0 < 120, "half white: {w0}");

    let with = |k: FilterKind, radius: f32| {
        let mut d = doc.clone();
        let mut f = Filter::new(k);
        f.params.radius = radius * 2048.0 / R as f32; // radius in texels at this resolution
        d.layers[1].mask.as_mut().unwrap().filters.push(f);
        d
    };
    let blurred = column(&q.run(&with(FilterKind::Blur, 8.0), None));
    assert!(grey_count(&blurred) >= 8, "blur softens the edge: {blurred:?}");
    let grown = white_count(&column(&q.run(&with(FilterKind::Grow, 6.0), None)));
    let shrunk = white_count(&column(&q.run(&with(FilterKind::Shrink, 6.0), None)));
    assert!(grown >= w0 + 5, "grow: {grown} vs {w0}");
    assert!(shrunk + 5 <= w0, "shrink: {shrunk} vs {w0}");
    // a disabled filter changes nothing
    let mut off = with(FilterKind::Blur, 8.0);
    off.layers[1].mask.as_mut().unwrap().filters[0].enabled = false;
    assert_eq!(column(&q.run(&off, None)), plain);
}

#[test]
fn filter_layers_adjust_the_stack_below_inside_their_mask() {
    let Some(mut q) = Quad::new() else { return };
    let mut doc = half_doc();
    // invert everything below
    let inv = doc.new_filter_layer("invert", vec![Filter::new(FilterKind::Invert)]);
    doc.layers.push(inv);
    let c = column(&q.run(&doc, None));
    assert!(c[5] > 230 && c[190] < 25, "inverted: top {} bottom {}", c[5], c[190]);
    // half opacity: mid grey everywhere
    doc.layers[2].opacity = 0.5;
    let c = column(&q.run(&doc, None));
    assert!(c.iter().all(|v| (150..215).contains(v)), "half-inverted is mid grey (sRGB ~188): {c:?}");
    // a mask limits the filter: with an inverted gradient, only the top half
    doc.layers[2].opacity = 1.0;
    let mut g = Generator::new(GeneratorKind::Gradient);
    (g.amount, g.softness, g.noise_amount) = (0.5, 0.0, 0.0);
    let mut m = Mask::with_generator(doc.mint(), g);
    m.invert = true;
    doc.layers[2].mask = Some(m);
    let c = column(&q.run(&doc, None));
    assert!(c[5] > 230 && c[190] > 230, "top inverted to white, bottom stays white: {} {}", c[5], c[190]);
    // levels: output white at 0.5 halves the colour
    let mut lv = Filter::new(FilterKind::Levels);
    lv.params.levels.out_white[3] = 0.5;
    doc.layers[2].mask = None;
    doc.layers[2].filters = vec![lv];
    let c = column(&q.run(&doc, None));
    assert!((120..136).contains(&c[190]), "levels out-white 0.5: {}", c[190]);
}

#[test]
fn anchors_feed_generators_above() {
    let Some(mut q) = Quad::new() else { return };
    let mut doc = half_doc();
    // the white layer raises the lower half and is the anchor
    doc.layers[1].anchor = Some("Raised".into());
    doc.layers[1].channels.height.enabled = true;
    if let LayerKind::Fill { values } = &mut doc.layers[1].kind {
        values.height = 0.6;
        values.base_color = [0.0; 3]; // keep the colour black: only the layer above shows
    }
    // a red layer masked by the anchor's mask directly
    let mut red = doc.new_fill_layer("red");
    if let LayerKind::Fill { values } = &mut red.kind {
        values.base_color = [1.0, 0.0, 0.0];
    }
    let mut g = Generator::new(GeneratorKind::Anchor);
    (g.amount, g.softness) = (0.5, 0.01);
    g.input = Some(GenInput::new("Raised", AnchorChannel::Mask));
    red.mask = Some(Mask::with_generator(doc.mint(), g));
    doc.layers.push(red);
    let c = column(&q.run(&doc, None));
    let w = white_count(&c);
    assert!(w > 80 && w < 120 && c[190] > 230 && c[5] < 25, "red where the anchor mask is: {w}");

    // edge wear reading the anchor's height finds the rim of the raised area
    let mut wear = Generator::new(GeneratorKind::EdgeWear);
    (wear.amount, wear.softness, wear.noise_amount, wear.ao_influence) = (0.3, 0.02, 0.0, 0.0);
    doc.layers[2].mask.as_mut().unwrap().generator = Some(wear.clone());
    let none = white_count(&column(&q.run(&doc, None)));
    assert!(none == 0, "no curvature on a flat quad without the anchor: {none}");
    wear.input = Some(GenInput::new("Raised", AnchorChannel::Height));
    doc.layers[2].mask.as_mut().unwrap().generator = Some(wear);
    let c = column(&q.run(&doc, None));
    let hits: Vec<usize> = c.iter().enumerate().filter(|(_, v)| **v >= 128).map(|(i, _)| i).collect();
    assert!(!hits.is_empty() && hits.len() < 30, "wear along the rim only: {hits:?}");
    let edge = (0..c.len()).find(|&i| i > 0 && c[i].abs_diff(c[i - 1]) > 0).unwrap_or(0);
    assert!(hits.iter().all(|h| (*h as i32 - edge as i32).abs() < 20), "rim near row {edge}: {hits:?}");
}

/// Painting under a blur filter layer: the partial composites must end up
/// identical to a full composite (the regions widen by the filter's reach).
#[test]
fn partial_composites_match_full_ones_under_spatial_filters() {
    let Some(mut s) = Scene::new() else { return };
    let mut f = Filter::new(FilterKind::Blur);
    f.params.radius = 24.0;
    let fl = s.doc.new_filter_layer("blur", vec![f]);
    s.doc.layers.push(fl);
    let mut sh = Filter::new(FilterKind::Sharpen);
    sh.params.radius = 8.0;
    let fl = s.doc.new_filter_layer("sharpen", vec![sh]);
    s.doc.layers.push(fl);
    let (d, q) = (&s.g.device, &s.g.queue);
    s.ts.composite(d, q, &s.doc, None);
    let _ = s.stroke(Vec2::new(250.0, 450.0), Vec2::new(550.0, 420.0));
    let (d, q) = (&s.g.device, &s.g.queue);
    let partial = io::read_material(d, q, &s.ts);
    s.ts.composite(d, q, &s.doc, None);
    let full = io::read_material(d, q, &s.ts);
    let diff = partial.color.iter().zip(&full.color).map(|(a, b)| a.abs_diff(*b)).max().unwrap();
    assert!(diff <= 2, "partial vs full composite differ by {diff}");
    let red = full.color.chunks_exact(4).filter(|p| p[0] > 120 && p[1] < 110).count();
    assert!(red > 50, "the stroke shows through the filters: {red}");
}
