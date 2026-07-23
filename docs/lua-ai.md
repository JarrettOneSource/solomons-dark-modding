# Lua enemy AI

`sd.ai` attaches bounded authority-side behavior to enemies registered by the
same Lua mod. It provides periodic `on_think` callbacks, per-spawn blackboards,
semantic participant targeting, and collision-preserving move-goal steering.

Capabilities:

- `ai.register` — entry-script controller registration.
- `ai.read` — active-controller snapshots.
- `ai.control.authority` — target and movement commands when the gameplay pump
  is installed.

## Registering a controller

Register the enemy first, then register one controller for that content ID:

```lua
local boss = sd.enemies.register({
  key = "grave_oracle",
  base = "skeleton_mage",
  hp = 500,
})

sd.ai.register({
  enemy = boss.id, -- or "grave_oracle"
  interval_ms = 100,
  blackboard = {phase = 1},
  on_think = function(context)
    local target = context.participants[1]
    if not target then
      return {target = false, move_goal = false}
    end
    return {
      target = target.ref,
      move_goal = {
        x = target.x,
        y = target.y,
        stop_distance = 80,
      },
      blackboard = {phase = context.blackboard.phase + 1},
    }
  end,
})
```

Registration is allowed only while the owning mod's entry script runs. The
`enemy` field must resolve to an enemy registered by that mod. A mod may retain
at most 256 registrations. `interval_ms` is an integer from 16 through 5000;
the default is 100. Each mod may own at most 512 live controller instances and
the engine invokes at most 64 due callbacks per pump.

The initial and returned blackboards use the same deterministic bounded value
format as `sd.state`. Each encoded blackboard is limited to 4096 bytes. A fresh
copy is created for every spawned enemy, so two enemies never share mutable Lua
tables or native state.

## Think context and decisions

`on_think(context)` runs only while its registered enemy is live in an active
run. The context contains no process addresses:

- `network_actor_id`, `content_id`, `key`, `base`, and `enemy_type`.
- `x`, `y`, `position`, `radius`, `hp`, `max_hp`, and `dead`.
- `think_count`, `monotonic_milliseconds`, and the instance `blackboard`.
- `target_mode`, optional `target_participant_id`, and optional `move_goal`.
- `participants`, sorted by participant ID. Each entry has `ref`,
  `participant_id`, `local_player`, `name`, `controller`, `in_run`, `alive`,
  `x`, `y`, `hp`, and `max_hp`.

Use `participant.ref` as a target. It is the string `"local"` for the local
wizard (including offline play), and a positive participant ID for another
wizard or Lua-controlled participant. This avoids inventing an offline network
identity while keeping scripts identical in solo and multiplayer.

A callback returns `nil` to preserve its last decision, or a table containing
any of:

- `target = "local"` or a positive participant ID: force that wizard target.
- `target = false`: explicitly clear the hostile target.
- `target = "stock"`: return target selection to the stock game.
- `move_goal = {x, y, stop_distance}`: steer native chase movement toward a
  finite world point. `stop_distance` defaults to 24.
- `move_goal = false`: stop applying the movement override.
- `blackboard = value`: replace the instance blackboard transactionally.

Unknown decision fields, malformed values, oversized blackboards, and invalid
world coordinates reject that decision and leave the prior state intact. A
callback error is logged and retried at its next normal interval; it does not
disable other controllers.

## Imperative control and inspection

These functions address a live instance by its semantic `network_actor_id`:

```lua
sd.ai.set_target(id, "local") -- false clears; nil restores stock selection
sd.ai.set_move_goal(id, x, y, 48)
sd.ai.stop(id)                -- remove only the move goal
sd.ai.clear(id)               -- restore stock target and movement

local state = sd.ai.get_state(id)
local all_owned_instances = sd.ai.list()
```

Mutating calls require simulation authority and the instance must belong to
the calling mod. `get_state` and `list` return copied semantic state; callback
references, actor pointers, vtables, native function addresses, and registry
indices are never exposed.

## Native movement and targeting boundary

The roadmap originally named `GameNpc_SetMoveGoal (0x005E9D50)`. Reverse
engineering established that it accepts the separate `GameNpc` class
(`0x1397`), not hostile `Badguy` actors. It is a different actor class, and
calling it on a skeleton, imp, or boss
would be a class-shape error.

Hostile control instead composes with the proven stock chain:

1. `MonsterPathfinding_RefreshTarget` runs normally.
2. A Lua target override writes both `actor + 0x168` and the required
   cross-group bucket delta at `actor + 0x164`.
3. `Badguy_CommonChaseTick` retains the normal attack cadence and class brain.
4. The `Badguy_MoveStep` hook rotates the native movement vector toward the
   requested point without changing its magnitude.
5. `PlayerActor_MoveStep` still performs stock collision, separation, grid
   rebinding, and movement.

The move goal deliberately does not manufacture motion while a class brain
submits a zero movement vector, so attack/idle states are not bypassed. A goal
is steering, not teleportation or a second physics system. `sd.nav.get_grid`
and `sd.nav.test_segment` are the formal address-free planning/collision reads
for scripts that need more than direct steering.

Target overrides also replace the old slot-only assumption. The loader's
validated default selector already widens stock enemies to all materialized
wizard participants; explicit Lua targets use the same exact actor-slot and
world-slot bucket calculation. Turn Undead locks retain priority. Multiplayer
clients never execute this selection or steering code for authoritative run
enemies.

## Multiplayer lifecycle

Enemy AI is simulation-class:

- Offline play and the multiplayer host create instances and execute Lua.
- Clients create no controller instances and never invoke `on_think`.
- Host movement, target fields, health, and death continue through the existing
  protocol-81 world snapshots. No AI-specific packet or mod-authored netcode is
  needed.
- The spawn serial produces the same positive semantic network actor ID in
  offline and hosted runs. Clients retain authority-stamped snapshot bindings.
- Commands and blackboards retire when the actor disappears, a run starts or
  ends, the mod unloads, or the Lua engine shuts down.

The disabled `sample.lua.ai_boss_lab` mod demonstrates deterministic boss
registration, nearest-participant targeting, a per-instance blackboard, and a
four-point orbit goal. `tools/verify_lua_ai.py` validates the registration and
address-free public contract against an already-running loader; it does not
launch the game.

For the full two-peer simulation acceptance, use a disposable local pair:

```powershell
py tools/verify_lua_ai_multiplayer.py --launch-pair --confirm-mutation
```

The pair verifier stages only `sample.lua.ai_boss_lab`, chooses a native
nav-validated clear lane, and spawns one registered Grave Oracle through the
retail exact-group spawner. It requires the host-only controller's think count
and per-spawn blackboard to advance together, a semantic participant target and
four-point move goal, collision-valid native displacement, and the same
authority-owned target and motion on the client's peer-local actor. The client
must retain zero AI instances and reject imperative target and movement
commands. Finally, the verifier kills the exact actor, requires controller
retirement on both peers, and stops only the exact processes it launched.
