"""The street-props kit: one entry per prop (pure Python; Blender, the texture
script, the index writer and scatter.py all import it).

Per prop:
    category    street_furniture | traffic | signage | utility | clutter | food | rooftop | nature | decal
    title, desc
    res         Pigment texture resolution (the project works at this size)
    embed       texture size embedded in the LOD0 glb (LOD1 gets half)
    lod1        build a decimated LOD1 (ratio)  -- None = no LOD1
    scatter     placement rules (see SCATTER_DOC and tools/props/scatter.py)

Districts used by the density tables (unknown districts fall back to "default"):
    downtown     corporate core: Hoshikawa towers, MERIDIAN everywhere, clean-ish
    commercial   neon shopping streets
    market       night market / food alleys, dense clutter
    residential  hillside housing
    industrial   port, works, depots
    slum         the undercity: trash, UNPLUG, broken things
    luxury       the luxury island: palms, planters, few people
"""

DISTRICTS = ["downtown", "commercial", "market", "residential", "industrial", "slum", "luxury"]

SLOTS = {
    "curb": "line along the curb (front = towards the road). Props sit on the sidewalk, `offset` metres back from the curb face (negative = onto the walk).",
    "walk": "line along the middle of the sidewalk (front = towards the road).",
    "frontage": "line along building fronts at street level (front = away from the wall, towards the street). `offset` = distance out from the wall.",
    "facade": "line along building walls, mounted at `mount_height` metres (wall-mounted props; origin = the wall mounting point).",
    "corner": "junction corners: point at the curb apex, `dir` points from the sidewalk into the junction.",
    "crossing": "pedestrian-crossing ends: point at the curb where the zebra meets it, `dir` points across the road.",
    "roadside": "line along the road edge on the asphalt (front = along the traffic); roadworks, barriers.",
    "road": "area: the carriageway (manhole steam vents, puddles).",
    "median": "line along a central reservation.",
    "alley": "line along alley walls (front = into the alley).",
    "alley_span": "pairs of alley walls facing each other: the prop spans the gap (scale X to the `span`).",
    "rooftop": "area: flat roofs (polygon + roof height).",
    "plaza": "area: squares, forecourts, parks.",
}

SCATTER_DOC = {
    "slots": "which slots the prop may use (keys of SLOTS)",
    "density": "per district: instances per 100 m of line (line slots), per 100 m2 (area slots) or probability per point (corner / crossing); 'default' is the fallback",
    "offset": "metres from the slot line along the front direction (negative = behind it)",
    "spacing": "minimum distance (m) to another instance of the same prop",
    "clearance": "radius (m) kept free of other props (and of context['blocked'])",
    "facing": "front: 'road' = along the slot's front; 'wall' = opposite; 'along' = parallel to the line; 'random'",
    "yaw_jitter": "degrees of random yaw",
    "cluster": "[min, max] instances per placement, within cluster_radius",
    "mount_height": "[min, max] metres above ground (facade props)",
    "along": "corner/crossing: metres along the curb from the apex (sign picks a side)",
}

ALL = list(DISTRICTS)


def dens(default=0.0, **kw):
    d = {"default": default}
    d.update(kw)
    return d


PROPS = {
    # ------------------------------------------------------------------ traffic
    "traffic_light_pole": dict(
        category="traffic", title="Traffic signal pole (3-light head + pedestrian head)",
        desc="Galvanised pole with a vertical 3-light vehicle head facing front and a pedestrian head facing +X, push-button box and a MERIDIAN sensor puck.",
        res=1024, embed=1024, lod1=0.45,
        scatter=dict(slots=["corner"], density=dens(0.9, residential=0.6, slum=0.3, market=0.4), along=[1.2, 2.0], offset=-0.55,
                     spacing=6.0, clearance=0.5, facing="road", yaw_jitter=0)),
    "traffic_light_mast": dict(
        category="traffic", title="Mast-arm traffic signal (two horizontal heads over the road)",
        desc="6 m tapered pole, 6.5 m arm reaching out to +X over the lanes, two horizontal 3-light heads, a street-name blade and a MERIDIAN camera at the tip.",
        res=2048, embed=1024, lod1=0.4,
        scatter=dict(slots=["corner"], density=dens(0.5, downtown=0.9, commercial=0.7, luxury=0.7, slum=0.0, market=0.1), along=[0.8, 1.5],
                     offset=-0.6, spacing=14.0, clearance=0.6, facing="road", yaw_jitter=0)),
    "ped_signal": dict(
        category="traffic", title="Pedestrian signal post",
        desc="2.9 m post with a walk / stop head, countdown screen and push button.",
        res=1024, embed=512, lod1=None,
        scatter=dict(slots=["crossing"], density=dens(0.8, slum=0.3), along=[0.9, 1.6], offset=-0.5, spacing=4.0, clearance=0.4,
                     facing="road", yaw_jitter=0)),
    "street_name_sign": dict(
        category="signage", title="Street-name sign (two crossed blades)",
        desc="Pole with two crossed blades (Japanese + English street names) and a finial.",
        res=1024, embed=512, lod1=None,
        scatter=dict(slots=["corner"], density=dens(0.7, downtown=0.9, slum=0.4), along=[2.2, 3.5], offset=-0.5, spacing=8.0,
                     clearance=0.4, facing="road", yaw_jitter=0)),
    "bollard": dict(
        category="street_furniture", title="Steel bollard with LED ring",
        desc="0.95 m domed steel bollard, retro-reflective band and a cyan LED ring.",
        res=512, embed=512, lod1=None,
        scatter=dict(slots=["curb", "corner"], density=dens(2.5, downtown=5.0, luxury=5.0, commercial=3.0, slum=0.5, industrial=1.5),
                     offset=-0.35, spacing=1.6, clearance=0.25, facing="road", yaw_jitter=0, along=[0.3, 4.0], cluster=[2, 5], cluster_radius=1.6, cluster_line=True)),
    "guard_rail": dict(
        category="traffic", title="W-beam guard rail (4 m, tileable)",
        desc="Galvanised W-beam on two posts at 2 m, 4 m long: chain them end to end along +X.",
        res=1024, embed=512, lod1=None, tile_length=4.0,
        scatter=dict(slots=["roadside", "median"], density=dens(2.0, industrial=8.0, residential=3.0, luxury=0.0, market=0.0), offset=-0.3,
                     spacing=0.0, clearance=0.0, facing="along", yaw_jitter=0, run=True)),
    "crash_barrier": dict(
        category="traffic", title="Water-filled plastic crash barrier",
        desc="1.8 m interlocking water-filled barrier (red or white).",
        res=1024, embed=512, lod1=None, tile_length=1.8,
        scatter=dict(slots=["roadside"], density=dens(1.5, industrial=4.0, slum=3.0, luxury=0.0), offset=0.6, spacing=8.0,
                     clearance=0.2, facing="along", yaw_jitter=3, cluster=[2, 6], cluster_radius=0.0, cluster_line=True, run=True)),
    "jersey_barrier": dict(
        category="traffic", title="Concrete jersey barrier (checkpoint)",
        desc="3 m precast concrete barrier with lifting loops, reflectors, a MERIDIAN checkpoint stencil and resistance tags.",
        res=1024, embed=512, lod1=None, tile_length=3.0,
        scatter=dict(slots=["roadside", "median"], density=dens(1.0, industrial=4.0, slum=3.0, downtown=2.0, luxury=0.0), offset=0.4,
                     spacing=10.0, clearance=0.3, facing="along", yaw_jitter=2, cluster=[1, 4], cluster_line=True, run=True)),
    "traffic_cone": dict(
        category="traffic", title="Traffic cone",
        desc="70 cm cone with two reflective collars on a rubber base.",
        res=512, embed=256, lod1=None,
        scatter=dict(slots=["roadside", "curb"], density=dens(0.8, industrial=3.0, slum=2.0, luxury=0.0), offset=0.5, spacing=3.0,
                     clearance=0.3, facing="random", yaw_jitter=180, cluster=[1, 5], cluster_radius=1.5)),
    "steam_vent": dict(
        category="utility", title="Manhole steam stack",
        desc="Orange-and-white steam chimney over a manhole: put a steam particle emitter at Socket_Steam.",
        res=512, embed=512, lod1=None,
        scatter=dict(slots=["road"], density=dens(0.02, downtown=0.04, commercial=0.04, industrial=0.06, luxury=0.0), spacing=30.0,
                     clearance=1.5, facing="random", yaw_jitter=180)),
    # ------------------------------------------------------------------ street furniture
    "bus_stop": dict(
        category="street_furniture", title="Bus shelter with lightbox ad",
        desc="4 m shelter: glass back wall, double-sided backlit ad box (Noctis / Dreamlink / MERIDIAN / Hoshikawa ads as variants), "
             "bench with anti-sleep dividers, route flag, timetable screen, LED strip under the roof.",
        res=2048, embed=1024, lod1=0.4,
        scatter=dict(slots=["curb"], density=dens(0.4, downtown=0.6, commercial=0.6, residential=0.4, slum=0.2, market=0.2, luxury=0.4),
                     offset=-0.9, spacing=120.0, clearance=2.6, facing="road", yaw_jitter=0)),
    "bench": dict(
        category="street_furniture", title="Anti-sleep bench",
        desc="1.8 m cast-iron and slat bench with a centre divider (so nobody can lie on it).",
        res=1024, embed=512, lod1=0.5,
        scatter=dict(slots=["walk", "frontage", "plaza"], density=dens(1.0, luxury=2.0, residential=1.5, downtown=1.5, industrial=0.2,
                     market=0.5), offset=0.6, spacing=10.0, clearance=1.1, facing="road", yaw_jitter=0)),
    "fire_hydrant": dict(
        category="utility", title="Fire hydrant",
        desc="Cast-iron pillar hydrant with two hose outlets and a pumper nozzle (red, yellow, Hoshikawa teal).",
        res=512, embed=512, lod1=None,
        scatter=dict(slots=["curb"], density=dens(0.8), offset=-0.45, spacing=60.0, clearance=0.5, facing="road", yaw_jitter=10)),
    "parking_meter": dict(
        category="street_furniture", title="Pay-by-score parking meter",
        desc="Post-mounted meter with a screen (PAY BY SCORE), card reader and solar cap.",
        res=512, embed=512, lod1=None,
        scatter=dict(slots=["curb"], density=dens(1.5, downtown=3.0, commercial=2.5, slum=0.0, market=0.5), offset=-0.45,
                     spacing=7.0, clearance=0.35, facing="road", yaw_jitter=0, cluster=[1, 3], cluster_radius=0.0, cluster_line=True)),
    "data_kiosk": dict(
        category="street_furniture", title="MERIDIAN data kiosk",
        desc="2.3 m monolith: citizen-score touch screen, eye camera ring, palm scanner, halo LED; ad on the back. Variants change the screen.",
        res=2048, embed=1024, lod1=0.5,
        scatter=dict(slots=["walk", "frontage", "plaza", "corner"], density=dens(0.4, downtown=1.0, commercial=0.6, luxury=0.4, slum=0.1),
                     offset=0.5, along=[3.5, 5.0], spacing=45.0, clearance=1.2, facing="road", yaw_jitter=0)),
    "phone_kiosk": dict(
        category="street_furniture", title="Public line booth",
        desc="Hooded wall-less payphone on two legs (PUBLIC LINE - MONITORED), handset, keypad, small screen, light under the hood.",
        res=1024, embed=512, lod1=0.5,
        scatter=dict(slots=["frontage", "walk"], density=dens(0.4, slum=0.8, residential=0.6, luxury=0.0), offset=0.35, spacing=40.0,
                     clearance=0.9, facing="road", yaw_jitter=0)),
    "cctv_pole": dict(
        category="utility", title="MERIDIAN surveillance pole",
        desc="5.5 m pole, cross-arm with three bullet cameras (red eye LEDs) and a dome camera, junction box with a MERIDIAN plate, solar panel.",
        res=1024, embed=512, lod1=0.5,
        scatter=dict(slots=["corner", "curb", "plaza"], density=dens(0.5, downtown=1.5, commercial=0.8, slum=0.6, luxury=0.8), offset=-0.5,
                     along=[3.0, 6.0], spacing=35.0, clearance=0.6, facing="road", yaw_jitter=25)),
    "drone_mast": dict(
        category="utility", title="Hoshikawa Aerial drone charging mast",
        desc="7.5 m mast with a hexagonal charging pad (LED rings, red beacon) and a parked courier drone; base cabinet with hazard stripes.",
        res=2048, embed=1024, lod1=0.45,
        scatter=dict(slots=["plaza", "rooftop", "curb"], density=dens(0.05, downtown=0.15, industrial=0.15, commercial=0.08), offset=-0.8,
                     spacing=80.0, clearance=1.5, facing="random", yaw_jitter=180)),
    # ------------------------------------------------------------------ signs / emissive
    "holo_pylon": dict(
        category="signage", title="Holographic ad pylon",
        desc="4 m triangular pylon of see-through emissive holo panels on an LED plinth; each face shows an ad (variants swap them).",
        res=2048, embed=1024, lod1=0.5,
        scatter=dict(slots=["plaza", "walk", "corner"], density=dens(0.2, downtown=0.6, commercial=0.8, luxury=0.5, market=0.4, slum=0.0),
                     offset=0.2, along=[4.0, 6.0], spacing=40.0, clearance=1.3, facing="random", yaw_jitter=180)),
    "neon_arrow_sign": dict(
        category="signage", title="Marquee arrow sign (wall-mounted)",
        desc="Arrow-shaped sign on a wall bracket: neon border, chase bulbs and a lit text panel (HOTEL / BAR / PACHINKO / CAPSULES variants). "
             "Origin on the wall at the bracket's bottom; the sign sticks out along +Z.",
        res=1024, embed=1024, lod1=None, mount="wall",
        scatter=dict(slots=["facade"], density=dens(0.8, commercial=2.0, market=2.0, slum=1.0, downtown=0.3, luxury=0.2, industrial=0.2),
                     mount_height=[3.2, 5.5], offset=0.0, spacing=12.0, clearance=1.0, facing="road", yaw_jitter=0)),
    "vending_machine": dict(
        category="clutter", title="Vending machine (drinks / Noctis memory capsules / instant ramen)",
        desc="1.0 x 0.75 x 1.85 m machine, backlit product window behind glass, lit header, selection buttons and a card panel.",
        res=2048, embed=1024, lod1=0.5,
        scatter=dict(slots=["frontage", "alley"], density=dens(1.5, commercial=3.0, market=3.0, residential=2.0, slum=2.0, luxury=0.3),
                     offset=0.4, spacing=6.0, clearance=0.75, facing="road", yaw_jitter=0, cluster=[1, 3], cluster_radius=0.0, cluster_line=True)),
    # ------------------------------------------------------------------ clutter
    "trash_bag_pile": dict(
        category="clutter", title="Trash bag pile",
        desc="Four tied bin bags (black and blue).",
        res=512, embed=512, lod1=None,
        scatter=dict(slots=["frontage", "alley", "curb"], density=dens(2.0, slum=8.0, market=6.0, industrial=3.0, luxury=0.0, downtown=0.5),
                     offset=0.4, spacing=4.0, clearance=0.8, facing="random", yaw_jitter=180)),
    "trash_bin": dict(
        category="clutter", title="Twin-slot street bin (BURNABLE / CANS)",
        desc="Hoshikawa Sanitation bin with two labelled slots.",
        res=1024, embed=512, lod1=None,
        scatter=dict(slots=["walk", "curb", "plaza"], density=dens(1.0, downtown=1.5, luxury=1.5, slum=0.3), offset=-0.6, spacing=30.0,
                     clearance=0.6, facing="road", yaw_jitter=0)),
    "cardboard_boxes": dict(
        category="clutter", title="Cardboard box stack",
        desc="Three taped boxes with Hoshikawa Logistics print and FRAGILE labels.",
        res=1024, embed=512, lod1=None,
        scatter=dict(slots=["frontage", "alley"], density=dens(1.0, market=4.0, slum=4.0, industrial=3.0, luxury=0.0, downtown=0.2),
                     offset=0.4, spacing=5.0, clearance=0.7, facing="random", yaw_jitter=25)),
    "pallet": dict(
        category="clutter", title="Wooden pallet",
        desc="1.2 x 0.8 m pallet; stack them or lean them on walls.",
        res=512, embed=512, lod1=None,
        scatter=dict(slots=["alley", "frontage"], density=dens(0.5, industrial=4.0, market=2.0, slum=2.0, luxury=0.0, downtown=0.0),
                     offset=0.6, spacing=4.0, clearance=0.8, facing="random", yaw_jitter=20, cluster=[1, 3], cluster_radius=0.0, stack=True)),
    "crate_stack": dict(
        category="clutter", title="Crate stack (Noctis Biologics)",
        desc="Two wooden shipping crates with stencils and a plastic crate on top.",
        res=1024, embed=512, lod1=None,
        scatter=dict(slots=["alley", "frontage"], density=dens(0.5, industrial=3.0, market=2.0, slum=1.5, luxury=0.0), offset=0.6,
                     spacing=6.0, clearance=0.9, facing="random", yaw_jitter=20)),
    "bicycle": dict(
        category="clutter", title="City bicycle",
        desc="Step-through city bike on its kickstand with a front basket.",
        res=1024, embed=512, lod1=0.4,
        scatter=dict(slots=["frontage", "curb", "alley"], density=dens(1.0, residential=3.0, market=2.0, slum=1.5, downtown=0.5, luxury=0.3),
                     offset=0.5, spacing=2.0, clearance=0.4, facing="along", yaw_jitter=8, cluster=[1, 4], cluster_radius=0.0, cluster_line=True, cluster_gap=0.7)),
    "scooter": dict(
        category="clutter", title="Hoshikawa Ride share e-scooter",
        desc="Rental kick scooter on its stand, with a display and a scan plate.",
        res=1024, embed=512, lod1=0.5,
        scatter=dict(slots=["curb", "frontage", "plaza"], density=dens(0.8, downtown=1.5, commercial=1.5, slum=0.3), offset=-0.7,
                     spacing=1.0, clearance=0.35, facing="random", yaw_jitter=60, cluster=[1, 3], cluster_radius=0.0, cluster_line=True, cluster_gap=0.55)),
    "ramen_cart": dict(
        category="food", title="Ramen yatai cart",
        desc="Wooden two-wheel cart: counter, roof on posts, noren curtains, red paper lanterns (lit), stools and a steaming pot.",
        res=2048, embed=1024, lod1=0.45,
        scatter=dict(slots=["frontage", "alley", "plaza"], density=dens(0.1, market=1.2, commercial=0.4, slum=0.4, residential=0.2, downtown=0.0, luxury=0.0),
                     offset=1.4, spacing=25.0, clearance=1.8, facing="road", yaw_jitter=0)),
    "skewer_stall": dict(
        category="food", title="Yakitori skewer stall",
        desc="Market stall: canopy on poles, charcoal grill with glowing coals and skewers, string lights, menu board, crates and a gas bottle.",
        res=2048, embed=1024, lod1=0.45,
        scatter=dict(slots=["frontage", "plaza", "alley"], density=dens(0.1, market=1.5, commercial=0.3, slum=0.4, downtown=0.0, luxury=0.0),
                     offset=1.4, spacing=12.0, clearance=1.8, facing="road", yaw_jitter=0)),
    "cable_bundle": dict(
        category="utility", title="Overhead cable bundle (8 m span)",
        desc="Four sagging cables with clamps and a hanging junction box, spanning 8 m between two walls at ~5.5 m. Scale X to the gap.",
        res=512, embed=512, lod1=None, span=8.0,
        scatter=dict(slots=["alley_span"], density=dens(4.0, slum=10.0, market=8.0, commercial=5.0, luxury=0.0, downtown=1.0),
                     spacing=3.0, clearance=0.0, facing="along", yaw_jitter=0, mount_height=[4.5, 7.5])),
    "ac_unit": dict(
        category="rooftop", title="Air-con condenser on a stand",
        desc="Split-system condenser with a perforated fan grille on a galvanised stand, refrigerant pipes and drain hose.",
        res=1024, embed=512, lod1=None,
        scatter=dict(slots=["rooftop", "alley"], density=dens(1.2, residential=2.0, slum=2.0, market=2.0), offset=0.35, spacing=1.2,
                     clearance=0.6, facing="random", yaw_jitter=0, cluster=[1, 4], cluster_radius=0.0, cluster_line=True, cluster_gap=0.95)),
    "satellite_dish": dict(
        category="rooftop", title="Satellite dish on a ballast mount",
        desc="1.2 m dish (Dreamlink uplink) on a non-penetrating ballast frame.",
        res=1024, embed=512, lod1=0.5,
        scatter=dict(slots=["rooftop"], density=dens(1.0, residential=2.0, slum=2.5), spacing=4.0, clearance=1.0, facing="random", yaw_jitter=40)),
    "water_tank": dict(
        category="rooftop", title="Rooftop water tank",
        desc="Wooden stave tank with steel hoops and a conical roof on a steel stand, with a ladder.",
        res=2048, embed=1024, lod1=0.4,
        scatter=dict(slots=["rooftop"], density=dens(0.3, residential=0.5, slum=0.6, industrial=0.5, luxury=0.0), spacing=20.0, clearance=2.0,
                     facing="random", yaw_jitter=180)),
    "puddle_decal": dict(
        category="decal", title="Puddle decals (3 shapes)",
        desc="Flat alpha-blended puddles: nodes Puddle_S (1.2 m), Puddle_M (2.2 m), Puddle_L (3.2 m). Lay 1-2 cm above the ground, no shadows.",
        res=1024, embed=1024, lod1=None,
        scatter=dict(slots=["road", "plaza"], density=dens(0.25, slum=0.6, industrial=0.5, market=0.4, luxury=0.1), spacing=6.0, clearance=0.0,
                     facing="random", yaw_jitter=180, decal=True)),
    # ------------------------------------------------------------------ nature-lite
    "planter": dict(
        category="nature", title="Concrete planter with shrubs",
        desc="1.6 m concrete planter, soil, clipped shrubs and a Hoshikawa Parks plate.",
        res=1024, embed=512, lod1=0.5,
        scatter=dict(slots=["walk", "frontage", "plaza"], density=dens(0.6, luxury=3.0, downtown=1.5, residential=1.0, slum=0.0, industrial=0.0),
                     offset=0.6, spacing=8.0, clearance=1.0, facing="road", yaw_jitter=0)),
    "street_tree": dict(
        category="nature", title="Stylised street tree in a grate",
        desc="5 m tree: tapered trunk, three branches, clumped canopy, iron tree guard and grate.",
        res=1024, embed=512, lod1=0.35,
        scatter=dict(slots=["curb", "plaza"], density=dens(0.8, residential=2.0, luxury=1.0, downtown=1.0, slum=0.0, industrial=0.0, market=0.3),
                     offset=-0.9, spacing=9.0, clearance=1.2, facing="random", yaw_jitter=180)),
    "palm_tree": dict(
        category="nature", title="Palm (luxury island)",
        desc="7 m curved palm with ringed trunk, 11 fronds, coconuts and a ground uplighter (Light_Uplight).",
        res=1024, embed=512, lod1=0.35,
        scatter=dict(slots=["curb", "plaza", "frontage"], density=dens(0.0, luxury=3.0), offset=-1.0, spacing=7.0, clearance=1.5,
                     facing="random", yaw_jitter=180)),
}


def names():
    return list(PROPS)
