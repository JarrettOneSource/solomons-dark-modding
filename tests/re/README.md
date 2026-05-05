# Native Seam RE Tests

This directory holds reverse-engineering and regression checks for gameplay
seams that are backed by native game data, hardcoded values, or loader-owned
workarounds.

The tests here are intentionally separate from runtime code. Their job is to:

- prove current hardcoded values against staged game data before changing them;
- keep verified native-data replacements from drifting back into code tables;
- keep a machine-checkable inventory of workaround-heavy source locations;
- capture the exact Ghidra/Lua evidence needed before a runtime cutover;
- make later cleanup reviewable instead of relying on chat history.

Run the static checks from the repo root:

```bash
python3 tests/re/run_static_re_tests.py
```

Use `--json` when another script needs structured output.

The static suite also checks that active live probes and diagnostic tools load
native addresses, trace body EIPs, progression offsets, collision fields, and
skill-choice stress offsets through `config/binary-layout.ini` instead of
owning direct address literals.

Live probes normally launch the default staged game. On machines where the
stock BASS startup music path crashes the unmodified game before Lua can drive
the run, prepare a no-music source copy and point probes at it:

```bash
python3 tests/re/prepare_no_music_game_dir.py --json
SD_PROBE_GAME_DIR="runtime/instances/live_no_music_source/stage" \
  python3 tests/re/run_live_pathfinding_layout_probe.py --json
```

This only empties the staged native `music/music.txt` list in a test source
copy. It does not patch `SolomonDark.exe`, `bass.dll`, or loader runtime code.
`tools/cast_state_probe.py` also accepts `SD_PROBE_RUNTIME_PROFILE` and
semicolon-separated `SD_PROBE_RUNTIME_FLAGS` for targeted launcher probes.
Live bot probes request `sample.lua.bots` through `SD_PROBE_REQUIRED_MODS`
before launch and restore the prior runtime mod-manager state afterward, so
they do not depend on a manually enabled Lua mod.

Run the live native spell-stat bot mana probe after a Release build:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/Build-All.ps1 -Configuration Release
python3 tests/re/run_live_native_spell_stats_probe.py
```

The live probe launches the staged game, drives to a testrun, uses the Lua
memory bridge to force bot mana, and queues each primary skill. A passing run
proves the resolver can read live Skills_Wizard progression stat outputs and
does not depend on staged wizard-skill files or in-code mana tables.

Run the live bot spell-upgrade combat flow probe after changing skill choice,
primary spell stat, mana, or default primary-cast code:

```bash
python3 tests/re/run_live_bot_skill_upgrade_combat_flow_probe.py --json
```

That probe launches with every element bot profile active, applies native
level-up choices until the Fire bot receives a Fireball upgrade, then queues a
baseline and post-upgrade default primary cast. It asserts the selected native
progression entry increments, the bot loadout still resolves to Fireball, and
the live Skills_Wizard primary stat output used by combat reports increased
damage and mana cost.

Run the upgraded Earth Boulder projection probe when the question is whether
the bot's native upgrade state is flowing into the held Boulder release diagnostics,
not only native stat output:

```bash
python3 tests/re/run_live_bot_upgrade_damage_delta_probe.py --json
```

That wrapper drives the same high-HP Earth setup twice and writes
`runtime/probe_earth_baseline_25000_bot_only_goal_confirm.json` plus
`runtime/probe_earth_upgraded_25000_bot_only_goal_confirm.json`. It keeps Earth
on `bot_only` positioning so the controlled target remains a live wave enemy in
the native damage scan. The baseline and upgraded runs both require the stock
native max-size release path and native post-release launch window. The
upgraded run uses the native bot skill picker to apply the native Boulder upgrade
before combat, then requires native mana cost, projected damage increase, and a
native max-size release while explicitly not treating incidental HP loss as proof
of a native release hit.

Run the all-bot skill-choice regression when touching bot level-up or choice
application behavior:

```bash
python3 tools/test_bot_skill_choice_regression.py --iterations 5 --active-bots all --min-bots 5
```

That wrapper drives native option rolls and choice application across all five
bot progressions, including the bonus choice-count path and HP/MP stat-changing
options when they are rolled.

Run the all-bot hub/run materialization probe after spawn or follow changes:

```bash
python3 tests/re/run_live_all_bots_hub_run_probe.py --json
```

That probe launches with every element bot profile active, drives a fresh hub
entry, verifies all five bots have live actor/progression/equipment handles
near the player, then starts a testrun and repeats the same checks. It guards
against bots materializing far away or only working in one scene.

Run the native player mana writer probe before changing bot mana spend logic:

```bash
python3 tests/re/run_live_player_mana_writer_probe.py
```

That probe watches the local player's progression MP field during a stock
player cast and records the actual native writer EIP/return data in
`runtime/live_player_mana_writer_probe.json`.

Run the focused bot native mana spend probe after the native seam is wired:

```bash
python3 tests/re/run_live_bot_native_mana_spend_probe.py
```

That probe launches the staged game, materializes a bot, forces both current
and max MP through the Lua memory bridge, queues an Earth primary cast, and
asserts the PerSecond spend log reports `native=1`, no SEH, a real MP delta,
the unscaled native Earth `mManaCost` rate, and restored local-player shim
fields.

Pure-primary PerCast mana is covered separately:

```bash
python3 tests/re/run_live_pure_primary_startup_probe.py --json
```

Run the focused out-of-mana rejection probe after touching bot cast admission
or mana readiness checks:

```bash
python3 tests/re/run_live_bot_out_of_mana_rejection_probe.py --json
python3 tests/re/run_live_bot_out_of_mana_rejection_probe.py --json --bot-key earth --bot-element-id 2 --current-mp 1 --max-mp 100 --allow-queued-rejection
```

That probe materializes a bot, forces the bot's live progression MP to zero,
queues its primary spell, and requires rejection before pending-cast insertion
with no cast lifecycle or effect logs, no native mana spend, and no active or
pending cast state left behind. The Earth variant keeps a small positive MP
pool so the queue layer can accept the command, then proves the held-cast preparation gate
rejects before any Boulder object or MP spend is created.

Source-profile producer work has two live probes. The negative probe records
finalized actor state, while the writer probe arms native traces and a
finalized-player source-window write watch before bot materialization:

```bash
python3 tests/re/run_live_source_profile_negative_probe.py --json
python3 tests/re/run_live_source_profile_writer_probe.py --json
```

The writer probe fails unless the native constructor/descriptor/clone traces
fire, the candidate `0x00515290` path stays out of bot materialization, and the
finalized player source-profile window has no writes.

Run the enemy spawn API removal probe before touching wave-spawn diagnostics or
any future `0x00469580` wrapper research:

```bash
python3 tests/re/run_live_enemy_spawn_api_removed_probe.py --json
```

That probe starts native wave combat, queues a manual Lua/API enemy spawn, and
fails unless the queued result is refused with the active-combat guard that
names the unresolved `(anchor=nullptr, mode=0, param_5=0, param_6=0,
override=0)` call shape.

Run the Earth boulder release/projection probe before changing boulder impact
or cleanup code:

```bash
python3 tests/re/run_live_boulder_impact_projection_probe.py
```

That wrapper drives the existing Earth element damage harness and then asserts
the native boulder object, release policy, native damage-output scale diagnostics,
live Boulder release-base damage field, native finalizer floor/cap handling, native
secondary-reach diagnostics, and victim/removal evidence. The static suite also
guards the held-charge retarget contract: Earth Boulder follows the bot's live
target while charging, then freezes that target at release and commits cleanup
after the native launch window so it cannot keep growing to max charge. The default keeps a
normal-HP real wave enemy under native movement so target-lethal release can
still be validated against the real damage scan when the target remains in the
impact path, not a pinned center-overlap harness.
Use `--positioning force_both` only for pinned-position diagnostics. Lower
target HP covers earlier target-lethal release once the native early-release
projection can kill the live retargeted enemy. The native overlap diagnostic
follows `0x00642090`: `distance^2 < query_radius^2 + actor_collision_radius^2`,
but the release decision is based on the bot's current target, live target HP,
and native projected release damage from the active Boulder object's
`spell_object_release_base_damage=0x1F8` field rather than rebuilding the
primary stat output array during the held cast.
Raise `--target-hp` when you specifically need the native max-size release path. Use
`--require-hp-write-watch` only when specifically investigating the native HP
writer path because page-guard watches can destabilize target acquisition.

Run the held-charge retarget probe before changing Boulder targeting or cleanup
code:

```bash
python3 tests/re/run_live_boulder_retarget_probe.py
```

That probe charges Boulder on one real wave enemy, retargets the bot to a second
real wave enemy during the held native tick, moves the original target out of
the impact radius, then asserts the native release target is the retargeted
enemy, the frozen release target is removed by native damage, and the original
target remains alive.

Run the native ally HP/default-resource probe around the clone HP cleanup:

```bash
python3 tests/re/run_live_ally_hp_native_defaults_probe.py --allow-hardcoded-baseline
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/Build-All.ps1 -Configuration Release
python3 tests/re/run_live_ally_hp_native_defaults_probe.py
```

The baseline mode proves the current shared-hub bot materializes through the
standalone clone rail while still showing the `25.0f` HP overwrite. Strict mode
fails unless the clone reports native `50.0f` HP/max HP and native `100.0f`
MP/max MP from the recovered constructor/recompute path.

Run the layout-backed pathfinding and movement probe after changing movement
controller, nav-grid, GameNpc, or `[gameplay.pathfinding]` policy seams:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/Build-All.ps1 -Configuration Release
python3 tests/re/run_live_pathfinding_layout_probe.py
```

That probe launches the staged game, verifies the launcher copied the current
movement/GameNpc/pathfinding layout keys into the runtime config, queries the
Lua nav-grid and movement-geometry surfaces, scans live movement circles for
the configured static and push-through gate policy values, samples GameNpc
motion fields, and issues a short `sd.bots.move_to` command to prove the
layout-backed path remains live.

The registered `GameNpc` participant rail is also statically guarded here:
`runtime/ghidra_registered_gamenpc_publication_blockers.txt` records that the
old clone handoff reaches the player-family `0x398` actor path instead of a
long-lived `0x1397` actor. The follow-up xref artifacts
`runtime/ghidra_registered_gamenpc_publication_xrefs.txt` and
`runtime/ghidra_registered_gamenpc_publication_expanded.txt` keep the
preview/source path and native GameNpc movement seams separated, so the inactive
registered rail was removed from active runtime code until that native
publication lifecycle is recovered. Live coverage for that removal guard is:

```bash
python3 tests/re/run_live_registered_gamenpc_blocker_probe.py --json
```

That probe materializes a controlled shared-hub bot and fails if the staged
runtime uses the registered rail, classifies the bot as `RegisteredGameNpc`,
produces a `0x1397` actor, or fires native GameNpc movement traces.

Run the stock-tick movement probe before changing the stock tick or
`PlayerActor_MoveStep` path in `player_actor_tick_hook.inl`:

```bash
python3 tests/re/run_live_stock_tick_restore_probe.py --json
```

That probe materializes a stable shared-hub standalone clone, uses low-impact
`sd.debug.watch` position watches during `sd.bots.move_to`, and samples the
actor after stop. It avoids page-guard write watches on actor position because
that hot object page can perturb the tick hook itself. Keep the supporting
Ghidra artifacts current before changing the restore:
`runtime/ghidra_stock_tick_restore_paths.txt`,
`runtime/ghidra_stock_tick_ownership_xrefs.txt`, and
`runtime/ghidra_stock_tick_input_offset_accesses.txt`.

Run the native bot speed-envelope probe before changing Fire/bot movement speed
or skill/stat movement effects:

```bash
python3 tests/re/run_live_bot_native_speed_probe.py --json
```

That probe launches all bots in a run, computes the Fire bot's native
PlayerActorTick cap from live actor fields, `progression +0x90`, and the global
movement scalars at `0x007DE810`, `0x00784740`, and `0x00784E20`. It verifies
baseline motion, temporarily lowers the bot-owned progression speed to prove
the movement path follows live memory, applies native Rush when offered, and
checks post-skill movement against the recomputed cap.

Run the standalone clone collision/materialization probe before removing or
changing the explicit standalone push bridge:

```bash
python3 tests/re/run_live_standalone_collision_probe.py
```

That probe launches the staged game, materializes standalone clone-rail bots,
records the native owner/grid/collision fields recovered from Ghidra, forces a
standalone/standalone overlap, and asserts the explicit standalone push
separates the actors without crash or invalidation log tokens. Keep the
supporting Ghidra artifacts current before changing that bridge:
`runtime/ghidra_standalone_collision_registration_paths.txt`,
`runtime/ghidra_standalone_collision_overlap_builder_paths.txt`,
`runtime/ghidra_standalone_collision_ownership_xrefs.txt`, and
`runtime/ghidra_standalone_collision_field_writes.txt`.

Run the cast shim/snapshot probe before removing slot-0 cast shims, stock tick
windows, or active spell object snapshot code:

```bash
python3 tests/re/run_live_cast_shim_snapshot_probe.py --json --timeout 180
```

That probe launches the staged game, queues an Earth primary bot cast, captures
the layout-backed cast fields before/active/after, verifies the local-player
slot/progression shim state is restored, verifies selection fields, active
handle sentinels, skill ids, and latch state after cleanup, and writes
`runtime/live_cast_shim_snapshot_probe.json`. Earth is intentional here: its
boulder object stays in the world-bucket table long enough for Lua to snapshot,
while faster PerCast primaries can complete before the poll observes a handle.
Keep `runtime/ghidra_cast_slot0_dispatch_xrefs.txt` and
`runtime/ghidra_cast_slot0_gate_offset_accesses.txt` current before changing
the slot shim. Keep the selection/latch artifacts current before touching
selection-state restore, active spell snapshots, or release cleanup:
`runtime/ghidra_selection_lifecycle_xrefs.txt`,
`runtime/ghidra_selection_and_cleanup_targets.txt`,
`runtime/ghidra_selection_brain_offset_accesses.txt`,
`runtime/ghidra_active_spell_lifecycle_xrefs.txt`,
`runtime/ghidra_cast_latch_offset_accesses.txt`, and
`runtime/ghidra_boulder_spell_object_vtable_slots.txt`.

Run the Lua bot enemy semantic probe before reintroducing object type checks in
Lua combat targeting:

```bash
python3 tests/re/run_live_lua_bot_enemy_semantic_probe.py --json
```

That probe runs the element-damage harness in `--semantic-snapshot-only` mode,
then validates its raw `sd.world.list_actors()` hostile snapshots. It fails
unless stock hostiles are published with `tracked_enemy`, matching `enemy_type`,
usable health, and nonzero actor addresses. Lua bot combat should consume that
semantic flag instead of owning native object type constants. Active Python
combat probes follow the same rule: they may print `object_type_id` for
diagnostics, but target classification and arena-health offset selection must
start from `tracked_enemy`.

For the autonomous probe's semantic setup path, use:

```bash
python3 tools/probe_bot_autonomous_combat_validation.py --semantic-setup-only --skip-hp-watch --output runtime/probe_bot_autonomous_combat_validation.semantic-setup.json
```

That mode validates tracked enemy selection and arena-health setup without
entering the full two-bot autonomous cast window. Keep the full autonomous
damage mode separate from enemy classification; a crash there is a cast-path
regression, not permission to restore probe-owned enemy type constants.

For the full two-bot autonomous cast validation, use:

```bash
python3 tools/probe_bot_autonomous_combat_validation.py --skip-hp-watch --output runtime/probe_bot_autonomous_combat_validation.full.json
```

The full probe now enables bot-scoped Lua diagnostics, waits for both managed
bots, selects the Fire pure-primary bot when present, and validates closest
targeting plus HP/native-cast evidence. It also arms the trace-overlap case
that used to corrupt the spell dispatcher hook; `dispatch_body=false` is the
expected safe result.

To validate the trace guard directly, use:

```bash
python3 tests/re/run_live_trace_overlap_guard_probe.py --json --timeout 90
```

That probe fails unless tracing `trace_spell_cast_dispatcher_body` is rejected
as overlapping an existing relative jump patch, while a clean 3EF trace still
arms and untraces by original game-image address.
