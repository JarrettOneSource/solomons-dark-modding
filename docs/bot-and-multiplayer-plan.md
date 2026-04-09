# Bot Scripting & Multiplayer Plan

Date: 2026-04-06
Status: Living document

## Goal

Build a Lua-scriptable bot system that spawns real wizard entities in the game world, driven by Lua scripts. Design it so the same participant model works for multiplayer remote players later — bots and remote humans share one rail.

## Guiding Principle

Every bot feature should be built as a "participant" feature. When we add multiplayer, a remote player is just a participant whose inputs come from the network instead of from Lua.

## Architecture (from SB precedent)

```
┌──────────────────────────────────────────────────┐
│                  Participant Rail                  │
│                                                    │
│  ┌─────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  Local   │  │   Lua Bot    │  │   Remote     │ │
│  │  Human   │  │  (scripted)  │  │   Human      │ │
│  └────┬─────┘  └──────┬───────┘  └──────┬───────┘ │
│       │               │                 │          │
│       └───────┬───────┘                 │          │
│               │                         │          │
│        Game Input                 Network Input    │
│               │                         │          │
│               ▼                         ▼          │
│       ┌───────────────────────────────────┐        │
│       │     ParticipantState              │        │
│       │  position, heading, hp, mp,       │        │
│       │  wizard_id, skills, cast_queue    │        │
│       └───────────────┬───────────────────┘        │
│                       │                            │
│                       ▼                            │
│              Game Entity System                    │
│        (real wizard object in the world)           │
└──────────────────────────────────────────────────┘
```

## Phase 1: Bot Entity Spawning (immediate)

Get a second wizard to appear in the game world, driven by code.

### 1.1 Find wizard entity creation function
- Use Ghidra to find how the player wizard is created at run start
- Trace from Arena_Create (0x0046EA90) or the region switch (0x005CDDD0)
- Find the function that allocates and initializes a wizard entity
- Determine the struct layout (position, heading, HP, MP, wizard_id, animation state)

### 1.2 Spawn a bot entity
- Call the wizard creation function to spawn a second wizard
- Place it at a known position near the player
- Verify it renders in-game (visible on screen)
- Ensure it doesn't crash or interfere with the player wizard

### 1.3 Wire to existing bot_runtime.h API
- `sd.bots.create({wizard_id=N, position={x,y}})` spawns a real entity
- `sd.bots.update({id=N, position={x,y}, heading=F})` moves the entity
- `sd.bots.destroy(id)` removes the entity
- Store bot_id -> entity_ptr mapping

### 1.4 Verify with Lua
```lua
sd.events.on("wave.started", function(e)
  local bot = sd.bots.create({
    wizard_id = 2,
    x = 100.0, y = 100.0,
  })
  log("bot spawned: " .. tostring(bot))
end)
```

## Phase 2: Bot Movement & AI (after Phase 1)

Make the bot move and interact with the world.

### 2.1 Position updates
- Write bot position to the entity's position fields each tick
- Smooth interpolation between Lua-provided waypoints
- Heading auto-calculated from movement direction

### 2.2 Bot brain Lua API
```lua
sd.events.on("runtime.tick", function()
  local player = sd.player.get_state()
  -- Follow the player
  sd.bots.update({
    id = my_bot,
    x = player.position.x + 2.0,
    y = player.position.y + 2.0,
    heading = 0.0,
  })
end)
```

### 2.3 Pathfinding (stretch)
- Expose walkable area data or use raycasts
- Simple follow-player pathfinding as baseline

## Phase 3: Bot Combat (after Phase 2)

Make the bot cast spells and kill enemies.

### 3.1 Find spell cast function
- Already partially done: spell.cast hook at 0x0054CC50
- Find the function that INITIATES a cast (not just detects one)
- Determine parameters: caster entity, spell id, target position/direction

### 3.2 Bot casting API
```lua
sd.bots.cast({
  id = my_bot,
  spell_id = 5,
  target_x = enemy.x,
  target_y = enemy.y,
})
```

### 3.3 Bot targeting
- Query nearby enemies via sd.world.get_enemies()
- Pick closest enemy
- Cast toward it

### 3.4 Demo: autonomous bot companion
```lua
-- Bot follows player and auto-attacks nearest enemy
sd.events.on("runtime.tick", function()
  local player = sd.player.get_state()
  local enemies = sd.world.get_enemies()
  local nearest = find_nearest(enemies, player.position)

  sd.bots.update({id = bot, x = player.x + 2, y = player.y + 2})

  if nearest then
    sd.bots.cast({id = bot, spell_id = 1, target_x = nearest.x, target_y = nearest.y})
  end
end)
```

## Phase 4: Participant Model (after Phase 3)

Abstract bots into the general participant system.

### 4.1 ParticipantState struct
```cpp
struct ParticipantState {
    uint64_t id;
    ParticipantKind kind;  // LocalHuman, LuaBot, RemoteHuman
    int wizard_id;
    bool ready;
    float position_x, position_y;
    float heading;
    int hp, max_hp, mp, max_mp;
    int level;
    int primary_skill_id;
    CastQueue cast_queue;
    void* entity_ptr;  // game wizard entity
};
```

### 4.2 Unified participant management
- All participants (local player, bots, future remote players) go through the same create/update/destroy path
- Game entity creation is the same for all participant types
- Input source differs: keyboard for local, Lua for bots, network for remote

### 4.3 Participant events
```lua
sd.events.on("participant.joined", function(e) ... end)
sd.events.on("participant.left", function(e) ... end)
sd.events.on("participant.cast", function(e) ... end)
```

## Networking Architecture Decisions

### Player Movement: Client-Owned (No Host Authority)

Each client owns their own wizard movement. Zero input lag.

```
Client A (host):                     Client B:
- Moves wizard locally (0 lag)       - Moves wizard locally (0 lag)
- Receives B's pos → updates puppet  - Receives A's pos → updates puppet
```

No client-side prediction needed. No lag compensation for player movement.
Remote player puppets interpolate smoothly toward latest received position.

### Enemy State: Host-Owned

Host runs all enemy simulation (AI, pathing, spawning, loot).
Clients receive enemy state and render puppet entities.

**Replication per enemy (host → clients, 10-20 updates/sec):**
- Position (x, y)
- Velocity (vx, vy) — enables dead reckoning on client
- HP (on change only)
- Death events

**Client dead reckoning:**
Between host updates, client extrapolates: position += velocity * dt.
On new update, smooth-correct toward real position over 3-4 frames.
Works for all enemy types including curved movers (Banshee) because
the velocity vector updates each packet, naturally following curves.

For even smoother curved movement: send previous + current velocity.
Client interpolates the velocity itself (quadratic extrapolation).
Zero per-enemy-type code. Same packet format for everything.

### Client Spell Casts: Optimistic + Host Hit Validation

Client casts spell → plays animation immediately (feels responsive).
Client sends cast packet to host with timestamp.
Host checks position history buffer: "was enemy near target at that timestamp?"
Hit confirmed → broadcast damage/effects to all clients.

This means clients hit what they SAW, even with 50-150ms latency.
Host keeps a short history buffer of enemy positions (last 5-10 frames).

### Boss Kill / Enemy Death

- Client deals killing blow → sends damage packet to host
- Host confirms kill → broadcasts enemy.death to all clients
- All clients see death within one round trip
- Loot is host-determined and broadcast

## Phase 5: Multiplayer Transport (after Phase 4)

Replace Lua bot inputs with network inputs.

### 5.0 Enemy Replication: Host-Authoritative Snapshot Interpolation

**Architecture** (recommended by Codex, agreed):

Host owns all enemy state. Clients render enemy puppets from buffered host snapshots,
interpolated 100-150ms behind real-time. No dead reckoning, no per-enemy-type code.

**Packets (host → clients):**
- `EnemySpawn` — reliable: net_id, type_id, x, y, heading, hp_max, flags
- `EnemySnapshotBurst` — unreliable, 10-20Hz: host_tick, count, [net_id, x, y, vx, vy, hp_delta, state_flags]
- `EnemyEvent` — reliable: net_id, kind (attack_start, phase_change, teleport, death)
- `EnemyDespawn` — reliable: net_id

**Client rendering:**
- Buffer last 2-3 host snapshots
- Render enemies 100-150ms behind host time
- Interpolate between snapshots (Hermite if velocity included, linear otherwise)
- Brief extrapolation on packet loss (<=100ms), leash-correct on large error
- Hard snap only on teleport/spawn/death

**Spell hit handling:**
- Client shows cast animation immediately (responsive)
- Client sends: cast_seq, spell_id, local_cast_time, target_net_id/impact_point
- Host checks position history: "was target plausible in recent window?"
- Host confirms → broadcasts damage/death to all clients

**Why this works for Banshee curves:** Clients follow real sampled host positions,
not a predicted model. Curved motion is captured naturally in the snapshot stream.
Zero per-enemy-type code. Same packet format for skeletons and Banshees.

**Bandwidth:** ~100 enemies at 10Hz with 12-16 byte compact deltas = reasonable for co-op.
HP/state only on change. Bosses can use 20Hz for smoother updates.

### 5.1 Protocol (port from SB)
- Packet kinds: State, Launch, Cast, Progression
- Magic: `SDMP` (Solomon Dark Multiplayer Protocol)
- Binary packed, versioned headers

### 5.2 Transport options
- **Steam P2P** (primary) — reliable, NAT traversal built in
- **Loopback** (testing) — two instances on same machine
- **Direct IP** (fallback) — for non-Steam scenarios

### 5.3 Session management
- Host creates lobby, others join
- Lobby browser in Dark Cloud UI tab
- Party formation in hub
- Synchronized run launch

### 5.4 Remote avatar rendering
- Remote participant state arrives via network packets
- Written to participant's entity each frame
- Same entity system as bots — just different input source

## Dependencies & Risks

| Risk | Mitigation |
|---|---|
| Wizard entity creation crashes on second wizard | May need to find a different spawn path or allocate entity differently |
| Game assumes single player throughout | May need to patch checks that assume one wizard |
| Spell casting tied to "the player" not "an entity" | Need to find entity-parameterized cast function |
| Animation system doesn't support multiple wizards | May need to drive animations manually |
| Network latency causes desynced combat | Host-authoritative model with prediction |

## What We Already Have

- [x] Bot runtime API (create/update/destroy) — `bot_runtime.h/cpp`
- [x] Lua bot bindings — `lua_engine_bindings_bots.cpp`
- [x] Multiplayer foundation scaffolding — `multiplayer_foundation.h/cpp`
- [x] Runtime protocol header — `multiplayer_runtime_protocol.h`
- [x] Service loop skeleton — `multiplayer_service_loop.h/cpp`
- [x] Enemy_Create function identified (0x00469580)
- [x] Spell cast hook identified (0x0054CC50)
- [x] Wave spawner automation working
- [x] Full run lifecycle automation working
- [x] Runtime debug toolkit for investigation
- [x] 77 named functions in Ghidra pseudo-codebase

## Current Bot Status (2026-04-08)

### Working:
- [x] Bot entity creation via direct player constructor (FUN_0052b4c0, alloc 0x398 bytes)
- [x] Bot registered into world via ActorWorld_Register (0x0063F6D0)
- [x] Bot renders as a proper wizard sprite again instead of the black silhouette path
- [x] ALLY health bar appears for bot
- [x] Physics/collision works (bot collides with trees, walls)
- [x] Input decoupled — bot does NOT mirror player keyboard/mouse
- [x] Puppet mode — drive-state byte held high, control-brain scrubbed each frame
- [x] Independent world-space position (not parented to player)
- [x] Lua patrol working (move_to between two points)
- [x] Scene API (sd.world.get_scene())
- [x] move_to / stop / get_state Lua API

### Known Issues:
- [x] Crash after bot creation fixed. Root cause was nulling `actor + 0x58`, which `FUN_00513090` dereferences on the first render/update frame.
- [ ] Independent wizard-type visuals keyed by `wizard_id` are still pending. Current workaround mirrors the local player's resolved sprite/render state.
- [ ] Hub bot rendering not working (arena only)
- [ ] Only 1 bot tested (multi-bot may crash like before)

### Architecture:
- Bot entity created via: _aligned_malloc(0x398) → PlayerActorCtor(0x0052b4c0) → ActorWorld_Register(0x0063F6D0)
- NOT using Gameplay_CreatePlayerSlot (that creates ally-AI actors with input mirroring)
- Puppet mode: preserve world/context at `actor + 0x58`, clear slot mirrors, bypass stock `PlayerActorTick`, and advance animation from loader-owned state
- Wizard visuals: current live workaround copies the local player's resolved actor render state into the standalone bot so the sprite atlas, robe color, and staff selection match the visible player. Independent `wizard_id` selection remains follow-up work.
- Movement: per-frame velocity application via game's movement system
- Cleanup: ActorWorld_Unregister → destructor → _aligned_free

### Key RE Findings:
- Player actor constructor: FUN_0052b4c0 (__thiscall, takes zeroed 0x398-byte allocation)
- Actor world/context pointer: +0x58 (required by render/update code, not safe to null)
- Actor slot byte: +0x5C (gameplay slot index, must be cleared for standalone)
- Movement controller: owner+0x378
- Slot linkage mirrors: +0x164, +0x166 (must be cleared)
- `FUN_00513090` / crash site: dereferences the world/context family behind `actor + 0x58`
- `FUN_0061AA00`: stock wizard clone path. It does not copy the entire render window; it refreshes progression, rebuilds visual state, then attaches `0xA8` visual-link objects into equip-runtime sinks.
- Actor visual rebuild call: actor vtable slot `+0x18`
- Actor descriptor block: `actor + 0x244`
- Actor-side visual attachment field: `actor + 0x264`
- Equip-runtime visual-link sinks: nested off `actor + 0x1FC` at `+0x1C`, `+0x18`, and `+0x30`
- Standalone safe path: keep `+0x58`, skip stock `PlayerActorTick`, drive movement/animation from loader state only
- Wizard visual safe path, current temporary version: direct standalone spawn plus donor resolved-render-state copy. This is enough to restore correct robes/staff while keeping the bot out of the gameplay slot system.

## Immediate Next Step

Finish the create-screen wizard-selection trace. The latest live probe shows that all create element and discipline actions dispatch against one create owner rooted at the first dword of `0x008203F0`, while the gameplay local-player actor watchers stay unchanged. The next step is to walk that create owner's preview and source-profile fields into `FUN_00466FA0 -> FUN_005E3080`, then reuse that source-profile pipeline for standalone bot `wizard_id` visuals.
