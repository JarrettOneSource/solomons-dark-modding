# ALLY Healthbar Text Investigation

Date: 2026-04-26

> **POST-COMPACTION CHECK**: re-read this file at start of any new session
> picking up the ALLY healthbar work. The summary may have flattened the
> open questions; this doc is the source of truth for what is and isn't
> confirmed.

## Spirit / Guidance

This doc is a **map of what we believe**, not a recipe. The investigation has
already produced two meaningful corrections to earlier assumptions, and the
next correction is probably waiting just past the next assumption we treat as
settled. So:

- **Treat Ghidra labels as hypotheses.** A function labelled
  `FUN_0060C540 (HUD ally-bar draw, ...)` is also self-evidently a Boulder/Rock
  list renderer once you read the body. Labels in this codebase are sticky;
  bodies are not.
- **Verify with runtime memory before designing patches.** The text storage
  struct at `0x0081DB88` was empty (all zeros) when probed without bots, and
  populated with vtable+buffer pointers when bots were in arena. A static
  decompile alone would have invited the wrong substitution point.
- **No band-aids.** If the text source is not in the binary, do not spam
  String_Assigns at every plausible site. Find the actual write, then design
  one substitution. The user has explicitly flagged this as a no-fallbacks
  task — build correctly the first time.
- **If a path looks too clean, look one level deeper.** The HUD render
  dispatcher at FUN_00512060 case 100 cleanly iterates 4 slot pointers and
  calls vt[7]/vt[10] on each — that's beautiful, but neither vt[7]
  (FUN_0054BA80) nor vt[10] (FUN_00528AD0) on PlayerWizard contains the
  ALLY/Golem/Bot text write. The clean path is incomplete.

## Goal

Replace the literal "ALLY" string on the four stacked HUD healthbars
(top-center, beneath the player's main HP bar) with each bot's individual
display name. User clarified that the same widget shows "Golem" when a Golem
is spawned — so the text is **per-entity dynamic**, not a static label.

The existing world-space nameplate path (`DrawGameplayHudParticipantName` in
`src/mod_loader_gameplay/gameplay_hooks/gameplay_hud_hooks.inl`) already does
this for floating actor names. We need the same substitution applied to the
top-center stacked-bar text source.

`/effort max`. Codex CLI couldn't solve this; we're picking it up fresh.

## Confirmed (with evidence)

### Image / runtime layout

- Image base: `0x00400000`.
- **Runtime image is relocated by `+0xA80000`.** Static `0x0054BA80` →
  runtime `0x00FCBA80`. Verified by reading the prologue bytes at the
  expected runtime address from `lua_disasm_vtfn.lua`.

### Slot iteration in case 100 of FUN_00512060

- Scene struct at `DAT_0081c264` has a slot array at offsets
  `+0x1358, +0x135C, +0x1360, +0x1364` (4 entries: player + 3 bots).
- For each non-null entry, after a visibility test (`FUN_00403da0`), the
  pointer is appended to a local `PointerList` (`local_94`).
- The list is then iterated and **vt[10] then vt[7]** are invoked on each:
  ```
  do {
    (**(code **)(*piVar7 + 0x28))(); // vt[10]
    (**(code **)(*piVar7 + 0x1c))(); // vt[7]
  } while (...);
  ```
- All 4 entries are `PlayerWizard` instances when bots are present (verified
  by RTTI probe).

### PlayerWizard vt[7] = FUN_0054BA80

- Decompiled in full: `Decompiled Game/dump_vt7_vt10.log`.
- Contains a single `String_Assign` at line 1734 that writes a `"%d"`
  formatted slot index (`*(char *)(param_1 + 0x5C)`) into `DAT_008199a0 +
  0xe7d98`. Verified by Lua probe of `DAT_007db6b8`:
  ```
  string @ 0x007db6b8 = "%d"
  ```
- This is **not** the ALLY render. It looks like a debug/index display.

### PlayerWizard vt[10] = FUN_00528AD0

- Decompiled in full: same log.
- Pure sprite/quad draw (`FUN_00414ea0`, `FUN_0041fe50`). **No text writes.**

### "ALLY" is not in the binary as ASCII

- `strings -t x SolomonDark.exe | grep ALLY` returns nothing standalone (only
  hits inside words like `INITIALLY`, `REALLY`, `LOCALLY`).
- `strings -e l` (UTF-16 LE) also empty.
- Game data files (`magenames.txt`, `wave.txt`, `items.cfg`,
  `wizardskills/*.cfg`) contain no `ALLY` literal either.

### FUN_0060c540 is mislabeled

- Existing log `decomp_ally_bar_residual.log` calls it
  "HUD ally-bar draw". Existing log `find_ally_bar_owners.log` calls it
  "Boulder/rocks/list-driven payload renderer". The body uses
  `PointerList<class_SmartPointer<struct_Boulder::Rock>_>::vftable` (line
  168), so the second label is closer to the truth.
- It DOES contain a `Text_Draw(DAT_00819978 + 0x4210)` at line 335,
  conditional on `*(float *)(local_74 + 0x1ec) != 0.0`. This is the only
  call to `Text_Draw` with that exact address in the entire decompiled
  corpus we've inspected.
- It's at vtable offset `0x1C` (vt[7]) of a different vftable starting at
  `0x0079e08c` (`FUN_005fbd90`). Not `PlayerWizard`. Likely a
  Boulder/Rock-spawning **PlayerWizard subclass or sibling class**.
- Caller search returned **0 callers** (`find_ally_bar_owners.log`) —
  meaning it's only reached via vtable dispatch, consistent with vt[7] of
  whatever class owns vftable `0x0079e08c`.

### Text storage struct at `0x0081DB88` (= `DAT_00819978 + 0x4210`)

- Empty (zeros) when no bots in arena.
- Populated with vtable-like pointers (`0x01208234` repeating) and buffer
  pointers when bots are present.
- Stride between similar-shaped entries appears to be `0x80`, suggesting an
  array of Text-objects starting somewhere around `+0x4180`/`+0x4210`.
- Field layout (probed live):
  - `+0x00..+0x07`: zero
  - `+0x08`: vtable pointer (`0x01208234`)
  - `+0x0C`: buffer pointer (`0x034A3134`) — content is more pointers, not
    a string
  - `+0x10`: small int (3) — possibly char count
  - `+0x18`: same vtable pointer
  - `+0x28..+0x2C`: small ints (5, 0xA) — possibly width/height
  - `+0x34`: another buffer pointer (`0x0121F6D4`)
  - `+0x4C..+0x60`: more (vtable, fb, 0x2B, ...) — possibly per-glyph
    sub-records

## Surprises

1. **The clean HUD dispatcher path is a dead end for ALLY text.**
   PlayerWizard's vt[7]/vt[10] don't write the ALLY string. The case-100
   loop is real but its output isn't the ALLY bar.

2. **"ALLY" doesn't exist as ASCII in the binary.** This was the biggest
   surprise. Implications: text source is either
   - assembled glyph-by-glyph from char codes, or
   - loaded from a binary asset / font glyph atlas with non-ASCII keys, or
   - constructed from a localization table that we haven't found, or
   - **the bars aren't actually saying "ALLY" right now** (we may have
     stale screenshots; haven't visually re-confirmed in latest build).

3. **`FUN_0060c540` is the only `Text_Draw(DAT_00819978 + 0x4210)` call
   site.** That makes it the strongest candidate text-draw site, but its
   *string assignment* must be elsewhere — `Text_Draw` reads a struct that
   was already populated. We have not yet found the writer.

4. **Multiple text destinations are in play.**
   - `DAT_00819978 + 0x4210` = `0x0081DB88` (the bar text — read-only in
     `Text_Draw`)
   - `DAT_008199a0 + 0xe7d98` = `0x013D5C98` (the slot-index `%d` text from
     PlayerWizard vt[7])
   - `DAT_00819978 + 0x381c` (a different Text_Draw target inside
     `FUN_00538b80`)
   These are distinct sprite/text managers; don't conflate.

## Things To Check (open questions)

1. ~~**Confirm what the bars currently say in the live build.**~~
   **CONFIRMED 2026-04-26**: `runtime/ally_healthbar_2026-04-26_topcenter_2x.png`
   shows 4 red bars stacked top-center, each labeled "ALLY" in yellow text.
   Layout: 1 wider top bar (paired with portrait icon + blue MP bar) +
   3 smaller bars below it. This matches the 4 slot entries
   (player + 3 bots) at scene+0x1358..0x1364.

2. **Find the writer of `DAT_00819978 + 0x4210`.** Use Ghidra to find ALL
   write xrefs (not READ refs — the existing `trace_ally_text.log` only
   captured READs). Candidate approach: run a script that searches for
   `MOV [0x0081DB88+x]` or for any function that calls `String_Assign`
   /`FUN_00402c10` with a destination computable as
   `DAT_00819978 + 0x4210` (or one of the +0x80-stride slots near it).

3. **Identify which class owns vftable `0x0079e08c`.** Read the
   RTTI_Complete_Object_Locator at `0x007e7ad0` (next preceding vftable
   meta ptr in `dump_vtable_60c540.log`) — that gives the demangled class
   name. If it's `PlayerWizard_Boulder` or similar, the case-100 loop
   *might* dispatch through this vftable when the bot is in
   boulder/casting state.

4. **Consider that the text might be drawn elsewhere entirely.** The HUD
   dispatch we mapped (FUN_00512060 case 100) might handle the world-space
   wizard but NOT the screen-space stacked bars. The stacked bars could be
   drawn from a separate top-level HUD draw entry — search for screen
   coordinate constants near top-center (e.g. y values clamped to ~screen
   top, x values centered).

5. **Could "ALLY" be glyph-indexed?** If the font system pre-bakes a glyph
   atlas, "ALLY" may live as 4 indices `(A, L, L, Y)` rather than ASCII.
   In that case the writer would be assigning glyph IDs, not bytes.
   `0x01208234` may be a Font/Glyph context — verify by reading its first
   8 bytes (likely a vtable name).

6. **Run a memory-write watch.** Lua `sd.debug` doesn't expose write
   breakpoints (need to verify), but periodic snapshots of `0x0081DB88`
   memory before/after a Golem spawn might catch the write.

7. **Re-read the existing investigation logs end-to-end before the next
   round.** `decomp_ally_bar_residual.log` (98K), `trace_ally_text.log`
   (58K), and `dump_512060.log` may already contain answers we
   skim-missed. Specifically check:
   - whether any function writes to offsets in the same `DAT_00819978 +
     0x4XXX` family
   - whether `DAT_00819980 + 0x5ac` / `+0x5cc` / `+0x5d4` (referenced in
     FUN_00538b80) is part of the same text manager and therefore close to
     the writer

## Tooling reminders

- Lua probe pipe: write script to `Mod Loader/scripts/_tmp_probe.lua`,
  then PowerShell:
  `Get-Content -Raw <path> | & 'Mod Loader\scripts\Invoke-LuaExec.ps1'`.
  The pipe drains via both `HookPlayerActorTick` and D3D9 `EndScene`, so
  it works in menus and gameplay.
- `sd.debug.read_bytes(addr, n)` returns a **hex-formatted string**, parse
  with `string.gmatch("(%x%x)")`.
- Headless Ghidra wrapper:
  `Decompiled Game/run_dump_*.bat` patterns; `dump_fn_tmp.py` takes
  multiple addresses; use replicas `slot-01..slot-06` to parallelize.
- Ghidra label noise: prefer **decompile body** over function name; cross
  check with vtable offset + RTTI when in doubt.

## Status snapshot (as of doc creation)

- Task #4 (find ALLY string and xrefs) — **completed but with a twist**:
  the string isn't in the binary. Effectively that question is closed
  with a null result.
- Task #5 (identify ally HUD bar render path and actor binding) —
  **partially complete**:
  - case-100 loop confirmed
  - PlayerWizard vt[7]/vt[10] ruled out as the ALLY writer
  - `FUN_0060c540` is the strongest remaining candidate read site for
    `DAT_00819978 + 0x4210`, but it's a Boulder/Rock class function and
    its caller is currently unidentified
- Task #6 (find bot name field on actor) — **not started**
- Task #7 (design substitution) — **blocked on finishing #5**

## Next actions (if picking up cold)

1. Re-read this doc.
2. Take a fresh screenshot of the running game with bots in arena to
   confirm the text actually says "ALLY" today.
3. Read RTTI for vftable `0x0079e08c` to identify the class owning
   FUN_0060c540.
4. Run a Ghidra script to find all WRITES to `0x0081DB88` (or the +0x80
   stride family `0x0081DB48..0x0081DD08`).
5. Only after the writer is identified, design substitution.
