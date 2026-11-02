//! Pigment core: GPU-free data model and logic.
//!
//! Everything here is plain data + pure functions so it can be unit-tested
//! without a graphics device. The renderer in `pigment` mirrors this state.

pub mod blend;
pub mod bridge;
pub mod brush;
pub mod camera;
pub mod curvature;
pub mod decal;
pub mod decal_layer;
pub mod document;
pub mod envmath;
pub mod export;
pub mod filters;
pub mod folders;
pub mod foliage;
pub mod foliage_set;
pub mod hibake;
pub mod ground;
pub mod image_fill;
pub mod interior;
pub mod mesh;
pub mod partquery;
pub mod project;
pub mod sheet;
pub mod templates;
pub mod texsets;
pub mod smart;
pub mod stage;
pub mod stroke;
pub mod tile;
pub mod tiles;
pub mod undo;
pub mod variants;

pub use camera::OrbitCamera;
pub use document::*;
pub use image_fill::{ImageChannel, ImageFill, Projection};
pub use mesh::{Mesh, Vertex};
