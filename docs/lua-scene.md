# Lua scene control

`sd.scene` exposes semantic scene state and the stock region-switch path without exposing
process addresses. It is intended for custom `.boneyard` campaigns and scripted movement
between stock or overlaid regions.

Capabilities: `scene.read` and `scene.switch.authority`.

## API

### `sd.scene.get_state() -> table|nil`

Returns `nil` before a gameplay scene exists. Otherwise it returns:

- `kind` and `name` — semantic labels such as `hub`, `region`, `arena`, or `transition`;
- `region_index` and `region_type_id` — the current stock region identifiers;
- `pending_level_kind`, `transition_target_a`, and `transition_target_b` — the stock
  transition values, useful while waiting for a switch to settle;
- `transitioning` — whether the current world is between materialized scenes;
- `is_authority` — whether this peer may request a switch;
- `can_switch_region` and `can_enter_run` — convenience guards for authored flows.

No gameplay-scene, world, arena, region-state, or other process address is returned.
`sd.world.get_scene()` remains the legacy inspection surface for tools that intentionally
need raw runtime identities.

### `sd.scene.switch_region(region_index) -> true`

Queues the stock gameplay-thread region switch. `region_index` must be an integer from
`0` through `5`:

- `0` is the shared hub;
- `1` through `4` are private stock/overlaid regions;
- `5` is the arena run.

Only the offline player or multiplayer host simulation authority can call this function. Region `5` may be
entered only from the shared hub and uses the existing seeded run-start path. A raw switch
cannot leave an active arena; use the stock Leave Game UI action so run teardown and peer
cleanup remain synchronized. Calls during a transition are rejected instead of stacking
ambiguous targets.

```lua
assert(sd.runtime.has_capability("scene.read"))

local scene = sd.scene.get_state()
if scene and scene.is_authority and scene.kind == "hub" then
  assert(sd.scene.switch_region(2))
end
```

## Multiplayer ownership

The host authors scene changes. Participant frames already carry a scene intent and are
accepted only from the configured authenticated authority endpoint. Clients follow host
intent for the shared hub and private regions through the same bounded gameplay-thread
queue. Run entry continues through the authenticated run-intent and run-nonce path.

Lua-controlled participants receive the queued target intent at the same time, so their
materialization follows the new world. A client cannot invoke `switch_region`, and a client
never follows a raw region request out of an arena; the existing synchronized Leave Game
flow owns that transition.
