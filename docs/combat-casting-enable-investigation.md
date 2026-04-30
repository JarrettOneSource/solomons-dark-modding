# Combat Casting Enable Investigation

Date: 2026-04-23

## Scope

This note isolates the stock state transition that makes arena combat casting
legal after the Solomon intro / `start_waves` handoff.

The target end state was:

- identify the narrow stock combat-state cluster
- validate it live through Lua/runtime inspection
- decide whether a safe Lua/API combat toggle can be exposed without starting
  waves

## New Typed Surface

The loader now exposes a typed combat-state getter:

- `sd.gameplay.get_combat_state()`

The loader now also exposes the prelude-only enable surface:

- `sd.gameplay.enable_combat_prelude()`

Current behavior of `enable_combat_prelude()`:

- runs on the gameplay thread
- does **not** call `sd.gameplay.start_waves()`
- does **not** increment the arena wave index
- does **not** spawn enemies
- applies the stock Solomon intro prelude sequence recovered from
  `0x0047D450` / `0x0047D570`:
  - `FUN_005C7300(gameplay_runtime, 0, 0)`
  - `FUN_005C7390(gameplay_runtime, 0, 0)`
  - `arena + 0x902A = 1`
  - `FUN_0068B6D0(arena + 0x8528, 0x0F)`
  - `arena + 0x8F14 = 1`
  - `arena + 0x872C = 1`

Current returned fields:

- `arena_id`
- `section_index`
- `wave_index`
- `wait_ticks`
- `advance_mode`
- `advance_threshold`
- `wave_counter`
- `started_music`
- `transition_requested`
- `active`

This is backed by the arena combat window already used by the gameplay-thread
start-waves dispatcher:

- `section_index` -> `arena + 0x8FEC`
- `wave_index` -> `arena + 0x8FF0`
- `wait_ticks` -> `arena + 0x8FF4`
- `advance_mode` -> `arena + 0x8FF8`
- `advance_threshold` -> `arena + 0x8FFC`
- `started_music` -> `arena + 0x8F14`
- `transition_requested` -> `arena + 0x902A`
- `wave_counter` -> `arena + 0x88`
- `active` -> `arena + 0x872C`

## Durable Probe

Focused live probe:

- [`tools/probe_combat_state_transition.py`](../tools/probe_combat_state_transition.py)

What it does:

- launches a clean game session
- drives through new game into hub
- starts `testrun` without waves
- captures `sd.gameplay.get_combat_state()` before `start_waves`
- calls either:
  - `sd.gameplay.start_waves()`, or
  - `sd.gameplay.enable_combat_prelude()`
- captures the same state after dispatch
- writes the artifact to `runtime/probe_combat_state_transition.json`

## Live Result

Clean validated `testrun` snapshot before `start_waves`:

- `wave_index = 0`
- `wait_ticks = 0`
- `advance_mode = 3`
- `advance_threshold = 0`
- `wave_counter = 999999999`
- `started_music = false`
- `transition_requested = false`
- `active = false`

Same scene immediately after stock `sd.gameplay.start_waves()`:

- `wave_index = 1`
- `wait_ticks = 0`
- `advance_mode = 3`
- `advance_threshold = 0`
- `wave_counter = 1`
- `started_music = true`
- `transition_requested = true`
- `active = true`

Observed diff:

- `wave_index`
- `wave_counter`
- `started_music`
- `transition_requested`
- `active`

Latest clean validated `testrun` snapshot after `sd.gameplay.enable_combat_prelude()`:

- `wave_index = 0`
- `wait_ticks = 0`
- `advance_mode = 3`
- `advance_threshold = 0`
- `wave_counter = 999999999`
- `started_music = true`
- `transition_requested = true`
- `active = true`
- `world.wave = 0`
- `world.enemy_count = 0`

This is the key no-spawn result:

- combat-facing state becomes active
- waves remain inactive
- enemy count remains zero

Additional 2026-04-23 no-wave validation:

- `tools/probe_bot_dead_inert.py` enables the combat prelude, kills the bot via
  the Lua memory API, then attempts post-death movement/facing/cast commands.
- The probe passed with:
  - `world.wave = 0`
  - `world.enemy_count = 0`
  - `combat_state.wave_index = 0`
  - `combat_state.wave_counter = 999999999`
- This confirms the prelude-only suppression remains pinned even while gameplay
  bot APIs and actor tick hooks are exercised.

Implementation note:

- `HookWaveSpawnerTick` treats explicit combat-prelude-only suppression as
  authoritative. It returns before the stock wave spawner can advance waves,
  and re-pins the arena state to wave `0` / counter `999999999` / active
  combat-prelude flags while the suppression is active.

Additional live behavior after `enable_combat_prelude()`:

- a synthetic gameplay left click now latches `player_actor + 0x270 = 32`
  while staying in:
  - `wave = 0`
  - `enemy_count = 0`
- before the prelude enable path, the same click left:
  - `player_actor + 0x270 = 0`
  - `player_actor + 0x27C = 0xFF`

Practical interpretation:

- the prelude-only API changes the player cast path materially even without
  wave spawning
- live user validation on the same path reported that combat spell casting now
  appears to work without starting waves

No scene identity change was required at the loader surface:

- before: `scene.name = testrun`, `scene.kind = arena`
- after: `scene.name = testrun`, `scene.kind = arena`

## Static RE

### `ArenaStartWaves` (`0x00465C00`)

Recovered writes / calls:

- sets `arena + 0x902A = 1`
- copies `arena + 0x8FF0` to `arena + 0x8FEC`
- increments `arena + 0x8FF0`
- sets `arena + 0x88 = 0`
- sets `arena + 0x8FF4 = 0`
- sets `arena + 0x9000 = 0`
- if `arena + 0x8FF8 == 4`, rewrites:
  - `arena + 0x8FF8 = 1`
  - `arena + 0x8FFC = 0`
- if `arena + 0x8F14 == 0`, calls the scene/audio manager at
  `0x00409FA0` on global `0x00B3BC28`
- sets:
  - `arena + 0x8F14 = 1`
  - `arena + 0x872C = 1`
- calls:
  - `0x005C9370` with argument `1`
  - `0x0068B6D0(arena + 0x8528, 2)`
- if a prior wave index already existed, also calls:
  - `0x0068B6D0(arena + 0x8528, 3)`

Important correction:

- `0x005C9370` is not a hidden combat gate. It updates the visible `Wave: %d`
  text on the gameplay-global object (`+0x1C30`), so it should be treated as
  UI/presentation work, not as the cast-legal bit itself.

### Solomon intro state 3 (`0x0047D570`)

Recovered combat-prelude handoff on the same arena object:

- calls `0x0068B6D0(arena + 0x8528, 0x0F)`
- if `arena + 0x8F14 == 0`:
  - sets `arena + 0x8F14 = 1`
  - calls the same scene/audio manager `0x00409FA0` on global `0x00B3BC28`
    with the `"combat"` / `"combatprelude"` strings

Important contrast against `ArenaStartWaves`:

- state-3 does **not** directly write the currently recovered:
  - `transition_requested` byte (`+0x902A`)
  - `active` byte (`+0x872C`)
  - `wave_index` (`+0x8FF0`)

So the currently recovered stock path is:

- Solomon intro prelude:
  - `started_music`
  - scene/audio manager `"combat" / "combatprelude"`
  - `68B6D0(..., 0x0F)`
- actual `start_waves`:
  - `transition_requested`
  - `active`
  - `wave_index`
  - `wave_counter`
  - `68B6D0(..., 2/3)`

## Failed Raw-Write Experiment

Live experiment on a fresh no-wave `testrun`:

- manually copied the obvious arena flag cluster from the stock post-wave
  state:
  - `wave_index = 1`
  - `started_music = 1`
  - `transition_requested = 1`
  - `active = 1`
  - `wave_counter = 0`
- then injected a player left-click through `sd.input.click_normalized(...)`

Result:

- the player actor cast window stayed inert:
  - `actor + 0x160 = 0`
  - `actor + 0x1EC = 0`
  - `actor + 0x270 = 0`
  - `actor + 0x27C = 0xFF`
- no stable committed cast state became visible

Interpretation:

- the obvious arena bytes alone are **not sufficient**
- some additional stock helper work still matters
- the remaining likely candidates are the stock helper calls that cannot be
  safely reproduced from the Lua debug thread:
  - `0x00409FA0`
  - `0x0068B6D0`

## Current Conclusion

The stock combat-casting enable path is narrower than full wave spawning, and
the current safe public surface is now the prelude-only enable path.

What is proven:

- `start_waves` flips a compact arena combat-state cluster
- the Solomon intro prelude flips a smaller overlapping subset
- raw cloning of the obvious arena bytes is not enough to make casting legal
- the stock prelude helper sequence can be replayed without spawning enemies
- replaying that sequence yields:
  - `started_music = true`
  - `transition_requested = true`
  - `active = true`
  - `wave_index = 0`
  - `enemy_count = 0`

What is not yet proven:

- the exact minimal reversible helper sequence for a full on/off toggle
- whether a public `disable_combat_prelude()` can be made stock-safe without
  additional teardown recovery

## Decision

Do **not** expose a public Lua on/off toggle yet.

The current safe end-state is:

- expose the typed combat-state getter
- expose the typed no-spawn prelude enable API
- keep using the focused probe to validate stock transitions
- defer the disable path until the reverse transition is explicitly recovered

## Next Targets

1. Recover and main-thread-wrap the exact `0x00409FA0` scene/audio manager call
   used by both state-3 and `ArenaStartWaves`.
2. Recover what `0x0068B6D0(arena + 0x8528, mode)` actually activates for:
   - `mode = 0x0F`
   - `mode = 2`
   - `mode = 3`
3. Re-run the no-wave player-cast experiment using a dedicated gameplay-thread
   API that performs the stock helper sequence instead of raw field writes.
