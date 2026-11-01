//! Parse and validate every WGSL shader without a GPU, so shader mistakes
//! fail `cargo test` instead of crashing the app at startup.

const COMMON: &str = include_str!("shaders/common.wgsl");

fn check(name: &str, src: &str) {
    let full = [COMMON, src].concat();
    let module = naga::front::wgsl::parse_str(&full).unwrap_or_else(|e| panic!("{name}: {}", e.emit_to_string(&full)));
    naga::valid::Validator::new(naga::valid::ValidationFlags::all(), naga::valid::Capabilities::default())
        .validate(&module)
        .unwrap_or_else(|e| panic!("{name}: {}", e.emit_to_string(&full)));
}

macro_rules! shader_test {
    ($test:ident, $file:literal) => {
        #[test]
        fn $test() {
            check($file, include_str!(concat!("shaders/", $file)));
        }
    };
}

shader_test!(viewport, "viewport.wgsl");
shader_test!(post, "post.wgsl");
shader_test!(env, "env.wgsl");
shader_test!(mip, "mip.wgsl");
shader_test!(texspace, "texspace.wgsl");
#[test]
fn composite() {
    // the weathering generators live in their own file, appended at load
    let src = [include_str!("shaders/composite.wgsl"), include_str!("shaders/gen_weather.wgsl"), include_str!("shaders/gen_ground.wgsl")].concat();
    check("composite.wgsl + gen_weather.wgsl + gen_ground.wgsl", &src);
}
shader_test!(stamp, "stamp.wgsl");
shader_test!(apply, "apply.wgsl");
shader_test!(bake_ao, "bake_ao.wgsl");
shader_test!(bake_curv, "bake_curv.wgsl");
shader_test!(bake_resolve, "bake_resolve.wgsl");
shader_test!(bake_blur, "bake_blur.wgsl");

/// The folder pass is appended to the compositor (it reuses its bindings).
#[test]
fn folder() {
    check("composite.wgsl + folder.wgsl", &[include_str!("shaders/composite.wgsl"), include_str!("shaders/gen_weather.wgsl"), include_str!("shaders/gen_ground.wgsl"), include_str!("shaders/folder.wgsl")].concat());
}
shader_test!(decal_box, "decal_box.wgsl");
shader_test!(foliage, "foliage.wgsl");
