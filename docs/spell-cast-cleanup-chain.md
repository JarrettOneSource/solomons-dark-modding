# Spell cast cleanup chain (player vs. bot)

Investigation that led to the watch-based bot cast handle release.
Supersedes the older 180-frame pump workaround.

## The native cast pipeline

Three addresses matter:

| Symbol | VA | Description |
|--------|----|----|
| `PlayerActorTick` | `0x00548B00` | Per-tick driver for a player actor (`__thiscall`). |
| `FUN_00548A00` | `0x00548A00` | Spell-cast dispatcher (`__thiscall`). Routes on `actor+0x270`. |
| `FUN_0052F3B0` | `0x0052F3B0` | Cast-active-handle cleanup (`__thiscall`). Releases the cached spell object. |

The pure-primary startup path also matters for fire, ether, and other
staff-driven primary effects:

- `0x0052DA80` is the live pure-primary allocator/startup path.
- `runtime/ghidra_pure_primary_equip_sink_paths.txt` proves that startup first
  reads `actor+0x1FC`; when that actor-owned equip runtime exists, the path uses
  its visual sink at `+0x30` and calls `0x00570D80`, which returns the sink's
  current item from `sink+0x4`.
- It selects mode `3` for item type `0x1B5C`.
- The builder call site is `0x0052DB04 -> 0x0044F5F0`.
- `0x0044F5F0` starts with a two-instruction prologue (`push -1`, then
  `push 0x76559B`), so any detour there must cover `7` bytes. A `5`-byte
  patch splits the second instruction and corrupts the trampoline.

## Actor offsets the cast state lives in

| Offset | Name | Purpose |
|-------:|------|---------|
| `+0x160` | `animation_drive_state` (u8) | Non-zero while a cast animation is playing. Handler sets it on init, clears it when animation ends. |
| `+0x1EC` | `mNoInterrupt` (u8) | Latched non-zero while the cast cannot be interrupted. Released when the handler decides the cast is done. |
| `+0x270` | `primary_skill_id` (i32) | Which spell to dispatch. Player input writes this on keypress. |
| `+0x27C` | `active_cast_group_byte` (u8) | Cached spell-object group — sentinel `0xFF` means "no live handle". |
| `+0x27E` | `active_cast_slot_short` (u16) | Cached spell-object world slot — sentinel `0xFFFF`. |
| `+0x2A8/+0x2AC` | `aim_target_x/y` (f32) | Cast aim target. |
| `+0x2B0/+0x2B4` | `aim_aux0/1` (u32) | Aux fields the projectile spawn path reads. |
| `+0x2DC` | `cast_spread_mode_byte` (u8) | `0` = use aim_target fields verbatim; non-zero adds spread. |

`0x0045ADE0` is the native cached-handle lookup used by cast cleanup and
selection paths. It dereferences `world + 0x500 + (group * 0x800 + slot) * 4`
internally, so runtime code calls that seam instead of duplicating the bucket
math.

## April 30 cast-state RE refresh

The current cast cleanup work is backed by these durable artifacts:

- `runtime/ghidra_stock_tick_slot_shim_cast_paths.txt`
- `runtime/ghidra_cast_state_offsets.txt`
- `runtime/ghidra_cast_spell_object_handlers.txt`
- `runtime/ghidra_pure_primary_equip_sink_paths.txt`
- `tests/re/run_live_cast_shim_snapshot_probe.py`
- `runtime/live_cast_shim_snapshot_probe.json`

Ghidra confirms `0x00548B00` owns the per-tick stock driver,
`0x00548A00` dispatches through the local progression slot selected from
`DAT_0081c264 + 0x1654 + actor+0x5C * 4`, and `0x0052F3B0` is the stock
active-handle cleanup path. `0x0052C910` owns the control-brain target fields
used while stock targeting is refreshed.

The handle lookup is now understood as a real native object seam:
`0x0052DA40` resolves the selection state for the actor, and `0x0045ADE0`
dereferences `world + 0x500 + (group * 0x800 + slot) * 4`. The Earth/boulder
handler at `0x00545360` proves the spell-object phase and release-timer fields
that gate the live boulder launch. Runtime code now names those fields through
`config/binary-layout.ini` rather than owning local numeric offsets.

The former slot shim blocker was the native init predicate:
`actor+0x5C == 0`. Ether has two separate native slot gates: one early setup
gate at `0x0053D1B3`, and one projectile-allocation gate at `0x0053D9D2` that
guards the stock `0x7D3` spell object allocation loop. The current runtime
removes the local-slot/progression redirect and installs layout-backed
native cast gate patches instead. These patches validate the live instruction as the
expected `jnz rel32` gate and capture the original bytes for restoration rather
than carrying copied per-site byte payloads in source. They unlock the exact
non-zero-slot branches while leaving
`actor+0x5C` pointed at the bot's real gameplay slot, so stock progression
lookups use the bot's live slot data.

The former pure-primary local equip sink shim was separate from that slot gate.
`0x0052DA80` already has a native actor-owned path through `actor+0x1FC`; the
loader now requires bots to carry that real equip runtime and no longer hooks
`0x00570D80`, swaps the local slot sink, or opens a local actor window around
pure-primary startup.

## May 1 slot-0 dispatch xref pass

The follow-up pass added two focused artifacts:

- `runtime/ghidra_cast_slot0_dispatch_xrefs.txt`
- `runtime/ghidra_cast_slot0_gate_offset_accesses.txt`

`0x00548A00` still has only one direct code caller, `PlayerActorTick`
at `0x00548B00`. The spell handlers checked from that dispatcher
(`0x00544C60`, `0x00541870`, `0x00545360`) still route through the same
local-slot actor gate and the same slot-indexed progression lookup:
`DAT_0081c264 + 0x1654 + actor+0x5C * 4`.

`0x0052F3B0` remains the cleanup method and is reached from
`PlayerActorTick` plus the boulder handler path, but it also checks
`actor+0x5C == 0` before touching the active handle. `0x0052DA40` likewise
uses `actor+0x5C` to select local progression state. The expanded offset scan
keeps the hot cast functions tied to `+0x5C`, `+0x270`, `+0x27C/+0x27E`, and
target handle `+0x164/+0x166`; the production fix is therefore a narrow native
cast gate patch set at `0x0052F3B9`, pure-primary Ether/Fire projectile gates
`0x0053D1B3`/`0x0053D9D2`/`0x0053E4E8`, `0x00544C92`, `0x00545393`, and
`0x00545C2C`.

`tests/re/run_live_cast_shim_snapshot_probe.py --json --timeout 180` now validates this
contract without starting arena waves. The April 30 run wrote
`runtime/live_cast_shim_snapshot_probe.json`, captured a live Earth spell
object (`object_type=2005`, group `0`, slot `5`) through the native world
bucket, confirmed the native active-object lookup, and checked
`gameplay_player_actor`, `gameplay_player_progression_handle`,
`bot_actor_slot`, and `bot_actor_progression_handle` after cast completion.

The May 1 rerun uses the same Earth primary because Fire/Ether PerCast primaries
finish too quickly to leave a stable world-bucket handle for Lua inspection.
In the no-wave harness Earth currently completes through the documented
`safety_cap` cleanup path, so the live probe default timeout is `60s` and the
artifact asserts restoration rather than assuming a max-size impact release.

## May 1 selection and active-handle lifecycle pass

The selection/latch pass added focused artifacts:

- `runtime/ghidra_selection_lifecycle_xrefs.txt`
- `runtime/ghidra_selection_and_cleanup_targets.txt`
- `runtime/ghidra_selection_brain_offset_accesses.txt`
- `runtime/ghidra_active_spell_lifecycle_xrefs.txt`
- `runtime/ghidra_cast_latch_offset_accesses.txt`
- `runtime/ghidra_boulder_spell_object_vtable_slots.txt`

`0x0052C910` remains the stock control-brain selection updater and has one
direct caller in the current static xref pass: `PlayerActorTick` at
`0x00548B00`. It owns selection-state target group/slot clearing, retarget
tick maintenance, facing/movement vector production, and the native target
sentinels at `actor+0x164/+0x166`, but it is not a standalone setter/clearer
API for bot-owned casts.

The globals at `0x00819EC4/0x00819EC8` are not a recovered bot selection API.
Their direct refs are UI/render setup paths and global selection-state array
maintenance (`FUN_005BC8E0`, `FUN_005D2380`, `FUN_0064AA80`,
`FUN_00652D90`). The bot runtime therefore still keeps its explicit
layout-backed selection-state priming/restoration until a real native owner
lifecycle is found.

Active-handle cleanup is still the stock `0x0052F3B0` chain. The xref pass ties
it to `0x0045ADE0` for world-bucket object lookup and `0x00524D70` for the
post-finalize collision/availability test; it calls the active object's
function-table entries at `+0x70` and then `+0x6C`, then writes
`actor+0x27C = 0xFF` and `actor+0x27E = 0xFFFF`.

The live Earth boulder handle resolves a runtime function table at `0x00A6E014`,
but the static image contains zero data and no references at that address. The
table is built or relocated at runtime, so it is useful as a live diagnostic but
not a static ownership seam. The live probe now also asserts that after cleanup
the active group/slot/object are sentinels, the cast skill ids are zeroed, and
the native idle latch state is bounded before the artifact is accepted.

Result: no native replacement setter/clearer or bot release/cancel transition
was recovered in this pass. The current explicit selection restore,
active-handle snapshot, and bounded latch cleanup remain documented blockers
rather than final native-clean code.

## Per-spell handler gate

Every per-spell handler (e.g. `FUN_00545360` for skill 0x3EE "Boulder",
`FUN_00541870` for 0x3EC, `FUN_00544C60` for 0x028) gates init on:

```
(actor+0x5C == 0) && (actor+0x27C == 0xFF)
```

Init allocates a spell object via `FUN_005b7080`, writes `spell_obj+0x5C` →
`actor+0x27C` (group) and `spell_obj+0x5E` → `actor+0x27E` (slot), and
optionally raises `actor+0x160`/`actor+0x1EC` if the animation or no-interrupt
window needs to persist across ticks.

Phase-2 continuation dereferences the cached handle on subsequent ticks.

### Slot-index bypass for gameplay-slot bots (2026-04-21)

The `(actor+0x5C == 0)` clause bakes in a "local player only" assumption.
`FUN_0052F3B0` cleanup mirrors the same early-out (`if (a[0x5C] != 0) return;`).

- **Standalone clone-rail bots** inherit slot 0 from the source player actor
  (player's slot) when `WizardCloneFromSourceActor` at `0x0061AA00` copies
  player state into the clone, so the gate passes and the April-20 verification
  observed spell effects spawning cleanly.
- **Gameplay-slot bots** (routed through
  `Gameplay_CreatePlayerSlot` + `ActorWorld_RegisterGameplaySlotActor`) keep
  their real slot in `actor+0x5C` (1/2/3) so enemies can target them. With that
  slot value the dispatcher still runs but the handler bails on the first gate
  clause before allocating a spell object — cast returned "instant" in the log
  (`ticks=0 saw_latch=0 group_post=0xFF drive_post=0x0`) yet no projectile or
  cone ever rendered.

Fix: `native_cast_gate_patches.inl` byte-checks and patches the exact stock
slot gates at `0x0052F3B9`, `0x0053D1B3`, `0x0053D9D2`, `0x0053E4E8`,
`0x00544C92`, `0x00545393`, and `0x00545C2C`. Bots keep their real gameplay
slot in `actor+0x5C`; stock progression lookups and targeting therefore
continue to observe the bot-owned slot. The pure-primary Ether/Fire handlers
still run their native setup and mana path, but the unlocked projectile branch
now reaches the stock allocator and world-registration calls instead of skipping
them for nonzero gameplay slots. Ether's MagicMissile hit handler at
`0x005F1F00` has a second damage gate at the short branch `0x005F1F39` that
tests the projectile's own group byte at `spell_obj+0x5C`; the same native cast
gate patches unlock that impact branch so bot-owned `0x7D3` projectiles reach
the stock damage call. The spell object itself is initialized from the
allocator's own `spell_obj+0x5C/+0x5E` (not actor identity), so it carries a
valid group/slot through cleanup.

### Control-brain vector contract for primary startup

`PlayerActor_UpdateControlBrainTargeting (0x0052C910)` receives two separate
two-float output vectors, not two scalar outputs:

- `param_2` is `movementVecOut[2]`
- `param_3` is `facingVecOut[2]`

`PlayerActorTick (0x00548B00)` consumes those lanes differently. The movement
vector feeds actor movement accumulators such as `actor + 0x158/+0x15C`; the
facing vector is magnitude-tested for attack/facing intent and drives the
visual/aim lane.

Bot casting must keep those lanes separate:

- never write attack facing into `movementVecOut`
- when a bot has an active pure-primary target, write the normalized target
  direction to both floats of `facingVecOut`
- keep `actor + 0x2A8/+0x2AC` aim-target fields refreshed alongside the
  selection target seed
- when movement and attack happen on the same tick, target-facing beats fallback
  movement heading, while movement direction stays on the movement lane

### Fire projectile direction ownership

`Fire (0x0053DC60)` does not use `actor + 0x2A8/+0x2AC` as its flight
direction. At the projectile-allocation tick it reads `actor + 0x6C`, converts
that heading to a unit vector through `0x00410500`, and copies the result into
`Fireball + 0x13C/+0x140` through `0x00529380`.

Remote transform playback runs after the remote actor's stock tick. A Fire cast
can arm its native action before the projectile is allocated, so a delayed
participant-frame heading must not overwrite the captured cast heading during
that window. Native remote playback retains the cast aim heading until the new
per-cast projectile is observed; after birth, participant transform authority
owns heading again. This preserves the stock Fire initializer without steering
an already-created projectile.

## Player cleanup path

`PlayerActorTick` runs `FUN_00548A00` every tick. Its skill-transition block
(`0x5496e5..0x5497ac`) compares `actor+0x270` against a stored previous skill
id and, when they differ, calls **`FUN_0052F3B0`** on the actor.

`FUN_0052F3B0` decompiles to:

```c
void __thiscall FUN_0052F3B0(ACTOR* a) {
    if (a[0x5C] != 0) return;
    if (a[0x27C] == (char)-1) return;         // already sentinel
    if (*DAT_00819e84 != 5) return;           // world state
    int* spell_obj = (int*)FUN_0045ade0(...); // resolve via world+0x500 table
    if (spell_obj != nullptr) {
        (**(code**)(*spell_obj + 0x70))();    // vtable slot 28 — teardown
        if (FUN_00524d70() == 0)
            (**(code**)(*spell_obj + 0x6c))();// vtable slot 27 — secondary
    }
    a[0x27C] = 0xFF;
    a[0x27E] = 0xFFFF;
}
```

So the player pattern is: press key → dispatcher runs one or more ticks →
handler finishes and drops the latches → keypress ends so `actor+0x270` goes
back to 0 → `PlayerActorTick` detects the transition and calls
`FUN_0052F3B0` → next cast's init gate passes.

## Bot divergence

Bots don't have keypresses. When we dispatch a bot cast we write
`actor+0x270 = skill_id` and never clear it, so the native skill-transition
block in `PlayerActorTick` never fires and `FUN_0052F3B0` never runs.

Consequence: after the first cast, `actor+0x27C` holds a valid cached group
byte. The next cast's init gate `(actor+0x27C == 0xFF)` fails, so init is
skipped and phase-2 runs immediately — but the cached `(group, slot)`
points at a freed or re-used world-storage slot. The dispatcher either
spins chasing a dangling handle or pushes corrupt state into `world+0x500`
until an unrelated FPU loop trips on NaN and hangs the gameplay thread.

## Loader fix: primer-dispatch + watch + explicit cleanup

Location: `ProcessPendingBotCast` in
`src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl`.

The per-tick flow for a bot actor is:

1. `HookPlayerActorTick` in `src/mod_loader_gameplay/gameplay_hooks/actor_tick_hooks.inl`
   calls `original(self)` first. The native `PlayerActorTick` runs
   `FUN_00548A00` for the bot actor, which in turn runs the per-spell
   handler if `actor+0x270` is set — driving the cast naturally each tick.
2. Our `ProcessPendingBotCast` runs after that.

### New-request path

- Consume one pending cast request.
- Compute `aim_heading = atan2(dy, dx) * 180/π + 90`, snap to `[0, 360)`.
- Save pre-cast backups (heading, aim_target, aim_aux, spread_mode).
- Write new aim, force `actor+0x2DC = 0` (non-spread).
- Write `actor+0x270 = skill_id`.
- **Pre-cleanup:** if `actor+0x27C != 0xFF` (prior leaked handle), call
  `FUN_0052F3B0` first so the handler's init gate will pass.
- **Primer dispatch:** one call to `FUN_00548A00` via
  `CallSpellCastDispatcherSafe`.
- Read post-dispatch state. If `group_post == 0xFF` OR
  `(drive_post == 0 && no_int_post == 0)`, the handler completed the cast
  synchronously inside the primer (observed for all projectile and melee
  spells in the current build). Release in place and don't arm the watch.
- Otherwise arm `ongoing_cast` with `ticks_waiting = 0`, `saw_latch = false`.

### Watch continuation path

When `ongoing_cast.active`, we do NOT re-dispatch; native `PlayerActorTick`
is driving the handler. We just:

- Re-pin `actor+0x270` and aim fields (so the handler's per-tick reads see
  consistent state even if something else touches them).
- Read `actor+0x160` and `actor+0x1EC`.
- Bump `ticks_waiting`.
- If either latch byte is non-zero, set `saw_latch = true`.
- Exit condition: `(saw_latch && drive == 0 && no_int == 0)` → "latch_released"
  OR `ticks_waiting >= 300` → "safety_cap" (≈3s at 100Hz, well above any
  observed cast duration).
- On exit, call `CallCastActiveHandleCleanupSafe` (which wraps `FUN_0052F3B0`
  with SEH), clear `actor+0x270`, and restore aim backups. Cleanup failures
  are logged as native failures; active code no longer writes the cached-handle
  bytes directly as a fallback.

### Why a watch and not another pump?

The old pump re-dispatched `FUN_00548A00` every frame until `actor+0x27C`
self-cleared. For spells whose handler never self-clears within the cap
(channeled, multi-stage), the cap tripped and the handle stayed leaked,
reproducing the exact hang the pump was meant to avoid.

The watch inverts the dependency. Native `PlayerActorTick` owns dispatch —
we don't fight it. Our only job is the cleanup call the native
skill-transition block would have made for a player, and we trigger it off
the handler's own "I'm done" signal (latches released) rather than
guessing a frame budget.

## Seams

`config/binary-layout.ini`:

```
[gameplay.hooks]
cast_active_handle_cleanup=0x0052F3B0

[gameplay.offsets]
actor_no_interrupt_flag=0x1EC
actor_active_cast_group_byte=0x27C
actor_active_cast_slot_short=0x27E
actor_aim_target_x=0x2A8
actor_aim_target_y=0x2AC
actor_aim_target_aux0=0x2B0
actor_aim_target_aux1=0x2B4
actor_cast_spread_mode_byte=0x2DC
```

Exposed C++ symbols (`src/gameplay_seams.{h,cpp}`):

- `kCastActiveHandleCleanup`
- `kActorNoInterruptFlagOffset`
- `kActorActiveCastGroupByteOffset`
- `kActorActiveCastSlotShortOffset`
- `kActorAimTargetXOffset`, `kActorAimTargetYOffset`
- `kActorAimTargetAux0Offset`, `kActorAimTargetAux1Offset`
- `kActorCastSpreadModeByteOffset`

Typedef + wrapper:

- `CastActiveHandleCleanupFn` in `src/mod_loader_gameplay/core/native_function_types.inl`
- safe-call declaration in `src/mod_loader_gameplay/core/seh_safe_call_declarations.inl`
- wrapper body in `src/mod_loader_gameplay/bot_actor_calls/spell_cast_calls.inl`

```cpp
using CastActiveHandleCleanupFn = void(__thiscall*)(void* actor);
bool CallCastActiveHandleCleanupSafe(uintptr_t fn, uintptr_t actor, DWORD* seh);
```

## Instrumentation caution

The builder/sink trace stack around `0x0044F5F0`, `0x0044FF03`, `0x00624610`,
and `0x00624652` is invasive. It proved the pure-primary path reaches builder
entry, callback-load, sink entry, and sink inner dispatch, but fully arming that
trace stack also reproduced a downstream crash family on both gameplay-slot bot
casts and local-player Ether casts.

Treat that crash family as trace-induced until proven otherwise. Prefer lighter
seams or tightly windowed traces around the explicit cast request when debugging
pure-primary startup.

## Live verification (2026-04-20)

Game PID 9328, log at
`runtime/stage/.sdmod/logs/solomondarkmodloader.log`.

| Test | Casts | Hangs | Exit path |
|------|------:|------:|-----------|
| `sandbox/cumulative_cast_test.lua` (mixed 0x3EB/0x018/0x020/0x028/0x3EC..0x3F0) | 20 | 0 | queue coalesces; trailing cast → `instant` |
| 5× same spell 0x3EB | 5 | 0 | queue coalesces; trailing cast → `instant` |
| 10× spell-change cycle | 10 | 0 | queue coalesces; trailing cast → `instant` |

All observed casts resolve via the "instant" branch (primer dispatch
completes the handler synchronously). The watch path is compiled, correct
by inspection, and dormant for the spells tested — it exists as the safety
net for any handler that holds the latch across ticks.
