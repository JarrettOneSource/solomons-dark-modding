# Real-flow enemy replication after host-initiated Solomon Dig

Date: 2026-07-29

Status: production-Steam failure reproduced and root-caused; post-fix
acceptance is pending

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
tasks in the already logged-in interactive Steam session. The task worker can
launch client B, send input to its exact staged game PID, and close processes
whose executable paths are beneath the exact run root. It never logs out,
changes Steam configuration, installs software, or returns persona/UI text in
durable evidence. The run root is deleted after its telemetry and captures are
copied home.

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
| beta.23 framing/reassembly mishandles real-path packet shapes | Large or fragmented world snapshots leave the host but are dropped, incomplete, or never dispatched on client B. | Per-family/per-channel send/receive accounting, fragment message IDs/counts/bytes, reassembly completion/expiry/drop records, and decoded world-snapshot sequence continuity. | Rejected. `local_udp` fragmentation completed without rejection. The Steam trace failed earlier: `ISteamNetworkingMessages::SendMessageToUser` returned result 25 before the rejected reliable fragments entered Steam, and the recovery path then closed the route and discarded queued reliable data. |

## Topology matrix

| Topology | Purpose | Broker/transport | Pre-fix | Post-fix |
| --- | --- | --- | --- | --- |
| Local Windows pair, 50711/50712 | Deterministic flow/session-state reproduction | Real desktop launcher flow; supported `local_udp` projection | PASS on beta.24 (`b24f23`) | Pending |
| Home PC to NFO, 51611/51612 staging allocation | Real-desktop cross-OS/WAN projection | Real desktop launchers over `local_udp`; **not** Steam broker acceptance | PASS on beta.24 (`nfob24f6`) | Pending |
| Home PC to ws20 | Owner's exact machine topology | Steam lobby plus Steam Networking Messages/SDR | FAIL reproduced on beta.24 (`ws20b24s1`): host 11 native enemies; client B 0 replicated/0 native enemies | Pending |

## Safety boundaries

- Local stage roots and profiles are harness-owned; the owner's installed beta
  and any pre-existing `SolomonDark.exe` processes are never modified or
  stopped.
- NFO work is confined to `/root/sd-netrepro-20260729`, uses only ports
  51611/51612, and brings its own GE-Proton and Xvfb payload. No package,
  firewall, service, production website/database, or `steamvnc` change is
  permitted.
- ws20 work is confined to `%USERPROFILE%\sd-netrepro-stage`, uses exact
  staged-path and PID ownership, performs no installation or machine
  reconfiguration, and is cleaned after the run.
- A run fails closed if an executable path, PID, instance root, port, lobby ID,
  or cleanup target is ambiguous.

## Root cause

The Steam-only send queue interpreted sustained
`k_EResultLimitExceeded` (result 25) as a broken peer route. Result 25 means
Steam already has too much data queued to accept another message; it is
backpressure, not a terminal session failure.

The beta.24 sequence was:

1. the host produced a reliable world-identity checkpoint;
2. `SendMessageToUser` returned result 25, so the application queue correctly
   retained the reliable packet for a 250 ms retry;
3. after two seconds, the queue emitted a “congestion recovery” event and
   permanently stopped retrying that peer;
4. the service thread responded by suspending the authenticated peer, clearing
   its application send queue, and calling `CloseSessionWithUser`; and
5. closing the Steam session without a linger guarantee discarded reliable
   data already queued below the application boundary. Reauthentication then
   repeated the same cycle.

The failing beta.24 host recorded 105 result-25 log intervals, 18 congestion
recoveries, and 18 saturated-route resets during the bounded run. At the final
aligned sample it had 11 native enemies and 127 reliable send failures, while
client B still had sequence 0, zero replicated actors, and zero native
enemies. The client was connected enough to exchange participant state, but
never received a complete current world-identity checkpoint.

The queue also had an adjacent ordering defect: moving a rejected reliable
packet back into the live deque could rotate retained fragments relative to
one another. A 12-fragment regression exposed that issue before the fix was
accepted.

## Fix

Steam result-25 pressure now remains wholly owned by the bounded send queue:

- reliable packets stay queued and retry every 250 ms until Steam accepts them
  or a separate terminal peer/session event resets the peer;
- disposable snapshots remain coalesced under pressure;
- a deferred queue preserves reliable FIFO order while allowing uncongested
  peers to make progress;
- the two-second threshold emits one sustained-backpressure diagnostic per
  episode but never mutates authentication, closes the Steam session, or
  clears reliable packets; and
- telemetry records the result of each actual Steam API send attempt, separate
  from the existing application queue-admission event.

Terminal disconnect, authentication failure, lobby departure, and explicit
teardown still reset the peer queue through their existing lifecycle paths.

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

### Remaining acceptance gate

Build an isolated package from the fixed committed SHA, rerun all three
topologies, manually inspect the paired Steam frames, run the full repository
battery, rebase onto current `main`, and repeat the affected proof before
landing. This document does not claim completion until that matrix is filled
with the exact landed SHA.
