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
│       │  character_profile, skills,       │        │
│       │  inventory, cast_queue            │        │
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
- Determine the struct layout (position, heading, HP, MP, character profile, animation state)

### 1.2 Spawn a bot entity
- Call the wizard creation function to spawn a second wizard
- Place it at a known position near the player
- Verify it renders in-game (visible on screen)
- Ensure it doesn't crash or interfere with the player wizard

### 1.3 Wire to existing bot_runtime.h API
- `sd.bots.create({profile={element_id=..., discipline_id=..., ...}, position={x,y}})` spawns a real entity
- `sd.bots.update({id=N, profile={...}, position={x,y}, heading=F})` updates the entity
- `sd.bots.destroy(id)` removes the entity
- Store bot_id -> entity_ptr mapping

### 1.4 Verify with Lua
```lua
sd.events.on("wave.started", function(e)
  local bot = sd.bots.create({
    profile = {
      element_id = 2,
      discipline_id = 2,
    },
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
    MultiplayerCharacterProfile character_profile;
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

## Current Bot Status (2026-04-09)

### Working:
- [x] Bot entity creation still works through the direct player-actor constructor path (`_aligned_malloc(0x398)` -> `PlayerActor` ctor -> `ActorWorld_Register`)
- [x] Bot is now VISIBLE in the arena. The current visual is wrong, but a wizard sprite does render.
- [x] Bot has collision, stays in place, and pathfinds back to its patrol point when pushed.
- [x] Arena rendering is stable only when the bot is published into a real gameplay slot (`gameplay + 0x1358 + slot * 4`, slot `1..3`).
- [x] Hostile AI compatibility now has a clean runtime cutover: stock hostile selection still prefers slot `0`, but the loader widens `MonsterPathfinding_RefreshTarget` so nearer gameplay-slot participants in slots `1..3` can be selected, retained, and attacked too.
- [x] Stock `PlayerActorTick` runs on the bot; skipping it makes the bot invisible.
- [x] Input remains decoupled through puppet drive-state/control scrubbing rather than by bypassing the stock tick.
- [x] Lua patrol still works (`move_to` between points).
- [x] Scene API (sd.world.get_scene())
- [x] move_to / stop / get_state Lua API

### Known Issues:
- [ ] `actor + 0x04` is still shared with the local player, so the bot is parented to the player transform instead of owning its own render node.
- [ ] The current sprite is wrong: black robes, incorrect frame selection, and T-pose-like animation.
- [ ] Independent wizard visuals keyed by `wizard_id` are still pending.
- [ ] `Object_Allocate` (`0x00402030`) was the obvious candidate for independent render-node allocation, but substituting it for `_aligned_malloc` corrupted the heap.
- [ ] Synthetic source profiles (`FUN_005E3080`) still need donor descriptor supplementation; without live atlas context the descriptor bytes stay empty.

### Architecture:
- Bot entity created via: `_aligned_malloc(0x398)` -> `PlayerActor` ctor (`0x0052B4C0`) -> `ActorWorld_Register` (`0x0063F6D0`)
- The ctor chain is now recovered: `Object_Ctor` -> `Puppet_Ctor` -> `GoodGuy_Ctor` -> `Player_Ctor` -> `PlayerActor` ctor. Each layer writes its own vtable.
- `actor + 0x04` is the render context / scene-graph node pointer. Reusing the player's value makes the bot visible, but also proves the parenting bug because the bot inherits the player transform.
- Arena rendering currently needs all three gates at once: a non-null `actor + 0x04`, a real gameplay slot entry (`slot 1..3`), and stock `PlayerActorTick` running every frame.
- Arena rendering ignores the hub visual-link path. The local player in arena can render with null source-profile/equip/progression/anim-table fields that matter in the hub pipeline.
- Wizard visuals remain split from basic visibility: synthetic source profiles can create the weapon attachment, but descriptor bytes still need donor supplementation for the correct independent wizard sprite.
- Movement remains game-native: collision resolves through the stock movement path, and the bot returns to patrol after being pushed.
- Hostile targeting validation now has live proof on the stock wave path:
  - slot-1 bot actor `0x02D4D7A8` was promoted over the stock slot-0 player target
  - hostile `0x14A3D638` logged `promoted_bucket_delta=2048`
  - five seconds later that hostile still held `target = 0x02D4D7A8` with `mirror = 2048`
  - the bot's HP dropped from `50.0` to `18.5`, then to `-293.5`
- Cleanup: ActorWorld_Unregister → destructor → _aligned_free

### Key RE Findings:
1. `actor + 0x04`: render context / scene-graph node pointer. `Object_Ctor` (`0x00401FF0`) seeds it with a ctor sentinel and game initialization later overwrites it with a heap pointer. When it stays null/uninitialized, the actor has collision but no sprite. Copying the player's `+0x04` makes the bot visible but parents it to the player transform.
2. `actor + 0x05`: flag byte. Player probe reads `0`; fresh bot reads `1` after ctor. `ActorWorld_Register` checks this byte.
3. `Object_Allocate` (`0x00402030`): calls `operator_new` and stores the result in global `DAT_00B4019C`. `Object_Ctor` checks that global. Replacing `_aligned_malloc` with `Object_Allocate` caused heap corruption and needs more investigation.
4. Constructor chain: `FUN_00401FF0` (`Object`) -> `FUN_006287D0` (`Puppet`) -> `FUN_0052A410` (`GoodGuy`) -> `FUN_0052A500` (`Player`) -> `0x0052B4C0` (`PlayerActor`). Each layer writes its own vtable.
5. Player actor vtable at `0x00793F74`:
   - `[0] +0x00 = 0x0052D340` (destructor)
   - `[1] +0x04 = 0x0052B900`
   - `[2] +0x08 = 0x00548B00` (`PlayerActorTick`)
   - `[3] +0x0C = 0x00528A60`
   - `[4] +0x10 = 0x0042E260`
   - `[5] +0x14 = 0x00529C90`
   - `[6] +0x18 = 0x00401FD0` (sets `actor + 0x05 = 1`)
   - `[7] +0x1C = 0x0054BA80` (`ActorAnimationAdvance`)
   - `[14] +0x38 = 0x00623C60` (`ActorMoveByDelta`)
6. Stock `PlayerActorTick` must run. Returning early in puppet mode makes the bot invisible even when the rest of the visual state is present, so input isolation has to happen via puppet drive state instead.
7. Gameplay slot assignment is required. The bot must live in slot `1..3` at `gameplay + 0x1358 + slot * 4` for the arena render pipeline. Slot `-1` is invisible; slot `0` conflicts with the local player.
8. Arena rendering ignores the hub visual-link system. The local player in arena renders with null values at source profile (`+0x178`), equip runtime (`+0x1FC`), progression runtime (`+0x200`), anim state pointer (`+0x21C`), and the packed discrete frame-state field (`+0x22C`).
9. Synthetic source profile (`FUN_005E3080`) sets the weapon attachment and variant bytes correctly, but animation correctness still depends on preserving bot-owned `+0x21C` and `+0x220..+0x263` state instead of donor-copying those windows.

## Immediate Next Step

Recover or allocate a unique render node for `actor + 0x04` without tripping the `Object_Allocate` / heap-ownership path. Once the bot has its own scene node, fix sprite selection by supplementing the synthetic source profile with donor descriptor bytes.
