# Spell cast cleanup chain (player vs. bot)

Investigation that led to the watch-based bot cast handle release.
Supersedes the 180-frame pump workaround documented in commits that
landed task #27.

## The native cast pipeline

Three addresses matter:

| Symbol | VA | Description |
|--------|----|----|
| `PlayerActorTick` | `0x00548B00` | Per-tick driver for a player actor (`__thiscall`). |
| `FUN_00548A00` | `0x00548A00` | Spell-cast dispatcher (`__thiscall`). Routes on `actor+0x270`. |
| `FUN_0052F3B0` | `0x0052F3B0` | Cast-active-handle cleanup (`__thiscall`). Releases the cached spell object. |

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

`world + 0x500 + (group * 0x800 + slot) * 4` is the cached-handle dereference used
by both `FUN_00548A00` (phase 2, after init) and `FUN_0052F3B0` (on cleanup).

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
- **Gameplay-slot bots** (task #18, routed through
  `Gameplay_CreatePlayerSlot` + `ActorWorld_RegisterGameplaySlotActor`) keep
  their real slot in `actor+0x5C` (1/2/3) so enemies can target them. With that
  slot value the dispatcher still runs but the handler bails on the first gate
  clause before allocating a spell object — cast returned "instant" in the log
  (`ticks=0 saw_latch=0 group_post=0xFF drive_post=0x0`) yet no projectile or
  cone ever rendered.

Fix: `InvokeWithLocalPlayerSlot` in `ProcessPendingBotCast`
(`bot_registry_and_movement_motion_helpers.inl`) wraps each native
dispatcher/cleanup call with a transient `actor+0x5C = 0` write and an immediate
restore to the saved slot. The flip lives entirely inside the synchronous
`__thiscall` into the game, so hostile AI / HUD / rendering observe the bot's
true slot on every other access. The spell object itself is initialized from
the allocator's own `spell_obj+0x5C/+0x5E` (not actor identity), so it still
carries a valid group/slot after the bot's slot is restored.

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
`src/mod_loader_gameplay/bot_registry_and_movement_motion_helpers.inl`.

The per-tick flow for a bot actor is:

1. Tick hook at line ~468/540 in `dispatch_and_hooks_tick_and_render_hooks.inl`
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

When `ongoing_cast.active`, we do NOT re-dispatch — native `PlayerActorTick`
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
  with SEH; on SEH fall back to writing the 0xFF/0xFFFF sentinels directly),
  clear `actor+0x270`, restore aim backups.

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

Typedef + wrapper (`src/mod_loader_gameplay.cpp`,
`bot_registry_and_movement_actor_call_wrappers.inl`):

```cpp
using CastActiveHandleCleanupFn = void(__thiscall*)(void* actor);
bool CallCastActiveHandleCleanupSafe(uintptr_t fn, uintptr_t actor, DWORD* seh);
```

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
