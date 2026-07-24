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

Only the offline player or multiplayer host simulation authority can call this
function. This is the authored scene-control API; ordinary host and client
players still enter and leave hub rooms through their own stock navigation.
Region `5` may be entered only from the shared hub and uses the existing seeded
run-start path. A raw switch cannot leave an active arena; use the stock Leave Game UI action
so run teardown and peer cleanup remain synchronized. Calls during a transition
are rejected instead of stacking ambiguous targets.

```lua
assert(sd.runtime.has_capability("scene.read"))

local scene = sd.scene.get_state()
if scene and scene.is_authority and scene.kind == "hub" then
  assert(sd.scene.switch_region(2))
end
```

## Multiplayer ownership

Hub rooms are participant-local. Each host or client may remain in the shared
hub, enter one of regions `1` through `4`, or occupy different private rooms
without forcing another player to transition. Authenticated participant frames
communicate that local scene intent for visibility; they do not grant one
participant ownership of another participant's hub navigation. Remote player
actors materialize only when their local and remote scene intents match.

The host keeps the shared courtyard simulation authoritative even while its
player is in a private room. It continues ticking the dormant courtyard and
publishes shared-hub students, traders, and other actors to clients that remain
there. Consequently, entering a room does not pause or replace the main hub
world for another participant.

Run entry remains synchronized and host-authored through the authenticated run
intent and run-nonce path. A client cannot invoke `sd.scene.switch_region`, and
neither peer can use a raw region request to leave an arena; the existing
synchronized stock Leave Game flow owns that transition.

## Two-peer acceptance

Use a disposable local pair for the full authority and scene-follow matrix:

```powershell
py tools/verify_lua_scene_multiplayer.py --launch-pair --confirm-mutation
```

The verifier creates a process-specific instance prefix, private stage and
profile directories, unique Lua pipes, and reserved transport ports. It stages
only `sample.lua.scene_lab`, suppresses window tiling, and does not kill or
attach to unrelated Solomon Dark processes.

It proves the exact host/client authority flags in the shared hub and rejects a
client-authored `sd.scene` switch. The host then enters private region `2` while
the client stays in the hub. The verifier requires the client's replicated hub
world to retain the same scene epoch while its student and named-NPC motion
advances. The client independently enters region `3`, proving that the peers can
occupy different private rooms, then returns to the hub while the host remains
in region `2`. After the host returns, region `5` entry must still converge
through the authenticated host participant intent. Finally, the host must
receive the stock Leave Game guard while the client remains authority-rejected.
Only the two process IDs returned by the verifier's own launch are stopped.
