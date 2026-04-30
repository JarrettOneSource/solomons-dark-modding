# Gameplay-Slot Primary Cast Crash Tracker

Date: 2026-04-22
Updated: 2026-04-24

## Scope

This note captures the current stable findings around the gameplay-slot bot
primary-cast investigation and preserves the most recent startup crash family
seen while reintroducing deeper builder instrumentation.

It exists so the current offsets, crash RVAs, and confirmed stock call-chain
facts are not lost between runs.

## Stable Facts

These points are confirmed on the current stable base:

- UI automation regression is fixed.
- Pre-wave combat gating is fixed.
- Dead gameplay-slot bots are now treated as inert corpses for the rest of the
  run. This is enforced in both layers:
  - gameplay tick hooks detect `hp <= 0 && max_hp > 0`, quiesce movement, stop
    actor motion, drain/release casts, publish a snapshot, and return before
    stock tick / movement / collision / behavior paths run
  - the Lua-facing bot runtime rejects post-death `move_to`, `face`, and
    `cast` requests and clears pending controls back to idle
- `0052DA80` is the live pure-primary allocator path and it does reach the
  builder call site.

## Dead-Inert Live Probe

Focused probe:

- [`tools/probe_bot_dead_inert.py`](../tools/probe_bot_dead_inert.py)

Latest artifact:

- `runtime/probe_bot_dead_inert.json`

Validated result on 2026-04-23:

- bot actor remained materialized:
  - `actor_address = 51476576`
- forced dead state stayed visible through the Lua/state surface:
  - `hp = 0.0`
  - `max_hp = 500.0`
- commands after death were handled correctly:
  - `sd.bots.move_to(...) -> false`
  - `sd.bots.face(...) -> false`
  - `sd.bots.cast(...) -> false`
  - `sd.bots.stop(...) -> true`
- runtime/controller state stayed inert:
  - `state = idle`
  - `moving = false`
  - `has_target = false`
  - `queued_cast_count = 0`
- actor raw movement/cast fields stayed inert:
  - `actor + 0x158 = 0.0`
  - `actor + 0x15C ~= 0.0` only as a denormal near-zero residue
  - `actor + 0x160 = 0`
  - `actor + 0x1EC = 0`
  - `actor + 0x270 = 0`
  - `actor + 0x27C = 0xFF`
  - `actor + 0x27E = 0xFFFF`
  - `actor + 0xE4 = 0`
  - `actor + 0xE8 = 0`
- corpse position did not drift across the post-death observation:
  - baseline `raw_x/raw_y = 918.58416748047, 2284.4350585938`
  - final `raw_x/raw_y = 918.58416748047, 2284.4350585938`
  - computed drift = `0.0`
- no-wave combat prelude remained pinned:
  - `world.wave = 0`
  - `world.enemy_count = 0`
  - `combat_state.wave_index = 0`
  - `combat_state.wave_counter = 999999999`

## Confirmed Stock Call Chain

No-analysis Ghidra dump of `0052DA80` shows:

- selection mode comes from:
  - `**(actor + 0x21C)` when present
  - otherwise slot-global fallback through `DAT_00819E84`
- item sink comes from:
  - `actor + 0x1FC` when non-zero
  - otherwise `DAT_0081C264 + slot*0x64 + 0x1410`
- item resolution then does:
  - `MOV ECX, [EAX + 0x30]`
  - `MOV ECX, [ECX]`
  - `CALL 0x00570D80`
- mode selection is:
  - no item -> `6`
  - staff `0x1B5C` -> `3`
  - otherwise -> `9`
- builder call site is:
  - `0052DB03 PUSH EDI`
  - `0052DB04 CALL 0x0044F5F0`

This means the builder call is not speculative. It is in the real stock path.

## 2026-04-24 Control-Brain Vector Contract

The stock control-brain function at `0052C910` does **not** receive two scalar
float outputs. Its second and third parameters are separate two-float vectors:

- `param_2` is `movementVecOut[2]`
- `param_3` is `facingVecOut[2]`

The surrounding stock player tick (`00548B00`) consumes those vectors on two
different lanes:

- `movementVecOut` is folded into actor movement accumulators such as
  `actor + 0x158` and `actor + 0x15C`
- `facingVecOut` is magnitude-tested for attack/facing intent and then drives
  the visual/aim lane

This explains the recent field symptoms:

- bot follow jittered or moved "back" while enemies were present because the
  target-facing override was writing attack delta into the movement output
- visual facing only partially tracked because the hook wrote one float to
  `param_3`, leaving the second facing-vector component stale
- primary effects/projectiles became unstable because the stock cast gate saw a
  malformed facing vector and stale aim target fields

Patch rule from this finding:

- never write attack facing into `movementVecOut`
- when a bot has an active pure-primary target, write the normalized target
  direction to both floats of `facingVecOut`
- keep `actor + 0x2A8` / `0x2AC` aim-target fields refreshed alongside the
  selection target seed
- when movement and attack happen on the same tick, target-facing beats
  movement-heading; movement direction stays on the movement lane only

Validation status:

- `luac -p mods/lua_bots/scripts/main.lua` passes
- `scripts/Build-All.ps1 -Configuration Release` passes with the two existing
  unused-variable warnings
- the automated primary-cast probe is currently blocked before combat by the
  new-game transition staying in `scene=transition`, so this document records
  the RE contract and code-level fix, not a completed live damage verdict

## Latest Live Primary-Cast Baseline

Current representative gameplay-slot direct-primary startup window:

- `c21c_val = 0x8`
- `dc = 0x87E690`
- `dc_vt = 0x7087B0`
- `dc_slot10 = 0x704610`
- `dc_vt_cb10 = 0x11EB86E8`
- `group = 0xFF`
- `slot = 0xFFFF`
- `e4/e8` often latch during startup, then settle back out
- staff item resolution is valid:
  - `result_type = 0x1B5C`

Despite that, the unresolved cast still commonly ends in:

- `cast complete (safety_cap)` or earlier no-object completion
- no persistent spell-object handle
- no visible projectile/effect

## Latest Explicit Queue Result

Fresh wave-run harness result on the current stable build:

- the direct cast request is real:
  - `[bots] queued cast for bot id=... state=attacking`
- the gameplay-slot bot cast prep is real:
  - `[bots] gameplay-slot cast prepped. ... lane=pure_primary`
- startup enters the stock pure-primary path with the local-slot selection shim:
  - `startup=1`
  - `local_sel_shim=1`
  - `fallback_slot_byte=0x0`
- the slot-0 fallback sink resolves a valid staff item:
  - `fallback_slot_plus4_type=0x1B5C`
  - `equip_sink_get_current_item ... result_type=0x1B5C`
- the stock gate still does not commit a spell:
  - `skill_after=0`
  - `cast_group_after=0xFF`
  - `drive_after=0x0`
  - `no_int_after=0x0`
- completion still times out by watch logic:
  - `[bots] cast complete (safety_cap) ... saw_latch=1 group_after=0xFF`

Final 2026-04-23 no-wave smoke artifact:

- `runtime/probe_bot_primary_wave_cast.final_combat_prelude_smoke.json`

This probe confirms the current stable no-wave behavior:

- direct cast API accepted the request:
  - `direct_cast.ok = true`
- cast prep and stock pure-primary entry both occurred:
  - `queued_cast_logged = true`
  - `cast_prepped_logged = true`
  - `pure_primary_start_entered = true`
  - `pure_primary_start_exited = true`
- no-wave suppression stayed pinned:
  - `world.wave = 0`
  - `world.enemy_count = 0`
  - `combat_state.wave_index = 0`
  - `combat_state.wave_counter = 999999999`
- the unresolved spell-object/effect seam remains:
  - completion still ended as `cast complete (safety_cap)`
  - `cast_group_after = 0xFF`

Most important paired probe result:

- runtime trace at `0x0052DB09` (`pure_primary_post_builder`) armed successfully
  and reported zero hits during the same explicit queue run.

Implication:

- on the explicit queue path, the loader now proves all of:
  - queue accepted
  - cast prep accepted
  - pure-primary start entered with valid item resolution
  - `0044F5F0` builder entry is called
- but execution still never reaches the post-`0044F5F0` resume site at
  `0x0052DB09`.

Latest paired runtime trace result:

- `bot_primary_builder_entry` at `0x0044F5F0`
  - armed successfully
  - hit repeatedly, including on the explicit queue path with `arg1=3`
  - on the explicit queue path, the function-entry return address is
    `0x60DB09`, i.e. the runtime-mapped `0052DB09` caller resume site
- `bot_primary_post_builder` at `0x0052DB09`
  - armed successfully
  - hit count stayed `0`

Current best interpretation:

- the explicit queue path does call the builder
- the builder entry itself proves the caller expects to resume at `0052DB09`
- despite that, the post-builder trace at `0052DB09` still stays dark
- that now makes the next seam narrower:
  - either the caller continuation trace is still the wrong probe site, or
  - control flow is being altered after builder entry in a way that still
    prevents the normal caller resume block from executing

Caller-side follow-up result on the refreshed probe:

- the post-builder trace at `0x0052DB09` was tightened from a 7-byte patch to
  a 5-byte patch so it only covers:
  - `MOV ESI, EAX`
  - `ADD ESP, 0x0C`
- a second caller-side trace was added at `0x0052DB0B` to watch the immediate
  follow-up block after the call-site stack fixup
- on a fresh successful explicit queue run:
  - `bot_primary_builder_entry` fired
  - `bot_primary_builder_callback_load` fired
  - `bot_primary_builder_return` fired
  - `bot_primary_post_builder` stayed at `0`
  - `bot_primary_post_builder_followup` stayed at `0`

That rules out the original `7`-byte `0052DB09` patch width as the likely
reason for the zero-hit result. The caller-side continuation block still does
not execute, even with the tighter patch and the second seam at `0052DB0B`.

### Builder Frame Slot Mapping

`0044F5F0` has a compact EH prologue and does **not** allocate an extra local
stack frame beyond its saved registers / EH state. That means the tail trace at
`0044FF38` can now be decoded precisely:

- `ret` field in the trace record is **not** the caller continuation
  - it is the security-cookie / EH slot at `[esp+0x00]`
- `arg7` is the real caller continuation at `[esp+0x20]`
- `arg8` is `param_1`, i.e. the pushed actor pointer from `0052DB03 PUSH EDI`

This explains why the explicit bot path can show `arg7=0x60DB09` at the builder
tail while the post-builder traces at `0052DB09 / 0052DB0B` still remain dark:
the builder tail is preserving the caller continuation slot, but control still
does not execute the normal caller-side block afterward.

## Builder Tail Callback Findings

The startup log previously used `dc_cb10` for the wrong field. The builder tail
does **not** call the vtable slot at `[dc_vt + 0x10]`. The relevant stock
instructions are:

- `44FEFA MOV EDX, [EDI + 0xDC]`
- `44FF00 MOV EAX, [EDX + 0x10]`
- `44FF0D CALL EAX`

That means the live callback target comes from the direct slot:

- `dc_slot10 = [actor + 0xDC] + 0x10`

Latest explicit queue result with the corrected trace:

- new trace armed at `0x0044FF03` (`bot_primary_builder_callback_load`)
- on both ambient builder traffic and the explicit gameplay-slot cast:
  - `EDX = 0x87E690`
  - `EAX = 0x704610`

So the builder tail is consistently calling the same direct sink callback, and
the explicit queue path is **not** diverging before that call.

### Callback Mapping

- runtime callback target: `0x704610`
- requested image address: `0x624610`

Objdump of `0x624610` shows a normal sink method:

- stores the incoming object pointer
- bumps that object's refcount when non-null
- calls an inner method through `[ECX]->4`
- releases the temporary reference
- returns with `RET 4`

Current interpretation:

- the builder tail callback target is now confirmed and stable
- the explicit gameplay-slot bot path reaches that callback with the same
  target as ambient builder traffic
- the unresolved seam is now after builder entry and after callback-target
  selection, not before it

### Resolver Fix

The runtime trace resolver itself was wrong for this seam:

- `ResolveExecutableRuntimeAddress()` originally returned the raw address first
  whenever that raw address was executable
- both `0x624610` and `0x704610` are executable in-process
- the gameplay callback target is the **runtime** address `0x704610`
- so tracing requested image-space `0x624610` silently armed the wrong
  executable region and produced false zero-hit results

The resolver now prefers the translated game-runtime address when
`ResolveGameAddressOrZero()` returns a different executable target. After that
fix, requested image-space trace addresses for the sink callback started
landing on the real runtime target.

### Live Sink Result After Resolver Fix

Fresh live explicit bot-cast runs now prove:

- `bot_primary_builder_callback_load` fires with:
  - `EAX = 0x704610`
  - `EDX = 0x87E690`
- `bot_primary_sink_entry` at requested `0x624610` now fires
- `bot_primary_sink_inner_call` at requested `0x624652` now fires
- at sink inner call:
  - `EAX = 0x87E690`
  - `ECX = actor+0xDC slot holder`
  - `EDX = 0x548940`

So the explicit gameplay-slot bot path definitely reaches:

- builder entry
- builder tail callback-load
- sink callback entry
- sink inner dispatch

This is the first confirmed post-builder control-transfer path after the
resolver fix.

## Post-Sink Crash Chain

Once the sink traces were live, the next real downstream failure became
visible:

- first-chance AV eventually lands at freed memory:
  - `eip = 0x2551C500`
  - `state = MEM_FREE`
- the game stack frame directly below the crash is:
  - `0x006296C6`

Static analysis:

- `0x548940` is not a function entry; it is a mid-function label inside
  `FUN_00548700`
- `0x6296C6` lives inside `FUN_00628f10`
- `FUN_00628f10` calls `FUN_00401310()` at `0x6296C8`
- `FUN_00401310` immediately calls `FUN_00401170`
- `FUN_00401170` is a PRNG / ring-buffer helper over a 0x37-entry state table

Important implication:

- the crash is no longer in the builder tail itself
- the next concrete RE seam is the post-sink path:
  - `0x624652 -> 0x548940 -> 0x6296C6 -> 0x401310 -> 0x401170`

Current caution:

- the sink traces are highly invasive and can destabilize ambient builder
  traffic if armed too broadly
- the main bot probe has been tightened so the sink-entry and sink-inner-call
  seams arm only around the explicit cast window
- even with that narrowing, the post-sink crash family is still reproducible,
  so the next step is to determine whether it is a trace-induced artifact or a
  real gameplay-slot-only failure in the `0x6296C6 / 0x401310` chain

## Builder Hook Lessons

Two instrumentation mistakes were confirmed:

1. `0044F5F0` hook boundary was wrong when set to `5`.
   - The real prologue starts with:
     - `PUSH -1` (2 bytes)
     - `PUSH 0x76559B` (5 bytes)
   - A 5-byte patch splits the second instruction.
   - The correct minimum patch size is `7`.

2. The builder/reset/finalize hooks were resolved and logged at startup, but
   were not actually installed in the gameplay hook init path until a later
   experiment.

## Latest Builder-Hook Crash Family

Newest crash artifact:

- dump: `runtime/stage/.sdmod/logs/solomondarkmodloader.crash.20260422_175654_772.tid17936.dmp`
- text log: `runtime/stage/.sdmod/logs/solomondarkmodloader.crash.log`

Captured first-chance exception:

- code: `0xC0000005`
- write/access fault near:
  - `eip = 0x0DB40003`
  - private RX/RWX stub region, not inside the game image
- disassembled stub bytes at fault:
  - `8B 06 E9 9B AD 9F F2 ...`
- register shape:
  - `eax = 0x0DB40000`
  - `ebx = 0x00000002`
  - `ecx = 0x00000000`
  - `esi = 0x00000000`
  - `edi = 0x00000001`

Loader module RVAs in the captured stack:

- `0x00074A1E`
- `0x0007888B`

Current interpretation:

- this crash family is strongly consistent with a hook/trampoline failure
  introduced by the newly enabled builder instrumentation path, not with the
  original gameplay bug itself.
- the private executable stub at `0x0DB40000` suggests the failure occurred in
  generated trampoline glue or a patched call-through path before control
  safely returned to the normal image code.

## Other Crash Offsets Seen In The Same Family

Additional loader RVAs observed across related crash entries:

- `0x0007444E`
- `0x00076169`
- `0x000770EB`
- `0x0007888B`
- `0x0007890B`
- `0x000BE73C`

Current source-file mapping:

- `0x0007444E` / `0x00074A1E`
  - source file: `src/logger_crash_reporting.cpp`
  - line-table range: around lines `328..363`
  - role: crash-dump writer / crash-report generation
- `0x00076169`
  - source file: `src/logger_exception_handlers.cpp`
  - line-table neighborhood: around lines `100..101`
  - role: exception-address / EIP description formatting
- `0x000770EB` / `0x000778D9`
  - source file: `src/logger_exception_handlers.cpp`
  - line-table neighborhood: around lines `280..345`
  - role: first-chance exception logging and stack-trace emission
- `0x0007888B` / `0x0007890B`
  - source file: `src/lua_engine.cpp`
  - line-table neighborhood: around lines `71..76`
  - role: Lua engine startup/teardown path in the same startup crash family
- `0x000BE73C`
  - source file: `src/mod_loader_gameplay/bot_casting/pending_cast_preparation.inl`
  - line-table neighborhood: near the
    `"[bots] gameplay-slot cast prepped..."` block
  - role: gameplay-slot cast startup / prep path

Current interpretation:

- the repeated `0x0007444E / 0x00074A1E / 0x00076169 / 0x000770EB /
  0x000778D9` frames are mostly the loader's own crash-reporting machinery.
- the important gameplay RVA in the newest family is `0x000BE73C`, which lands
  in the gameplay-slot cast-prep helper. That means the failing startup family
  is reaching bot cast prep before the logger-side frames dominate the stack.
- this is consistent with the builder-hook reintroduction destabilizing the
  cast startup path, while the logger frames are mostly downstream reporting.

## Current Best Interpretation

- The stock pure-primary path definitely resolves a valid staff item and
  definitely contains a call to `0044F5F0`.
- The absence of trustworthy builder logs in earlier runs was not evidence that
  the call never happened; the instrumentation itself was partially wrong.
- The latest attempt to fully enable builder hooks destabilized startup, so the
  builder path should be treated as a crash-prone instrumentation seam until
  the above RVAs are mapped and the hook/trampoline path is proven safe.

## Next RE Targets

- map the crash RVAs above back to concrete source locations in the loader DLL
- decide whether builder hooks can be made safe or whether the next proving
  step should come from a different seam
- continue comparing player-vs-bot primary-start contracts around:
  - `actor + 0x1FC`
  - `actor + 0x21C`
  - selection fields `+0x04/+0x06/+0x08/+0x0C/+0x10/+0x14`
  - progression `+0x750`

## 2026-04-23 Local Player Ether Baseline In Combat Prelude

Boyle's `sd.gameplay.enable_combat_prelude()` path made it possible to run a
local-player cast baseline in:

- `testrun`
- `wave = 0`
- `enemy_count = 0`
- `combat.active = true`

without starting waves.

### Input Binding Correction

`sd.input.click_normalized(...)` needed two fixes for this baseline:

1. it had to try the stock gameplay mouse-left queue before failing for window
   visibility/client-rect reasons
2. it also had to preserve the requested normalized cursor position before
   queueing the gameplay click, otherwise the click could hit whatever world
   target the cursor was already hovering and accidentally interact with
   `Solomon_Dig`

The current binding now:

- clamps the normalized point
- tries to move the cursor to that point first when the host window is
  available
- then queues the stock gameplay mouse-left edge if a run is active
- only falls back to `SendInput` if the queue path fails

### Light Local-Player Result

A fresh Ether `testrun` plus one off-center synthetic click at `(0.82, 0.50)`
stays in no-wave combat-prelude state and does enter the local-player
pure-primary startup path.

Live signs:

- `prog_750 = 1`
- `actor_27c` / `actor_27e` flip from `0xFF / 0xFFFF` to `0 / 0`
- loader log shows:
  - `Queued gameplay mouse-left click. gameplay=...`
  - `Injected gameplay mouse-left click. ... cast_intent=1`
  - `[player-cast-probe] arm ... click_serial=3 ...`
  - `[bots] pure_primary_start enter ... bot_id=0 ... local_player=1`
  - `[bots] equip_sink_get_current_item ... local_player=1 ... result_type=0x1B5C`

This proves the local-player baseline reaches the same pure-primary startup and
sink-item path used for the gameplay-slot bot investigation.

### Traced Local-Player Result

With the full builder/sink trace stack armed, the same off-center Ether click
reproduces the same downstream crash shape previously seen on the traced bot
path.

Confirmed local-player trace hits:

- `player_primary_builder_entry`
- `player_primary_builder_finalize`
- `player_primary_builder_after_finalize`
- `player_primary_builder_keep_object`
- `player_primary_builder_callback_load`
- `player_primary_sink_entry`
- `player_primary_sink_inner_call`
- `player_primary_builder_drop_object`
- `player_primary_builder_return`

Observed local-player values:

- callback load at `0x44FF03`: `EAX = 0x704610`, `EDX = 0x87E690`
- sink entry at `0x624610`
- sink inner call at `0x624652` with `EDX = 0x548940`
- builder return at `0x44FF38` with `arg7 = 0x60DB09`

The traced local-player pass then faults immediately with the same downstream
game frame:

- first-chance AV on freed memory `0x2551C500`
- stack frame `[5] 0x006296C6`

Just like the traced bot path, the local-player pass still does **not** log
the caller continuation traces at:

- `0x52DB09`
- `0x52DB0B`

### Meaning

This is the strongest proof so far that the `0x6296C6 -> 0x401310 ->
0x401170` crash family is not a confirmed bot-only stock rejection path. The
same heavy builder/sink trace stack can drive a clean local-player cast into
the same post-sink crash neighborhood.

So the current interpretation is:

1. lightly traced / untraced local-player Ether clicks can enter the
   pure-primary startup path without crashing
2. the fully armed builder/sink trace stack is itself a credible crash source
   for both local-player and gameplay-slot bot casts

That moves the next RE target away from treating `0x6296C6` as the confirmed
bot blocker. The next proving step should reduce the active trace set until the
local-player path survives while still distinguishing:

- successful local-player cast
- failed gameplay-slot bot cast
