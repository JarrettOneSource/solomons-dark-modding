# Native presentation, UI, fonts, controls, loader, and game-over art

## Scope

This document closes the static native-art pass for the presentation atlases
that are not owned by a particular enemy, item, projectile, or world object:

- `Fonts`;
- `UI`;
- `ControlPanel`;
- `Controls`;
- `Create`;
- `Loader`;
- `GameOver`.

It joins each generated atlas builder to its runtime singleton, concrete
record destinations, and native consumers. The lower-level file lookup,
decode, GPU upload, cache, and device-reset behavior is documented in
[native-asset-system.md](native-asset-system.md). The bundle byte grammar is
documented in [sprite-bundle-format.md](../../tools/sprite-bundle-format.md).
The higher-level screen and control ownership model remains in
[ui-engine-system-map.md](../ui-engine-system-map.md) and
[ui-binary-map.md](../ui-binary-map.md).

The record counts and wrapper metadata below come from
[`native-content-inventory.json`](native-content-inventory.json). Direct
compiled consumers come from
[`native-atlas-consumers.json`](native-atlas-consumers.json) and the vtable
join in [`native-asset-object-map.json`](native-asset-object-map.json).

## Static result at a glance

| Atlas | Builder | Singleton | Records | Static result |
| --- | ---: | ---: | ---: | --- |
| Fonts | `0x004EA3D0` | `0x008199A0` | 627 | Nine compiled bitmap-font wrappers are live; standalone record 0 is stock-dormant |
| UI | `0x004F3590` | `0x008199E4` | 113 | 107 records have compiled selections; records 35, 36, 38, 60, 67, and 83 are stock-dormant |
| ControlPanel | `0x004E7EF0` | `0x00819988` | 116 | Ordinary records 0, 4..5, and 8..23 plus the 92-glyph wrapper are live; ordinary records 1..3 and 6..7 are stock-dormant |
| Controls | `0x004E84E0` | `0x0081998C` | 4 | Control-scheme picker selects records 0, 2, or 1; record 3 is stock-dormant |
| Create | `0x004E8680` | `0x00819990` | 24 | Create-wizard flow consumes every record except stock-dormant record 8 |
| Loader | `0x004EC1F0` | `0x008199BC` | 5 | All five records are constructed and released but stock-dormant; the renderer uses primitives |
| GameOver | `0x004EA650` | `0x008199A4` | 3 | Game-over renderer consumes records 0 and 1; record 2 is stock-dormant |

"Stock-dormant" means the exhaustive singleton-xref, literal-destination, and
instruction-level register trace found no compiled record selection. It does
not mean a loader could not address the parsed descriptor through a new hook.

## Bitmap-font ABI

Fonts are not loaded as an operating-system font and are not inferred from
the PNG. Each font is compiled into the bundle as:

1. a three-float header;
2. a finite kerning-pair table;
3. a finite glyph-ID table;
4. one sprite record per declared glyph.

The atlas builder passes that metadata into a large fixed runtime wrapper.
Text rendering selects the wrapper first, looks up a character by its numeric
glyph ID, applies the wrapper's kerning data, and draws the corresponding
sprite. A replacement therefore has to preserve the font wrapper ABI as well
as the PNG dimensions and bundle sprite geometry. Merely adding a glyph to a
PNG cannot make it addressable.

### `Fonts` wrapper inventory

`Bundle_Fonts` contains one ordinary record followed by nine font wrappers.
All nine wrappers have compiled consumers. Ordinary record 0 is the only
stock-dormant record.

| Group | Records | Runtime destination | Header | Kerning pairs | Glyphs | Proved consumer role |
| ---: | ---: | ---: | --- | ---: | ---: | --- |
| 0 | `1..92` | `+0x00FC` | `[13, 3, 28]` | 58 | 92 | Small/body UI text used broadly across controls and gameplay presentation |
| 1 | `93..184` | `+0x04D530` | `[16, 4, 28]` | 105 | 92 | Medium UI text used broadly across menus and panels |
| 2 | `185..215` | `+0x09A964` | `[20, 5, 28]` | 53 | 31 | Restricted punctuation and uppercase face used by specialized presentation |
| 3 | `216..307` | `+0x0E7D98` | `[24, 6, 28]` | 210 | 92 | Menu/dialog face, including `GameOver` and Dark Cloud screens |
| 4 | `308..349` | `+0x1351CC` | `[40, 10, 28]` | 132 | 42 | Large headings used by create, main-menu header, Hall of Fame, and control-scheme picker |
| 5 | `350..375` | `+0x182600` | `[14, 4, 28]` | 13 | 26 | Uppercase-only face used by skill/level-up presentation |
| 6 | `376..442` | `+0x1CFA34` | `[24, 5, 28]` | 1,043 | 67 | Game-slot or belt-adjacent presentation rooted at `0x005D2520` |
| 7 | `443..534` | `+0x21CE68` | `[10, 3, 28]` | 1 | 92 | Timeline text used by `TimelineExecutor_Tick` (`0x004DDB00`) |
| 8 | `535..626` | `+0x26A29C` | `[10, 3, 28]` | 1 | 92 | Belt-button text rooted at `0x005D3E10` |

Groups 0, 1, 3, 7, and 8 cover the general glyph IDs `33..91`, `93..123`,
and `125..126`. Group 2 covers `33`, `39..41`, `58`, and uppercase `65..90`.
Group 4 covers selected punctuation, digits, and uppercase. Group 5 is exactly
uppercase `65..90`. Group 6 covers selected punctuation, digits, uppercase,
and lowercase. The full glyph and kerning tables are preserved in the content
inventory rather than duplicated here.

The role labels above are consumer anchors, not inferred typeface names. Where
the binary does not expose a source font name, this work does not invent one.

### `ControlPanel` embedded font

`Bundle_ControlPanel` has 24 ordinary sprite records and then a separate
92-glyph font wrapper at records `24..115`:

- runtime wrapper destination `+0x0438`;
- header `[14, 4, 29]`;
- 39 kerning pairs;
- general glyph IDs `33..91`, `93..123`, and `125..126`.

The direct-record consumer mapper intentionally does not expand a font wrapper
into 92 independent sprite xrefs. Consequently records `24..115` appearing in
a direct-record "unmapped" list does **not** mean they are unused: their live
consumer is the wrapper itself.

## Shared `UI` atlas and screen ownership

The 113-record `UI` atlas is the shared presentation vocabulary used across
multiple screen owners. It does not own the current screen state. The native
ownership stack is:

```text
active Bundle/screen owner
        |
        v
screen-specific build/tick/render code
        |
        +--> shared widget/control builders
        |
        +--> Fonts wrapper selection
        |
        +--> fixed UI sprite record selection
        v
screen-space render context DAT_00B401A8
        v
low-level text, sprite, and primitive drawing
```

The current active-bundle work, widget constructors, layout fields, menu
labels, and semantic `sd.ui` seams are documented in the two UI maps linked at
the top. For art replacement, the important distinction is that `UI.bundle`
provides fixed sprite descriptors while a separate screen object supplies
behavior, state, layout, and actions.

### Directly anchored `UI` records

The consumer join found 85 functions that reference the `UI` singleton. Of
those, 58 map literal singleton-relative destinations to 66 records. Useful
semantic anchors include:

| Record(s) | Consumer evidence |
| ---: | --- |
| `18` | `MainMenu_Render` (`0x00598780`) |
| `20`, `30`, `31`, `33`, `42`, `58`, `66` | `DarkCloudBrowser_Render` (`0x00594FC0`) |
| `21` | `SpellPicker_Render` (`0x004FA460`) |
| `43` | `InventoryHint_Render` (`0x005D08C0`) |
| `101..102` | Main-menu headers and shared panels, including `0x005A0960` |
| `103..104` | Labeled and unlabeled control renderers (`0x005C65A0`, `0x005C6A50`) |
| `105..106` | Reused controls and dialog/panel presentation |
| `107..110` | `UiPanel_Render` and other panel renderers |
| `111..112` | Shared controls rooted at `0x00565B40` |
| `86..89` | Shared control render paths |

The exact many-to-many function join is machine-readable in
`native-atlas-consumers.json`; this table names only strong anchors rather
than assigning speculative semantics to every visual fragment.

### `UI` decompiler residual and machine-code closure

The following 47 records have no literal-destination mapping in the compiled
singleton-xref pass:

```text
1, 4, 6..7, 9..11, 13..14, 16..17, 22, 24, 26..29,
34..36, 38..41, 47..48, 50, 52..57, 60, 63..64, 67..68,
70..71, 80..83, 98..100
```

That list is a limitation of the decompiler-source join, not a retail unused
list. Several native calls have no recovered prototype, so Ghidra omits the
ECX `thiscall` argument from pseudocode even though the disassembly loads the
`UI` singleton and adds the exact sprite offset immediately before the call.
For example:

- `0x005C876B -> 0x005C8777` selects record 81 at `+0x3E3C`;
- `0x005C87ED -> 0x005C87FA` selects record 82 at `+0x3F00`;
- `0x005D7950 -> 0x005D7961` stores record 47 at `+0x2434` into a child
  control, and `0x005D7A5C -> 0x005D7A6D` does the same for record 48;
- `BeltButton` at `0x005D3E10` selects the record-98..100 vector owner at
  `+0x40C8`, closing the three mouse-button images.

`tools/ghidra-scripts/trace_singleton_register_offsets.py` follows these
register-derived fields directly in machine code. It proves 41 of the 47
decompiler-residual records are live:

```text
1, 4, 6..7, 9..11, 13..14, 16..17, 22, 24, 26..29,
34, 39..41, 47..48, 50, 52..57, 63..64, 68, 70..71,
80..82, 98..100
```

The recovered consumers span `InventoryGrid`, `InventoryScreen`,
`DarkCloudSwipebox`, `DarkCloudRating`, `Game`, `BeltButton`, the Hall of
Fame, skill presentation, and shared panel/control renderers. The six actual
retail-dormant records are:

| Record | Contact-sheet appearance | Static proof |
| ---: | --- | --- |
| `35` | thin gold bar | no singleton-derived field or subfield access outside builder/teardown |
| `36` | thin gold bar variant | same |
| `38` | skull | same |
| `60` | dark rounded square | same |
| `67` | gray bar | same |
| `83` | small dot | same |

The only co-occurring `+0x1D50` constants outside teardown belong to the
`Bonedit` singleton (`0x0081997C`), not `UI`; disassembly at `0x004D738C` and
`0x005D3B6F` makes that alias distinction explicit. Thus all 113 `UI` records
now have either a compiled consumer or a proved dormant classification.

## `ControlPanel`: editor and reusable controls

The `ControlPanel` name is easy to confuse with the gamepad scheme picker, but
its consumer population is primarily the boneyard/editor `CPanelControl_*`
family and related editing panels. The ordinary record layout is:

- inline records 0..7 at the standard `0xC4` stride;
- eight two-record arrays:
  - `8..9` at `+0x065C`;
  - `10..11` at `+0x066C`;
  - `12..13` at `+0x067C`;
  - `14..15` at `+0x068C`;
  - `16..17` at `+0x069C`;
  - `18..19` at `+0x06AC`;
  - `20..21` at `+0x06BC`;
  - `22..23` at `+0x06CC`.

Direct native consumers map records `0`, `4`, `5`, and all arrays `8..23`.
Ordinary records `1..3` and `6..7` are stock-dormant. Records
`24..115` belong to the live font wrapper described above and are not dormant
records.

## `Controls`: control-scheme picker

`ControlPicker` is constructed at `0x005A84C0`; its renderer is
`ControlSchemePicker_Render` at `0x005B9A30`, on vtable `0x00799C9C`. The
renderer prints `SELECT A CONTROL SCHEME` with Fonts group 4 and selects one
of three atlas records from the picker bitmask at object `+0x2A0`:

1. record 0 at bundle `+0x0038`;
2. record 2 at bundle `+0x01C0`;
3. record 1 at bundle `+0x00FC`.

That order is the compiled branch order, not a proposed enum numbering.
Record 3 at bundle `+0x0284` is stock-dormant. The picker destructor
releases the atlas bundle through the common bundle-release path.

## `Create`: create-wizard flow

The create-wizard screen object uses vtable `0x00797B7C`. Its key slots are:

- construction/build: `0x00593C30`;
- update: `0x0058A820`;
- presentation render: `0x0059AD40`;
- pause-menu-compatible action/render slot: `0x0058EA50`.

The atlas destinations are:

| Records | Destination | Static consumer result |
| ---: | ---: | --- |
| `0..7` | inline `+0x0038` through `+0x0594`, stride `0xC4` | Rendered directly; record 4 also participates in update logic |
| `8` | inline `+0x0658` | Stock-dormant |
| `9..13` | array `+0x0720`, count 5 | Five-choice presentation group in the renderer |
| `14..15` | array `+0x0730`, count 2 | Navigation/presentation pair used in construction and update |
| `16..19` | array `+0x0740`, count 4 | Four-state group used by update logic |
| `20..23` | array `+0x0750`, count 4 | Four-state group used by update logic |

All 24 records except record 8 therefore have a compiled consumer. The binary
proves the grouping and selection sites; it does not expose trustworthy names
for each visual option, so the groups remain numeric here.

## `Loader`: owned atlas, primitive renderer

The startup path at `0x005BAB60` allocates a `0x484`-byte `MyLoader` object and
embeds `Bundle_Loader` at object `+0x78`. `_DAT_008199BC` points at that
embedded bundle. The same startup path invokes the five-record builder
`0x004EC1F0`, stores the loader at `MyApp +0xDA4`, and registers it with the
application lifecycle.

`MyLoader` uses vtable `0x00799BDC`:

- destructor slot `+0x00`: `0x005AACF0`;
- renderer slot `+0x0C`: `0x005BCA40`.

The renderer draws fullscreen and progress presentation with primitive
geometry and the progress globals `DAT_0081F6A8`, `DAT_0081F6AC`, and
`DAT_0081F6B0`. It contains no reference to `_DAT_008199BC` or any of its five
record destinations. The only compiled singleton reference is the bundle's
construction/publication path. The destructor nevertheless calls the common
bundle-release function `0x00413760`.

Therefore, in this retail executable:

- the Loader PNG and bundle are loaded;
- the five sprite descriptors are constructed;
- their owning bundle has a normal lifetime and release path;
- the active loader renderer does not draw any of them.

This is a proved statically dormant art path, not evidence that loader asset
loading failed.

## `GameOver`

The three-record builder is `0x004EA650`. The screen uses vtable `0x0079B0CC`;
its renderer is `0x005C9030`. When the relevant fade/state fields beginning at
object `+0x7C` are active, it draws records 0 and 1, uses Fonts group 3 for
text, and composes fullscreen fade layers. Record 2 is stock-dormant.

## Lifetime and replacement implications

These atlases follow the same resident bundle lifecycle as gameplay atlases:

1. builder resolves the density-specific image and bundle;
2. image data becomes a resident page/GPU handle;
3. records are decoded into fixed inline fields, arrays, or font wrappers;
4. screen and control code selects those fixed destinations;
5. owner teardown invokes the common bundle release path;
6. device-reset paths rebuild resident texture state as documented in the
   core asset-system map.

For custom art, this yields four concrete constraints:

- replacement atlases must preserve every compiled destination and array
  count used by native code;
- bitmap fonts must preserve wrapper headers, glyph IDs, and kerning grammar,
  not only record count;
- adding a new PNG or extra bundle record does not create a screen, widget, or
  selection branch;
- art-only replacement is presentation-local, while adding new UI behavior
  requires Lua/native control logic above the atlas layer.

For multiplayer synchronization, UI and font replacements are normally local
presentation state. Gameplay-significant UI mods can still include Lua, so the
future mod manifest must synchronize the complete enabled mod identity rather
than deciding determinism from file extension alone.

## Runtime closure and optional sampling

The isolated 2026-07-21 runtime pass closed the scene-lifetime targets that
affect the native art contract. Create acquired its atlas and released it on
the transition to Hub; Game Over acquired its atlas over the still-resident
arena; and the Loader global was observed pointing at released allocation
storage after startup-owner destruction. Exact samples and the cross-scene
reference-count table are in
[native-live-validation.md](native-live-validation.md).

The following are optional presentation sampling or `sd.ui`-automation work,
not blockers on the native-art ABI:

1. sample representative records from each Fonts wrapper and confirm wrapper
   destination and text consumer at runtime;
2. observe the control-scheme bitmask and confirm its record branch while
   cycling the three choices;
3. observe create-wizard grouped-array selection;
4. continue semantic `sd.ui` API work independently of native-art closure.

No website download or automatic mod-enablement behavior was implemented as
part of this analysis.
