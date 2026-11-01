"""Tree kit species: the parameters of tools/trees/treegen.py (pure data, no bpy).

Every species is a recursive branch model (trunk -> scaffolds -> branches ->
twigs) with alpha-tested leaf cards on the twigs. Lengths are in metres,
angles in degrees. A variant is (species, seed): the same species parameters
grown from a different seed (3-5 per species), plus optional look swaps
(`looks`: the same skeleton with other leaf cells, e.g. autumn ginkgo or
cherry in blossom).

Level parameters (levels[0] = children of the trunk, levels[1] = their
children...):
    n         children per parent (scaled by parent length / max length)
    start/end where along the parent they grow (0..1)
    angle     angle from the parent axis at the parent's base / tip ([a0, a1]) +- angle_var
    phyllo    rotation between successive children around the parent (137.5 = spiral, 180 = alternate)
    length    fraction of the parent's length (times the crown envelope for level 0)
    curve     total bend (deg) upward (+) / downward (-) along the branch
    wobble    random bend per metre (deg)
    gravity   droop per metre (+ = down, - = up / phototropism), stronger on thin branches
    radius    child base radius / parent radius at the attachment
    seg       segment length at LOD0 (m)
    sides     tube sides at LOD0 (0 = not meshed: the leaf cards carry the twig)
    outward   horizontal pull away from the trunk axis (opens the crown)

Leaves (`leaves`):
    mode      spray (cards along twigs), tuft (crossed cards at twig tips: pine),
              hang (cards hanging along branches: cedar), strip (a folded strip
              along each frond: palm), cloud (cards over a volume: shrubs)
    cells     atlas cells with weights (see LEAF_CELLS)
    size      card [width, length] in metres, size_var
    spacing   metres between cards along a twig; start: fraction where they begin
    tilt      up-tilt of the card's length axis, droop: tip sag (fraction of length)
"""

# The leaf / needle / blossom card atlas (tools/trees/tree_textures.py builds it in
# Pigment as a decal atlas). name -> [width, height] in metres of the painted card.
LEAF_CELLS = {
    "pagoda_spray": [0.62, 0.78],     # pinnate compound leaves, 9-15 ovate leaflets
    "pagoda_spray_b": [0.62, 0.78],
    "zelkova_spray": [0.5, 0.7],      # small serrate alternate leaves on a zig-zag twig
    "zelkova_spray_b": [0.5, 0.7],
    "ginkgo_spray": [0.5, 0.6],       # fan leaves in clusters on spur shoots
    "ginkgo_gold": [0.5, 0.6],        # autumn
    "cherry_blossom": [0.55, 0.6],    # five-petal pale pink clusters, no leaves
    "cherry_green": [0.55, 0.65],     # elliptic serrate leaves
    "pine_tuft": [0.42, 0.5],         # paired needles in a brush
    "cedar_spray": [0.5, 0.75],       # awl needles in drooping sprays
    "palm_frond": [0.55, 2.2],         # pinnate frond, rachis down the middle
    "azalea": [0.34, 0.34],           # small leaves, dense
    "azalea_bloom": [0.34, 0.34],     # magenta flowers over leaves
    "box_leaves": [0.3, 0.3],         # clipped box / holly
}

BARK = {   # bark tile per species: [width, height] of the seamless tile in metres
    "pagoda": [0.8, 1.2],
    "zelkova": [0.8, 1.2],
    "ginkgo": [0.8, 1.2],
    "cherry": [0.8, 0.8],
    "pine": [0.8, 1.2],
    "cedar": [0.6, 1.6],
    "palm": [0.8, 0.8],
}

SPECIES = {
    # ---------------------------------------------------------------- Japanese pagoda tree
    "pagoda": dict(
        title="Japanese pagoda tree (Styphnolobium japonicum, 'Japanese acacia')",
        role="avenue / park: a broad rounded crown on a short trunk",
        bark="pagoda", height=[10.0, 13.0], trunk_radius=0.22, flare=0.55, roots=5,
        trunk=dict(length=0.72, lean=5, wobble=7, seg=0.7, sides=9, split=None),
        crown=dict(base=0.24, shape="hemispherical", width=1.0),
        levels=[
            dict(n=7, start=0.26, end=0.92, angle=[62, 42], angle_var=10, phyllo=137.5, length=0.62, length_var=0.15,
                 curve=-18, wobble=9, gravity=0.6, radius=0.62, seg=0.6, sides=6, outward=0.35),
            dict(n=9, start=0.18, end=1.0, angle=[50, 38], angle_var=12, phyllo=150, length=0.46, length_var=0.2,
                 curve=10, wobble=14, gravity=2.0, radius=0.6, seg=0.7, sides=3, outward=0.2),
            dict(n=6, start=0.2, end=1.0, angle=[48, 40], angle_var=15, phyllo=180, length=0.45, length_var=0.25,
                 curve=0, wobble=20, gravity=2.5, radius=0.55, seg=0.5, sides=0, outward=0.1),
        ],
        leaves=dict(mode="spray", cells=[["pagoda_spray", 1.0], ["pagoda_spray_b", 1.0]], size=[0.95, 1.15], size_var=0.18,
                    spacing=0.42, start=0.15, tilt=0.35, droop=0.12, budget=560, lod1=150),
        variants=4,
    ),
    # ---------------------------------------------------------------- Japanese zelkova (keyaki)
    "zelkova": dict(
        title="Japanese zelkova (Zelkova serrata, keyaki)",
        role="the Tokyo avenue tree: a vase of upright leaders on a short trunk",
        bark="zelkova", height=[12.0, 16.0], trunk_radius=0.24, flare=0.45, roots=6,
        trunk=dict(length=0.2, lean=2, wobble=4, seg=0.5, sides=10, split=dict(n=[5, 7], angle=[18, 30], length=0.82, radius=0.62, curve=-10)),
        crown=dict(base=0.22, shape="flame", width=0.9),
        levels=[
            # on the leaders: ascending side branches, longer towards the top (vase)
            dict(n=8, start=0.28, end=1.0, angle=[48, 34], angle_var=10, phyllo=137.5, length=0.42, length_var=0.2,
                 curve=-6, wobble=10, gravity=0.6, radius=0.55, seg=0.6, sides=4, outward=0.45),
            dict(n=7, start=0.15, end=1.0, angle=[45, 35], angle_var=12, phyllo=180, length=0.5, length_var=0.25,
                 curve=0, wobble=18, gravity=1.6, radius=0.55, seg=0.45, sides=0, outward=0.15),
        ],
        leaves=dict(mode="spray", cells=[["zelkova_spray", 1.0], ["zelkova_spray_b", 1.0]], size=[0.75, 0.95], size_var=0.15,
                    spacing=0.34, start=0.1, tilt=0.45, droop=0.1, budget=600, lod1=160),
        variants=4,
    ),
    # ---------------------------------------------------------------- ginkgo
    "ginkgo": dict(
        title="Ginkgo (Ginkgo biloba, icho)",
        role="avenue tree: a tall upright, slightly irregular crown; golden in autumn",
        bark="ginkgo", height=[12.0, 16.0], trunk_radius=0.22, flare=0.35, roots=5,
        trunk=dict(length=0.97, lean=2, wobble=5, seg=0.6, sides=9, split=None),
        crown=dict(base=0.2, shape="tapered", width=0.55),
        levels=[
            dict(n=16, start=0.18, end=0.96, angle=[58, 38], angle_var=12, phyllo=137.5, length=0.36, length_var=0.3,
                 curve=16, wobble=8, gravity=-0.3, radius=0.42, seg=0.6, sides=5, outward=0.15),
            dict(n=8, start=0.12, end=1.0, angle=[52, 40], angle_var=14, phyllo=137.5, length=0.42, length_var=0.3,
                 curve=6, wobble=12, gravity=0.6, radius=0.5, seg=0.45, sides=0, outward=0.1),
        ],
        leaves=dict(mode="spray", cells=[["ginkgo_spray", 1.0]], size=[0.8, 0.95], size_var=0.15,
                    spacing=0.36, start=0.08, tilt=0.4, droop=0.06, budget=520, lod1=140),
        looks={"gold": {"ginkgo_spray": "ginkgo_gold"}},
        variants=3,
    ),
    # ---------------------------------------------------------------- cherry (sakura)
    "cherry": dict(
        title="Cherry (Prunus x yedoensis, Somei-yoshino)",
        role="parks and temple grounds: low, wide, arching scaffolds",
        bark="cherry", height=[6.5, 8.5], trunk_radius=0.2, flare=0.5, roots=4,
        trunk=dict(length=0.3, lean=8, wobble=10, seg=0.4, sides=10, split=dict(n=[3, 5], angle=[38, 58], length=0.95, radius=0.72, curve=-34)),
        crown=dict(base=0.25, shape="spherical", width=1.35),
        levels=[
            dict(n=9, start=0.12, end=1.0, angle=[55, 40], angle_var=14, phyllo=137.5, length=0.5, length_var=0.2,
                 curve=-12, wobble=16, gravity=1.4, radius=0.55, seg=0.5, sides=4, outward=0.3),
            dict(n=7, start=0.15, end=1.0, angle=[50, 40], angle_var=15, phyllo=160, length=0.45, length_var=0.25,
                 curve=-6, wobble=22, gravity=2.6, radius=0.5, seg=0.4, sides=0, outward=0.1),
        ],
        leaves=dict(mode="spray", cells=[["cherry_blossom", 1.0]], size=[0.85, 0.95], size_var=0.15,
                    spacing=0.32, start=0.1, tilt=0.2, droop=0.14, budget=560, lod1=150),
        looks={"green": {"cherry_blossom": "cherry_green"}},
        variants=3,
    ),
    # ---------------------------------------------------------------- Japanese black pine (kuromatsu)
    "pine": dict(
        title="Japanese black pine (Pinus thunbergii, kuromatsu)",
        role="shore, mountain road and lookout: a leaning, windswept trunk with cloud pads",
        bark="pine", height=[8.0, 12.0], trunk_radius=0.23, flare=0.35, roots=4,
        trunk=dict(length=0.95, lean=14, wobble=8, seg=0.5, sides=9, split=None, sweep=0.35, upright=1.2),
        crown=dict(base=0.35, shape="tend_flame", width=0.85),
        levels=[
            dict(n=11, start=0.32, end=0.98, angle=[86, 62], angle_var=14, phyllo=137.5, length=0.38, length_var=0.3,
                 curve=-8, wobble=18, gravity=0.0, radius=0.42, seg=0.45, sides=6, outward=0.55, downwind=0.45),
            dict(n=7, start=0.3, end=1.0, angle=[55, 40], angle_var=18, phyllo=137.5, length=0.4, length_var=0.25,
                 curve=18, wobble=20, gravity=-0.8, radius=0.5, seg=0.6, sides=3, outward=0.2),
            dict(n=4, start=0.4, end=1.0, angle=[45, 35], angle_var=15, phyllo=120, length=0.45, length_var=0.2,
                 curve=10, wobble=20, gravity=-1.0, radius=0.5, seg=0.35, sides=0, outward=0.0),
        ],
        leaves=dict(mode="tuft", cells=[["pine_tuft", 1.0]], size=[0.62, 0.72], size_var=0.15,
                    spacing=0.3, start=0.45, tilt=0.6, droop=0.0, budget=640, lod1=170),
        variants=4,
    ),
    # ---------------------------------------------------------------- Japanese cedar (sugi)
    "cedar": dict(
        title="Japanese cedar (Cryptomeria japonica, sugi)",
        role="mountain forest: tall straight trunk, narrow conical crown",
        bark="cedar", height=[20.0, 27.0], trunk_radius=0.3, flare=0.4, roots=6,
        trunk=dict(length=1.0, lean=1.5, wobble=2.5, seg=1.0, sides=9, split=None),
        crown=dict(base=0.38, shape="conical", width=0.28),
        levels=[
            dict(n=48, start=0.38, end=0.99, angle=[100, 62], angle_var=10, phyllo=137.5, length=0.2, length_var=0.2,
                 curve=14, wobble=8, gravity=0.5, radius=0.32, seg=0.6, sides=4, outward=0.0),
        ],
        leaves=dict(mode="hang", cells=[["cedar_spray", 1.0]], size=[0.95, 1.25], size_var=0.15,
                    spacing=0.45, start=0.05, tilt=-0.1, droop=0.25, budget=560, lod1=140),
        variants=4,
    ),
    # ---------------------------------------------------------------- palm (corporate island)
    "palm": dict(
        title="Canary Island date palm (Phoenix canariensis)",
        role="the corporate island: a ringed trunk and a crown of arching pinnate fronds",
        bark="palm", height=[8.0, 11.0], trunk_radius=0.3, flare=0.25, roots=8,
        trunk=dict(length=1.0, lean=6, wobble=3, seg=0.5, sides=12, split=None, sweep=0.12, taper=0.25),
        crown=dict(base=0.9, shape="cylindrical", width=1.0),
        levels=[
            # fronds: thin rachis tubes (4 sides) carrying one folded strip each
            dict(n=26, start=0.985, end=1.0, angle=[95, 18], angle_var=8, phyllo=137.5, length=0.4, length_var=0.12,
                 curve=-55, wobble=4, gravity=0.6, radius=0.18, seg=0.4, sides=3, outward=0.0, abs_length=[3.4, 4.2],
                 radius_abs=0.035, age_sort=True),
        ],
        leaves=dict(mode="strip", cells=[["palm_frond", 1.0]], size=[1.25, 1.0], size_var=0.1,
                    spacing=0.0, start=0.1, tilt=0.0, droop=0.0, budget=26, lod1=26),
        variants=3,
    ),
    # ---------------------------------------------------------------- shrubs
    "azalea": dict(
        title="Azalea (Rhododendron, tsutsuji)",
        role="planters, park borders: dense clipped mounds, magenta in bloom",
        bark="cherry", height=[0.9, 1.2], trunk_radius=0.03, flare=0.0, roots=0,
        shrub=dict(shape="mound", size=[1.4, 1.2, 1.0], stems=6),
        leaves=dict(mode="cloud", cells=[["azalea", 1.0]], size=[0.42, 0.42], size_var=0.2, budget=150, lod1=50),
        looks={"bloom": {"azalea": "azalea_bloom"}},
        variants=2,
    ),
    "box": dict(
        title="Box hedge (Buxus / Ilex crenata)",
        role="clipped hedges and planters",
        bark="cherry", height=[0.6, 0.6], trunk_radius=0.02, flare=0.0, roots=0,
        shrub=dict(shape="box", size=[1.9, 0.6, 0.6], stems=5),
        leaves=dict(mode="cloud", cells=[["box_leaves", 1.0]], size=[0.36, 0.36], size_var=0.15, budget=170, lod1=60),
        variants=1,
    ),
}

# shrubs sized for the props-kit planter (1.6 x 0.6 m concrete trough, soil at 0.95 m)
PLANTER_SHRUBS = {
    "planter_box": dict(base="box", shrub=dict(shape="box", size=[1.42, 0.44, 0.42], stems=4), budget=120, lod1=44),
    "planter_azalea": dict(base="azalea", look="bloom", shrub=dict(shape="mound", size=[1.42, 0.46, 0.5], stems=4), budget=110, lod1=40),
}

# LOD distances (m): LOD0 below lod1, LOD1 below lod2, impostor below far
LODS = {
    "default": dict(lod1=38.0, lod2=110.0, far=650.0),
    "cedar": dict(lod1=30.0, lod2=85.0, far=900.0),
    "palm": dict(lod1=45.0, lod2=130.0, far=650.0),
    "shrub": dict(lod1=18.0, lod2=55.0, far=140.0),
}


def variant_keys():
    """Every exported key: tree_<species>_<letter>[_<look>] and the planter shrubs."""
    out = []
    for sp, d in SPECIES.items():
        for k in range(d["variants"]):
            v = chr(ord("a") + k)
            out.append((f"tree_{sp}_{v}", sp, k, None))
            for look in d.get("looks", {}):
                # every look on the first 2 shapes (enough variety, keeps the kit small)
                if k < 2 or sp in ("azalea",):
                    out.append((f"tree_{sp}_{v}_{look}", sp, k, look))
    for name, d in PLANTER_SHRUBS.items():
        out.append((f"tree_{name}", d["base"], 0, d.get("look")))
    return out
