# Wave Scaling RE

Date: 2026-04-30

## Scope

This note maps the stock wave-spawn and enemy-health path enough to choose a
player-count scaling seam. The immediate question was whether we can scale
enemy counts, especially per wave and burst density, and whether enemy health
already scales as waves progress.

## Short Answer

Yes, there is an easy count seam.

- Data seam: generate or overlay `data/wave.txt` per scaling rule. Existing
  `mods/wave_fast_start` already proves this path with a plaintext wave-file
  overlay.
- Runtime seam: hook the native wave spawner around `WaveSpawner_Tick`
  (`0x0046D000`) or the event handler that constructs the spawner
  (`0x0046C9A0`, case `7`). This keeps stock placement, actor registration,
  enemy config construction, and combat bookkeeping intact.

Enemy health does scale, but the important scaling is mostly data/config
driven, not a simple automatic `wave_index -> hp` ramp.

- `FLAG_HPUP` maps to enemy modifier `1` and multiplies config HP by `1.5`.
- `FLAG_HPDOWN` maps to modifier `2` and multiplies config HP by `0.5`.
- Later retail waves use many more `FLAG_HPUP` entries, so wave progression
  increases effective enemy HP through `wave.txt` composition.
- The arena also has a global future-config HP scalar at `arena + 0x9008`.
- Spawned enemy current HP is additionally multiplied by the arena player-count
  scalar at `arena + 0x8FE4`, refreshed from `0x00649F40`.

Recommended first implementation: scale enemy count only by rewriting or
overlaying wave data, and leave HP alone. If HP scaling is needed later,
`BuildEnemyConfig` finalizes through a clean `arena + 0x9008` scalar.

## Current Data

Retail `../SolomonDarkAbandonware/data/wave.txt` and staged
`runtime/stage/data/wave.txt` are byte-identical in the current runtime:

- SHA-256: `363a985d79dc3ca28fb5ce519f56c436f5269a9bea1bedc7d1a825e8139499fc`
- waves: `42`
- `SPAWN` range: `3..60`, total budget `918`
- `MAXENEMIES` range: `40..80`, values `40, 45, 50, 70, 75, 80`
- groups per wave: `1..17`, total `205`
- configured enemy entries: `680`

Retail configured enemy entries by type:

- `SKELETON`: `344`
- `SKELETONARCHER`: `140`
- `IMP`: `63`
- `SKELETONMAGE`: `58`
- `ZOMBIE`: `41`
- `COFFIN`: `15`
- `DEMON`: `14`
- `WRAITH`: `5`

Relevant health/difficulty flags in retail wave data:

- `FLAG_HPUP`: `175`
- `FLAG_HPDOWN`: `91`
- `FLAG_WEAK`: `72`
- `FLAG_FAST`: `62`
- `FLAG_SLOW`: `32`

The health progression trend is visible in the data: early waves lean on
`FLAG_HPDOWN` and `FLAG_WEAK`, while waves `24+` mostly switch to `FLAG_HPUP`
and armor/equipment modifiers.

## Native Wave Path

Primary functions:

- `0x006387F0` `WaveData_LoadFromFile`: loads `data\wave.txt` and calls
  `WaveData_Parse`.
- `0x00632730` `WaveData_Parse`: parser branch recognizes `WAVE`, `ENDWAVE`,
  `SPAWN:`, `SPAWNDELAY:`, `WAVEDELAY:`, `MAXENEMIES:`, `GROUP`, and monster
  flag strings.
- `0x0046C9A0` wave/timeline event handler: case `7` creates the live wave
  spawner object.
- `0x0046D000` `WaveSpawner_Tick`: decrements spawn timers, selects group
  records, builds enemy configs, and calls stock enemy spawn.
- `0x00469580` `SpawnEnemy`: stock actor creation, placement, registration,
  combat-audio state.
- `0x0046B390` `BuildEnemyConfig`: applies base enemy stats, wave flags, type
  variants, and global arena stat scalars.

Live wave-spawner fields recovered from `0x0046C9A0` and `0x0046D000`:

- `+0x18`: current wave/action record pointer
- `+0x20`: remaining spawn budget
- `+0x24`: spawn delay countdown
- `+0x28`: base spawn delay
- `+0x2C`: longer wave/burst timer
- `+0x30`: randomize spawn delay byte
- `+0x31`: sequential/group-expansion byte
- `+0x34`: sequential group index
- `+0x38`: current group-member index
- `+0x3C/+0x40`: spawn X/Y or spawn-location parameters

`SPAWN` feeds the remaining budget at `spawner + 0x20`. If the parsed budget is
zero for grouped records, the case-7 constructor switches on `+0x31` and sums
the referenced group-member counts to produce the budget.

`SPAWNDELAY` feeds the per-spawn countdown/base-delay path. After a successful
spawn, `WaveSpawner_Tick` resets `+0x24` from `+0x28`, optionally adding random
jitter when `+0x30` is set.

`WAVEDELAY` feeds the longer `+0x2C` timer. While this timer remains positive,
the spawner normally emits one budget unit, resets the spawn delay, and returns.
Once it expires, the same tick can keep looping and drain more of the remaining
budget immediately.

`MAXENEMIES` is not the inner spawn-loop counter. Static evidence ties it to
the wave/trigger advancement gate that uses global enemy count. In practice it
controls how aggressively later waves are allowed to overlap while the live
enemy population is below the threshold. If we scale `SPAWN` materially upward,
we should scale `MAXENEMIES` with it or the stock overlap/cap behavior can
become the limiting factor.

## Count Scaling Seams

Preferred data seam:

- Generate or overlay a scaled `data/wave.txt`.
- Multiply `SPAWN` by the chosen player-count rule.
- Adjust `SPAWNDELAY` lower if the goal is denser bursts, not just more enemies
  over a longer period.
- Adjust `MAXENEMIES` upward with `SPAWN` so the stock overlap gate does not
  hold later waves at the original population thresholds.
- Keep `GROUP`/`FORMATION` contents intact unless we also want composition
  scaling.

Runtime seam:

- Hook `0x0046C9A0` case `7` when the spawner is constructed, or hook
  `0x0046D000` before calling the original spawner tick.
- Mutate `spawner + 0x20` once per spawner/wave to increase budget.
- Mutate `+0x24/+0x28` and/or expire `+0x2C` to make spawns arrive closer
  together.
- Track idempotence by spawner pointer plus wave/record pointer so the budget is
  not multiplied every tick.

Do not reintroduce a manual Lua/API `sd.world.spawn_enemy(...)` path for
active-wave scaling. The loader removed that diagnostic surface because its
partially recovered `0x00469580` call shape could wedge the stock placement
sweep once combat state was populated. The wave-spawner path already uses the
legal stock spawn shape.

## Manual Spawn Call Shape

Focused Ghidra follow-up in `runtime/ghidra_enemy_spawn_call_shapes.txt`
recovered all direct `0x00469580` references:

- `0x0046BC66` in `FUN_0046BB50`
- `0x0046BD82` in `FUN_0046BCD0`
- `0x0046C773` in `FUN_0046C710`
- `0x0046C93C` in `FUN_0046C790`
- `0x00689F14` in `FUN_00689750`

`0x0046BCD0` proves a stock wrapper can call `0x00469580` with
`anchor=0`, an explicit config buffer, and `mode=0`, but its known callers are
actor/AI tick paths inside `FUN_00489000`, not the active wave spawner. The
tail arguments are caller-owned native state, not a recovered universal
contract. `0x00689F14` proves a different script/action shape with a non-null
first stack argument, `mode=1`, and `config=0`.

That evidence is not enough to keep a manual runtime wrapper. The production
API was removed; `tests/re/run_live_enemy_spawn_api_removed_probe.py` verifies
the Lua surface stays absent in both hub and run scenes while native
wave-spawned tracked enemies remain available for tests.

## Health Scaling

Base enemy config defaults are established by `0x00640240`, then modified by
`0x0046B390`.

Base HP recovered from the stock defaults:

- `SKELETON`, `SKELETONARCHER`, `SKELETONMAGE`: `5`
- `WRAITH`: `2`
- `ZOMBIE`: `105`
- `LESSER DEMON`: `400`
- `COFFIN`: `100`
- `IMP PORTAL`: `300`
- boss/special configs include larger stock defaults, for example
  `THE DISCORPOREAL` around `3500`, `DIRE FACULTY` around `2010`, and
  `HEARTMONGER` around `2000`.

Flag-to-modifier mapping relevant to HP/damage:

- `FLAG_HPUP` -> modifier `1` -> `config + 0x58 *= 1.5`
- `FLAG_HPDOWN` -> modifier `2` -> `config + 0x58 *= 0.5`
- `FLAG_STRONG` -> modifier `3` -> damage fields `+0x5C/+0x60/+0x64 *= 1.5`
- `FLAG_WEAK` -> modifier `4` -> damage fields `+0x5C/+0x60/+0x64 *= 0.5`
- `FLAG_HELM`/`FLAG_HORNED`/`FLAG_HOODED` also add flat HP through modifiers
  `9`/`10`/`11`.

The final `BuildEnemyConfig` scalar pass multiplies:

- `config + 0x58` by `arena + 0x9008` for HP
- `config + 0x5C/+0x60/+0x64/+0x68` by `arena + 0x900C..0x9018` for damage
- `config + 0x6C` by `arena + 0x901C` for chase speed
- `config + 0x70` by `arena + 0x9020` for attack speed
- `config + 0xD4` by `arena + 0x9024` for XP/reward

`0x00468060` is a native scalar action that can modify those arena scalar
fields and applies the same change to already-held configs. Mode `0` is the HP
scalar.

Spawned actor health flow:

- `0x00462790` copies `config + 0x58` into `actor + 0x170` and, for normal
  initialization, copies that into `actor + 0x174`.
- `0x00463B50` then multiplies `actor + 0x174` by `arena + 0x8FE4`.
- `0x00462410` refreshes `arena + 0x8FE4` from `0x00649F40`.
- `0x00649F40` counts matching gameplay slot/index entries across up to four
  slots. Static evidence points to this as the stock player-count/current-HP
  multiplier.

Evidence artifact:

- `runtime/ghidra_enemy_wave_spawn_paths.txt`

Important caveat: the stock player-count scalar multiplies current HP
(`actor + 0x174`) after max HP (`actor + 0x170`) is initialized. If we later
touch HP scaling directly, validate which field the healthbar and damage code
use before deciding whether to scale current HP, max HP, or both.

## Implementation Recommendation

For first player-count scaling, do not scale enemy health. Scale only enemy
count and population pacing:

- player count `1`: retail data
- player count `2+`: multiply `SPAWN` and `MAXENEMIES`
- optionally lower `SPAWNDELAY` for denser pressure
- keep enemy flags untouched

The cleanest first patch is a wave-data transformation layer because it is easy
to inspect, easy to diff, and rides the native spawner. A runtime spawner hook is
still a good second seam if we need dynamic scaling without rewriting staged
wave data.

## Manual Spawn Status

`sd.world.spawn_enemy(...)` and `sd.world.get_last_spawned_enemy(...)` are no
longer exported. They were diagnostic-only APIs around a partially recovered
call shape into `0x00469580`, not valid production replacements for stock wave
scaling. Active combat spawns need the native wave spawner's placement,
group-budget, config, and bookkeeping path.

Live coverage:

- `tests/re/run_live_enemy_spawn_api_removed_probe.py`
- `runtime/live_enemy_spawn_api_removed_probe.json`
