# Netcode Review — 2026-07-23

A code-level assessment of the multiplayer stack: architecture, interpolation,
bandwidth, and a ranked improvement list. Everything below was verified against
source on this date (protocol 81); file references are exact so items can be
picked up without re-deriving them.

## Verdict

The netcode is genuinely good — unusually disciplined for a DLL-level mod. The
trusted-host model (client echo + authority verification, no rollback) is the
right architecture for 4-player co-op, and the implementation carries it
through: fail-closed validation, epoch/nonce guards everywhere, deterministic
host-seeded world generation, and per-lane bandwidth budgets. The improvement
list below is optimization work, not rescue work.

## Verified inventory (code truth, not the README table)

Send cadences and budgets — `multiplayer_local_transport.cpp:92-146`
(shared by the Steam backend through `QueueSteamGameplayPacketSend`):

| Lane | Interval | Mode |
|---|---|---|
| Participant frame (pose/vitals/wave summary) | 50 ms (20 Hz) | UnreliableNoDelay |
| World snapshot (enemies/hub NPCs) | 200 ms base (5 Hz), bandwidth-stretched | UnreliableNoDelay |
| World snapshot reliable checkpoint | 1000 ms base | ReliableNoNagle |
| State checkpoint (`StatePacket`, ~5 KB) | 1000 ms | ReliableNoNagle |
| Loot snapshot | 250 ms (animated: 50 ms) | UnreliableNoDelay |
| Spell-effect snapshot | 16 ms | UnreliableNoDelay |
| Lua mod state checkpoint | 5000 ms | ReliableNoNagle |
| Cast input (held phase) | 50 ms | UnreliableNoDelay (press/release reliable) |

Budgets: world 96 KB/s, auxiliary 48 KB/s, reliable checkpoint 24 KB/s
(`BandwidthLimitedSnapshotIntervalMs` stretches intervals rather than
dropping). Send-mode mapping: `outgoing_packet_sync.inl:1-24`. Service thread
ticks at 16 ms and owns Steam callbacks/session/send queue
(`multiplayer_service_loop.cpp:21`); inbound gameplay packets drain on the
game thread.

Interpolation:

- Remote players: 120 ms fixed delay
  (`bot_movement/native_remote_playback.inl:9`), 8-sample receive-time history
  (`kParticipantTransformHistoryCapacity`,
  `multiplayer_runtime_effect_state.inl:194`).
- World actors: 150 ms fixed delay
  (`world_snapshot_reconciliation/state_timeline_and_formation.inl:3`).
- Sampler (`multiplayer_runtime_state.cpp:454`): lerp position, shortest-arc
  heading, and the walk-cycle/render-drive floats; snap across run/scene
  boundaries; hold-last on starvation (no extrapolation). Presentation fields
  ride the newest bracketing sample so animation does not inherit the
  transform delay.

Packet economics (`multiplayer_runtime_protocol.h`):

- `WorldActorSnapshotPacketState` ≈ 250+ B/actor, 3 actors per fragment
  (`kWorldSnapshotActorsPerFragment`, header line 16). 60 enemies ≈ 20
  fragments ≈ ~18 KB per generation → ~90 KB/s per client at 5 Hz, i.e. at
  the budget ceiling.
- `ParticipantFramePacket` ≈ ~500 B (includes a 20-row wave summary, ~240 B)
  at 20 Hz, sent peer-to-peer full mesh.
- `StatePacket` carries full 64-item inventory + 128-entry progression-book
  arrays (~5 KB) every checkpoint, change or not.

## What's strong

- Per-participant sequence staleness rejection + session-nonce epochs for
  reconnects; retired-nonce packets ignored.
- Scene-epoch / run-nonce guards on snapshot application; fragmented snapshot
  reassembly is generation-consistent.
- Reliable checkpoint lane separates structural convergence from disposable
  visual updates — the correct split.
- Host-seeded deterministic RNG for Boneyard generation (scenery is generated,
  not replicated), with the seed re-applied at the `Arena_Create` boundary.
- Loot/pickups/level-ups are host-owned request/confirm lifecycles; the
  level-up barrier auto-picks after 60 s so loss cannot strand a client.
- Multiplayer profile disables every debug mutation backdoor (fail closed).

## The interpolation problem worth fixing

World actors interpolate at a **150 ms delay against a 200 ms snapshot
interval**. The delay is shorter than the packet spacing, so the sampler runs
out of "future" sample for the tail of every window and holds position —
enemies micro-step at 5 Hz, and the bandwidth limiter stretches this further
on heavy waves. Remote players are healthy (120 ms vs 50 ms spacing = 2.4
intervals of buffer). The README's "20 Hz enemy snapshots" table is
aspirational; the code ships 5 Hz.

Fixes, in payoff order:

1. Make higher rates affordable (see below), then run world snapshots at
   10–15 Hz.
2. Adaptive delay: derive delay from observed per-lane arrival spacing
   (~1.5 × recent p90) instead of a constant, so it self-corrects when the
   budget limiter stretches sends.
3. Cheap remote-player extrapolation: `movement_intent` is already replicated;
   project it for one missed frame before hold-last to hide relay jitter.

## Ranked optimizations

1. **Split world-actor identity from motion.** Most of the ~250 B/actor is
   static per actor (Lua spawn params, Student book palettes, named-hub-NPC
   presentation, type/slot identity) and reships every generation. Move it to
   a reliable send-on-spawn/change record; keep a hot motion record (id, pos,
   heading, hp, anim word, walk phase ≈ 40–50 B) in the unreliable lane.
   ~5× steady-state reduction → 15–20 Hz enemy snapshots inside the existing
   96 KB/s budget. This is the single highest-value change.
2. **Change-gate the `StatePacket` checkpoint arrays.** Revision counters
   already exist (inventory/equipment/books); send the big arrays only when
   the corresponding revision moved.
3. **Move the wave summary off the 20 Hz frame lane.** It changes on
   kills/spawns, not frames; send on change or on a 250–500 ms lane.
4. **Coalesce spell-effect snapshots.** The 16 ms lane sends per effect;
   bundle all active effects into one packet per tick to cut header overhead
   during heavy fights.
5. **Smooth authority corrections.** Hard snaps are correct but jarring; a
   ~100 ms exponential blend on correction application would remove the jar
   without weakening authority.
6. Position quantization (int16 centimeters, region-relative) — only worth it
   after item 1.

## Scaling notes (post player-count-255 change)

- Participant frames are full mesh (O(N²)) and host world fanout is ~90 KB/s
  per client: ~8–10 players is the practical ceiling before interest
  management (distance-scored per-client actor scheduling) becomes necessary.
- `kLevelUpWaitStatusMaxParticipants = 8` (`multiplayer_runtime_protocol.h:22`)
  truncates the level-up waiting list in a 9+ lobby — the one concrete packet
  ceiling below 255.
- The native game seats 4 wizards regardless; >4 participants is framework
  territory, not proven gameplay.

## Known open issue in this area

The kill-stress harness previously narrowed a post-cast convergence timeout to
loader participant **transform ownership** (loader-driven march after casts —
see memory/stress-harness notes). Interpolated targets are applied by direct
position writes each tick, so ownership ambiguity manifests as exactly this
drift. Resolve it before deep interpolation tuning; it pollutes measurements.

## Doc drift to fix in `README.md`

- Tick-rate table: says 20 Hz snapshots / 30 Hz input / 50 ms service pump;
  code ships 5 Hz world (budget-stretched), 20 Hz frames, 1 Hz state
  checkpoint, 16 ms service tick.
- `StatePacket` described as the movement lane; it is now the 1 Hz reliable
  checkpoint, with `ParticipantFramePacket` as the pose lane.
