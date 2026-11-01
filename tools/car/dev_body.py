import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import body  # noqa: E402
import panels  # noqa: E402
import preview  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)
t = time.time()
ob = body.build_cage()
body.subdivide(ob, 2)
shell, panes = panels.cut_body(ob)
print("cut s", time.time() - t)
print("tris", sum(len(p.vertices) - 2 for p in ob.data.polygons))
out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "C:/tmp/car/dev"
bpy.ops.wm.save_as_mainfile(filepath=out + "/dev.blend")
preview.clay(out, views=("front34", "side", "rear34", "low34"))
