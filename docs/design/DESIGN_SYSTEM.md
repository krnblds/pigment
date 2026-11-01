# Pigment design system

Code: `crates/app/src/app/design/` (`mod.rs` tokens and theme, `fonts.rs`, `icons.rs`,
`components.rs`, `gallery.rs`). Every screen is built from these tokens and components.
The test `design::tests::no_raw_styles_outside_design` fails the build if a screen
file (`ui.rs`, `tour.rs`, `welcome.rs`, `dialogs.rs`, `dock.rs`, `folders_ui.rs`,
`panels/*`) uses a raw `Color32::from_rgb/from_gray/...`, a named colour, or a
literal spacing, margin, radius or font size. Another test checks WCAG contrast
for every text role on every surface in both themes.

See it live: `pigment --design-gallery`.

| Dark | Light |
|---|---|
| ![gallery](gallery.png) | ![gallery light](gallery_light.png) |

## Principles

1. **Clarity for beginners.** Say what a thing does in plain words, next to it:
   tooltips have a title, a sentence and the shortcut. Empty states explain what
   would appear and offer the next action.
2. **Progressive disclosure.** Simple mode shows a material library, four tools, one
   weathering slider, lighting and Export. Advanced mode shows the full stack
   (folders, masks, generators, channels, variants). Rare options sit under
   "More options" headers.
3. **Direct manipulation.** Click a material and the model changes. Click a part to
   fill it. Click the surface to stick a decal. Drag a layer by its grip to move or
   nest it. Drag a panel tab to re-dock it.
4. **Beautiful defaults.** Materials ship with wear that follows the model's shape,
   lighting presets are one click, and exports go to a sensible folder without a
   file dialog.
5. **Never block.** Bakes, exports and autosaves run without freezing the window
   and report through toasts. Dialogs are modal only when a decision is needed.

## Tokens

### Colour roles (`design::Palette`)

| Role | Dark | Light | Use |
|---|---|---|---|
| `bg` | #111215 | #DEE1E6 | behind everything, viewport surround |
| `surface` | #1B1D21 | #F4F5F7 | panels, bars |
| `surface_raised` | #23262B | #FFFFFF | cards, rows, tabs |
| `surface_hover` | #2D3137 | #E8EBEF | hovered rows and buttons |
| `well` | #131518 | #EAECF0 | text fields, tracks |
| `overlay` | #24272D | #FFFFFF | menus, toasts, dialogs |
| `glass` | black 77% | white 84% | viewport HUD chips |
| `border` / `border_strong` | #33373E / #484D56 | #D4D8DE / #B2B8C1 | dividers / emphasis |
| `text` | #ECEEF1 | #16181C | primary text (>= 7:1) |
| `text_secondary` | #BABFC7 | #3E434B | labels (>= 4.5:1) |
| `text_muted` | #8C929C | #606771 | hints, captions (>= 3:1) |
| `text_disabled` | #5C626B | #A0A6AF | disabled |
| `accent` / `hover` / `pressed` | #F08A3C / #FFA058 / #D6742A | #D26216 / #E67222 / #B85410 | the one action colour |
| `accent_subtle` | #402B1C | #FBE2CD | selected rows, tabs |
| `on_accent` | #1A1006 | #FFFFFF | text on accent |
| `success` `warn` `danger` `info` | #4CC38A #F2B33D #F0605A #60AAF0 | #1A8C56 #B07000 #C8342E #1C70C8 | status |
| `focus` | #7DB7FF | #2470DC | keyboard focus ring |
| `selection` | #563820 | #F8D6BA | text selection |
| `scrim`, `shadow` | | | behind modals, elevation |

### Spacing (`design::space`)

`XXS 2 · XS 4 · SM 6 · MD 8 · LG 12 · XL 16 · XXL 24 · XXXL 32` points. Panel padding is `LG`,
items within a row `MD`, rows `SM`, sections `SM` above a caption, dialogs `XXL`.

### Radii and elevation

`radius::SM 4` (thumbnails, key caps) · `MD 6` (buttons, rows, fields) · `LG 10` (cards,
tiles, tabs) · `XL 14` (dialogs) · `PILL`.
`elevation(0)` flat · `1` subtle lift · `2` menus, popovers, toasts · `3` dialogs, palette.

### Type (`design::font`, `design::fonts`)

Inter (OFL) for the interface, JetBrains Mono (OFL) for numbers and file names; egui's
default fonts stay behind them for symbols. Files and licences: `crates/app/assets/fonts/`.

| Token | Size | Weight | Use |
|---|---|---|---|
| `DISPLAY` | 28 | SemiBold | welcome title |
| `HEADING` | 18 | SemiBold | dialog titles, layer name |
| `TITLE` | 15 | SemiBold | card titles |
| `BODY` | 13.5 | Regular | default |
| `SMALL` | 12 | Regular | labels, hints |
| `CAPTION` | 11 | SemiBold, upper case | section headers |
| `MONO` | 12.5 | JetBrains Mono | values, sizes, paths |

### Icons (`design::Icon`)

62 icons drawn as vectors on an 18 x 18 grid with a 1.6 pt stroke that scales with the
icon, 2 pt padding, round joins (`Icon::ALL`). Sizes: `icon::SM 14` (inline), `MD 18`
(tools, rows), `LG 24`, `XL 40` (empty states). An icon always has a text label or a tooltip.

### Motion (`design::motion`)

`FAST 0.08 s` (toggles), `NORMAL 0.16 s` (egui animation time, toasts sliding in),
`SLOW 0.28 s` (fades), `TOAST 4 s` on screen (errors 10 s). Easing `ease_out` (cubic)
and `ease_in_out`.

### Sizes (`design::size`)

Controls 28 pt (small 22), tools 36, layer rows 44, row thumbnails 32, library tiles 92,
tab bar 30, splitters 4, dialogs 520 wide.

## Components (`design::components`)

| Component | API | Notes |
|---|---|---|
| Buttons | `Btn::primary/secondary/ghost/danger(label).icon().shortcut().small()/large().selected().enabled().fill()` | one primary per screen area |
| Icon button | `IconBtn::new(icon, tip).shortcut().selected().enabled().size()` | tooltip shows the shortcut |
| Tool button | `tool_button(ui, icon, label, tip, shortcut, selected)` | the left tool rail |
| Toggle | `toggle(ui, &mut bool, label)` | animated switch |
| Segmented | `segmented(ui, &mut v, &[(value, icon, label)])` | wraps in narrow panels |
| Tabs | `tabs(ui, &mut v, &[(value, label)])` | underline style |
| Slider row | `slider_row(_ex)(ui, label, &mut f32, range, Unit, log, tip)` | slider + typed value field with unit (`Percent`, `Suffix(" m", 2)`) |
| Swatches | `swatch`, `paint_material_swatch`, `color_picker` | material swatch shows sheen, gloss, glow, see-through |
| Cards | `card`, `card_selectable`, `overlay_frame`, `glass_frame` | |
| Layer row | `layer_row(ui, &LayerRow, payload)` | grip (drag source), fold arrow, eye, thumbnail, name + kind, lock, mask thumbnail; `drop_zone_at` + `paint_drop_hint` for above / into / below |
| Tooltips | `tooltip_body`, `.rich_tip(title, body)` | title, sentence, key cap |
| Toasts | `Toasts::push / finish / show` | info, success, warn, error, progress (spinner until finished) |
| Modal | `modal(ctx, id, title, width, add)` | scrim, Esc / click-outside dismiss |
| Empty state | `empty_state(ui, icon, title, body, action)` | |
| Progress | `progress(ui, Some(frac) / None, label)`, `icons::spinner` | |
| Search field | `search_field(ui, &mut String, hint)` | icon + clear button |
| Command palette | `command_palette(ctx, &mut state, &[Command])` + `fuzzy_score` | Ctrl+K, arrows, Enter |
| Property grid | `prop_grid`, `prop_label(ui, label, tip)` | label column + control column |
| Asset tile | `asset_tile(_ex)(ui, w, img_h, texture, fallback, title, subtitle, selected)` | library, generators, decals, tile sets, samples |
| Key cap, badge | `kbd`, `badge` | |

States: every interactive component draws rest, hover (`surface_hover` / border strong),
pressed (`accent_subtle` or `accent_pressed`), selected (accent border or accent text),
keyboard focus (2 pt `focus` ring outside) and disabled (`text_disabled`, half-strength fill).

### Do and don't

- Do take colours from `pal(ui)` roles. Don't write `Color32::from_rgb` in a screen.
- Do use `space::*` steps. Don't use `add_space(5.0)`.
- Do give every icon-only button a tooltip (`IconBtn` requires one).
- Do put the most likely action in a primary button. Don't put two primaries side by side.
- Do explain an empty panel with `empty_state`. Don't leave it blank.
- Do report long work with a progress toast. Don't block the frame.
- Do show material colours with `srgb()` / swatches (they're data, not tokens).

## Layout grid of the main window

```text
┌ top bar 44: logo · File Edit View Window Help · [Simple|Advanced] · project ··· ↶ ↷ ⌘K ? · Send to Blender · Export ┐
├ tool options 40: current tool · size / strength (/ hardness / spacing) or decal mode, size, wear ··· paint target ┤
├ tool ┬ dock ──────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ rail │  left column (Advanced)  │  viewport (HUD: view chips, lighting, axis gizmo, hint)  │  right inspector      │
│ 60   │  Materials / Brush       │                                                          │  Layers               │
│      │  Decals / Parts / ...    ├──────────────────────────────────────────────────────────┤  Properties / Mask /  │
│      │                          │  bottom: History / Variants / Export                     │  Channels             │
├ status 30: message · job progress ································· texture size (· fps, tris, VRAM in Advanced) ┤
```

Simple mode's default ("Beginner") is the viewport plus a right column: Materials on top,
Weathering / Lighting / Export below.

## Docking panels

`dock.rs` is a small docking system (egui_dock has no release for egui 0.37). The window
is a tree of splits whose leaves hold tabbed panels.

- **Drag a tab** onto another leaf: the centre adds it as a tab, an edge (outer 22%) splits
  the leaf left / right / top / bottom. The drop zone is highlighted with an accent-tinted
  rectangle and a label ("Add Layers here" / "Split: Layers").
- **Drop a tab outside the dock**, or right-click it and choose *Float as window*, to float
  it. A floating panel has a *Dock* button to go back.
- **Close** a tab with its x; reopen it from **Window**. The viewport can't be closed.
- **Splitters** between leaves are 4 pt and turn accent when hovered or dragged.
- **Layouts**: Window > Layouts has the presets *Beginner*, *Painting*, *Texturing*
  (Advanced) and *Compact*, your saved layouts, *Save current layout as…* and *Reset
  layout*. Simple and Advanced mode each remember their own layout.
- **Persistence**: layouts are part of `prefs.json` (`<config>/pigment`), saved two seconds
  after a change and on exit; broken layouts are repaired on load (the viewport is
  restored, duplicates dropped).
- **Panels** are widget structs registered by `PanelId` in `panels/mod.rs` (`trait Panel`).
  Each keeps its own state (the library's search and category, the decal browser's
  folder, the parts filter), and its scroll position is stored per panel id. To add a
  panel: add a `PanelId`, implement `Panel`, register it in `Panels::new`.

Panels: Viewport, Materials, Weathering, Brush, Layers, Properties, Channels, Mask &
generators, Decals, Parts, Variants, Lighting, History, Export, Texture set & bake.

| Painting layout | Compact layout |
|---|---|
| ![painting](../agents/ui/layout_painting.png) | ![compact](../agents/ui/layout_compact.png) |
