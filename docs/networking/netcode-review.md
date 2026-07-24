# Netcode Review — 2026-07-23

This is a source-level review of the current multiplayer transport, protocol,
interpolation, and steady-state packet cost. It also records the disposition of
each optimization identified during the review. The code and packet sizes below
are for protocol 82.

## Verdict

The trusted-host design is appropriate for cooperative play: owners publish
their player state, the host owns world actors and shared progression
lifecycles, and receivers reject packets that do not match the expected
endpoint, participant session, scene epoch, or run nonce. The original review
did find a real world-motion cadence problem and three unnecessarily hot payload
families. Protocol 82 addresses those without changing the authority model.

The remaining scaling boundary is gameplay, not a hidden eight-player wire
limit. The level-up barrier now carries a variable-length list of as many as 250
participants, matching the configured Steam lobby ceiling, while the native game
still has only four proven wizard seats.

## Current wire lanes

The authoritative constants live in
`SolomonDarkModLoader/src/multiplayer_local_transport.cpp`; packet layouts and
compile-time sizes live in
`SolomonDarkModLoader/include/multiplayer_runtime_protocol.h`.

| Lane | Payload | Cadence | Steam mode |
|---|---:|---|---|
| Participant frame | 322 B | 50 ms / 20 Hz | UnreliableNoDelay |
| Participant state checkpoint | 604 B | 1,000 ms | ReliableNoNagle |
| Run-world motion | 968 B per 10 actors | 67 ms minimum / about 15 Hz, bandwidth-stretched | UnreliableNoDelay |
| Run-world identity | 1,032 B per 3 actors | spawn/identity change plus bandwidth-limited reliable checkpoint | ReliableNoNagle |
| Shared-hub world state | 1,032 B per 3 actors | 200 ms minimum / 5 Hz, bandwidth-stretched | Unreliable with reliable checkpoints |
| Inventory snapshot | 40 B + 28 B/item | first send, revision change, and 5 s checkpoint | ReliableNoNagle |
| Progression-book snapshot | 44 B + 20 B/entry | first send, revision change, and 5 s checkpoint | ReliableNoNagle |
| Wave summary | 296 B | change plus 400 ms checkpoint | UnreliableNoDelay |
| Loot snapshot | variable | 250 ms; 50 ms while animated | UnreliableNoDelay |
| Native spell effects | 32 B + 124 B/effect | one coalesced generation per 16 ms tick | UnreliableNoDelay |
| Lua mod state | variable fragments | 5,000 ms checkpoint | ReliableNoNagle |
| Cast input | 128 B | held update every 50 ms | held unreliable; press/release immediate unreliable plus reliable convergence |

The world-motion budget is 96 KiB/s, auxiliary snapshots use 48 KiB/s, and
reliable world-identity checkpoints use 24 KiB/s. The limiter increases a
lane's interval when its complete fragmented generation would exceed the
corresponding budget.

For a 60-actor run generation, motion uses six 968-byte fragments, or 5,808
bytes. At the 67 ms base interval that is about 86.7 KB/s per receiving peer,
inside the 96 KiB/s budget. The old full-state format required twenty
1,032-byte fragments per generation, or 20,640 bytes; at 5 Hz it exceeded the
same budget and was necessarily stretched.

## World identity and motion

Run actors now use two packet families:

- `WorldSnapshot` is the structural record. It carries native and Lua identity,
  spawn configuration, presentation identity, and the full actor state needed
  to bootstrap or recover a receiver. It is sent reliably when identity changes
  and as a convergence checkpoint.
- `WorldMotionSnapshot` is the hot record. Its 92-byte actor rows carry network
  identity, target, transform, health, animation, locomotion, and transient
  status. Each validated fragment independently updates the matching actors in
  a rolling identity-backed snapshot. Per-actor generation checks prevent a
  late fragment from regressing newer motion.

Shared-hub NPCs retain the full snapshot path because their rich presentation
identity is part of the state being animated and their actor count is small.

Structural snapshots retain generation-consistent fragment assembly. Disposable
motion fragments reject stale actors and mixed scene/run timelines individually;
a motion fragment without a matching full identity cannot invent an actor.

## Protocol-82 regression follow-up — 2026-07-24

### Test gap

The original acceptance matrix used scripted single-enemy damage probes, final
pose convergence, and eventual Fire cast release. It never sampled sustained
organic combat with enough live enemies to fragment a motion generation, and it
never timestamped the start and stop edges of a short client-owned Air
(Lightning) cast. Green results from that matrix therefore did not cover either
reported regression.

### Findings and correction

- Multi-enemy state was neither corrupted nor routed through the 400 ms wave
  summary lane. Run motion remained on its approximately 15 Hz disposable lane,
  but the receiver withheld an entire generation until every motion fragment
  arrived. Losing one fragment from a two-or-more-fragment organic generation
  discarded useful updates for all other enemies and produced long client
  stalls. The receiver now applies each validated fragment immediately to its
  matching actor subset. A rolling identity-backed snapshot retains the newest
  state for actors in other fragments, and per-actor snapshot IDs reject late
  regressions.
- Cast input was not coalesced with participant frames or wave summaries.
  Press and release were one-shot `ReliableNoNagle` messages on Steam channel
  zero, so either edge could wait behind retransmission of a fragmented
  structural checkpoint. Held input and Air terminal frames used the
  low-latency lane, but an Air terminal frame did not release the remote native
  input lifecycle. Press and release now send an immediate
  `UnreliableNoDelay` copy before the reliable convergence copy. Receivers
  deduplicate the shared packet sequence before playback and relay, preserving
  one semantic edge without a retry timer.
- Participant-frame slimming, the change-driven/400 ms wave summary, and the
  variable level-up barrier are not on either failing application path and were
  retained.

The isolated pre-fix organic loopback sample reached a 704 ms client motion
arrival gap and 65.756 units of native-clone error even though every completed
authoritative payload matched the host. After partial-fragment application, the
same live gate held at 125 ms maximum arrival gap, 26.313 units maximum clone
error, zero authoritative position/HP/state error, and 12–16 simultaneously
compared moving enemies. Both players took real enemy damage. The 12-frame
client Air cast reached the host in 24 ms, stopped there 16 ms after client
release, differed in observed duration by 8 ms, and completed 22 ms after
release.

## Interpolation and correction

Remote participants retain an eight-sample receive-time history and a 120 ms
presentation delay. Interpolation covers the normal 50 ms frame cadence. If a
sample time runs beyond the newest frame, the sampler can extrapolate observed
velocity for at most one observed arrival interval, but only while non-zero
movement intent agrees with that velocity. Idle, reversed, invalid, and
cross-scene samples hold the last authoritative transform.

World actors no longer use an unconditional 150 ms delay. The recommended
delay is `1.5 * recent arrival p90`, clamped to 100–600 ms, with a 150 ms
fallback until two compatible samples exist. This follows both the normal
15 Hz run lane and any interval stretching caused by the bandwidth limiter.
Position, shortest-arc heading, and locomotion phase interpolate within one
scene/run timeline; presentation fields can still use the newest compatible
snapshot so animation does not inherit transform latency.

Run enemies already had correction smoothing before this review: ordinary live
errors below 192 world units apply a 0.2 soft-correction factor, while large
errors, deaths, forced writes, and relevant transient states take the
authoritative transform immediately. No second generic correction blend was
added because it would obscure the existing authority and damage-observation
rules.

## Cold participant state

`StatePacket` remains a 1 Hz reliable convergence record for profile,
equipment, derived progression, scene/run intent, vitals, transform, and
revision counters. It no longer embeds the fixed 64-item inventory and
128-entry progression-book arrays.

Inventory and book rows now have separate variable-length, owner-authored
packets. Each receiver validates the exact prefix-plus-row wire length,
participant session, row count, row identity, and revision before replacing
replicated state. The sender evaluates changes during its state checkpoint,
sends on first observation or revision change, and repeats each record every
five seconds for convergence. A packet stale in either book revision is
rejected.

The level-up barrier likewise uses an exact variable wire length. Its 52-byte
prefix is followed by 32 bytes per participant, up to 250 participants; unused
capacity is never transmitted. The state checkpoint no longer carries a second
truncated barrier copy that could overwrite the dedicated reliable record.

## Wave and spell-effect traffic

The 20-row wave summary has moved out of `ParticipantFramePacket`. The host now
sends one authenticated `WaveSummary` packet when the semantic summary changes
and repeats it every 400 ms. Clients accept it only from the configured
authority endpoint and session, and validate phase, row ordering, row totals,
and aggregate totals before replacing their semantic view.

The original review's spell-effect recommendation was based on a mistaken read
of the 16 ms send interval. Native effects were already coalesced: one
variable-length generation carries as many as 32 active effects, including
terminal tombstones needed to survive transient loss. No per-effect packet
split existed to remove.

## Optimization disposition

| Rank | Review item | Disposition |
|---:|---|---|
| 1 | Split world identity from motion | Implemented in protocol 82; run motion is about 15 Hz within the existing budget. |
| 2 | Change-gate large participant arrays | Implemented as variable reliable inventory and progression-book packets. |
| 3 | Move wave summaries off the frame lane | Implemented as authenticated change/400 ms snapshots. |
| 4 | Coalesce spell effects | Already implemented before the review; documentation corrected. |
| 5 | Smooth authority corrections | Existing 0.2 soft correction retained; hard corrections remain for explicit authority boundaries. |
| 6 | Quantize positions | Deferred. The actor split meets the present budget, and quantization needs measured world-range and precision evidence before changing the wire representation. |

## Scaling and security notes

- Participant frames are peer fanout traffic, so aggregate traffic still grows
  quadratically with player count. The four-player launch target is unaffected;
  a larger lobby will eventually need per-peer interest management.
- Host world traffic grows linearly with receiving peers. At the 60-actor
  example, each peer receives about 87 KB/s of disposable motion plus reliable
  structural checkpoints.
- The 250-entry barrier removes the previous protocol truncation, but it does
  not claim that 250-player native gameplay is supported.
- Packet-family, exact-size, bounded-count, sequence, endpoint, participant
  session, scene-epoch, run-nonce, and authority checks remain fail closed.
- Steam and loopback UDP use the same packet validation and application paths;
  loopback UDP is the deterministic multi-process test backend, not a weaker
  schema.

## Regression gates

`tests/native/multiplayer_runtime_state_tests.cpp` exercises adaptive world
delay, bounded participant extrapolation, protocol sizes, exact variable packet
lengths, and a full 250-participant level-up barrier. The static RE/transport
suite checks the packet split, send modes, authority validation, project
membership, and documentation contracts. The normal Windows loader build keeps
all packet `static_assert` sizes enforced by MSVC, while CI also compiles and
runs the native runtime-state regression on Linux.

`tests/native/world_motion_fragment_merge_tests.cpp` drops alternating fragments
from 12-actor generations and proves that received enemy subsets advance while
untouched actors remain stable; it also rejects a late fragment without
regression. `tools/verify_multiplayer_organic_enemy_cast_timing.py` is the live
two-instance loopback gate. It requires at least six natural enemies and four
moving enemies, bounds host/client authoritative and client-native position,
HP, animation, target, and arrival-gap measurements throughout organic combat,
and confirms that enemies actually damage a player. The same run casts client
Air for 12 frames and requires both host-observed start and stop within 150 ms,
host/client duration error within 100 ms, and native completion within 250 ms
of the client release.
