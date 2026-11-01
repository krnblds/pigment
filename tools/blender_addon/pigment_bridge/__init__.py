"""Pigment Bridge: link Blender objects to Pigment texture exports and keep them live.

3D Viewport > Sidebar (N) > Pigment. See docs/agents/blender-bridge/NOTES.md.
"""
import os

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import core

bl_info = {
    "name": "Pigment Bridge",
    "author": "Pigment",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > Pigment",
    "description": "Build materials from Pigment texture exports, live-reload them, random variants, mesh round trip",
    "category": "Material",
}


def _prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _exe(context=None):
    p = _prefs(context)
    return core.find_pigment_mcp(p.pigment_mcp if p else "")


class PigmentBridgePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    pigment_mcp: StringProperty(name="pigment-mcp", subtype="FILE_PATH",
                                description="pigment-mcp executable, used to export linked .pigment projects "
                                            "(default: $PIGMENT_MCP, the repo's target/release, or PATH)")

    def draw(self, context):
        self.layout.prop(self, "pigment_mcp")
        found = core.find_pigment_mcp(self.pigment_mcp)
        self.layout.label(text=f"Using: {found}" if found else "pigment-mcp not found (projects can't be linked)")


def _options(s):
    return {
        "height_mode": s.height_mode,
        "bump_distance": s.bump_distance,
        "bump_strength": s.bump_strength,
        "displacement_scale": s.displacement_scale,
        "ao_strength": s.ao_strength,
        "emission_mult": s.emission_mult,
        "flake_normal": s.flake_normal,
    }


class PigmentBridgeSettings(bpy.types.PropertyGroup):
    source: StringProperty(name="Source", subtype="DIR_PATH",
                           description="Pigment texture folder (with material.json or <name>_<Map>.png), "
                                       "an <asset>__<variant> folder, or a .pigment project folder")
    material_name: StringProperty(name="Set", description="Texture set (base name) in the folder; empty = the folder's main set")
    use_variants: BoolProperty(name="Random variant per object", default=False,
                               description="Pick a random <asset>__<variant> sibling folder for each object")
    seed: IntProperty(name="Seed", default=0)
    height_mode: EnumProperty(name="Height", default="BUMP", items=[
        ("NONE", "Off", "Ignore the height map"),
        ("BUMP", "Bump", "Height drives a Bump node (cheap, works in EEVEE)"),
        ("DISPLACEMENT", "Displacement", "True displacement (Cycles) plus bump; needs subdivision"),
    ])
    bump_distance: FloatProperty(name="Bump distance", default=0.01, min=0.0, soft_max=0.2, unit="LENGTH", precision=4)
    bump_strength: FloatProperty(name="Bump strength", default=1.0, min=0.0, max=1.0)
    displacement_scale: FloatProperty(name="Displacement", default=0.02, min=0.0, soft_max=0.5, unit="LENGTH", precision=4)
    add_subdivision: BoolProperty(name="Add adaptive subdivision", default=True,
                                  description="With Displacement: add a subdivision modifier so there is geometry to displace")
    ao_strength: FloatProperty(name="AO into base colour", default=0.5, min=0.0, max=1.0)
    emission_mult: FloatProperty(name="Emission ×", default=1.0, min=0.0, soft_max=20.0,
                                 description="Multiplier on Pigment's exported emissive_scale")
    flake_normal: BoolProperty(name="Metallic flake sparkle", default=True,
                               description="With a Flake map: jitter the base normal per tiny cell under the clearcoat "
                                           "(turn off before a glTF export, which can't carry the procedural normal)")
    auto_reload: BoolProperty(name="Auto-reload", default=True,
                              description="Watch linked texture files and reload them when Pigment re-exports")
    watch_projects: BoolProperty(name="Re-export linked projects", default=False,
                                 description="When a linked .pigment project is saved, re-export it with pigment-mcp")
    interval: FloatProperty(name="Check every", default=1.0, min=0.2, max=60.0, unit="TIME_ABSOLUTE")


def _linkable(context):
    return [o for o in context.selected_objects if o.type == "MESH"]


class PIGMENT_OT_link(bpy.types.Operator):
    """Link the selected meshes to the Pigment source and build their material(s)"""
    bl_idname = "pigment.link"
    bl_label = "Link Selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.pigment_bridge
        objs = _linkable(context)
        if not objs:
            self.report({"ERROR"}, "Select one or more mesh objects")
            return {"CANCELLED"}
        if not s.source:
            self.report({"ERROR"}, "Choose a Pigment folder or project first")
            return {"CANCELLED"}
        try:
            res = core.link_objects(objs, s.source, s.material_name or None, _options(s), variants=s.use_variants,
                                    seed=s.seed, subdivide=s.add_subdivision, exe=_exe(context))
        except (FileNotFoundError, RuntimeError, ValueError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        mats = sorted({m.name for m in res.values()})
        self.report({"INFO"}, f"Linked {len(res)} object(s) to {len(mats)} material(s): {', '.join(mats)}")
        return {"FINISHED"}


class PIGMENT_OT_rebuild(bpy.types.Operator):
    """Rebuild the active object's Pigment material with the panel's options (all objects using it update)"""
    bl_idname = "pigment.rebuild"
    bl_label = "Rebuild Material"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        m = context.object.active_material if context.object else None
        return m is not None and m.get("pigment_folder")

    def execute(self, context):
        s = context.scene.pigment_bridge
        mat = context.object.active_material
        try:
            spec = core.discover(mat["pigment_folder"], mat["pigment_name"])
        except FileNotFoundError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        uv = context.object.data.uv_layers[0].name if len(context.object.data.uv_layers) else ""
        core.build_material(spec, mat, _options(s), uv)
        if s.height_mode == "DISPLACEMENT" and s.add_subdivision:
            for o in context.scene.objects:
                if o.type == "MESH" and o.active_material == mat:
                    core.add_displacement_subdivision(o)
        return {"FINISHED"}


class PIGMENT_OT_reload(bpy.types.Operator):
    """Reload every Pigment material from disk now"""
    bl_idname = "pigment.reload"
    bl_label = "Reload Now"

    force: BoolProperty(name="Rebuild all", default=False)

    def execute(self, context):
        r = core.check_reload(force=self.force, watch_projects=context.scene.pigment_bridge.watch_projects, exe=_exe(context))
        self.report({"INFO"}, f"Reloaded {len(r['reloaded'])} image(s), rebuilt {len(r['rebuilt'])} material(s)")
        return {"FINISHED"}


class PIGMENT_OT_reroll(bpy.types.Operator):
    """Pick new random variants for the selected objects"""
    bl_idname = "pigment.reroll_variants"
    bl_label = "Re-roll Variants"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        res = core.reroll_variants(_linkable(context))
        self.report({"INFO"}, f"Re-rolled {len(res)} object(s)")
        return {"FINISHED"}


class PIGMENT_OT_import_mesh(bpy.types.Operator):
    """Import the exact mesh Pigment painted (exported by send_to_blender) with its material"""
    bl_idname = "pigment.import_mesh"
    bl_label = "Import Pigment Mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.pigment_bridge
        try:
            spec = core.discover(core.resolve_source(s.source, _exe(context)), s.material_name or None)
            objs = core.import_mesh(spec)
        except (FileNotFoundError, RuntimeError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported {len(objs)} object(s)")
        return {"FINISHED"}


class PIGMENT_OT_export_project(bpy.types.Operator):
    """Export the linked .pigment project again with pigment-mcp (textures, sidecar, mesh)"""
    bl_idname = "pigment.export_project"
    bl_label = "Re-export Project"

    def execute(self, context):
        s = context.scene.pigment_bridge
        src = s.source
        mat = context.object.active_material if context.object else None
        if mat is not None and mat.get("pigment_project"):
            src = mat["pigment_project"]
        if not src or not core.is_project(src):
            self.report({"ERROR"}, "No linked .pigment project")
            return {"CANCELLED"}
        try:
            out = core.export_project(src, exe=_exe(context))
        except (FileNotFoundError, RuntimeError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        core.check_reload()
        self.report({"INFO"}, f"Exported to {out}")
        return {"FINISHED"}


class PIGMENT_PT_bridge(bpy.types.Panel):
    bl_label = "Pigment Bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Pigment"

    def draw(self, context):
        s = context.scene.pigment_bridge
        lay = self.layout
        col = lay.column(align=True)
        col.prop(s, "source", text="")
        col.prop(s, "material_name")
        row = lay.row(align=True)
        row.prop(s, "use_variants")
        sub = row.row()
        sub.enabled = s.use_variants
        sub.prop(s, "seed")

        box = lay.box()
        box.prop(s, "height_mode")
        if s.height_mode == "BUMP":
            box.prop(s, "bump_distance")
            box.prop(s, "bump_strength")
        elif s.height_mode == "DISPLACEMENT":
            box.prop(s, "displacement_scale")
            box.prop(s, "add_subdivision")
        box.prop(s, "ao_strength")
        box.prop(s, "emission_mult")
        box.prop(s, "flake_normal")

        lay.operator(PIGMENT_OT_link.bl_idname, icon="LINKED")
        row = lay.row(align=True)
        row.operator(PIGMENT_OT_rebuild.bl_idname, icon="NODE_MATERIAL")
        row.operator(PIGMENT_OT_reroll.bl_idname, icon="FILE_REFRESH")
        lay.operator(PIGMENT_OT_import_mesh.bl_idname, icon="IMPORT")

        box = lay.box()
        row = box.row(align=True)
        row.prop(s, "auto_reload")
        row.prop(s, "interval", text="")
        box.prop(s, "watch_projects")
        row = box.row(align=True)
        row.operator(PIGMENT_OT_reload.bl_idname, icon="FILE_REFRESH")
        row.operator(PIGMENT_OT_export_project.bl_idname, icon="EXPORT")
        rep = core.last_report
        if rep["rebuilt"] or rep["reloaded"]:
            box.label(text=f"Last: {len(rep['reloaded'])} image(s), {len(rep['rebuilt'])} rebuilt", icon="INFO")

        obj = context.object
        mat = obj.active_material if obj else None
        if mat is not None and mat.get("pigment_folder"):
            box = lay.box()
            box.label(text=mat.name, icon="MATERIAL")
            box.label(text=f"Folder: {os.path.basename(mat['pigment_folder'])}")
            if obj.get("pigment_variants"):
                box.label(text=f"Variant: {core.split_variant(mat['pigment_folder'])[1] or '-'}")
            box.label(text=f"Maps: {mat.get('pigment_channels', '')}")
            if mat.get("pigment_resolution"):
                box.label(text=f"Resolution: {mat['pigment_resolution']}")
            users = sum(1 for o in context.scene.objects if o.type == "MESH" and mat.name in o.data.materials)
            box.label(text=f"Shared by {users} object(s)")
            box.label(text=f"Emissive scale (Pigment): {mat.get('pigment_emissive_scale', 1.0):.3g}")
            box.prop(mat, '["pigment_emission_mult"]', text="Emission ×")
            if mat.get("pigment_project"):
                box.label(text=f"Project: {os.path.basename(mat['pigment_project'])}")


# ------------------------------------------------------------------ timer

def _tick():
    """Auto-reload timer: check linked files' mtimes. Returns the next interval."""
    scene = getattr(bpy.context, "scene", None)
    s = getattr(scene, "pigment_bridge", None) if scene else None
    if s is None:
        return 2.0
    if s.auto_reload:
        try:
            r = core.check_reload(watch_projects=s.watch_projects, exe=_exe())
            c = core.check_city_events()        # tools/city build / watch events (file queue)
            if r["reloaded"] or r["rebuilt"] or c["events"]:
                for w in bpy.context.window_manager.windows:
                    for a in w.screen.areas:
                        a.tag_redraw()
        except Exception as e:  # never let the timer die
            print("Pigment Bridge: reload failed:", e)
    return float(s.interval)


@persistent
def _on_load(_):
    core.forget_seen()


classes = (
    PigmentBridgePreferences,
    PigmentBridgeSettings,
    PIGMENT_OT_link,
    PIGMENT_OT_rebuild,
    PIGMENT_OT_reload,
    PIGMENT_OT_reroll,
    PIGMENT_OT_import_mesh,
    PIGMENT_OT_export_project,
    PIGMENT_PT_bridge,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.pigment_bridge = PointerProperty(type=PigmentBridgeSettings)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=1.0, persistent=True)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    del bpy.types.Scene.pigment_bridge
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
