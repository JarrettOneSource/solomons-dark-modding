# Networking Architecture

Solomon's Dark is a single-player retail ARPG. The networking design adds
4-player co-op as a DLL-level mod: trusted-host Steam sessions, not competitive
anti-cheat, not persistent-world infrastructure. Launch scope is 4 players, but
protocol and roster code should avoid hardcoding 4 where practical so 8-10
player private sessions can remain a later stretch target instead of a launch
promise.

## TL;DR

One player hosts a normal Solomon's Dark session and becomes the authoritative world. Every other player sends movement and gameplay intents to the host; the host broadcasts authoritative player / enemy / drop / run state at ~20 Hz plus reliable gameplay events (cast, damage, pickup, wave transition). Clients render their own input immediately for responsiveness and hard-snap when the host disagrees. Multiplayer mode disables the dev/debug mutation backdoors and refuses mismatched mod sets so peers cannot silently diverge. No rollback, no serious anti-cheat, no dedicated server, no persistent-world machinery in the first ship — just one trusted-host Steam session that keeps everyone in the same fight and the same run.

## Implementation boundary

The current source has the multiplayer foundation and participant rail, not a
finished peer networking layer.

- `multiplayer_runtime_state.h` defines the shared `ParticipantInfo`,
  `MultiplayerCharacterProfile`, `ParticipantSceneIntent`, and runtime snapshot
  model used by Lua bots and future remote participants.
- `multiplayer_service_loop.cpp` pumps Steam bootstrap/callback state every
  50 ms and mirrors readiness into runtime state. It does not yet own peer
  sessions, packet IO, or replication.
- `multiplayer_runtime_protocol.h` is a fixed-packet scaffold with
  `State`, `Launch`, `Cast`, and `Progression` packets. The packet families
  below describe the target co-op protocol, not what the current header fully
  implements.
- `docs/multiplayer-participant-model.md` is the implementation-facing model
  for profiles, scene intent, Lua bots, and future remote players.

## Committed decisions

| Area | Decision |
|---|---|
| Authority | Host-authoritative-lite. Clients render local echo; hard-snap on host disagreement. |
| Transport | `ISteamNetworkingSockets` + Steam Datagram Relay (SDR) only in v1. |
| Off-Steam transport | **Not in v1.** GameNetworkingSockets / ENet / direct-IP deferred. |
| Dedicated server | **Not in v1.** P2P-host only for first ship. |
| Identity | Connection-bound. Host ignores client-declared player / actor IDs. |
| Mod compatibility | **Exact** protocol version + mod-manifest hash. Mismatch refuses connect. |
| Anti-cheat | None in the serious sense. Baseline hygiene only (see below). |
| Loot | Gold-only drops in v1. Non-gold inventory stays SP until non-gold RE work lands. |

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
- `progression-delta` — XP, gold, level, live loadout mutation (when non-gold lands)
- `disconnect / reconnect`

**Unreliable channel**
- `input` — per-client input w/ sequence number
- `snapshot-delta` — variable-size entity state burst, carrying `last_processed_input_seq` per receiving client

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

- `ITransport` abstraction + Steam `ISteamNetworkingSockets` impl
- Steam lobby → transport handoff
- `hello` + `manifest` handshake + `join/bootstrap` (chunked full-state)
- Input stream + player pose snapshots at target rates
- Enemy snapshot burst (20/30 Hz)
- Cast / damage / death events
- Wave + run lifecycle sync
- Gold-drop spawn + pickup-request/confirm/deny
- Progression-delta (XP / gold / level)

### Phase 2 — Hardening

- Stateful reconnect
- Admin tooling (kick / ban / adminlist)
- Latency simulation + stress test
- Soft reconciliation upgrade for hard-snap (interpolate to host pos over 100–200ms) if playtests show chatter

### Phase 3+ — Post-ship

- Dedicated server: `SteamGameServer_Init`, headless D3D9 stub, `--server` loader flag, slot-0 decoupling, server browser + direct-IP
- Off-Steam transport: standalone GameNetworkingSockets or ENet
- Non-gold inventory replication (after non-gold loot RE)

## Latency characteristics (what input lag looks like)

For a non-host client on a typical Steam SDR connection (50–100ms RTT):

| Action | Client experience |
|---|---|
| Movement | **Zero lag** — local echo applies input the frame it's pressed. |
| Cast spell (animation) | **Zero lag** — animation plays optimistically on key-down. |
| See damage numbers / hit resolve | **RTT delay** (~50–100ms) — host resolves, broadcasts. |
| Pick up gold | **RTT delay** — pickup-request → host confirm. |
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
- Inventory replication beyond gold
- Hot-swap of participant controller on live actor

## Known gaps we accept in v1

- Host can cheat in their own session (trusted-peer model)
- Cross-region divergence (host sims one region; multi-region is later work)
- Durable inventory persistence beyond one run (Phase 3+)
- Gold-only drops are likely the biggest intentional v1 gameplay limitation; non-gold inventory replication stays deferred until the RE work lands.

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
