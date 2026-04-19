# Solomon's Dark: Netcode Plan v3 (lightweight / mod-context)

Date: 2026-04-19
Status: Final-candidate. Revised from v2 after user reframing.

## Reframing (new constraints from user)

- This is a **mod adding multiplayer to a single-player game**, not a from-scratch online game.
- Not an FPS. Not competitive. Simple co-op ARPG.
- **Goal**: synchronized world state so players can play together and have fun.
- **Drop anti-cheat if it adds meaningful architectural complexity.** Accept modded clients may cheat in their own session.
- **Drop full server-authoritative prediction + reconciliation if it requires engine rewrite.** Accept occasional hard snap on host correction.
- Keep it simple. Keep it shippable.

## What we're actually building

**Host-authoritative-lite, trusted-peers model.**

- Host runs the game sim. Clients are presentation + input source.
- Clients send inputs / intents to host. Host broadcasts world state.
- Clients show their own movement immediately (input is local → feels responsive). If host disagrees, hard snap. No replay/rollback.
- No server validation of hits / lag compensation / prediction rollback. Accepted trade-off for a co-op mod.
- No anti-cheat beyond baseline hygiene: disable dev mutators (`sd.debug`, exec pipe, native-mod arbitrary load, debug-UI direct_write) in multiplayer builds; connection-bound identity; malformed-packet drop.

This is closer to **Terraria / Magicka / Divinity: Original Sin** than to Diablo 4 or CS.

## Authority table (simplified)

| Entity | Authority | Sync | Rate |
|---|---|---|---|
| Local player | Self (input) → host (sim) → broadcast | Input to host with seq; host pose broadcast; local echo for responsiveness; hard snap on correction | Input 30 Hz; pose 20 Hz |
| Remote player | Their client's input → host → snapshot | Snapshot interpolation | 20 Hz |
| Enemies | Host | Snapshot burst (pos + vel + hp + state) | 20 Hz baseline, 30 Hz bosses / hot states |
| Drops | Host | Reliable spawn; reliable pickup-request + confirm/deny | event-driven |
| Casts | Caster optimistic (play animation); host broadcasts + confirms hit | Reliable event | event-driven |

## Transport

- **Steam path**: `ISteamNetworkingSockets` + Steam Datagram Relay (SDR).
- **Off-Steam path**: Standalone GameNetworkingSockets (API symmetry with Steam) OR ENet (smaller footprint).
- **Loopback**: in-process for testing.
- One `ITransport` interface above the line; Phase 1-4 code is transport-agnostic.

## Protocol

Variable-size envelope + payload families. Replaces v1 fixed structs.

**Reliable channel:**
- `hello` — version, mod-manifest hash
- `join / auth` — participant upsert
- `world-bootstrap` — chunked full state for fresh/reconnecting clients
- `spawn / despawn` — entity lifecycle
- `cast-event`, `damage`, `death`, `drop-event`, `pickup-request`, `pickup-confirm/deny`
- `wave-event`, `boss-phase-event`, `run-end`
- `progression-delta` — XP, gold, level, loadout, inventory mutation
- `disconnect / reconnect`

**Unreliable channel:**
- `input` — per-player input w/ seq
- `snapshot-delta` — variable-size entity state burst

**Not included in v1:**
- `clock-sync` (no single authoritative sim tick exists in the engine)
- `save-provenance` (replaced with lightweight run-identity object)
- input-replay-for-rollback (no rollback in this plan)

## Run-identity object (replaces v2's save/world object)

Minimal:
- `run_nonce` (once we actually seed it — `run_nonce` is currently a schema placeholder, never written)
- host / session id
- region / mission seed or lineup
- participant roster
- per-participant character/loadout snapshot
- mod-manifest hash
- protocol version
- started-at tick

No backup/restore/migration/save transfer in v1.

## Dropped from v2

- ❌ Client-side prediction + reconciliation (rollback). Engine doesn't support it for the slot-0 player; only bot-puppet path has replayable movement. Downgraded to local cosmetic echo + hard snap.
- ❌ Clock-sync packet family. Multiple local `GetTickCount64` clocks; no authoritative sim tick. Not needed without rollback.
- ❌ Save provenance as a replicated object. Overapplied from persistent-world co-op. Replaced with run-identity object.
- ❌ Trust partitioning between private-host and secure-dedicated. Accept host is trusted in P2P.
- ❌ EAC/BattleEye/VAC/any injected anti-cheat.
- ❌ Lag-comped hitscan with position-history rewind. Not needed for ARPG projectile/AoE spells.

## Kept from v2 (non-negotiables)

- ✅ `ISteamNetworkingSockets` (not deprecated `ISteamNetworking`).
- ✅ Variable-size envelope protocol (not fixed structs).
- ✅ Connection-bound identity (host ignores client-declared player IDs — lesson from the shooter repo).
- ✅ Unreliable state lanes + reliable event lanes.
- ✅ 20 Hz enemy baseline, 30 Hz bosses + hot states.
- ✅ Real multiplayer runtime profile (kill dev mutators).
- ✅ Mod-manifest handshake on join.
- ✅ Phased order: runtime-profile + participant abstraction → P2P host → enemy+drop sync → dedicated → hardening.

## Phases

### Phase 0 — Multiplayer runtime profile + participant abstraction
Non-negotiable prerequisite for ANY network code.

- Multiplayer build profile that disables:
  - Named-pipe Lua exec server
  - `sd.debug` binding registration (writes, native calls, field accessors, nav-grid copy)
  - Debug-UI mutation (`activate_action`, `activate_element`, `perform`, `direct_write`)
  - `sd.hub.start_testrun`, `sd.gameplay.start_waves`, `sd.world.spawn_*`, `sd.input.*`
  - Native DLL mod host arbitrary loading (either disable, or require manifest allowlist)
  - For non-host clients: disable `sd.bots.*` and all gameplay-mutating Lua surface except host-intent RPCs
- Generic `ReadParticipantSnapshot` + controller-source interface keyed by `participant_id`
- Support `RemoteParticipant + Native` at actor creation time (pre-materialization swap)
- Slot-0 decoupling: safe game-thread pump that runs without a live local-player actor (needed for dedicated in Phase 3, but architecturally clean to isolate now)

### Phase 1 — P2P host mode (hidden-local-player = host)
- `ITransport` + Steam `ISteamNetworkingSockets` impl
- Steam lobby → transport handoff
- `hello` + `join/auth` + mod-manifest handshake
- `world-bootstrap` packet
- Input stream + pose snapshot
- Cast event, damage, death
- Basic wave/run lifecycle sync (requires seeding `run_nonce` for real)

### Phase 2 — Enemy + drop sync
- Enemy seam RE: damage, attack-start, teleport, boss-phase, stagger
- 20 Hz enemy snapshot burst, 30 Hz bosses + hot states
- Reliable enemy lifecycle events
- Drop spawn / pickup-request / confirm-deny (start gold-only; scope beta accordingly)
- Progression-delta packets (XP / gold / level)

### Phase 3 — Dedicated server
- `SteamGameServer_Init` anonymous bootstrap
- Headless D3D9 stub + `--server` loader flag
- Server browser + direct-IP connect
- Run-identity object with mod-manifest + protocol version check

### Phase 4 — Hardening
- Stateful reconnect
- Admin tooling (kick/ban/adminlist)
- Latency simulation + stress test
- Inventory replication if non-gold RE lands

## Known gaps we're explicitly NOT solving in v1

- Host abuse in P2P (accept that trusted-peer model means host can cheat)
- Strict mod-compatibility (simple manifest hash; tolerant policy)
- Cross-region divergence (host sims one region; multi-region is later)
- Save file merging / migration between sessions
- Inventory durable persistence beyond one run (Phase 4+)
- Hot-swap participant controller on live actor (pre-materialization only)

## Open question for Codex v3 consolidation pass

Given the user's stated framing — mod context, simplicity over completeness, drop anti-cheat if too expensive, keep synchronized world state — does this plan land correctly? Are we still over-engineering anywhere, or under-engineering somewhere critical?
