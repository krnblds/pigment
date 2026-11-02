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
    not an open context menu's parent palette state, and it doesn't clear the
    command palette query.

## Consistency

20. **Primary buttons in panels** ("Use the decal tool", "Export for Blender") compete
    with the top-bar Export, contrary to "one primary per screen area".
21. **Settings dialog** mixes a prop label + segmented control with slider rows of a
    different label width; there's no density option.
22. **Light theme** shares radii and shadows designed for dark; fine, not a priority.

---

## Status after the pass

(see below; updated when the pass landed)
