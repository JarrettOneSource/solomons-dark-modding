# Lua Bot Constants RE Notes

This note classifies the remaining numbers in `mods/lua_bots/scripts/lib/`.
The goal is to avoid treating bot policy values as native facts and to remove
duplicate native facts when the loader already exposes a semantic API.

## Native-Backed Values

### Enemy targeting

Lua no longer owns a wave enemy object type constant. The native-facing C++
scene actor surface classifies arena wave enemies and publishes
`actor.tracked_enemy` plus `actor.enemy_type` through `sd.world.list_actors()`.
`mods/lua_bots/scripts/lib/lua_bots/combat.lua` now consumes that semantic
flag instead of duplicating the `1001` object type in Lua.

The native type check still lives in the C++ semantic producer:
`IsArenaCombatActorType(...)` in
`SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl`.
That is the right owner because it is tied to the recovered actor layout,
health reader, and combat-state fallback.

`tests/re/run_live_lua_bot_enemy_semantic_probe.py` validates the surface from
the staged runtime by running the element-damage harness in
`--semantic-snapshot-only` mode. That keeps this semantic test on stock
wave-spawned enemies after the manual `sd.world.spawn_enemy(...)` API removal,
and still requires the raw `sd.world.list_actors()` snapshots to publish
`tracked_enemy`, `enemy_type`, and usable HP fields for Lua.

Active Python combat probes now use the same semantic flag for target
classification and only select the arena-health offsets after the actor address
is found in a `tracked_enemy` world snapshot. The probes may still print raw
`object_type_id` for diagnostics, but they should not own the wave-enemy type
constant. Close-range combat validation uses stock wave-spawned hostiles and
repositions the tracked actor instead of seeding a manual enemy identity.

### Primary loadout entry indices

Lua no longer owns the primary entry-index map. Bot profiles call
`sd.bots.resolve_primary_entry(element_id)`, which is backed by the shared
native primary selection owner in `native_spell_stats.cpp`. That keeps Lua bot
loadouts aligned with the same native selection helper used by cast admission,
mana resolution, visual seeding, and skill-upgrade flow.

### Primary attack window

Lua no longer computes attack ranges or the water cone formula. Autonomous
combat asks `sd.bots.get_primary_attack_window(bot_id, element_id)` and treats a
missing native/semantic window as "do not cast yet".

The C++ semantic producer now reads the live native target-selection range
instead of owning fixed attack windows. Ghidra artifacts
`runtime/ghidra_primary_attack_window_dispatcher.txt` and
`runtime/ghidra_actor_spell_config_writer_context.txt` show the primary
dispatcher (`FUN_00548B00`) filling the live actor spell-config block before the
water handler feeds the native cone query `FUN_00641B10`. The stock control-brain
target selector `FUN_0052C910` owns `actor_control_brain_pursuit_range` at the
layout-backed `kActorControlBrainPursuitRangeOffset` seam and applies the native
Water special-case global `water_primary_control_brain_range=0x00786CE8` for the
`0x20` selection state. `sd.bots.get_primary_attack_window(...)` exposes those
native sources as `native_selection_pursuit_range` or
`native_water_control_brain_range`.

## Policy Values

These are intentionally loader/Lua behavior policy. They are not currently
claimed as native game data:

- follow distance, resume distance, target-arrival distance, and retarget
  refresh distance;
- tick, command, spawn retry, scene update, and diagnostics intervals;
- bot spawn formation offsets relative to the live player and default active
  bot set;
- stuck detection thresholds.

Spawn placement intentionally applies a compact formation offset directly to
the live player or explicit scene anchor. The follow policy keeps bots inside a
100-unit outer band with a 50-unit inner deadzone. The all-bot formation spaces
the five element companions outside that 50-unit band so the native/loader
collision response does not push one companion out of the player-visible group.
Hub maintenance uses the semantic bot scene-position update when a companion
drifts outside that band, because stock hub pathing can reject cross-cell
movement between otherwise visible companion positions. The native sync layer
preserves those exact existing-entity hub update coordinates, while spawn
materialization still validates placement before creating an actor. Nav-grid
snapping remains limited to spawn validation plus run follow and travel targets
because using it for hub maintenance can move visible bots away from the player
in hub layouts.

Keep these values in Lua config until there is a native behavior source to
replace them.

### Private-area travel

Private-area travel no longer owns fixed entrance descriptors, hub anchors, or
manually observed interior coordinates. When the player is already inside a
stable private scene, Lua builds the bot scene intent from the live
`scene.region_index` and `scene.region_type_id` values and lets the semantic
scene-update path place the bot near the player. Returning to hub similarly
requests the shared-hub scene intent without descriptor coordinates.
