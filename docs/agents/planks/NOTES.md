# Planks: procedural wood floors

`GeneratorKind::Planks` (GPU id 21, `gn_planks` in `gen_ground.wgsl`) cuts the
surface into planks and grows the wood of each plank, so a wood floor is a
stack of ordinary fill layers that every slider in the layer panel can change.

## Layouts (`variant`, `ground::PLANK_LAYOUTS`)

| Layout | Geometry |
|---|---|
| `boards` | rows along x; board ends at `i * length`, each pushed up to +-35 % of a length, so lengths vary and the joints stagger row to row |
| `herringbone` | slats of width 1 and length n (`length_ratio`, rounded): H(k, j) covers [k + jn, k + jn + n) x [k - jn, k - jn + 1), V(k, j) covers [k + jn, k + jn + 1) x [k - jn + 1, k - jn + 1 + n); a texel finds its slat by testing three j around (x - y) / 2n |
| `chevron` | columns of slats cut at 45 degrees, alternate columns mirrored so they meet in a point |
| `basketweave` | square blocks of n slats, alternate blocks turned 90 degrees |

Everything is in metres on the surface plane (`wx_surface`), shifted by part of
a plank so joints don't line up with mesh or tile edges. In tile mode the plank
width / length snap so a whole number of layout periods fits the tile, and
plank ids wrap (herringbone: the lattice repeats by (k, j) + (P/2, P/2n) and
(P, 0) slats), so tiles stay seamless.

## Outputs (`output` / `extra[3]`, `ground::PLANK_OUTPUTS`)

- `surface`: 1 on plank faces, 0 in the joints (anti-aliased over the texel footprint).
- `joints`: the complement.
- `latewood`: growth-ring density and knots, times `amount`.
- `pores`: open earlywood vessels, times `amount`.

Side channels for fill layers: `g_prof` is the plank profile (a 1.5 mm eased
edge, slight cupping, each plank a touch higher or lower), so `height_profile`
gives real relief; `g_inst` is a random per plank, so `jitter` tones each plank.

## The wood

Each plank is a board sawn from its own log. Growth rings are cylinders around
the pith: radius = |(v - v0, depth + tilt * u)| plus slow wander. Flat-sawn
boards (`flat_sawn` near 1) are cut close to the pith with the log axis tilted
against the face, which shows nested arches; quarter-sawn ones (near 0) sit far
from it and show straight stripes. Ring spacing and the latewood share vary
year to year; latewood darkens gradually and ends at a sharp boundary. Knots (at
most one per 0.7 m of board) push the rings aside and have a dark core and rim.
Long colour streaks run along each board.

Detail finer than a texel is filtered, not aliased: `gn_footprint` measures the
metres per texel from the position bake (ignoring neighbours off the image, off
the mesh or across a UV seam) and `gn_filter` fades rings and pores to their
average once a cycle is shorter than two texels. A 4 m floor at 2048 px keeps
the rings and loses the pores; at 4096 px the rings are crisp.

## Shared layout

A floor's layers each read a different output of one layout, so editing the
layout on any of them (panel or `update_layer` with a `mask`) copies it to the
other planks layers in the same folder: `Document::sync_planks` copies all
settings but the output and amount. Changing plank width is one edit.

## Parameters

| Slot | Planks meaning | MCP name |
|---|---|---|
| `noise_scale` | planks per metre across (1 / width) | `scale` |
| `noise_amount` | grain waviness | `waviness` |
| `ao_influence` | joint width, metres | `joint_width` |
| `curvature_weight` | plank length / width | `length_ratio` |
| `extra[0]` | growth rings per cm | `rings_per_cm` |
| `extra[1]` | flat-sawn figure 0..1 | `flat_sawn` |
| `extra[2]` | knots 0..1 | `knots` |
| `extra[3]` | output | `output` |

## Smart materials

`Document::wood_floor(WoodFloor)` builds the stack: joints, wood (profile
height, per-plank jitter), latewood, pores, lacquer, worn lacquer in the
walking lanes, scuffs, grime. Used by Oak floorboards, Dark walnut floor,
Herringbone parquet, Chevron parquet and Basketweave parquet.

## Tests

`ground_tests.rs`: `planks_tile_seamlessly_in_every_layout` (seams no worse
than the interior in colour and normal, joints a thin network) and
`planks_layers_share_their_layout` (an `update_layer` moves every layer to the
new layout and keeps each one's output).

## Known limits

- Pigment's viewport can show joint edges as dashed at grazing angles (normal
  map sampling); the exported maps and Blender renders are clean.
- No medullary ray flecks (quarter-sawn oak), no end grain, no stain bleeding.
