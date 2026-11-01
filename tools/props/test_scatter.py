"""Checks for scatter_props (plain Python):  python tools/props/test_scatter.py"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scatter  # noqa: E402


def main():
    idx = scatter.load_index()
    ctx = scatter.demo_context(3, "market")
    a = scatter.scatter_props(ctx, index=idx)
    b = scatter.scatter_props(ctx, index=idx)
    assert a == b and a, "deterministic and not empty"
    c = scatter.scatter_props(dict(ctx, seed=4), index=idx)
    assert a != c, "seed changes the result"

    # same-prop spacing (outside clusters / runs) and no overlap with blocked discs
    by = {}
    for p in a:
        by.setdefault(p["prop"], []).append(p)
    for name, ps in by.items():
        rule = idx["props"][name]["scatter"]
        sp = rule.get("spacing", 0)
        if sp <= 0 or rule.get("cluster") or rule.get("run"):
            continue
        for i, p in enumerate(ps):
            for q in ps[i + 1:]:
                d = math.hypot(p["pos"][0] - q["pos"][0], p["pos"][2] - q["pos"][2])
                assert d >= sp - 1e-6, f"{name}: {d:.2f} m < spacing {sp}"
    for blk in ctx["blocked"]:
        for p in a:
            if p["slot"] == "facade" or p["slot"] == "alley_span":
                continue
            d = math.hypot(p["pos"][0] - blk["pos"][0], p["pos"][2] - blk["pos"][2])
            assert d >= blk["radius"] - 1e-6, f"{p['prop']} inside a blocked disc"

    # curb props face the road: front (+Z rotated by yaw) points to the junction centre side
    for p in a:
        if p["slot"] == "curb" and idx["props"][p["prop"]]["scatter"].get("facing") == "road":
            fx, fz = math.sin(p["yaw"]), math.cos(p["yaw"])
            x, z = p["pos"][0], p["pos"][2]
            # demo curbs run along the axes; the road is towards the nearer axis
            to_road = (0.0, -math.copysign(1, z)) if abs(z) < abs(x) else (-math.copysign(1, x), 0.0)
            assert fx * to_road[0] + fz * to_road[1] > 0.7, f"{p['prop']} at {p['pos']} does not face the road"

    # luxury gets palms, market gets food stalls / trash, no palms
    lux = scatter.summary(scatter.scatter_props(scatter.demo_context(3, "luxury"), index=idx))
    mkt = scatter.summary(a)
    assert lux.get("palm_tree", 0) > 0 and mkt.get("palm_tree", 0) == 0
    assert mkt.get("trash_bag_pile", 0) > lux.get("trash_bag_pile", 0)

    # xform is a Godot Transform3D (basis columns + origin) with yaw about +Y
    p = a[0]
    xf = p["xform"]
    assert abs(xf[0] - math.cos(p["yaw"]) * p["scale"][0]) < 1e-4 and all(abs(u - v) < 1e-3 for u, v in zip(xf[9:], p["pos"]))
    # rules: a list restricts, a dict overrides
    only = scatter.scatter_props(ctx, ["bench"], index=idx)
    assert only and {q["prop"] for q in only} == {"bench"}
    more = scatter.scatter_props(ctx, {"bench": {"density": {"default": 20}}}, index=idx)
    assert len(more) > len(only)
    print(f"test_scatter: ok ({len(a)} props in the market demo)")


if __name__ == "__main__":
    main()
