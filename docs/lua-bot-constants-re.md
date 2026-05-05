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

The primary entry-index map in
`mods/lua_bots/scripts/lib/lua_bots/config.lua` is native-derived selection
state data, not behavior tuning:

- ether: `0x08`
- fire: `0x10`
- air: `0x18`
- water: `0x20`
- earth: `0x28`

`docs/lua-memory-tooling.md` records the live selection-state observations
behind this map.

### Water primary range

Water auto-attack range is native-derived but still computed in Lua because the
autonomous combat controller needs a conservative range window before queuing a
cast. Ghidra/live notes in `docs/lua-memory-tooling.md` identify the water
primary handler (`FUN_00543860`) calling the shared cone query
`FUN_00641B10` with:

```text
range = 205 + 4 * actor[0x290]
```

Runtime Lua does not hardcode the actor offset. It reads the field via
`sd.debug.layout_offset("actor_spell_config_290")` and falls back to the
policy range if that layout seam is unavailable.

## Policy Values

These are intentionally loader/Lua behavior policy. They are not currently
claimed as native game data:

- follow distance, resume distance, target-arrival distance, and retarget
  refresh distance;
- tick, command, spawn retry, scene update, and diagnostics intervals;
- bot spawn formation offsets relative to the live player and default active
  bot set;
- autonomous attack windows outside the native water range formula;
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

## Remaining Blockers

Private-area travel anchors and region ids are still manually observed scene
automation constants. They should eventually be replaced by a semantic
hub/region entrance API, but no native entrance list producer is currently
recovered.
