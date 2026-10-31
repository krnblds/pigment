//! Contact sheets: lay equally sized RGBA renders out in a grid, each with a
//! small text label (e.g. `FRONT`, `YAW 90`), so one image shows an asset from
//! every side. Labels use a built-in 3x5 pixel font (A-Z, 0-9, `-+.`).

/// One rendered view: tightly packed RGBA8, `w * h * 4` bytes.
pub struct Tile {
    pub rgba: Vec<u8>,
    pub w: u32,
    pub h: u32,
    pub label: String,
}

const GAP: u32 = 4;
const BG: [u8; 4] = [18, 18, 22, 255];

/// Grid of `tiles` (all the same size as the first) with `cols` columns.
/// Returns (rgba, width, height).
pub fn contact_sheet(tiles: &[Tile], cols: usize) -> (Vec<u8>, u32, u32) {
    let Some(first) = tiles.first() else { return (vec![], 0, 0) };
    let (tw, th) = (first.w, first.h);
    let cols = cols.clamp(1, tiles.len()) as u32;
    let rows = (tiles.len() as u32).div_ceil(cols);
    let (w, h) = (cols * tw + (cols + 1) * GAP, rows * th + (rows + 1) * GAP);
    let mut out: Vec<u8> = BG.iter().copied().cycle().take((w * h * 4) as usize).collect();
    for (i, t) in tiles.iter().enumerate() {
        let (cx, cy) = (i as u32 % cols, i as u32 / cols);
        let (ox, oy) = (GAP + cx * (tw + GAP), GAP + cy * (th + GAP));
        for y in 0..th.min(t.h) {
            let src = &t.rgba[(y * t.w * 4) as usize..((y * t.w + tw.min(t.w)) * 4) as usize];
            let d = (((oy + y) * w + ox) * 4) as usize;
            out[d..d + src.len()].copy_from_slice(src);
        }
        if !t.label.is_empty() {
            let scale = (th / 128).clamp(1, 4);
            let (lw, lh) = (text_width(&t.label) * scale, 5 * scale);
            // dark band behind the label, bottom-left of the tile
            let pad = 2 * scale;
            let (bx, by) = (ox, oy + th.saturating_sub(lh + 2 * pad));
            for y in by..(by + lh + 2 * pad).min(oy + th) {
                for x in bx..(bx + lw + 2 * pad).min(ox + tw) {
                    let p = ((y * w + x) * 4) as usize;
                    for c in 0..3 {
                        out[p + c] = (out[p + c] as u32 * 2 / 7) as u8;
                    }
                }
            }
            draw_text(&mut out, w, (bx + pad, by + pad), scale, &t.label, [235, 235, 240, 255], (ox + tw, oy + th));
        }
    }
    (out, w, h)
}

fn glyph(c: char) -> &'static str {
    match c.to_ascii_uppercase() {
        'A' => "010101111101101",
        'B' => "110101110101110",
        'C' => "011100100100011",
        'D' => "110101101101110",
        'E' => "111100110100111",
        'F' => "111100110100100",
        'G' => "011100101101011",
        'H' => "101101111101101",
        'I' => "111010010010111",
        'J' => "001001001101010",
        'K' => "101101110101101",
        'L' => "100100100100111",
        'M' => "101111111101101",
        'N' => "110101101101101",
        'O' => "010101101101010",
        'P' => "110101110100100",
        'Q' => "010101101110011",
        'R' => "110101110101101",
        'S' => "011100010001110",
        'T' => "111010010010010",
        'U' => "101101101101111",
        'V' => "101101101101010",
        'W' => "101101111111101",
        'X' => "101101010101101",
        'Y' => "101101010010010",
        'Z' => "111001010100111",
        '0' => "111101101101111",
        '1' => "010110010010111",
        '2' => "110001010100111",
        '3' => "110001010001110",
        '4' => "101101111001001",
        '5' => "111100110001110",
        '6' => "011100110101010",
        '7' => "111001010010010",
        '8' => "010101010101010",
        '9' => "010101011001110",
        '-' => "000000111000000",
        '+' => "000010111010000",
        '.' => "000000000000010",
        _ => "000000000000000",
    }
}

/// Width in font pixels (3 per glyph + 1 spacing).
pub fn text_width(s: &str) -> u32 {
    (s.chars().count() as u32 * 4).saturating_sub(1)
}

fn draw_text(out: &mut [u8], w: u32, at: (u32, u32), scale: u32, s: &str, color: [u8; 4], clip: (u32, u32)) {
    for (i, c) in s.chars().enumerate() {
        for (bit, on) in glyph(c).bytes().enumerate() {
            if on != b'1' {
                continue;
            }
            let (gx, gy) = (bit as u32 % 3, bit as u32 / 3);
            for sy in 0..scale {
                for sx in 0..scale {
                    let (x, y) = (at.0 + (i as u32 * 4 + gx) * scale + sx, at.1 + gy * scale + sy);
                    if x < clip.0 && y < clip.1 {
                        let p = ((y * w + x) * 4) as usize;
                        out[p..p + 4].copy_from_slice(&color);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn solid(c: u8, label: &str) -> Tile {
        Tile { rgba: [c, c, c, 255].repeat(64 * 48), w: 64, h: 48, label: label.into() }
    }

    #[test]
    fn grid_layout_places_tiles() {
        let tiles: Vec<Tile> = (0..5).map(|i| solid(40 * i as u8 + 40, "")).collect();
        let (img, w, h) = contact_sheet(&tiles, 3);
        assert_eq!((w, h), (3 * 64 + 4 * GAP, 2 * 48 + 3 * GAP));
        let px = |x: u32, y: u32| img[((y * w + x) * 4) as usize];
        assert_eq!(px(GAP + 10, GAP + 10), 40);
        assert_eq!(px(GAP * 2 + 64 + 10, GAP + 10), 80);
        assert_eq!(px(GAP + 10, GAP * 2 + 48 + 10), 160);
        // the empty sixth cell stays background
        assert_eq!(px(w - GAP - 10, h - GAP - 10), BG[0]);
    }

    #[test]
    fn labels_are_drawn() {
        let (img, w, _) = contact_sheet(&[solid(128, "FRONT 90")], 1);
        let bright = img.chunks_exact(4).filter(|p| p[0] == 235).count();
        assert!(bright > 30, "{bright} label pixels");
        assert_eq!(text_width("AB"), 7);
        // the label sits at the bottom: the top row of the tile is untouched
        let row = &img[((GAP * w + GAP) * 4) as usize..((GAP * w + GAP + 64) * 4) as usize];
        assert!(row.chunks_exact(4).all(|p| p[0] == 128));
    }
}
