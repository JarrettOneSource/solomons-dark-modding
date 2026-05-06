# Native Seam RE Cleanup Plan

This pass exists to remove hardcoded gameplay facts and loader-owned
workarounds only after the native contract is understood. Runtime fixes are
blocked until each item has:

1. a static source inventory;
2. a passing static regression test or captured baseline;
3. Ghidra evidence for the relevant native table, function, field writer, or
   object lifecycle;
4. Lua live-memory evidence against the staged game;
5. a documented replacement seam with ownership, inputs, outputs, and failure
   behavior.

## Current Evidence Gate

Static checks live in `tests/re/`:

```bash
python3 tests/re/run_static_re_tests.py
```

Live RE checks also live in `tests/re/`:

```bash
python3 tests/re/run_live_native_spell_stats_probe.py
python3 tests/re/run_live_bot_mana_writer_probe.py
python3 tests/re/run_live_bot_native_mana_spend_probe.py
python3 tests/re/run_live_pure_primary_startup_probe.py --json
python3 tests/re/run_live_boulder_impact_projection_probe.py
python3 tests/re/run_live_source_profile_negative_probe.py --json
python3 tests/re/run_live_source_profile_writer_probe.py --json
python3 tests/re/run_live_cast_shim_snapshot_probe.py --json --timeout 180
python3 tests/re/run_live_lua_bot_enemy_semantic_probe.py --json
```

The static tests now enforce that the old primary mana arrays and Earth boulder
damage table stay removed. The live probe launches the staged game, drives to a
testrun, uses the Lua memory bridge, and queues all five primary skills through
`sd.bots.cast`; the run fails if the loader cannot resolve live native spell
stats from the bot progression object. The bot mana-writer probe traces
`0x0052B150` during bot casts. It first queues coordinate-only Earth startup in
a no-wave run and fails if stale `actor+0x2D0` data causes a bot MP drain; it
then targets a real native wave enemy and requires bot-actor negative native
delta hits, a plausible per-update delta relative to the native-resolved spend
rate, and a real MP decrease on the bot's live progression state. The native
mana-spend probe then isolates the Earth bot, forces bot MP, queues an Earth
primary against a real wave enemy, and fails unless stock spell-handler
execution spends bot MP without changing the gameplay local-player actor
pointer.
`tests/re/run_live_pure_primary_startup_probe.py --json` covers the PerCast
side: Fire and Ether pure-primary casts must leave startup through the native
lifecycle, trace stock bot-owned `0x0052B150` mana deltas, and reduce bot MP
before the probe passes. It also asserts the pure-primary startup log shows a
real actor-owned equip runtime (`actor1fc_plus4_type=0x1B5C`) and none of the
former local slot/window shim markers.

## Completed This Pass

- Primary mana arrays were removed from
  `bot_runtime/public_api/casting_api.inl`.
- The duplicated primary combo build-skill mapping was removed from
  `bot_runtime/public_api/casting_api.inl`; combo and pure-primary mana now
  resolve from the shared native primary selection helper instead of owning a
  second build-skill table.
- Earth boulder base damage table was removed from
  `mod_loader_gameplay/bot_casting/resource_state.inl`.
- The interim staged-file reader was removed. The loader now uses
  `native_spell_stats`, which calls `0x00666020`
  (`Skills_Wizard::BuildPrimarySpell`) against the bot's live progression
  runtime and reads the native output array at progression `+0x774/+0x778`.
  Pure Ether/Water/Air/Earth mana outputs are display-scaled by the native
  double at `0x007DE810`; bot MP spending divides by that live binary scalar
  and logs both the stat output and the spend cost.
- Ghidra confirmed the native mana/stat path:
  - `0x0065E760`: native float lookup for keys such as `mManaCost`.
  - `0x006741B0`: native combo/entry mana resolver.
  - `0x00666020`: native Skills_Wizard primary build-skill/stat builder; pure
    primary outputs expose damage and mana at indices 0/1, while combo outputs
    expose damage channels and mana at index 2.
- `runtime/ghidra_primary_spell_builder_resource_paths.txt` records that
  `0x00666020` writes the current spell id and the output array at
  progression `+0x774/+0x778`, not HP/MP resource fields. Cast preparation now
  trusts `0x0065F9A0`'s native ratio-preserving resource recompute instead of
  snapshotting and restoring HP/MP from loader code.
- Lua live validation confirmed the staged loader reaches `startup-complete`,
  exposes the Lua bridge, enters a testrun, materializes a bot, and queues
  Fire, Water, Earth, Air, and Ether primary casts without staged resolver
  failures.
- Ghidra and Lua trace evidence identified `0x0052B150` as the stock mana
  delta function and `0x0052B171` as its local-actor gate. The loader now
  byte-checks that branch and patches it once with the other native cast gates,
  so stock spell handlers own bot MP mutation through their existing
  `0x0052B150` calls. The loader no longer writes progression MP directly,
  calls a manual `TrySpendBotMana` path, or swaps `gameplay+0x1358` around a
  synthetic local-player mana window.
- Ghidra and live traces also showed Earth primary's native mana path spends
  from `actor+0x2D0`, which `PlayerActorTick (0x00548B00)` rebuilds only after
  `PlayerControlBrain_Update (0x0052C910)` produces a real facing/control
  vector. Coordinate-only bot startup in a no-wave run can leave that field
  stale, so cast preparation invalidates the per-second native rate field and
  manual post-stock dispatch is gated until the field has been repopulated to a
  finite value within the native-resolved spend-rate envelope. The loader never
  populates `actor+0x2D0` from its own mana value; it only rejects stale native
  config before dispatch.
- `runtime/ghidra_mana_delta_instructions.txt` records the gate
  (`CMP ESI,[gameplay+0x1358]` / `JNZ 0x0052B496`) and the native MP stores.
  `runtime/ghidra_mana_delta_callers.txt` records the stock spell-handler
  callers, including Earth primary.
- `tests/re/run_live_bot_native_mana_spend_probe.py` validates the bot path in
  the staged runtime: an Earth PerSecond cast traces a negative bot-actor
  native mana delta, reduces the bot's live MP, and leaves the gameplay
  local-player actor pointer unchanged.
- `tests/re/run_live_pure_primary_startup_probe.py --json` validates the
  Fire/Ether PerCast branch in the staged runtime: both pure-primary casts must
  trace stock bot-owned native mana deltas, reduce bot MP, and start from the
  bot actor's direct equip runtime instead of a local-slot sink fallback.
- `runtime/ghidra_pure_primary_equip_sink_paths.txt` proves
  `0x0052DA80` checks `actor+0x1FC` before falling back to
  `DAT_0081C264 + actor_slot * 0x64 + 0x1410`, then calls `0x00570D80` on the
  actor-owned sink and reads the current item from `sink+0x4`. The loader no
  longer hooks the sink accessor or swaps local slot state around pure-primary
  startup.
- Earth boulder release/damage was deepened with Ghidra and live evidence:
  - `0x00544C60`: Earth primary handler creates/updates boulder object `0x7D5`.
  - `0x005E5450`: native finalizer computes released damage from the live
    Boulder object field `spell_object_release_base_damage=0x1F8` times
    `size^2`, with native cap/floor handling.
    Early input release first applies the native `0x007DE808` half-scale to
    the staged damage/base-damage fields; the finalizer then clamps with the
    native floor at `0x007DE8F0` and cap scale at `0x00784740`.
  - `0x005E5450`/`0x0060B700`: native Boulder release damage and secondary
    launch scale from the live spell object's current charge. Live retarget
    probes proved the target-radius-only scan is too broad, and the finalizer
    center radius is too small for fired Boulder cleanup. `0x00642090` uses
    the stock radius-query predicate `distance^2 < query_radius^2 +
    actor_collision_radius^2`; the loader reports that overlap and may use it
    to pick an already-overlapped victim when no current target is available.
    The normal target-lethal release rule uses the live current target selected
    through bot facing/retarget state and releases once live native
    projected damage from the active Boulder object can kill that target. The
    fired Boulder then continues through the native projectile/collision path.
    The loader no longer writes guessed `stat_source+0x8BCC..0x8BD8` query
    context and does not rebuild the Skills_Wizard stat output array while the
    Boulder is already charging.
  - `0x004621B0`: the object `+0x58` vfunc reads the world's active query
    context, so it is not a standalone damage formula source. The native
    `Skills_Wizard` damage output scale at `0x007A03F0` remains logged as
    diagnostic RE context, but the active Boulder release path uses the
    finalizer's live released-damage value directly for HP lethality. The
    active release policy therefore compares live target HP against
    `clamp(base_damage * 0.5 * size^2)` for the live target,
    or uses the stock max-size release path when lethal damage plus native
    victim-scan eligibility is not yet proven. While the boulder is still
    charging, the projection follows the bot's live target through the same
    facing-target seam used by combat retargeting; when release is requested,
    the release target is frozen for cleanup and logs. The loader preserves the
    native input falling edge so stock cleanup can finalize the boulder, and it
    pins the chosen charge/release-charge plus the recovered growth-stop field
    that native `0x00544C60` sets once the release threshold is crossed.
  - `tests/re/run_live_boulder_impact_projection_probe.py` validates the
    target-lethal or max-size release path against a live wave enemy so the
    victim is in the native damage scan, not just a forced-position actor.
  - `tests/re/run_live_boulder_retarget_probe.py` validates the target swap
    contract against two live wave enemies: the held Boulder follows the bot's
    live facing target while charging, swaps early in the held-charge window,
    freezes that retargeted actor at release, removes that actor through native
    damage, and leaves the original target alive after it has been moved outside
    the impact radius.
- Synthetic source-profile RE is documented in
  `docs/native-source-profile-re.md`. Ghidra verifies the native consumer
  (`0x005E3080`) and clone-from-source actor path (`0x0061AA00`), but no safe
  native producer/materializer for arbitrary bot appearance profiles has been
  recovered yet. The negative scan proves `0x005B7080`/`0x005E9A90` create only
  a blank source actor shell; the expanded candidate pass rejects `0x00515290`
  as an unrelated `0x139A/0x139E` object setup; and live validation records
  finalized actors with `actor+0x178 == 0` plus zero finalized-player source
  window writes in `runtime/live_source_profile_negative_probe.json` and
  `runtime/live_source_profile_writer_probe.json`.
- Cast-state RE is now layout-backed for the recovered fields:
  - `runtime/ghidra_stock_tick_slot_shim_cast_paths.txt` proves
    `0x00548B00`, `0x00548A00`, `0x0052F3B0`, and `0x0052C910` ownership.
  - `runtime/ghidra_cast_spell_object_handlers.txt` proves the
    `0x0045ADE0` world-bucket lookup and `0x00545360` spell-object phase and
    release fields.
  - `tests/re/run_live_cast_shim_snapshot_probe.py --json --timeout 180` writes
    `runtime/live_cast_shim_snapshot_probe.json` and validates a live native
    spell object plus slot/progression restoration.
  - `runtime/ghidra_cast_slot0_dispatch_xrefs.txt` and
    `runtime/ghidra_cast_slot0_gate_offset_accesses.txt` refresh the blocker:
    `0x00548A00` remains reachable only from `PlayerActorTick`,
    `0x0052F3B0` and the checked handlers still gate on `actor+0x5C == 0`,
    and no per-actor dispatcher/cleanup seam is recovered.
  - `runtime/ghidra_selection_lifecycle_xrefs.txt`,
    `runtime/ghidra_selection_and_cleanup_targets.txt`,
    `runtime/ghidra_selection_brain_offset_accesses.txt`,
    `runtime/ghidra_active_spell_lifecycle_xrefs.txt`,
    `runtime/ghidra_cast_latch_offset_accesses.txt`, and
    `runtime/ghidra_boulder_spell_object_vtable_slots.txt` refresh the
    selection/latch side: `0x0052C910` is still only called from
    `PlayerActorTick`, the selection globals at `0x00819EC4/0x00819EC8` are
    UI/render state rather than a bot-safe setter API, active-handle cleanup
    remains tied to `0x0052F3B0`, and the live boulder dispatch table is
    runtime-built rather than a static vtable that can be used as an ownership
    seam.
- Lua bot enemy targeting no longer duplicates the native wave-enemy object
  type in Lua. The C++ scene actor producer owns the native type classification
  and publishes `actor.tracked_enemy`; `mods/lua_bots/scripts/lib/lua_bots/combat.lua`
  consumes that semantic flag.
- Remaining active probe/runtime native addresses are now layout-backed. The
  first-chance movement-collision recovery EIPs, wizard HP/MP default globals,
  cast trace body EIPs, combat wave-text field, standalone collision diagnostic
  flags, skill-choice stress offsets, and shared-hub movement probe callback
  offsets live in `config/binary-layout.ini`. The static suite rejects the old
  direct-address forms in runtime code and active probes.

## Current Limits

This pass did not claim the entire bot casting path is native-clean. The
remaining rows below still need their own Ghidra and Lua evidence before
runtime cleanup. Actor source profiles, creation defaults, movement/collision
ownership, and selection state remain tracked smell sources. The prior
local-slot cast shim and pure-primary equip-sink shim are removed from active
runtime code.

The PerCast spend branch is now live-proven for Fire and Ether, but the
pure-primary driver still terminates the current test casts through
`target_lost` after startup rather than a complete native target lifecycle.
That remains part of the broader pure-primary/cast-latch cleanup, not a reason
to reintroduce direct MP writes.

The May 1, 2026 full autonomous crash is resolved. The dump at
`runtime/stage/.sdmod/logs/solomondarkmodloader.crash.20260501_090713_326.tid21608.dmp`
showed an execute fault through the spell dispatcher prologue: the probe armed
`trace_spell_cast_dispatcher_body=0x00548A03`, which resolves inside the
loader's existing 5-byte `E9` hook at runtime `0x00818A00`. The trace hook then
patched the middle of that relative-jump operand and corrupted the dispatcher
jump target. Runtime tracing now rejects windows that overlap an existing
relative jump patch, and `untrace_function` resolves executable/game-image
addresses through the same path as `trace_function`.

The fixed staged runtime was validated with:

```bash
python3 tests/re/run_live_trace_overlap_guard_probe.py --json --timeout 90
python3 tools/probe_bot_autonomous_combat_validation.py --skip-hp-watch --output runtime/probe_bot_autonomous_combat_validation.full-after-selected-bot-fix.rerun.json
```

The full autonomous probe now passes with two managed bots present, selects the
Fire pure-primary bot for scoped diagnostics, records closest-target switching,
native cast/mana evidence, and HP damage, and leaves no fresh crash artifact.

## Tooling

- Ghidra: run through `scripts/Invoke-GhidraHeadless.ps1` so replica locks are
  managed and the source project remains read-only.
- Lua live RE: launch through `dist/launcher/SolomonDarkModLauncher.exe` and
  query with `tools/lua-exec.py` or `scripts/Invoke-LuaExec.ps1`.
- Static tests: keep durable, reviewable checks in `tests/re/`, not as one-off
  chat snippets.

## Investigation Register

| Area | Current source | Required native evidence | Replacement direction |
| --- | --- | --- | --- |
| Primary mana costs | `bot_runtime/public_api/casting_api.inl`, `native_spell_stats.cpp`, `pending_cast_preparation.inl` | done: `0x00666020` live progression stat builder and `+0x774/+0x778` output array; `runtime/ghidra_primary_spell_builder_resource_paths.txt` shows pure Ether/Water/Air/Earth outputs multiply `mManaCost` by the native double at `0x007DE810`, while `0x0065F9A0` preserves current resource ratios when recomputing max values | done: mana cost resolves from live native Skills_Wizard output, spend cost normalizes display-scaled pure-primary outputs through the live native scalar, held casts require the native per-second rate to start, and there is no staged wizard-skill file reader or loader-owned HP/MP snapshot restore around native stat/refresh calls |
| Primary build-skill mapping | `scene_and_animation_bot_priming_and_selection.inl` | done: `0x00666020` native `Skills_Wizard` primary builder returns the active build spell id and writes progression `+0x750`; live resolution now enumerates native primary entry pairs, calls the builder against bot-owned progression, restores any previous current spell id, and validates the returned/current id instead of carrying a loader table | done: bot mana and cast selection share `native_spell_stats` primary selection resolution; active code has no skill-id-to-build-id table, no reverse primary build-id switch, and no duplicate Lua primary entry map |
| Manual mana spend | `bot_casting/resource_state.inl`, `pending_cast_processing.inl`, `native_cast_gate_patches.inl` | done: player MP writer watch, `0x0052B150` native delta function, `0x0052B171` local-actor gate branch, stock spell-handler callers in `runtime/ghidra_mana_delta_callers.txt`, and live bot-actor negative delta traces | done: native local-actor gate is layout-backed, validated as a live `jnz rel32` branch, captured for restore, and patched once; stock spell handlers own bot MP mutation, while loader code only performs live MP admission/depletion observation and never swaps `gameplay+0x1358` or manually spends MP |
| Earth boulder damage | `resource_state.inl`, `boulder_damage_projection.inl`, `native_spell_stats.cpp` | done: Earth primary native stat output, active Boulder object release-base field `0x1F8`, damage output diagnostic scale `0x007A03F0`, finalizer floor/cap globals `0x007DE8F0`/`0x00784740`, native victim-scan radius predicate, and live victim/removal probe | done: held-cast base damage resolves from the live Boulder object's `spell_object_release_base_damage=0x1F8` field and is projected through the native release/finalizer floor and cap globals; no guessed query-context writes and no mid-charge Skills_Wizard stat rebuild; Boulder releases at native max size or once live projected release damage is enough to kill the targeted enemy; held charging follows the live bot target, freezes that target at release, preserves the stock input falling edge for native cleanup, and pins charge/release-charge plus the recovered native growth-stop field so cleanup does not keep charging toward max |
| Synthetic source profiles | removed hardcoded profile buffer and element-color table | done for active code: native consumer `0x005E3080`, clone path `0x0061AA00`, source actor ctor `0x005E9A90`, stock new-character choice path `0x005D0290`, and native `Skills_Wizard` color seam `0x00660760` are documented; live probes verify finalized actors keep `actor+0x178 == 0`; `runtime/ghidra_color_vector_helpers.txt` and `runtime/ghidra_color_mix_scalar_scan.txt` keep the native color-helper evidence current | done: active runtime stages a transient native-derived source profile from `0x00660760`, lets `0x005E3080` build the descriptor, clears the staging pointer before clone publication, uses live descriptor/native color payloads directly, and has no hardcoded element color table or inverse color reconstruction constants |
| Default ally HP | `spawn_standalone_wizard.inl` | done: `0x0061AA00` clone path calls `0x00674EE0` progression ctor and `0x0065F9A0` stat recompute; ctor globals are 50 HP and 100 MP | done: loader HP overwrite removed; standalone clone rail preserves native progression defaults |
| Enemy spawn call shape | removed manual `sd.world.spawn_enemy` runtime API | done for active code: wave scaling is legal through `0x0046D000`/`0x0046C9A0` and `data/wave.txt`; direct `0x00469580` call shapes are recorded in `runtime/ghidra_enemy_spawn_call_shapes.txt`; `tests/re/run_live_enemy_spawn_api_removed_probe.py` covers API removal and native wave enemy availability | done: no hardcoded manual spawn wrapper remains in production; use wave seam for scaling and stock tracked enemies for probes |
| Pathfinding policy | `bot_pathfinding_grid_setup.inl`, `bot_pathfinding_cell_math.inl`, `bot_pathfinding_traversability.inl` | partial: native grid/circle/placement-query fields proven in `runtime/ghidra_pathfinding_movement_paths.txt`; policy scalar provenance recorded in `runtime/ghidra_pathfinding_policy_scalar_scan.txt`, `runtime/ghidra_pathfinding_policy_scalar_decompile.txt`, and `runtime/ghidra_pathfinding_policy_float_globals.txt`; no native arbitrary A-to-B planner recovered | done for raw path constants: use `[gameplay.pathfinding]` seams plus live circle-policy coverage; keep loader-owned A* documented |
| Registered GameNpc movement | removed inactive registered GameNpc rail | blocked for future feature work: `0x005E9D50`, `0x005EA450`, `0x006042C0`, `0x00483480`, and `runtime/ghidra_player_gamenpc_movement_seed_paths.txt` prove goal/tracked-slot/current-target/cadence fields; `runtime/ghidra_registered_gamenpc_publication_blockers.txt` proves the previous clone handoff reaches player-family size `0x398`, not a long-lived `0x1397` actor; `runtime/ghidra_registered_gamenpc_publication_xrefs.txt` and `runtime/ghidra_registered_gamenpc_publication_expanded.txt` limit `0x00466FA0` to the preview/source path and keep movement seams separate from publication; `tests/re/run_live_registered_gamenpc_blocker_probe.py` verifies shared-hub bots stay on the standalone rail with `gamenpc_count=0` and zero GameNpc movement traces | done: inactive blocked rail, public kind, safe wrapper, movement stub, and project entries are removed from active runtime; only RE artifacts remain |
| PlayerActor movement seeds | `wizard_bot_movement_step.inl` | done for active movement: `0x0052A500`, `0x0052C910`, `0x00548B00`, and `PlayerActor_MoveStep` recover constructor/control-brain/tick contracts for `+0x218` and `+0x158/+0x15C`; no native bot input producer recovered; Fire speed regression traced to bypassing the native PlayerActorTick speed envelope, now backed by `0x007DE810`, `0x00784740`, `0x00784E20`, actor `+0x120/+0x74`, and progression `+0x90` | done: movement now executes one native `PlayerActor_MoveStep` request from the layout-backed accumulated vector and live cap, no longer tries hardcoded rotated recovery detours, and `tests/re/run_live_bot_native_speed_probe.py` verifies baseline, lowered live progression speed, and post-Rush Fire movement against the recomputed native cap |
| Standalone collision | removed loader-owned collision push bridge | done for active code: `0x0061AA00`/`0x0063F6D0`/`0x005217B0` prove native clone registration and grid-cell binding; `0x00521B80`/`0x00522500`/`0x00522C00`/`0x00522B20` prove the stock overlap-response context; `runtime/ghidra_standalone_collision_ownership_xrefs.txt` and `runtime/ghidra_standalone_collision_field_writes.txt` confirm `0x00622D90`/`0x005217B0` are position-rebind/cell-repair seams and that `0x00525800` owns the direct overlap-response calls, while `tests/re/run_live_standalone_collision_probe.py` and `runtime/live_standalone_collision_probe.json` preserve the historical live evidence for the removed bridge | done: active tick code no longer runs a loader-owned circle push or writes bot positions for collision separation; recover a native dynamic overlap-response lifecycle before adding standalone actor pushback again |
| Stock tick position restore | `player_actor_tick_hook.inl` | done for active code: `runtime/ghidra_stock_tick_restore_paths.txt` refreshes `0x00548B00`, `0x00525800`, `0x0052C910`, and `0x0052A500`; `runtime/ghidra_stock_tick_ownership_xrefs.txt` shows `0x00548B00` is only a vtable target, `0x0052C910`/`0x00548A00` are only reached from `PlayerActorTick`, and `0x00525800` is a shared executor rather than a bot ownership handoff; `runtime/ghidra_stock_tick_input_offset_accesses.txt` keeps `+0x158/+0x15C`, `+0x218`, `+0x21C`, and control-brain `+0x30/+0x34` tied to the PlayerActor tick/control-brain path; `tests/re/run_live_stock_tick_restore_probe.py` and `runtime/live_stock_tick_restore_probe.json` remain the regression evidence for the removed restore | done: active tick code no longer snapshots and rewrites bot X/Y around stock `PlayerActorTick`; stale inputs are cleared before stock tick and movement is applied through the native move-step executor |
| Slot-0 cast shim | removed `local_player_cast_shim.inl`; added `native_cast_gate_patches.inl` | done: `runtime/ghidra_cast_slot0_dispatch_xrefs.txt` and `runtime/ghidra_cast_slot0_gate_offset_accesses.txt` identify the exact slot gates; `0x0052F3B9`, `0x00544C92`, `0x00545393`, and `0x00545C2C` are now layout-backed native cast gate patches validated from live instruction shape, so gameplay-slot bots keep their real `actor+0x5C` and live progression slot | done: no local-slot/progression redirect remains in active code; failed branch validation aborts input injection instead of silently falling back |
| Pure-primary equip sink | removed `equip_attachment_hook.inl` and local pure-primary actor/window slot fallback state | done: `runtime/ghidra_pure_primary_equip_sink_paths.txt` proves `0x0052DA80` uses the actor-owned equip runtime at `actor+0x1FC`, dereferences its visual sink at `+0x30`, calls `0x00570D80`, and reads the current staff item from `sink+0x4`; the fallback slot path is only for missing actor equip state | done: bots must carry the real actor-owned equip runtime; active startup logs require `actor1fc_plus4_type=0x1B5C`, and there is no sink accessor hook, local slot item swap, or local actor window shim in active runtime code |
| Skill selection state | `skill_selection_rules.inl` | done: `0x0052C910` proves selection-brain target slot/handle/tick fields and those offsets are now `binary-layout.ini` seams; `runtime/ghidra_selection_lifecycle_xrefs.txt`, `runtime/ghidra_selection_and_cleanup_targets.txt`, and `runtime/ghidra_selection_brain_offset_accesses.txt` remain the selection lifecycle evidence | done: active casts require the native primary descriptor's selection state and no longer own a skill-id-to-selection fallback table |
| Active spell object lookup | `native_active_spell_object_state.inl` | done: `0x0045ADE0` is now called through `actor_world_lookup_object_by_handle` instead of duplicating `world+0x500` bucket math; `0x00545360` still proves the boulder spell-object phase/release fields used for diagnostics, target-lethal release checks, and max-size release checks | done: active code uses the native lookup seam and no longer reads spell-object vtable slots as a release authority |
| Cast latch cleanup | `release_and_latch_helpers.inl` | done: `0x0052F3B0` proves native active-handle cleanup and `runtime/ghidra_cast_latch_offset_accesses.txt` keeps the cast latch fields tied to the stock `PlayerActorTick` transition | done: direct active-handle sentinel fallback writes and damage-threshold spell-object charge mutation are removed; cleanup failures are logged and left visible |
| Lua bot constants | `mods/lua_bots/scripts/lib/lua_bots/config.lua`, `mods/lua_bots/scripts/lib/lua_bots/combat.lua` | done: C++ scene actor state publishes native-backed `tracked_enemy`; `sd.bots.resolve_primary_entry` owns primary loadout semantics; `sd.bots.get_primary_attack_window` reads live `FUN_0052C910` control-brain range through `actor_control_brain_pursuit_range` plus the Water `0x00786CE8` native special case; private-region intent is built from live `scene.region_index`/`scene.region_type_id` instead of descriptor coordinates | semantic enemy targeting, primary entry lookup, primary attack windows, and private-region scene intent are native/live-backed; keep only documented follow, spawn, stuck, and timing policy in Lua |
| Skill choice constants | `bot_runtime/helpers/skill_choices.inl` | done: `0x0067C250` native `level_up`, progression `+0x40` non-local mode, vtable slots, option semantics, and `0x3F`/`0x34` choice evidence | done: binary-layout-backed named seams drive level sync, bot-owned non-local progression mode, bonus-count, and special-choice ids without direct level/HP/MP writes |
| Probe script constants | `tools/*probe*.py`, `tools/watch_*.py`, `tests/re/run_live_*_probe.py` | done for active probes: shared layout keys cover native globals, trace body EIPs, movement/collision fields, skill-choice stress offsets, staged/root layout fallback, and semantic `tracked_enemy` target classification | active probes load from layout/semantic surfaces; remaining direct constants are diagnostic sentinels, Win32 flags, Ghidra helper arguments, or documented unresolved evidence |

## Implementation Rule

Runtime code should not be changed for an area until its row has both Ghidra and
Lua evidence. If live execution is unavailable, only tests/docs/tooling may be
updated and the runtime item remains blocked with the exact missing condition.
