//! Shape queries over mesh parts: "thin flat parts larger than 1 m²",
//! "small pieces on the roof", "the 10 biggest parts" — so scripts and
//! agents can select parts without paging through every part's JSON.
//!
//! Sizes are the part's axis-aligned bounding box. Its sides sorted
//! ascending are `thickness <= width <= length`; `area` = width x length
//! (the broad face), `facing` = the world axis of the thinnest side.

use crate::mesh::PartInfo;

/// Inclusive bounds; `None` = unbounded.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Range {
    pub min: Option<f32>,
    pub max: Option<f32>,
}

impl Range {
    pub fn contains(&self, x: f32) -> bool {
        self.min.is_none_or(|m| x >= m) && self.max.is_none_or(|m| x <= m)
    }
    pub fn is_any(&self) -> bool {
        self.min.is_none() && self.max.is_none()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SortKey {
    Id,
    Triangles,
    /// Longest side.
    Size,
    Area,
    Thickness,
    Volume,
}

impl SortKey {
    pub const ALL: [(&'static str, SortKey); 6] =
        [("id", SortKey::Id), ("triangles", SortKey::Triangles), ("size", SortKey::Size), ("area", SortKey::Area), ("thickness", SortKey::Thickness), ("volume", SortKey::Volume)];
    pub fn from_id(id: &str) -> Option<SortKey> {
        Self::ALL.iter().find(|(n, _)| *n == id).map(|(_, k)| *k)
    }
}

/// Derived shape measures of one part.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Shape {
    pub center: [f32; 3],
    pub size: [f32; 3],
    pub thickness: f32,
    pub width: f32,
    pub length: f32,
    pub area: f32,
    pub volume: f32,
    /// 0 = x, 1 = y, 2 = z: the axis the broad face looks along.
    pub facing: usize,
}

impl Shape {
    pub fn of(p: &PartInfo) -> Shape {
        let size = [0, 1, 2].map(|k| (p.max[k] - p.min[k]).max(0.0));
        let center = [0, 1, 2].map(|k| (p.max[k] + p.min[k]) * 0.5);
        let mut s = size;
        s.sort_by(f32::total_cmp);
        let facing = if size[0] <= size[1] && size[0] <= size[2] { 0 } else if size[1] <= size[2] { 1 } else { 2 };
        Shape { center, size, thickness: s[0], width: s[1], length: s[2], area: s[1] * s[2], volume: s[0] * s[1] * s[2], facing }
    }
}

pub const AXES: [&str; 3] = ["x", "y", "z"];

/// All conditions must hold (unset ones are ignored).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PartQuery {
    pub triangles: Range,
    pub thickness: Range,
    pub width: Range,
    pub length: Range,
    pub area: Range,
    pub volume: Range,
    /// Thinnest side along this world axis (0 x, 1 y = horizontal slabs, 2 z).
    pub facing: Option<usize>,
    /// Part centre inside this box (min, max corners).
    pub inside: Option<([f32; 3], [f32; 3])>,
    /// Only these ids (e.g. to narrow an earlier selection).
    pub ids: Option<Vec<u32>>,
}

impl PartQuery {
    pub fn matches(&self, id: usize, p: &PartInfo) -> bool {
        let s = Shape::of(p);
        self.triangles.contains(p.triangles as f32)
            && self.thickness.contains(s.thickness)
            && self.width.contains(s.width)
            && self.length.contains(s.length)
            && self.area.contains(s.area)
            && self.volume.contains(s.volume)
            && self.facing.is_none_or(|a| s.facing == a)
            && self.inside.is_none_or(|(lo, hi)| (0..3).all(|k| s.center[k] >= lo[k] && s.center[k] <= hi[k]))
            && self.ids.as_ref().is_none_or(|ids| ids.contains(&(id as u32)))
    }

    /// Ids of matching parts, sorted by `sort` (ties by id).
    pub fn run(&self, parts: &[PartInfo], sort: SortKey, descending: bool) -> Vec<usize> {
        let mut ids: Vec<usize> = parts.iter().enumerate().filter(|(i, p)| self.matches(*i, p)).map(|(i, _)| i).collect();
        let key = |i: usize| -> f32 {
            let p = &parts[i];
            let s = Shape::of(p);
            match sort {
                SortKey::Id => i as f32,
                SortKey::Triangles => p.triangles as f32,
                SortKey::Size => s.length,
                SortKey::Area => s.area,
                SortKey::Thickness => s.thickness,
                SortKey::Volume => s.volume,
            }
        };
        ids.sort_by(|&a, &b| {
            let o = key(a).total_cmp(&key(b));
            (if descending { o.reverse() } else { o }).then(a.cmp(&b))
        });
        ids
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn part(tris: u32, min: [f32; 3], max: [f32; 3]) -> PartInfo {
        PartInfo { triangles: tris, min, max }
    }

    fn kit() -> Vec<PartInfo> {
        vec![
            part(12, [0.0, 0.0, 0.0], [10.0, 12.0, 8.0]),     // 0 shell
            part(2, [1.0, 2.0, -0.01], [2.2, 3.5, 0.0]),      // 1 glass pane facing z, 1.8 m²
            part(2, [3.0, 2.0, -0.01], [3.5, 2.5, 0.0]),      // 2 small pane, 0.25 m²
            part(40, [0.0, 12.0, 0.0], [4.0, 12.05, 3.0]),    // 3 roof slab, facing y
            part(300, [5.0, 12.0, 1.0], [5.3, 12.8, 1.8]),    // 4 AC unit on the roof
        ]
    }

    #[test]
    fn thin_flat_parts_larger_than_an_area() {
        let q = PartQuery { thickness: Range { min: None, max: Some(0.06) }, area: Range { min: Some(1.0), max: None }, ..Default::default() };
        assert_eq!(q.run(&kit(), SortKey::Id, false), vec![1, 3]);
        let q = PartQuery { facing: Some(2), ..q };
        assert_eq!(q.run(&kit(), SortKey::Id, false), vec![1]);
    }

    #[test]
    fn region_triangles_ids_and_sorting() {
        let roof = PartQuery { inside: Some(([-1e9, 11.9, -1e9], [1e9, 1e9, 1e9])), ..Default::default() };
        assert_eq!(roof.run(&kit(), SortKey::Id, false), vec![3, 4]);
        let busy = PartQuery { triangles: Range { min: Some(30.0), max: None }, ..Default::default() };
        assert_eq!(busy.run(&kit(), SortKey::Triangles, true), vec![4, 3]);
        let all = PartQuery::default();
        assert_eq!(all.run(&kit(), SortKey::Area, true), vec![0, 3, 1, 4, 2]);
        assert_eq!(all.run(&kit(), SortKey::Id, true), vec![4, 3, 2, 1, 0]);
        let some = PartQuery { ids: Some(vec![2, 4]), ..Default::default() };
        assert_eq!(some.run(&kit(), SortKey::Size, false), vec![2, 4]);
        let s = Shape::of(&kit()[1]);
        assert_eq!(s.facing, 2);
        assert!((s.area - 1.8).abs() < 1e-4 && (s.thickness - 0.01).abs() < 1e-6);
    }
}
