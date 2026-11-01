"""Write a small synthetic world in the traffic lane format (world-lanes/1) for the headless tests.

    python tools/traffic/make_test_world.py [out.json]      (default game/tests/data/test_world.json)

3 x 3 junctions, 130 m apart, on flat ground (y = 0, Godot space), drive on the left.
  - the middle row and column are avenues: 2 lanes each way, 3.4 m lanes, 1 m median, 16.7 m/s
  - the other streets are 1 lane each way, 3.5 m, 12.5 m/s
  - every boundary junction has a free arm that runs 70 m to a dead end (spawn / despawn sink)
  - the centre and the avenue crossings are signalled (one with explicit phases), the rest are
    yield junctions with explicit priority roads; one junction is an all-way stop
  - one street is curved and one carries explicit "lanes" (instead of the lanes_forward shorthand)
It doubles as a worked example of the format for the world workstream (docs/agents/traffic/NOTES.md).
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "game", "tests", "data", "test_world.json")
SP = 130.0
FREE = 70.0


def line(a, b, step=8.0, bend=0.0):
    n = max(2, int(math.dist(a, b) / step))
    pts = []
    for i in range(n + 1):
        t = i / n
        x = a[0] + (b[0] - a[0]) * t
        z = a[1] + (b[1] - a[1]) * t
        if bend:
            # sideways bow, zero at both ends
            dx, dz = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dz)
            nx, nz = -dz / L, dx / L
            o = bend * math.sin(math.pi * t)
            x, z = x + nx * o, z + nz * o
        pts.append([round(x, 3), 0.0, round(z, 3)])
    return pts


def main():
    J = {}
    for i in range(3):
        for k in range(3):
            J[f"J{i}{k}"] = ((i - 1) * SP, (k - 1) * SP)
    roads = []
    avenue = {"lanes_forward": 2, "lanes_backward": 2, "lane_width": 3.4, "median": 1.0, "speed_limit": 16.7}
    street = {"lanes_forward": 1, "lanes_backward": 1, "lane_width": 3.5, "speed_limit": 12.5}

    def add(rid, a, b, kind, bend=0.0, ja=None, jb=None):
        r = {"id": rid, "points": line(a, b, bend=bend), "start": {"junction": ja} if ja else None,
             "end": {"junction": jb} if jb else None, "parking": ["left", "right"] if kind is street else []}
        r.update(kind)
        r["width"] = round(2 * (r["lane_width"] * r["lanes_forward"] + r.get("median", 0) / 2), 2)
        roads.append(r)

    for i in range(3):
        for k in range(3):
            a = f"J{i}{k}"
            if i < 2:      # east-west road to the next column
                b = f"J{i + 1}{k}"
                add(f"EW{i}{k}", J[a], J[b], avenue if k == 1 else street, ja=a, jb=b)
            if k < 2:      # north-south road to the next row
                b = f"J{i}{k + 1}"
                add(f"NS{i}{k}", J[a], J[b], avenue if i == 1 else street, bend=14.0 if (i, k) == (0, 0) else 0.0, ja=a, jb=b)
    # free arms off the boundary (dead ends)
    for name, (x, z) in J.items():
        i, k = int(name[1]), int(name[2])
        for di, dk, tag in ((-1, 0, "W"), (1, 0, "E"), (0, -1, "N"), (0, 1, "S")):
            if 0 <= i + di <= 2 and 0 <= k + dk <= 2:
                continue
            if (di and k != 1 and (i, k) not in ((0, 0), (2, 2))) or (dk and i != 1 and (i, k) not in ((0, 2), (2, 0))):
                continue    # not every boundary junction gets every free arm
            end = (x + di * FREE, z + dk * FREE)
            kind = avenue if (di and k == 1) or (dk and i == 1) else street
            add(f"X{name}{tag}", (x, z), end, kind, ja=name)
    # one street with explicit lanes (equivalent to the shorthand)
    for r in roads:
        if r["id"] == "EW00":
            r.pop("lanes_forward"), r.pop("lanes_backward")
            r["lanes"] = [{"offset": 1.75, "width": 3.5, "dir": 1}, {"offset": -1.75, "width": 3.5, "dir": -1},
                          {"offset": 4.6, "width": 2.0, "dir": 1, "kind": "parking"}, {"offset": -4.6, "width": 2.0, "dir": -1, "kind": "parking"}]
    junctions = []
    for name, (x, z) in J.items():
        i, k = int(name[1]), int(name[2])
        jd = {"id": name, "pos": [x, 0.0, z], "radius": 12.0}
        if i == 1 or k == 1:
            jd["control"] = "signal"
            if name == "J11":
                jd["phases"] = [{"roads": ["EW01", "EW11"], "green": 16, "amber": 3},
                                {"roads": ["NS10", "NS11"], "green": 12, "amber": 3}]
        elif name == "J22":
            jd["control"] = "stop"
        else:
            jd["control"] = "yield"
            jd["priority_roads"] = [r["id"] for r in roads if r["id"].startswith("EW") and name in (r["start"] or {}).get("junction", "") + (r["end"] or {}).get("junction", "")]
        junctions.append(jd)
    world = {"format": "traffic-test/1", "coords": "godot", "traffic": "left-hand", "speed_limit": 13.9,
             "roads": roads, "junctions": junctions}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(world, f, indent=1)
    print(f"{OUT}: {len(roads)} roads, {len(junctions)} junctions")


main()
