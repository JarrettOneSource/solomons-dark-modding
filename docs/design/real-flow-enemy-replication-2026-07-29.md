# Real-flow enemy replication after host-initiated Solomon Dig

Date: 2026-07-29

Status: the two-layer production-Steam queue failure is fixed and the
investigation branch passes all three real-flow topologies; rebase, exact-SHA
repeat acceptance, and landing are pending

## Owner incident

The owner reported a live v0.1.0-beta.24 failure over a real remote
connection:

1. both players opened the desktop launcher;
2. the home PC hosted;
3. client B joined by lobby ID and explicitly selected **Launch Game**;
4. both players materialized in the shared hub;
5. the host started the match;
6. the host walked to Solomon Dig and completed the stock conversation;
7. the host saw spawned enemies, while client B saw no enemies.

The missing acceptance slice is exact: previous Dig acceptance drove
`sd.hub.start_testrun()` and placed a participant at the NPC, and its release
gate emphasized the client-B-initiated modal. It did not prove a
desktop-launcher-created remote session in which the host starts the match,
physically approaches Dig, completes the stock dialogue, and then has client B
render and fight the replicated wave.

## Real broker and transport

The production connection has three distinct layers:

1. The desktop host action launches the staged game in Steam host mode. The
   loader calls Steam matchmaking `CreateLobby`, publishes the supported build
   and manifest metadata to that Steam lobby, and exposes the resulting 64-bit
   lobby ID in the launcher.
2. A direct lobby-ID join first asks the configured Solomon Dark Revived
   website for the host's mod manifest when available. The website is an
   optional directory and compatibility source; it does not carry gameplay
   traffic and is not the session broker.
3. Before **Launch Game**, the client desktop launcher joins the actual Steam
   lobby through its x86 `steam_api.dll` helper. On explicit launch it leaves
   that temporary launcher membership, starts the staged game with the same
   lobby ID, and the loader joins the Steam lobby again. Authenticated gameplay
   packets then use `ISteamNetworkingMessages` over Steam Networking
   Sockets/SDR.

The real broker is therefore the Steam lobby, and the real WAN gameplay
transport is Steam Networking Messages/SDR. Normal website requests made by
the launcher remain part of the owner flow but are not a substitute for Steam
lobby membership.

The loopback topology is intentionally the launcher's supported development
projection of the same launcher and game state machines. It uses the exact
desktop launcher actions and staged games, while `local_udp` supplies the
transport on the reserved ports 50711/50712. Its lobby ID is the host UDP port,
so it cannot by itself prove Steam brokering. Every claim about the production
broker must come from the real WAN topology.

## Reproduction contract

`tools/verify_real_flow_e2e.py` is the permanent config-driven harness. A valid
run must:

- stage an isolated launcher profile and game for every peer;
- set `SDMOD_NETWORK_TELEMETRY=1` and `SDMOD_DISABLE_AUDIO=1` before every
  launcher process starts;
- drive **Host Game**, the requested privacy, and **Start Lobby** through the
  desktop launcher;
- read the lobby ID produced by that real host launch;
- enter that ID in client B's desktop launcher, invoke **Join Game**, observe
  actual Steam lobby membership on WAN, and invoke **Launch Game** explicitly;
- complete native character/loadout onboarding with owned-window input;
- wait for both players to materialize in the shared hub;
- have the host start the match with owned-window input;
- have the host physically walk to Solomon Dig and complete the stock
  conversation with owned-window input;
- never call `sd.gameplay.start_waves()`, `sd.hub.start_testrun()`, or
  `sd.hub.trigger_solomon_dig()` in the repro path;
- sample both peers from match start through the first wave;
- capture both game windows at the same wall-clock barrier;
- require client B to contain host-authored enemy replicas, render them, observe
  motion or attacks, and damage at least one through real player input; and
- delist/leave the lobby and stop only exact recorded staged executables and
  process IDs.

For the NFO projection, the controller also builds its two Win32 helpers from
the checked-out source, archives the configured package and original game,
uploads those inputs plus the configured GE-Proton archive, creates only
`/root/sd-netrepro-20260729`, bundles Xvfb and its runtime libraries without
installing packages, verifies input/output hashes, and deletes that exact stage
after copying evidence home. A pre-existing remote stage is rejected.

For the workstation20 Steam topology, the controller uses the granted
temporary SSH boundary only to stage files and create short-lived scheduled
tasks in the already logged-in interactive Steam session. Its stage must be a
new direct profile child named `sd-<token>-stage`; the worker rejects every
other parent and leaf. The task worker can launch client B, send input to its
exact staged game PID, and close processes whose executable paths are beneath
the exact run root. It never logs out, changes Steam configuration, installs
software, or returns persona/UI text in durable evidence. The complete stage
is deleted after its telemetry and captures are copied home.

Lua and loader observability may read state. It may not initiate the match,
teleport a player to Dig, trigger the Dig state machine, start waves, spawn an
enemy, or directly damage an enemy.

## Evidence schema

Each run writes one immutable evidence directory with:

- normalized redacted config and source SHA;
- before/after process and port inventories;
- launcher UI event transcript and lobby-membership proof;
- exact PID and executable-path ledger;
- host and client loader logs;
- both `network-telemetry.jsonl` streams;
- a monotonic sample timeline containing scene, session state, run nonce,
  wave/epoch state, native enemy roster, replicated-actor roster, Solomon state,
  and client suppression/subscription state;
- paired PNG captures with one UTC wall-clock barrier identifier;
- the client damage assertion with enemy identity and HP before/after;
- cleanup and lobby-leave results; and
- a per-file SHA-256 manifest.

The committed documentation names the second participant only as client B.

## Required hypotheses

The harness and temporary evidence probes distinguish these hypotheses.

| Hypothesis | Prediction | Required discriminator | Verdict |
| --- | --- | --- | --- |
| Run/wave epoch or session-state divergence | Client B receives spawn/snapshot traffic but rejects it because its accepted run nonce, run generation, wave epoch, or lobby session state differs from the host-authored values. | Aligned host send/client receive packet records plus both accepted/rejected epoch fields across match start and Dig completion. | Rejected. Both `local_udp` projections converged on scene epoch 2 and the same run nonce. In the failing Steam trace client B never received a current world-identity generation to reject: its replicated state remained invalid at sequence 0 while the host retained valid epoch-2 authority. |
| Client enemy-simulation suppression is wrongly engaged | Client B has replicated enemy identity but presentation/materialization is gated by the wrong suppression state. | Client suppression decisions, stock spawner state, native enemy roster, and bound replicated roster at the same samples. | Rejected. Both projections materialized and rendered the roster. The failing Steam client had zero replicated identities and zero bindings, so presentation suppression was downstream of the loss, not its cause. |
| Enemy snapshot subscription depends on how the run began | The real match-start path never arms or resets the client run-world snapshot consumer that the `start_testrun` seam happens to arm. | Subscription/reset lifecycle events for seam-started control evidence versus real-flow evidence. | Rejected. The native Start Match path worked over both `local_udp` topologies. On Steam the host built and queued reliable world-identity checkpoints; the trace loses them at the Steam send boundary instead of omitting them at the publisher. |
| Host-side Dig state interferes with authority | Host modal completion or deferred Solomon retirement mutates authority, run state, or reconciliation in a way the client-initiated Dig slice cannot exercise. | Host/client Solomon state, modal completion, deferred-retirement counters, authority ID, and first post-Dig world snapshots. | Rejected as the replication fault. The host retained authority and produced 11 enemies after the native Dig flow. The transport was already cycling authenticated peer state under send pressure and continued doing so after Dig; no Dig state mutation reset authority or the world publisher. |
| beta.23 framing/reassembly mishandles real-path packet shapes | Large or fragmented world snapshots leave the host but are dropped, incomplete, or never dispatched on client B. | Per-family/per-channel send/receive accounting, fragment message IDs/counts/bytes, reassembly completion/expiry/drop records, and decoded world-snapshot sequence continuity. | Rejected. `local_udp` fragmentation completed without rejection. The beta.24 Steam trace failed earlier: `ISteamNetworkingMessages::SendMessageToUser` returned result 25 before rejected fragments entered Steam. After the destructive reset was removed, `ws20fix4` received all 11 identity records but materialized none because stale reliable generations and recovery duplicates remained ahead of the current binding state. |

## Topology matrix

| Topology | Purpose | Broker/transport | Pre-fix | Post-fix |
| --- | --- | --- | --- | --- |
| Local Windows pair, 50711/50712 | Deterministic flow/session-state reproduction | Real desktop launcher flow; supported `local_udp` projection | PASS on beta.24 (`b24f23`) | PASS on branch SHA `796052a` (`post796loop1`): client B bound/materialized 10/10 and killed one through real input |
| Home PC to NFO, 51611/51612 staging allocation | Real-desktop cross-OS/WAN projection | Real desktop launchers over `local_udp`; **not** Steam broker acceptance | PASS on beta.24 (`nfob24f6`) | PASS on branch SHA `1560980` (`post156nfo1`): client B bound/materialized 10/10 and killed one through real input |
| Home PC to ws20 | Owner's exact machine topology | Steam lobby plus Steam Networking Messages/SDR | FAIL reproduced on beta.24 (`ws20b24s1`): host 11 native enemies; client B 0 replicated/0 native enemies | PASS on branch SHA `2f49b68` (`ws20ray1`): client B initially bound/materialized 9/9, rendered and observed moving/attacking enemies, and killed one through remote physical input; all 3,701 Steam sends were accepted |

These post-fix rows are immutable investigation-branch evidence. They are not
the final landing claim: the same matrix must pass on the exact rebased commit
that is pushed and merged.

## Safety boundaries

- Local stage roots and profiles are harness-owned; the owner's installed beta
  and any pre-existing `SolomonDark.exe` processes are never modified or
  stopped.
- NFO work is confined to `/root/sd-netrepro-20260729`, uses only ports
  51611/51612, and brings its own GE-Proton and Xvfb payload. No package,
  firewall, service, production website/database, or `steamvnc` change is
  permitted.
- ws20 work is confined to one new direct profile child matching
  `%USERPROFILE%\sd-<token>-stage`, uses exact staged-path and PID ownership,
  performs no installation or machine reconfiguration, and deletes that
  complete stage after the run.
- A run fails closed if an executable path, PID, instance root, port, lobby ID,
  or cleanup target is ambiguous.

## Root cause

The failure had two Steam-only queue layers. Removing the first made the second
observable; the first patch was therefore necessary but not sufficient.

### Layer 1: result 25 was treated as terminal

The beta.24 send queue interpreted sustained
`k_EResultLimitExceeded` (result 25) as a broken peer route. Result 25 means
Steam already has too much data queued to accept another message; it is
backpressure, not a terminal session failure.

The beta.24 sequence was:

1. the host produced a reliable world-identity checkpoint;
2. `SendMessageToUser` returned result 25, so the application queue retained
   the reliable packet for a 250 ms retry;
3. after two seconds, the queue emitted a “congestion recovery” event and
   permanently stopped retrying that peer;
4. the service thread suspended the authenticated peer, cleared its application
   send queue, and called `CloseSessionWithUser`; and
5. closing the Steam session without a linger guarantee discarded reliable
   data already queued below the application boundary. Reauthentication then
   repeated the cycle.

The failing beta.24 host recorded 105 result-25 log intervals, 18 congestion
recoveries, and 18 saturated-route resets. At the final aligned sample it had
11 native enemies and 127 reliable send failures, while client B still had
sequence 0, zero replicated actors, and zero native enemies.

Commit `c49525b` stopped treating backpressure as a terminal route event. In
`ws20fix2`, that change drained result-25 pressure and materialized 15/15
enemies, but the run missed only the paired-capture timing gate. A later
decisive repeat, `ws20fix4`, disproved the patch as a complete solution.

### Layer 2: opaque reliable FIFO traffic starved current state

After `c49525b`, repeated reliable checkpoints, fragmented generations, and
recovery events still entered the queue as opaque FIFO packets. Under Steam
pressure:

1. old checkpoint generations remained ahead of their replacements;
2. the recovery publishers enqueued semantic duplicates of already accepted
   or queued logical events;
3. producers continued adding traffic while the route was saturated; and
4. fresh identity bindings and current state waited behind stale generations
   long enough for one-way liveness to fail.

`ws20fix4` is the decisive discriminator. The host had 11 native enemies and
client B received those same 11 network identities, but client B bound and
materialized none. The host made 9,070 Steam API send attempts: 8,511 were
accepted, 559 returned result 25, and the recovery path published 1,477
recovery sends. The client later lost the one-way session and reset its
replicated sequence to zero. The defect was therefore no longer missing
publication, decoding, or presentation; semantically stale reliable work was
head-of-line blocking the current world.

The queue also had an adjacent ordering defect: moving a rejected reliable
packet back into the live deque could rotate retained fragments relative to
one another. A 12-fragment regression exposed that issue before the
foundational fix was accepted.

## Fix

Steam result-25 pressure now remains wholly owned by a bounded,
semantics-aware send queue:

- Steam route queue time provides proactive pacing with 250 ms high-water and
  50 ms low-water hysteresis, before result 25 is required to signal pressure;
- retryable Steam rejection retains work and retries after 250 ms, while the
  two-second threshold emits one diagnostic and never mutates authentication,
  closes the session, or clears the queue;
- latest-stream snapshots replace older values from the same stream;
- latest-generation checkpoints evict complete older generations, including
  all retained fragments, instead of interleaving generations;
- distinct logical recovery events deduplicate against both queued and already
  accepted events;
- genuinely ordered events preserve FIFO order;
- a blocked peer cannot prevent other peers from making progress;
- only authenticated, send-enabled peers can admit gameplay work; and
- hello, acknowledgement, and keepalive control traffic stays outside the
  congestible gameplay FIFO.

Telemetry records queue admission, semantic supersession/deduplication, route
queue time, and every actual Steam API result separately. Terminal disconnect,
authentication failure, lobby departure, and explicit teardown still reset a
peer through their existing lifecycle paths.

The permanent test-gap work is implemented on the investigation branch:

- `tools/verify_real_flow_e2e.py` owns the host-initiated case end to end;
- `tools/_real_flow_e2e/` contains config validation, read-only observation,
  paired evidence, exact process ownership, and topology adapters;
- `scripts/Stage-RealFlowNfo.sh` and
  `scripts/Run-RealFlowRemotePeer.sh` provide a self-contained, exact-root NFO
  stage;
- `scripts/Invoke-RealFlowWindowsSession.ps1` and its constrained worker adapt
  the granted ws20 interactive Steam session without changing that session;
- `tools/real_flow_e2e.example.json`,
  `tools/real_flow_e2e_nfo.example.json`, and
  `tools/real_flow_e2e_ws20.example.json` are topology templates; and
- `tests/test_real_flow_e2e.py` permanently rejects forbidden start seams,
  weak screenshot acceptance, telemetry/audio omissions, unsafe topology
  ports/stage roots, and loss of Steam failure counters.

The real-input proof uses read-only camera state to project the same stock
world-to-screen target the game renders. A remote workstation action sends one
bounded five-click sequence to the exact staged PID, avoiding an SSH
round-trip between casts. If the nearest attacking enemy is just outside the
camera, the harness preserves the player-to-enemy ray and clips the target to
the camera edge instead of selecting a farther visible enemy.

Run a loopback acceptance with:

```bash
cp tools/real_flow_e2e.example.json /mnt/d/codex-evidence/netrepro/run.json
# Replace paths, run name, evidence root, and expectedSourceSha.
python3 tools/verify_real_flow_e2e.py \
  /mnt/d/codex-evidence/netrepro/run.json \
  --phase full
```

For `wan_udp_nfo`, set `protonArchive` to a local GE-Proton tarball, set client
B to `linux_ssh_proton`, use the exact granted SSH target/stage root and
51611/51612 mapping, and use a new evidence root. The controller performs and
cleans the remote stage; it never reuses a remote install.

## Validation

### Pre-fix beta.24 evidence

| Assertion | Loopback `b24f23` | Home PC↔NFO `nfob24f6` | Home PC↔ws20 `ws20b24s1` |
| --- | --- | --- | --- |
| Desktop launcher on both peers | PASS | PASS | PASS through the Steam lobby |
| Host native Start Match | PASS | PASS | PASS |
| Host physical Solomon traversal and stock dialogue | PASS | PASS | PASS |
| Client B replicated/native wave-one enemies | 9/9 | 10/10 | **FAIL: 0/0 while host had 11** |
| Client B enemy render | projected native-enemy crop accepted | projected native-enemy crop accepted; screenshot visually inspected | **FAIL: empty client frame visually inspected** |
| Client B real-input damage | 2.5→0 HP in one click | 2.5→0 HP in one click | Not reachable |
| Enemy movement | 11 replicas moved | 12 replicas moved | Not reachable |
| Enemy attacks client B | 41.04→0 HP | 48.52→0 HP | Not reachable |
| World identity delivery | kind-31: 24 accepted, 12 assemblies, 0 rejected | kind-31: 20 accepted, 10 assemblies, 0 rejected | **FAIL: client world sequence stayed 0** |
| Telemetry start | exactly one per peer | exactly one per peer | exactly one per peer |
| Cleanup after run | zero reserved ports/owned processes | zero reserved ports/owned processes | zero owned processes/tasks; logged-in Steam session retained |

Both evidence roots contain `evidence-sha256.txt`. The recorded screenshot
barrier in these pre-hardening runs is controller request-start skew
(0.54 ms loopback; 3.26 ms WAN). The landed harness records the actual capture
instant; WAN captures use a minimum-RTT SSH clock-offset estimate and include
its uncertainty.

### Post-fix branch evidence

| Assertion | Loopback `post796loop1` | Home PC↔NFO `post156nfo1` | Home PC↔ws20 `ws20ray1` |
| --- | --- | --- | --- |
| Exact source SHA | `796052a` | `1560980` | `2f49b68` |
| Desktop launcher, native Start Match, host physical Dig | PASS | PASS | PASS through the real Steam lobby |
| Client B initial replicated/native enemies | 10/10 | 10/10 | 9/9 |
| Client B render and motion | PASS | PASS | PASS; paired frames visually inspected |
| Client B real-input damage | 2.5→0 HP | 2.5→0 HP | 2.5→0 HP in one bounded remote action |
| Enemy attacks client B | PASS | PASS | 50→0 HP over the sampler; 50→21.817 during the damage action |
| Steam send results | Not applicable | Not applicable | 3,701/3,701 accepted; zero result-25 or other rejection |
| Steam route queue | Not applicable | Not applicable | connected throughout; host maximum 4,318 µs |
| Actual paired capture skew | 267,800 ns | 184,687,562 ns, with 234,926,657 ns clock uncertainty | 590,180,700 ns |
| Cleanup | zero reserved ports/owned processes | exact remote stage deleted; zero reserved ports/owned processes | zero owned processes/tasks; one pre-existing Steam process retained |

Every row used the real launcher flow, the native Start Match action, physical
host traversal to Solomon Dig, stock dialogue, and no forbidden start or
damage seam. Each evidence root contains its logs, telemetry, timeline,
captures, safety inventory, result, and SHA-256 manifest.

### Remaining landing gate

Rebase onto current `main`, run the full repository battery, build and verify an
isolated package from that exact commit, and repeat all three topologies.
Manually inspect the final Steam frames, push and merge that same SHA, verify
its CI, and repeat the safety/cleanup audit. This document does not claim
landing completion from the pre-rebase branch evidence above.
