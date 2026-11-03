//! Pigment engine: the app, renderer and headless automation, shared by the
//! `pigment` desktop app and the `pigment-mcp` server.

#![recursion_limit = "512"]

pub mod app;
pub mod cli;
pub mod mcp;
pub mod mcp_args;
pub mod render;

#[cfg(test)]
mod gpu_tests;
#[cfg(test)]
mod shader_tests;
