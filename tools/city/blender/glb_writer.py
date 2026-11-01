"""A small, fast glTF binary writer for Blender meshes (numpy; runs inside Blender).

Writes what tools/godot/export_town.export_mesh() writes for the world meshes: one node, one
mesh, a primitive per used material with POSITION / NORMAL / TEXCOORD_n and indices, material
*names* only (Godot maps surfaces to materials by name), glTF Y-up axes (x, z, -y), and
v flipped. Vertices are split per (position, corner normal, UVs) like Blender's exporter.

Why: Blender's glTF exporter walks the whole scene on every call. In the 38k-object world
scene that is ~1-2.5 s per file, ~55 min for the 1,428 world glbs. This writes one in
milliseconds, so a cold world export is bounded by the build, not the exporter.
"""
import json
import struct

import numpy as np


def _get(coll, attr, n, dtype, width):
    a = np.empty(n * width, dtype=dtype)
    if n:
        coll.foreach_get(attr, a)
    return a.reshape(n, width) if width > 1 else a


def mesh_arrays(me):
    """Per used material: (positions, normals, [uvs...], indices) in glTF space."""
    me.calc_loop_triangles()
    nt, nv, nl = len(me.loop_triangles), len(me.vertices), len(me.loops)
    tri_loops = _get(me.loop_triangles, "loops", nt, np.int32, 3)
    tri_mat = _get(me.loop_triangles, "material_index", nt, np.int32, 1)
    co = _get(me.vertices, "co", nv, np.float32, 3)
    vidx = _get(me.loops, "vertex_index", nl, np.int32, 1)
    try:
        cn = me.corner_normals
        nrm = _get(cn, "vector", len(cn), np.float32, 3)
    except AttributeError:          # older Blender
        nrm = _get(me.loops, "normal", nl, np.float32, 3)
    # the world glbs carry one UV set (what the exporter wrote for them): the active render UV map
    lay = next((uv for uv in me.uv_layers if uv.active_render), None) or (me.uv_layers[0] if len(me.uv_layers) else None)
    uvs = [_get(lay.data, "uv", nl, np.float32, 2)] if lay is not None else []
    P = co[vidx]
    # like Blender's exporter, corners whose normals agree to ~1e-4 share a vertex
    nrm = np.round(nrm, 4)
    rows = [P, nrm] + uvs
    allrows = np.concatenate(rows, axis=1) if rows else P
    out = []
    for m in sorted(set(tri_mat.tolist())):
        L = tri_loops[tri_mat == m].reshape(-1)
        sub = allrows[L]
        uniq, inv = np.unique(sub, axis=0, return_inverse=True)
        inv = inv.reshape(-1).astype(np.uint32)
        p = uniq[:, 0:3]
        n = uniq[:, 3:6]
        gp = np.stack([p[:, 0], p[:, 2], -p[:, 1]], axis=1).astype(np.float32)
        gn = np.stack([n[:, 0], n[:, 2], -n[:, 1]], axis=1).astype(np.float32)
        ln = np.linalg.norm(gn, axis=1, keepdims=True)
        gn = np.where(ln > 1e-12, gn / np.maximum(ln, 1e-12), np.array([0, 1, 0], np.float32)).astype(np.float32)
        guv = []
        for k in range(len(uvs)):
            u = uniq[:, 6 + 2 * k: 8 + 2 * k].astype(np.float32).copy()
            u[:, 1] = 1.0 - u[:, 1]
            guv.append(u)
        out.append((m, gp, gn, guv, inv))
    return out


def write_glb(me, path, name="_export_tmp"):
    prims = mesh_arrays(me)
    mats = [m.name if m else None for m in me.materials]
    blob = bytearray()
    views, accessors = [], []

    def add(arr, target, comp, typ, minmax=False):
        nonlocal blob
        while len(blob) % 4:
            blob += b"\0"
        off = len(blob)
        data = np.ascontiguousarray(arr).tobytes()
        blob += data
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": int(arr.shape[0]), "type": typ}
        if minmax:
            acc["min"] = [float(x) for x in arr.min(axis=0)]
            acc["max"] = [float(x) for x in arr.max(axis=0)]
        accessors.append(acc)
        return len(accessors) - 1

    materials, mat_index, primitives = [], {}, []
    for m, gp, gn, guv, inv in prims:
        attrs = {"POSITION": add(gp, 34962, 5126, "VEC3", True), "NORMAL": add(gn, 34962, 5126, "VEC3")}
        for k, u in enumerate(guv):
            attrs[f"TEXCOORD_{k}"] = add(u, 34962, 5126, "VEC2")
        idx = inv.astype(np.uint16) if gp.shape[0] < 65536 else inv
        ia = add(idx, 34963, 5123 if idx.dtype == np.uint16 else 5125, "SCALAR")
        pr = {"attributes": attrs, "indices": ia, "mode": 4}
        mname = mats[m] if m < len(mats) else None
        if mname:
            if mname not in mat_index:
                mat_index[mname] = len(materials)
                materials.append({"name": mname, "doubleSided": True})
            pr["material"] = mat_index[mname]
        primitives.append(pr)
    while len(blob) % 4:
        blob += b"\0"
    doc = {"asset": {"generator": "tools/city glb_writer", "version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [{"mesh": 0, "name": name}], "meshes": [{"name": me.name, "primitives": primitives}],
           "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    if materials:
        doc["materials"] = materials
    js = json.dumps(doc, separators=(",", ":")).encode()
    while len(js) % 4:
        js += b" "
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A))
        f.write(js)
        f.write(struct.pack("<II", len(blob), 0x004E4942))
        f.write(blob)
