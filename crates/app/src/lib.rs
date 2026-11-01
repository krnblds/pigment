//! Pigment engine: the app, renderer and headless automation, shared by the
//! `pigment` desktop app and the `pigment-mcp` server.

pub mod app;
pub mod mcp_args;
pub mod render;

#[cfg(test)]
mod gpu_tests;
#[cfg(test)]
mod shader_tests;
