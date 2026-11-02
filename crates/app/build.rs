//! Embeds the app icon into `pigment.exe` and `pigment-mcp.exe` on Windows.
//! Elsewhere this does nothing; Linux ships `pigment.desktop` plus a PNG.
//!
//! `winresource` is a `cfg(windows)` build-dependency, and build-dependency
//! cfgs follow the host, so the call is gated on the host as well as the target.

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=../../assets/branding/pigment.ico");
    #[cfg(windows)]
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let mut res = winresource::WindowsResource::new();
        res.set_icon("../../assets/branding/pigment.ico");
        res.set("FileDescription", "Pigment");
        res.set("ProductName", "Pigment");
        res.compile().expect("embedding the Windows icon resource");
    }
}
