# UX audit: every screen, before the dark / compact pass

Walked every screen offscreen with the UI harness
(`cargo test -p pigment --release design_shots -- --ignored`, see
`crates/app/src/app/design_shots.rs`): welcome, Simple mode, Advanced mode, every
dock panel on its own, the decal tool, the layer context menu, the export, settings
and new-project dialogs, the command palette (empty and filtered), the shortcut
sheet, toasts and the light theme. Findings are grouped by kind and ranked by how
often they get in the way. **Status** is filled in after the pass (see the bottom).

## Visual density and hierarchy

1. **Chrome competes with the model.** Panels (#1B1D21) and raised cards (#23262B)
   are close to the viewport's grey, the orange accent is used for slider fills,
   tab underlines, the selected tool, selected rows, primary buttons in panels and
   the history cursor at once, so nothing reads as *the* selection.
2. **Everything is big.** 28 pt controls, 44 pt layer rows, 30 pt tab bars, a 60 pt
   tool rail with labels and 12 pt panel padding: the Texturing layout shows four
   and a half layers, and the Properties panel needs scrolling for a single fill.
3. **Rounded, card-heavy surfaces.** 6–14 pt radii, cards inside panels inside
   rounded tabs, and large shadows on menus and dialogs make it look like a web
   page rather than a tool.
4. **Two slider styles side by side.** `slider_row` (slider + boxed value) and raw
   `egui::Slider` (slider + bare value, other column widths) in the same panel
   (Properties: Opacity vs Roughness / Metallic / Height). The circle handles are
   large, labels and values are far apart, and the value is not where you look.
5. **Tool options bar is spread out.** Each slider takes 205 pt; with four brush
   sliders the paint-target message is pushed to the far right edge, and the values
   sit 60–80 pt from their labels.

## Clarity and labels

6. **Truncated names without an ellipsis** in layer rows ("Rust in crevic").
7. **The layers hint refers to a "⠿" handle glyph that the font can't draw**
   (renders as a box).
8. **"Layer / Mask (none)" tabs** in Properties look like plain text; it is not
   obvious they switch what the panel edits.
9. **The paint target ("Painting the mask of Grunge")** lives at the far right of the
   tool options bar, far from where you paint.
10. **Viewport hint pill** ("Left-drag to paint · Right-drag to orbit…") floats over
    the model's bottom-left corner and covers it; it is the only place mouse
    controls are explained.

## Too many clicks / missing affordances

11. **Layer context menu is thin:** no Rename, Hide/Show, Lock, Add mask, no icons, no
    shortcuts, and it is clipped at the panel edge.
12. **No context menus on parts or decals** (only on layers and dock tabs).
13. **Collapsible sections forget their state**; most sections can't collapse at
    all, so long panels (Properties, Mask & generators, Decals) always need scrolling.
14. **No quick search in the decal browser or the foliage library**, only folders.
15. **Undo history is a list of grey labels**: no step numbers, no clear "you are
    here", undone steps are only slightly dimmer.
16. **Menus lack shortcuts for some actions** (Undo history panel, Settings, view
    modes), and tooltips on several icon buttons don't show their keys.

## Feedback

17. **Command palette fuzzy matching is loose:** "rus" ranks *Re-bake AO + curvature*
    and *Foliage brush* (scattered letters) above more relevant results, matched
    letters aren't highlighted, and an empty query shows an arbitrary first dozen
    rather than recent commands.
18. **Active tool indication in the viewport** is only the rail highlight and the
    cursor; nothing in the status area says what the mouse buttons will do *now*.
19. **Escape is inconsistent:** it closes the shortcut sheet and resets the tool, but
    the command palette keeps its old query when reopened, a search box can't be
    cleared from the keyboard, and dialogs have no visible close affordance.

## Consistency

20. **Primary buttons in panels** ("Use the decal tool", "Export for Blender") compete
    with the top-bar Export, contrary to "one primary per screen area".
21. **Settings dialog** mixes a prop label + segmented control with slider rows of a
    different label width; there's no density option.
22. **Light theme** shares radii and shadows designed for dark; fine, not a priority.

---

## Status after the pass

Fixed:

- **1–3 (chrome, density, cards):** new near-black, low-chroma palette (a test keeps
  every chrome colour's chroma <= 10 and the greys in the Blender range), Compact
  density by default (22 pt controls, 20 pt fields, 28 pt layer rows, 24 pt tabs, 8 pt
  padding) with a Comfortable option, radii 2–4 pt, short shadows. The accent is now
  only on the selection, the active tool, the active tab underline and the primary
  action; slider fills are neutral grey.
- **4–5 (sliders):** one Blender-style `DragField` everywhere (value inside the bar,
  drag / Shift fine / Ctrl snap / double-click to type / arrow ends). Raw `egui::Slider`
  is now rejected by the lint. The tool options bar uses drag fields with inline labels.
- **6:** names elide with an ellipsis; the full name and kind show on hover.
- **7:** the layers hint no longer refers to a glyph the font lacks.
- **8:** `tabs` have a hover fill and readable inactive labels.
- **9:** the paint target and the mask black / white switch (with its X key) sit right
  after the brush controls.
- **10, 18:** the hint pill is gone; the status bar shows the active tool's mouse and key
  hints with mouse glyphs (or the hovered control's), and a small chip in the viewport
  names the active tool. The tool rail shows each tool's key letter.
- **11:** the layer context menu has Rename, Duplicate, Group, Hide / Show, Lock,
  Move up / down, Into / out of folder and Delete, with icons and keys, the same
  `MenuItem` row everywhere. Double-click or F2 renames inline; Ctrl+D, Ctrl+G, H and
  Delete work while the pointer is over the panel.
- **12 (partly):** decal tiles have a right-click menu (stick it on, scatter copies).
- **13:** `collapsible` sections with small chevrons; open / closed state is remembered
  in `prefs.json` (also used by the brush, filter and export panels).
- **14:** quick search in the decal browser (across folders) and the foliage library.
- **15:** History has Undo / Redo buttons with keys, "step n of m", numbered steps, a
  "now" marker and "undone" tags.
- **16:** menus show keys for Settings (Ctrl+,), view modes (M); the shortcut sheet has
  Layers and Number-field sections.
- **17:** the palette's fuzzy match requires substrings or word-initial runs (no
  scattered letters), highlights matched letters, lists Recent first then groups on
  an empty query, scrolls, and supports Tab / PgUp / PgDn and click-outside.
- **19:** Esc clears a focused search box, closes the palette with its query reset;
  dialogs have a close button.
- **20:** "Use the decal tool", "Use the foliage brush" and "Bake from high poly" are
  secondary; panels keep at most one primary.
- **21:** Settings has a Density control next to Theme.

Left for later:

- Context menus on Parts rows and on library materials (12).
- Light theme is kept working and readable but not tuned to the same degree (22).
- `egui::DragValue` pairs (UV tiling, offsets, normal tilt) still use egui's own field,
  themed but without the fill bar.
- Drag-and-drop of library materials onto layers / parts in the viewport.
