# PlayerActor `+0x2D4` field — write/read model

Date-of-analysis: 2026-04-19
Build: `SolomonDark.exe` (exe alloc_base was 0x000D0000 this run)

## Scope

This document captures the full write/read model of `[PlayerActor + 0x2D4]`
based on Ghidra static analysis. It is needed because bot clones of the
local-player class leave this field at `0`, which prevents `FUN_004857b0`
(the MoveStep wrapper) from producing any displacement, and the prior
working model in memory (`actor_per_tick_speed_offset.md`) turned out to
be incomplete.

## Writers of `[X + 0x2D4]`

Found via `find_writes_to_offset.py` on the decompiled game. 10 writes:

| Addr        | Function            | Kind                   | Notes |
|-------------|---------------------|------------------------|-------|
| `0x0041cb26`| `FUN_0041c780`      | FST float              | not PlayerActor class (TODO identify) |
| `0x0047934d`| `FUN_00479150`      | FSTP float             | `Demon` ctor — Demon.vftable at top. Sets `[0xb5]=0`. Wrong class. |
| `0x004799f8`| `FUN_00479940`      | MOV dword              | Likely Demon method. Wrong class. |
| `0x0047d9e0`| `FUN_0047d570`      | FSTP float             | `Demon` combat tick (taunt strings like `SAY_GETHIMBOYS`). Writes `[+0x2D4]=_DAT_007de9d0`. Wrong class. |
| `0x0047e028`| `FUN_0047df30`      | MOV dword              | Likely Demon. Wrong class. |
| `0x00485c5c`| `FUN_004857b0`      | FST float              | **PlayerActor MoveStep wrapper** — reads `[0xb5]`, uses it as scalar, then ramps `[0xb5] += _DAT_007de8a0`. |
| `0x00487b3a`| `FUN_00487300`      | FSTP float (array)     | `[ESI + EAX*0x4 + 0x2d4]` — an array-indexed write to a struct that starts at offset 0x2D4; likely animation/channel scratch. Does not conflict with the scalar semantic above because the base struct has multiple consecutive floats at 0x2D0/0x2D4/0x2D8 treated together. |
| `0x0054a92b`| `FUN_00548b00`      | FSTP float             | **PlayerActorTick** — writes `[0xb5] = FUN_0065fff0(actor, stat_id=0)` **only inside a gate** that requires `FUN_00529670(actor)[0x750] == 0x3EF` (the local-player template ID). |
| `0x007049b7`| `FUN_00704640`      | MOV dword              | Different class (see `[ECX+0x2D4]=EAX`). Not PlayerActor. |
| `0x007049ee`| `FUN_00704640`      | MOV dword              | Same function, writes `0x80` to some `[EAX+0x2D4]`. Not PlayerActor. |

Only `FUN_004857b0` and `FUN_00548b00` mutate `[PlayerActor+0x2D4]`.

## What the field actually means

For PlayerActor whose profile template ID is `0x3EF` (local-player
template):

- **Per tick, start of tick**: `PlayerActorTick` (FUN_00548b00, addr
  `0x00548b00`) walks a chain of profile reads and three stat
  computations. The third stores `FUN_0065fff0(actor, stat_id=0)` into
  `[actor + 0x2D4]`. The call and store live inside
  `if (*(int*)(FUN_00529670(actor) + 0x750) == 0x3ef) { ... }` starting
  at tick asm `0x0054a881`.
- **During a move**: `FUN_004857b0` reads `[actor+0x2D4]` as a scalar,
  multiplies the unit direction by it to compute dx/dy, calls
  `PlayerActor_MoveStep` (FUN_00525800), and then performs
  `[actor+0x2D4] += _DAT_007de8a0` at `LAB_00485c48` (addr `0x00485c48`).
  This is a per-call ramp, not a per-tick ramp.

Consequence: `[0x2D4]` behaves as **seed + ramp** within a tick. Each
tick the seed is set to `FUN_0065fff0(actor, 0)`. Each MoveStep-wrapper
invocation during that tick bumps it by a constant.

## Why `[bot+0x2D4] == 0`

Bot actors are not local-player-template; their profile's `+0x750` is
**not** `0x3EF`. `PlayerActorTick`'s 0x3EF gate at `0x54a881` skips the
whole block, so `[bot+0x2D4]` is never written by tick. The initial
value at construction depends on which PlayerActor-derived class the
bot is; for the `Demon` subclass the constructor sets `[0xb5]=0`.

Because our bot-tick calls `PlayerActor_MoveStep` (0x00525800)
**directly** rather than `FUN_004857b0`, the ramp in `FUN_004857b0`
also never runs. So there is no path by which `[bot+0x2D4]` ever
leaves `0`.

This is consistent with the observed log line:
```
[bots] standalone_mv bot=… before=(694.2,150.0) after=(694.2,150.0)
       d=0.0 dir=(-1.0,0.0) 0x74=1.0 0x2D4=0.0 player_0x2D4=0.0
       0x1BC=0.0 0x1E0=0.0 0x268=0.0 path=player_move_step_ok
```

## Why `[player+0x2D4] == 0` in idle hub

The player IS a 0x3EF template, so `PlayerActorTick` **does** run the
write block each tick. But `FUN_0065fff0` is a full stat calculator
that multiplies base stats, buffs, and per-slot modifiers; for an idle
hub player (not pressing a movement key, no combat buffs applied,
base stat table for slot 0 likely sparse) it returns a value below
the lower threshold `_DAT_007de840` and clamps to `0`.

So an idle player legitimately has `[0x2D4] == 0`. This is not a bug
— the player simply isn't producing any per-tick speed seed until the
movement intent raises one of the inputs `FUN_0065fff0` reads.

This means **mirroring `[player+0x2D4]` onto the bot is wrong** — the
player field is zero when idle; copying zero doesn't help.

## FUN_0065fff0 — the stat calculator, summarized

Signature: `float10 FUN_0065fff0(this, float base_offset, float stat_id, char apply_scaling)`.

Reads from the actor, indexed by `stat_id`:
- `actor[0x24]` — array length for the stat table
- `actor[0x20]` — pointer to stat table; slot at `+0x1c + stat_id*0x70` gives a secondary index
- `actor[0x84]` — base-stat add for this stat
- `actor[0xfc]` — global add
- `actor[0x288 + stat_id*4]` — per-stat add
- `actor[0x120 + secondary*4]` — profile add
- `actor[0xf4]` — global multiplier
- `actor[0x140 + stat_id*4]` — per-stat mult
- `actor[0x100 + secondary*4]` — profile mult
- `actor[0xf8]` — scale factor (applied if stat's flag byte at `+0x27` is set)

Clamps to `0` if final value `< _DAT_007de840`.

Important consequence for bots: even if we call `FUN_0065fff0(bot, 0, 0, 1)`
manually, the result depends entirely on whether the bot's actor-state
fields above are populated. For a freshly-spawned bot, they almost
certainly are not — so the call will return 0 just like for idle
player.

## Writers of other +0x2Dx offsets in the same tick block

Inside the 0x3EF branch of PlayerActorTick:
- `[actor+0x2D0]` (`[0xb4]`): `FUN_006600f0(...) / *(profile+0xc00)` — a ratio.
- `[actor+0x2D4]` (`[0xb5]`): `FUN_0065fff0(actor, 0, 0)` — stat 0.
- `[actor+0x2D8]` (`[0xb6]`): `FUN_0065fff0(actor, 1, 0)` — stat 1.

0x2D8 is initialized to 1.0f (`0x3f800000`) in the Demon ctor; that is
the "walk cycle scale" used as a multiplier.

## Asm-level confirmation

`FUN_004857b0` around `0x00485b18` (before MoveStep):
```
00485b18 FLD   float ptr [ESI + 0x2d4]    ; load scalar
00485b2f FLD   ST0                        ; dup
00485b37 FMUL  float ptr [ESP + 0x4c]     ; * dir_x
00485b3b FSTP  float ptr [ESP + 0x1c]     ; save dx
00485b3f FMUL  float ptr [ESP + 0x50]     ; * dir_y
00485b43 FSTP  float ptr [ESP + 0x20]     ; save dy
00485b59 CALL  0x00525800                 ; MoveStep(ctx, actor, {dx,dy})
```
After MoveStep, at `0x00485c48`:
```
00485c48 FLD   float ptr [ESI + 0x2d4]
00485c4e FADD  double ptr [0x007de8a0]    ; += 0.05 (double)
00485c5c FST   float ptr [ESI + 0x2d4]    ; write back
00485c62 FDIV  double ptr [0x007de910]    ; / 3.0
00485c68 FMUL  double ptr [0x007849e8]    ; * 0.1
00485c6e FADD  float ptr [ESI + 0x218]
00485c7c FST   float ptr [ESI + 0x218]    ; also updates 0x218
```

So the field is both a displacement scalar (pre-MoveStep) and a
self-ramping walk-cycle counter (post-MoveStep, +0.05/call). `[0x218]`
is a cumulative `(counter/3 * 0.1)` integrator.

## Key globals dumped

| Symbol              | Kind    | Value |
|---------------------|---------|-------|
| `_DAT_007de8a0`     | double  | `0.05` — per-call phase increment for 0x2D4 ramp |
| `_DAT_007de840`     | double  | `0.0` — FUN_0065fff0 zero-clamp threshold (any positive value passes) |
| `_DAT_007de910`     | double  | `3.0` — 0x218 integrator divisor |
| `_DAT_007849e8`     | double  | `0.1` — 0x218 integrator multiplier |
| `_DAT_007de808`     | double  | `0.5` |
| `_DAT_007de888`     | double  | `180` — likely degrees/pi-half |
| `_DAT_007de878`     | double  | `360` — degree wrap |
| `_DAT_007de820`     | double  | `1.0` |
| `_DAT_007de960`     | double  | `25` |
| `_DAT_007de870`     | float   | `0.5` |
| `_DAT_007de8a8`     | float   | `3.14159` — pi |
| `_DAT_007de9d0`     | float   | `2.0` — constant written to `[Demon+0x2D4]` in combat tick |
| `_DAT_00786ab0`     | double  | `4096` — large constant |
| `_DAT_007847c8`     | double  | `50` |
| `_DAT_007de8f0`     | double  | `0.25` |

## Open questions

1. **What stat is stat_id=0?** The SolomonDark stat table at
   `DAT_0081c264 + 0x1654` is a pointer array indexed by actor class
   (`[actor+0x5c]`). We should extract this table and identify which
   slot 0 maps to. A follow-up `dump_stat_table.py` Ghidra script
   could enumerate it.
2. **Bot profile template ID.** Runtime probe needed: read
   `[bot_actor+0x5c]`, use it to index `[DAT_0081c264 + 0x1654 +
   class*4]`, follow to profile struct, read `[profile+0x750]`.
   If that equals 0x3EF, PlayerActorTick SHOULD be writing [0x2D4].
   If not, we now know which template class the bot is and what its
   own equivalent speed field is (e.g. 0x298 for 0x3EE).
3. **Does `FUN_004857b0` vs direct `FUN_00525800` matter for our
   hook?** The mod-loader currently calls `FUN_00525800` directly at
   `bot_registry_and_movement_tick_and_movement.inl:371`. If we
   switched to calling `FUN_004857b0`, the ramp would happen, but we
   would still need to seed `[bot+0x2D4]` to a non-zero value first
   since the ramp starts from whatever is there.

These open questions block any "compute bot speed ourselves" fix. We
should resolve them before editing code, per the understand-before-fix
rule.

## Implications for the bot-stationary bug

- Do **not** mirror `[player+0x2D4]` onto the bot — that value is often
  zero by design.
- Do **not** hard-code a non-zero seed — that value's units are unclear
  until questions 1-3 above are answered.
- **Next step**: (a) dump the stat table to learn what stat 0 is; (b)
  dump the globals 0x007de8a0 and 0x007de840; (c) decide whether to
  call `FUN_004857b0` (the wrapper, which ramps and reads speed from
  `[0x2D4]`) instead of `FUN_00525800` directly.

## File references

- `Mod Loader/SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_motion_helpers.inl:137-163`
- `Mod Loader/tools/ghidra-scripts/find_writes_to_offset.py`
- `Mod Loader/tools/ghidra-scripts/decompile_targets.py`
