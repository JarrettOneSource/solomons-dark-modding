# Netcode Review — 2026-07-23

This is a source-level review of the current multiplayer transport, protocol,
interpolation, and steady-state packet cost. It also records the disposition of
each optimization identified during the review. The code and packet sizes below
are for protocol 86.

## Verdict

The trusted-host design is appropriate for cooperative play: owners publish
their player state, the host owns world actors and shared progression
lifecycles, and receivers reject packets that do not match the expected
endpoint, participant session, scene epoch, or run nonce. The original review
did find a real world-motion cadence problem and three unnecessarily hot payload
families. Protocol 86 addresses those without changing the authority model.

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
| Participant frame | 370 B | 50 ms / 20 Hz | UnreliableNoDelay |
| Participant state checkpoint | 652 B | 1,000 ms | ReliableNoNagle |
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

Participant state and frame packets also carry the run-scoped native Game Over
command and acknowledgement epochs. The host emits that command only after
every connected member on the active run nonce has entered the native terminal
death state; clients accept it only from the configured authority. The
reliable state checkpoint owns eventual delivery, while the participant frame
provides the low-latency copy.

Those two packets also carry the run-loading ack/release nonce, deadline,
participant counts, and hashes of the frozen expected and locally visible
participant-ID sets. A count alone cannot prove mutual visibility in a larger
lobby because a stale extra actor could mask a missing expected actor. The
host therefore accepts an ack only when both count and membership hash match
its frozen set. The reliable checkpoint owns convergence; the participant
frame keeps healthy loading latency low.

The world-motion budget is 96 KiB/s, auxiliary snapshots use 48 KiB/s, and
reliable world-identity checkpoints use 24 KiB/s. The limiter increases a
lane's interval when its complete fragmented generation would exceed the
corresponding budget.

For a 60-actor run generation, motion uses six 968-byte fragments, or 5,808
bytes. At the 67 ms base interval that is about 86.7 KB/s per receiving peer,
inside the 96 KiB/s budget. The old full-state format required twenty
1,032-byte fragments per generation, or 20,640 bytes; at 5 Hz it exceeded the
same budget and was necessarily stretched.

## Player-authored enemy damage ownership

Native player-authored contact executes only on the cast owner's process.
Host-owned contact mutates the host enemy directly. Client-owned contact is
observed around `Badguy::Contact`, reduced to the exact native HP endpoint,
and sent in `EnemyDamageClaimPacket`; the host validates it and writes
`min(current_host_hp, client_after_hp)`. No transport-side damage multiplier
is applied.

Packet-driven replay spell actors are presentation-only on the receiving
process and are rejected before they can mutate a replicated run enemy. This
gate is distinct from host-owned `LuaBrain` participants, whose native
contacts remain host-authoritative. Issue #52 demonstrated why the boundary
must be explicit: an observer-side Earth replay once stacked a second native
contact beside the client's valid stock claim.

## Optimization archaeology

The recent optimization series has one behavioral implementation commit and
two follow-ups:

| Commit | Enemy replication change |
|---|---|
| `7bf7489` | Recorded the review and proposed the split; documentation only, with no cadence, packet, interpolation, or runtime change. |
| `9f7aa39` | Implemented protocol 82. Run actors moved from full 1,032-byte snapshots (three actors per fragment, 200 ms minimum / 5 Hz before bandwidth stretching) to 92-byte motion rows (ten actors per 968-byte fragment, 67 ms minimum / about 15 Hz) plus reliable full identity only on structural change/checkpoint. Every live actor still appears in each motion generation; there is no distance or per-enemy priority scheduler. It also replaced the fixed 150 ms world delay with `1.5 * recent arrival p90`, clamped to 100–600 ms over an eight-snapshot history. Participant cold arrays and wave summaries were split/change-gated, but those lanes do not carry enemy transforms. |
| `5d3aadb` | Fixed linked-worktree lookup for staged reverse-engineering artifacts and tests; no packet cadence, batching, delta, priority, interpolation, or send-rate change. |
| `0215c36` | Kept the protocol-82 sender rates but changed receive batching: instead of withholding a motion generation until every fragment arrived, each valid fragment immediately advances its actor subset in a rolling identity-backed snapshot, with per-actor generation rejection. It also sent cast press/release on the immediate unreliable lane before reliable convergence. |

The pre-optimization behavioral baseline is `a1132f0`, the parent of
`9f7aa39`.

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

## Authority-fidelity regression follow-up — 2026-07-24

The organic loopback gate still paired host and client payloads by identical
snapshot sequence. That proves packet decoding, but it compares a received
client snapshot with the host snapshot that produced it, so position error is
zero even when the rendered client enemy is hundreds of milliseconds behind
the host's current native actor. Its client-clone check also compares the clone
with that same delayed client snapshot. Neither measure represented what a
player sees against current host authority.

The replacement samples host and client native enemies on their independent
monotonic clocks, interpolates the host track at each client observation,
estimates per-enemy latency by bounded cross-correlation, and counts client-only
teleports, direction reversals, freezes, and persistent missing/extra ghosts.
The live gate now defaults to a deterministic local UDP proxy with 40 ms
one-way latency and 12 ms uniform per-datagram jitter.

Under that identical profile, the pre-optimization `a1132f0` loader measured
30.761 units p95 authority divergence, 304 ms p95 observed latency, 188 ms p95
presentation-source age, and 41.365 units maximum divergence. The optimized
build measured 36.976, 320 ms, 305 ms, and 47.162 respectively. The adaptive
eight-sample p90 estimator amplified a jittery fragment interval into a roughly
300 ms presentation delay for several successive frames.

The correction reverts only that adaptive interpolation change to the original
fixed 150 ms delay. It retains compact 15 Hz motion, immediate independent
fragment application, per-actor stale rejection, and the cast-edge convergence
fix. The controlled fixed-delay build measured 29.242 units p95 divergence,
288 ms p95 observed latency, 150 ms p95 source age, and 36.207 units maximum
divergence—at least as good as the pre-optimization baseline on every fidelity
measure.

## Interpolation and correction

Remote participants retain an eight-sample receive-time history and a 120 ms
presentation delay. Interpolation covers the normal 50 ms frame cadence. If a
sample time runs beyond the newest frame, the sampler can extrapolate observed
velocity for at most one observed arrival interval, but only while non-zero
movement intent agrees with that velocity. Idle, reversed, invalid, and
cross-scene samples hold the last authoritative transform.

World actors use a fixed 150 ms delay. A short receive history still brackets
normal 15 Hz motion samples, but a transient fragment interval cannot inflate
presentation latency for the rest of the history window.
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

`tests/native/multiplayer_runtime_state_tests.cpp` exercises fixed world delay
under uneven arrivals, bounded participant extrapolation, protocol sizes, exact variable packet
lengths, and a full 250-participant level-up barrier. The static RE/transport
suite checks the packet split, send modes, authority validation, project
membership, and documentation contracts. The normal Windows loader build keeps
all packet `static_assert` sizes enforced by MSVC, while CI also compiles and
runs the native runtime-state regression on Linux.

`tests/native/world_motion_fragment_merge_tests.cpp` drops alternating fragments
from 12-actor generations and proves that received enemy subsets advance while
untouched actors remain stable; it also rejects a late fragment without
regression. `tools/verify_multiplayer_organic_enemy_cast_timing.py` is the live
two-instance impaired-loopback gate. It requires at least six natural enemies
and four moving enemies; bounds current-host versus client-observed native
position, p95 update latency, presentation-source age, teleports, rubber-bands,
freezes, ghosts that remain unresolved for at least 500 ms, HP, animation,
target, and arrival gaps throughout
organic combat; and confirms that enemies actually damage a player. The same run casts client
Air for 12 frames and requires both host-observed start and stop within 150 ms,
host/client duration error within 100 ms, and native completion within 250 ms
of the client release.

Enemy-motion fidelity and enemy-target validity are a joint live acceptance
boundary. `tools/verify_multiplayer_enemy_retarget.py` is the second mandatory
two-instance impaired-surface gate; the loopback enemy acceptance is green only
when both live artifacts report `ok: true`. The retarget gate uses fresh,
isolated runtime roots and exact launcher-returned process identities. It:

- lets a stock wave enemy kill the host while the client remains alive, then
  requires host authority to select the client within 1,500 ms and the client
  to apply that target within 2,000 ms;
- repeats the direction symmetrically with the client dead and host alive;
- casts the native Ether `Call Leviathan` summon, places the registered
  Leviathan nearest, and requires the host-authored native target identity to
  resolve on both peers; this case does not depend on a native selector call
  happening after placement, so it also enforces the host's bounded 100 ms
  nearest-target maintenance cadence;
- rejects dead/ineligible participant targets and requires five consecutive
  matching target samples; and
- stores host/client backbuffer captures plus every authority target-ID sample
  under `runtime/multiplayer_enemy_retarget`.

The summon case requires the target's owner participant and native type on
both peers, and checks that same composite identity in the host-authored world
snapshot. Matching the native type alone is insufficient because two players
may own the same summon class in different peer-local ActorWorld slots.

The death cases first require three consecutive host-authority samples showing
that the selected wave enemy targets the controlled nearest victim. The gate
then drives that participant to authoritative `life_current <= 0`, begins its
latency window, and disarms the positioning harness before sampling. It does
not wait on the longer native death-presentation countdown, so presentation or
random contact-damage timing cannot hide or fail the independent target-
validity contract. Natural enemy damage and death stay covered by the separate
organic player-death regression. That companion gate is also an ordering
contract: life-zero target invalidation is captured immediately but target
mutation for local slot 0 waits for the native ineligible/death-animation
signal at `actor + 0x160`, so retargeting cannot preempt
`Player_DeathTransition`. The general animation-drive byte is explicitly not
a death signal because ordinary damage and cast animations also set it.

Before spawning the attacker, the gate requires three consecutive stable host
authority observations of both players' native actor position fields, with the
controlled local host position within eight world units. It deliberately does
not use the remote participant's network target transform, which can lead the
native proxy actually compared by acquisition. The gate derives the attack
point from those native positions and proves the nominal victim is strictly
nearer than the survivor. A test-only target-pointer writer therefore cannot
force a victim that host authority actually observes as farther away.

The prior target-authority check could accept two matching zero targets, so it
was blind to enemies idling after a target death. The new gate explicitly
fails that state: a cleared host and cleared client are agreement, but not
valid acquisition.

The beta.17 host-death baseline demonstrates the hole: the authority retained
the ineligible host corpse for 23 samples, then both peers converged to target
zero for the rest of a 34-sample window. Reacquisition latency was unbounded
(`null`) and stable eligible-target agreement was `0/5`, even though the old
agreement-only predicate saw matching zero targets. The generated baseline is
`runtime/multiplayer_enemy_retarget/beta17-host-death-baseline.json`.

The final 2026-07-25 two-peer run passed all three target cases:

| Case | Host acquisition | Client application | Stable agreement |
|---|---:|---:|---:|
| Host dies, client survives | 0.002 ms | 157.3 ms | 31 samples |
| Client dies, host survives | 81.2 ms | 235.0 ms | 30 samples |
| Client-owned Ether minion nearest | 159.2 ms | 237.2 ms | 33 samples |

The target artifact is
`runtime/multiplayer_enemy_retarget/all-final-cadence-v4.json`; its sibling
directory contains both-peer backbuffer captures and authority target-ID
samples. Three additional isolated Ether-minion repetitions acquired on the
host in 80.4–157.5 ms and converged on the client in 156.2–377.0 ms.

The companion authority-fidelity run remained above the restored-baseline bar:
21.765 units p95 and 26.063 units maximum native divergence, 272 ms p95 native
latency, 150 ms p95 presentation-source age, and zero teleport, rubber-band,
freeze, or persistent-ghost episodes. This is better than both the
pre-optimization `a1132f0` result (30.761 p95 / 41.365 maximum / 304 ms /
188 ms) and the prior fixed-delay result (29.242 / 36.207 / 288 ms / 150 ms).
The evidence is
`runtime/multiplayer_enemy_retarget/fidelity-final-cadence-v1.json`.
