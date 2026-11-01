//! Pigment core: GPU-free data model and logic.
//!
//! Everything here is plain data + pure functions so it can be unit-tested
//! without a graphics device. The renderer in `pigment` mirrors this state.

pub mod blend;
pub mod camera;
pub mod curvature;
pub mod document;
pub mod envmath;
pub mod export;
pub mod folders;
pub mod mesh;
pub mod project;
pub mod smart;
pub mod stroke;
pub mod tiles;
pub mod undo;

pub use camera::OrbitCamera;
pub use document::*;
pub use mesh::{Mesh, Vertex};
