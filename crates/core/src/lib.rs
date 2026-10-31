//! Pigment core: GPU-free data model and logic.
//!
//! Everything here is plain data + pure functions so it can be unit-tested
//! without a graphics device. The renderer in `pigment` mirrors this state.

pub mod camera;
pub mod mesh;

pub use camera::OrbitCamera;
pub use mesh::{Mesh, Vertex};
