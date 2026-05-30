# Networking Architecture

Solomon's Dark is a single-player retail ARPG. The networking design adds
4-player co-op as a DLL-level mod: trusted-host Steam sessions, not competitive
anti-cheat, not persistent-world infrastructure. Launch scope is 4 players, but
protocol and roster code should avoid hardcoding 4 where practical so 8-10
player private sessions can remain a later stretch target instead of a launch
promise.

## TL;DR

One player hosts a normal Solomon's Dark session and becomes the authoritative world. Every other player sends movement and gameplay intents to the host; the host broadcasts authoritative player / enemy / drop / run state at ~20 Hz plus reliable gameplay events (cast, damage, pickup, wave transition). Clients render their own input immediately for responsiveness and hard-snap when the host disagrees. Multiplayer mode disables the dev/debug mutation backdoors and refuses mismatched mod sets so peers cannot silently diverge. No rollback, no serious anti-cheat, no dedicated server, no persistent-world machinery in the first ship — just one trusted-host Steam session that keeps everyone in the same fight and the same run.

The implementation direction is client-predicted / authority-verified: clients
perform local movement and presentation immediately, then the host or dedicated
authority accepts, corrects, or rejects the claim. Clients never own canonical
HP, deaths, drops, XP, or wave state.

## Implementation boundary

The current source has the multiplayer foundation and participant rail, not a
finished peer networking layer.

- `multiplayer_runtime_state.h` defines the shared `ParticipantInfo`,
  `MultiplayerCharacterProfile`, `ParticipantSceneIntent`, and runtime snapshot
  model used by Lua bots and future remote participants.
- `multiplayer_service_loop.cpp` pumps Steam bootstrap/callback state every
  50 ms and mirrors readiness into runtime state. It also pumps the local UDP
  development transport when `SDMOD_MULTIPLAYER_TRANSPORT=local_udp`.
- `multiplayer_runtime_protocol.h` is a fixed-packet scaffold with
  `State`, `Launch`, `Cast`, `Progression`, `WorldSnapshot`, and
  `LootSnapshot` packets. The
  packet families below describe the target co-op protocol, not what the
  current header fully implements.
- `multiplayer_local_transport.cpp` is the first replication slice: two local
  processes exchange `StatePacket` movement/heading snapshots over UDP and
  materialize the peer as `RemoteParticipant + Native`. Remote player packets
  are kept in a short transform history; gameplay samples that history about
  120 ms in the past and applies interpolated position/heading on the actor
  tick. The gameplay sync queue is only for materialization/rematerialization,
  not continuous pose updates. The local host also sends passive
  `WorldSnapshot` packets for non-player shared-hub scene actors and run-world
  tracked enemies. Clients keep a short world-snapshot history, sample it about
  150 ms in the past, and expose the latest replicated snapshot through Lua for
  verification. Shared-hub actors are reconciled to the buffered host
  transform/heading snapshot on the gameplay thread; presentation state is
  overlaid from the latest same-timeline host snapshot so animation phase does
  not inherit the transform interpolation delay. Known phase-advancing named
  hub NPC families (`0x138B`, `0x138C`, `0x138D`) advance the replicated drive
  word by the measured native phase rate while waiting for the next snapshot.
  Named hub NPC serializers use recovered per-family allocation sizes for
  bounds; the larger player/Student render window is not reused for those
  classes. Hub snapshots also carry a typed presentation payload: the host's
  full hub animation-drive word
  for factory-backed hub NPCs, plus Student-specific book/variant bytes and
  randomized color/state bytes. Missing known hub
  NPC families (`0x1389`, `0x138A`, `0x138B`, `0x138C`, `0x138D`, `0x138F`,
  `0x1390`) are created through the stock factory plus generic world-register
  path before being reconciled. Run-world enemy
  snapshots now bootstrap client wave activation through the existing gameplay
  action queue and reconcile stock-created tracked enemies to the host
  transform/heading/drive snapshot, plus live HP/max-HP for matched tracked
  enemies. The run enemy presentation probe confirms the current wave enemy
  family does not need the hub-style full drive-word serializer: the wider
  drive word stays zero, the existing drive byte converges, and HP-zero dead
  state converges without writing the native death-handled byte. Run enemy
  snapshots prefer a host lifecycle spawn serial captured by
  the native enemy-spawn hook and allocate a stable host-local supplemental ID for
  tracked run actors that do not expose that serial; clients bind their local
  stock-spawned pool actors to those host IDs before applying reconciliation.
  If a client has fewer stock wave enemies than the host
  snapshot, it accelerates its native wave-spawner timers to fill the local
  enemy pool through the stock path. Extra client-side hub NPCs from replicated
  factory-backed families are unregistered from the client world so the hub NPC
  set converges to the host snapshot, and replicated hub NPCs created by the
  client are unregistered before a native scene switch so hub-to-run teardown
  does not leave loader-created actors in the outgoing world. Host-authoritative
  run entry is driven by the host's `StatePacket` scene intent: connected
  clients reject direct `sd.hub.start_testrun` calls and block direct arena
  `switch_region` attempts, then queue their local hub-to-run transition when
  the configured host reports `in_run`. Extra run enemies
  are still parked because the run enemy pool is stock-spawner owned. Run loot
  drops are not global-RNG lockstep state: they are host-owned lifecycle
  entities with reliable spawn/despawn, pickup-request, and pickup-confirm/deny
  events. The local UDP transport now sends a run-only `LootSnapshot` metadata
  slice for host gold drops (`0x7DC`) with a stable host drop id, amount, tier,
  active byte, lifetime, and position, and exposes the client view through
  `sd.world.get_replicated_loot()`. This deliberately does not spawn a stock
  local gold actor on the client yet: stock pickup still credits the
  process-global slot-0 gold scalar, so authoritative pickup must be hooked and
  routed into participant-owned inventory/gold/book state first. This is a
  development transport, not the final Steam P2P backend.
- `docs/multiplayer-participant-model.md` is the implementation-facing model
  for profiles, scene intent, Lua bots, and future remote players.
- `docs/networking/world-sync-authority-plan.md` records the current hub NPC
  live/RE evidence and the decision to use host-authoritative world snapshots
  instead of global-RNG lockstep for non-player actors.

## Committed decisions

| Area | Decision |
|---|---|
| Authority | Host-authoritative-lite. Clients render local echo; hard-snap on host disagreement. |
| Transport | `ISteamNetworkingSockets` + Steam Datagram Relay (SDR) only in v1. |
| Local dev transport | UDP loopback can be enabled with `SDMOD_MULTIPLAYER_TRANSPORT=local_udp` so two local stage instances can test connection and pose sync without two Steam accounts. |
| Off-Steam transport | **Not in v1.** GameNetworkingSockets / ENet / direct-IP deferred. |
| Dedicated server | **Not in v1.** P2P-host only for first ship. |
| Identity | Connection-bound. Host ignores client-declared player / actor IDs. |
| Mod compatibility | **Exact** protocol version + mod-manifest hash. Mismatch refuses connect. |
| Anti-cheat | None in the serious sense. Baseline hygiene only (see below). |
| Loot | Synced host-owned run drops. Each participant owns their own inventory, gold, spellbook, and statbook state; stock slot-0/global pickup paths must be replaced or bypassed before pickups become authoritative. |

## Tick rates

| Channel | Rate |
|---|---|
| Client → host input | 30 Hz |
| Player snapshots | 20 Hz |
| Enemy snapshots (baseline) | 20 Hz |
| Enemy snapshots (bosses / hot states) | 30 Hz |
| Reliable events | Immediate |

Sampling happens on the stock game thread after native updates — no extra sim thread.

## Player count / scaling

- v1 is designed, tested, and balanced around **4-player co-op**.
- Avoid hardcoding `4` into protocol, roster, or actor-plumbing decisions where the cost is low.
- `8-10` players is a plausible later private-session stretch target, but **not** a launch commitment.
- Above 4 players, the likely bottlenecks are host CPU and enemy / effect / drop replication fanout, plus combat readability, more than raw player-input traffic.

## Packet families

**Reliable channel**
- `hello / manifest` — protocol version + exact mod-manifest hash
- `join / bootstrap` — participant upsert + chunked full-state for fresh/reconnecting clients
- `spawn / despawn` — entity lifecycle
- `gameplay-event` — casts, damage, death, pickups, wave/boss transitions, run start/end
- `loot-drop` — host-owned drop spawn/despawn state for gold, item, potion,
  orb, and powerup carriers as each native pickup seam is proven
- `pickup-request / pickup-result` — client intent, host sanity check, and
  per-participant inventory/spellbook/statbook credit
- `progression-delta` — XP, gold, level, spellbook, statbook, and live loadout
  mutation
- `disconnect / reconnect`

**Unreliable channel**
- `input` — per-client input w/ sequence number
- `snapshot-delta` — variable-size entity state burst, carrying `last_processed_input_seq` per receiving client
- `state` — current fixed-packet development snapshot for local UDP movement /
  heading tests. Carries network `participant_id`, profile/loadout summary,
  vitals, position, and heading.

**Explicitly not in v1:** `clock-sync`, `save-provenance`, input-replay-for-rollback.

## Authority table

| Entity | Authority | Sync | Rate |
|---|---|---|---|
| Local player | Self (input) → host (sim) → broadcast | Input to host w/ seq; host pose broadcast; local echo; hard-snap on correction | Input 30 Hz · pose 20 Hz |
| Remote player | Their client's input → host → snapshot | Snapshot interpolation | 20 Hz |
| Enemies | Host | Snapshot burst (pos + vel + hp + state) | 20 Hz · 30 Hz for bosses / hot states |
| Drops | Host | Reliable spawn; reliable pickup-request + confirm/deny | Event-driven |
| Casts | Caster optimistic (plays anim); host broadcasts + confirms hit | Reliable event | Event-driven |

## Phase order

### Phase 0 — Gating (non-negotiable before *any* network traffic ships)

- Multiplayer runtime profile that disables:
  - Named-pipe Lua exec server (`lua_exec_pipe`)
  - `sd.debug` mutators (write_*, write_field_*, copy_bytes, call_*, nav-grid copy)
  - Debug-UI mutation paths (`activate_action`, `activate_element`, `perform`, `direct_write`)
  - `sd.hub.start_testrun`, `sd.gameplay.start_waves`, `sd.world.spawn_*`, `sd.input.*`
  - Native-DLL mod host arbitrary loading → manifest allowlist
  - On non-host clients: `sd.bots.*` and all gameplay-mutating Lua surface except host-intent RPCs
- Generic `ReadParticipantSnapshot` + controller-source interface keyed by `participant_id`
- `RemoteParticipant + Native` supported at actor creation (pre-materialization swap only; no hot-swap)
- Seed `run_nonce` for real — stop treating the schema field as scenery
- Packet sanitation: size / version / family + stale-sequence rejection

### Phase 1 — P2P host MVP

- Local UDP two-process development harness:
  `scripts/Launch-LocalMultiplayerPair.ps1` launches `local-mp-host` and
  `local-mp-client` with separate runtime/stage roots and ports `47770/47771`.
  The client launch uses `--temporary-profile`, which redirects APPDATA,
  LOCALAPPDATA, and the staged `savegames` compatibility path into a fresh
  runtime-local temporary profile so joining a multiplayer host cannot mutate
  the user's single-player save files.
  This validates participant connection plus movement/heading materialization
  without Steam identity constraints. The harness assigns
  `SDMOD_MULTIPLAYER_PLAYER_NAME` and unique `SDMOD_LUA_EXEC_PIPE_NAME` values
  so both copies can be probed without colliding on the default Lua exec pipe.
  `tools/verify_local_multiplayer_sync.py` is the live smoke test for hub/run
  participant visibility, host-authoritative run entry, connected-client
  run-start blocking, idle movement/heading convergence, player/player
  collision push, and remote nameplate resolution.
- `ITransport` abstraction + Steam `ISteamNetworkingSockets` impl
- Steam lobby → transport handoff
- `hello` + `manifest` handshake + `join/bootstrap` (chunked full-state)
- Input stream + player pose snapshots at target rates
- Enemy snapshot burst (20/30 Hz)
- Cast / damage / death events
- Wave + run lifecycle sync
- Loot-drop spawn/despawn + pickup-request/confirm/deny
- Progression-delta (XP / gold / level / spellbook / statbook / live loadout)

### Phase 2 — Hardening

- Stateful reconnect
- Admin tooling (kick / ban / adminlist)
- Latency simulation + stress test
- Soft reconciliation upgrade for hard-snap (interpolate to host pos over 100–200ms) if playtests show chatter
- The local UDP development backend already uses snapshot interpolation for
  remote player and world actor presentation; the later Steam backend should
  reuse that boundary instead of reintroducing latest-packet playback.

### Phase 3+ — Post-ship

- Dedicated server: `SteamGameServer_Init`, headless D3D9 stub, `--server` loader flag, slot-0 decoupling, server browser + direct-IP
- Off-Steam transport: standalone GameNetworkingSockets or ENet
- Durable participant inventory/book persistence after the per-run ownership
  model is proven

## Latency characteristics (what input lag looks like)

For a non-host client on a typical Steam SDR connection (50–100ms RTT):

| Action | Client experience |
|---|---|
| Movement | **Zero lag** — local echo applies input the frame it's pressed. |
| Cast spell (animation) | **Zero lag** — animation plays optimistically on key-down. |
| See damage numbers / hit resolve | **RTT delay** (~50–100ms) — host resolves, broadcasts. |
| Pick up loot | **RTT delay** — pickup-request -> host confirm; the host credits the owning participant's inventory, gold, spellbook, or statbook state. |
| See enemies | **100–150ms in the past** — snapshot interpolation buffer. |
| Hard-snap / rubber-band | **Rare** — collision edge cases, desync after host correction. |

Host feels none of this; their sim is local.

The intended feel is native local movement with delayed authoritative
confirmation for hits, pickups, and other host-owned outcomes. Under normal
latency the correction path should be rare; if hard-snaps become visibly
disruptive in playtest, Phase 2 adds soft reconciliation by interpolating toward
host position over a short window.

## What we are explicitly NOT doing in v1

- Client-side prediction + reconciliation (rollback)
- Clock-sync packet family
- Client-side hit validation / lag compensation
- Save-file merging / migration between sessions
- Dedicated server
- Off-Steam transport
- Injected anti-cheat (EAC / BattleEye / VAC)
- Persistent-world machinery
- Hot-swap of participant controller on live actor

## Known gaps we accept in v1

- Host can cheat in their own session (trusted-peer model)
- Cross-region divergence (host sims one region; multi-region is later work)
- Durable inventory/book persistence beyond one run (Phase 3+)
- Non-gold item and potion materialization still need native pickup/factory RE,
  but the multiplayer model no longer treats them as single-player-only state.

## Run-identity object (replaces "save-provenance" from earlier drafts)

Minimal fields sent at join:

- `run_nonce` (seeded for real, not placeholder)
- host / session id
- region / mission seed or lineup
- participant roster
- per-participant character / loadout snapshot
- mod-manifest hash
- protocol version
- started-at tick

No backup / restore / migration / save-transfer in v1.
