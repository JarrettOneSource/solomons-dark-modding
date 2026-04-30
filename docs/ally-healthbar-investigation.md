# Ally Healthbar Text System

This note captures the recovered facts around the stacked top-center ally
healthbars used for player/bot party members in arena scenes. The goal is to
replace the stock `ALLY` label with each participant's display name without
adding broad text-draw patches or fallback string spam.

## Target Surface

The relevant HUD widget is the stacked red healthbar group drawn below the main
player health/mana area. With participant bots present, the live layout shows:

- one wider top entry paired with portrait and MP bar context
- three smaller entries below it
- yellow `ALLY` text on each stacked entry

This matches the four slot entries at `SdGameplayScene + 0x1358..0x1364`
(`player + 3 bot slots`) when gameplay-slot bots are present.

The world-space participant nameplate path already exists in
`src/mod_loader_gameplay/gameplay_hooks/gameplay_hud_hooks.inl`; the missing
piece is the top-center stacked-bar text source.

## Confirmed Runtime Layout

- Static image base: `0x00400000`.
- The observed runtime image was relocated by `+0xA80000` in the captured
  session. For example, static `0x0054BA80` mapped to runtime `0x00FCBA80`.
- Scene slot array:
  - `scene + 0x1358`
  - `scene + 0x135C`
  - `scene + 0x1360`
  - `scene + 0x1364`
- All four slot entries were verified as `PlayerWizard` instances when bots were
  present.

## HUD Dispatcher Findings

`FUN_00512060` case `100` is a real HUD participant path:

1. It reads the four gameplay slot pointers.
2. It applies a visibility test through `FUN_00403DA0`.
3. It appends survivors to a local pointer list.
4. It calls vtable slot `10`, then vtable slot `7`, on each survivor.

The obvious `PlayerWizard` vtable slots are not the `ALLY` writer:

- `PlayerWizard vt[7] = 0x0054BA80`
  - contains one `String_Assign`
  - writes a formatted slot index using `"%d"` into `DAT_008199A0 + 0xE7D98`
  - does not write `ALLY`
- `PlayerWizard vt[10] = 0x00528AD0`
  - sprite/quad drawing only
  - no text assignment

So the case-100 loop is relevant to the stacked HUD path, but the `ALLY` string
source is not in the plain `PlayerWizard vt[7]` or `vt[10]` bodies.

## Text Storage Candidate

The strongest known text draw site is inside `FUN_0060C540`:

- it calls `Text_Draw(DAT_00819978 + 0x4210)`
- the effective text object address is `0x0081DB88`
- the draw is conditional on `*(float *)(local_74 + 0x1EC) != 0.0`
- the function appears under a different vtable family around `0x0079E08C`

The existing function label for `FUN_0060C540` should not be trusted blindly.
The body also resembles a Boulder/Rock list renderer, so the owning class still
needs RTTI/vtable confirmation before this can be treated as the final ally-bar
class.

Live observations of `0x0081DB88`:

- empty when no bots were present in arena
- populated with vtable-like pointers and buffer pointers when bots were
  present
- neighboring entries appear to have an `0x80` stride

Observed field shape:

- `+0x08`: vtable-like pointer
- `+0x0C`: buffer pointer
- `+0x10`: small integer, possibly character count
- `+0x18`: repeated vtable-like pointer
- `+0x28..+0x2C`: small dimensions or glyph counts
- `+0x34`: secondary buffer pointer

## String Storage Facts

`ALLY` is not present as a standalone ASCII or UTF-16 literal in:

- `SolomonDark.exe`
- `magenames.txt`
- `wave.txt`
- `items.cfg`
- `wizardskills/*.cfg`

That makes a direct literal substitution unlikely. The source is probably one of:

- glyph-indexed text
- a binary/localized text table not found by ordinary strings
- a dynamic text object populated from non-ASCII identifiers
- a class-specific HUD string builder that writes through the text-object API

## Distinct Text Destinations

Do not conflate these destinations:

- `DAT_00819978 + 0x4210` / `0x0081DB88`
  - strongest current stacked-bar text candidate
- `DAT_008199A0 + 0xE7D98` / `0x013D5C98`
  - slot-index `%d` text from `PlayerWizard vt[7]`
- `DAT_00819978 + 0x381C`
  - separate text target used by `FUN_00538B80`

The `ALLY` substitution should target the writer for the first family, not the
debug/index display path.

## Implementation Boundary

Before patching the label, the loader needs one precise substitution seam:

1. Identify the writer that populates `DAT_00819978 + 0x4210` or its `0x80`
   stride family.
2. Confirm the owner of vtable `0x0079E08C` and whether `FUN_0060C540` is the
   stacked-bar reader for participant HUD entries.
3. Map the participant slot or actor pointer available at the writer.
4. Substitute the participant display name at that writer or at one tightly
   scoped text-object update call.

Broad hooks around every `Text_Draw` / `String_Assign` candidate are explicitly
the wrong implementation shape for this system.
