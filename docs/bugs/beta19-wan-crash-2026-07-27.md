# Beta.19 WAN disconnect and native crashes (2026-07-27)

Status: investigation in progress. This checkpoint records the completed
artifact inventory and peer-correlated timeline. Dump analysis, static reverse
engineering, root-cause proof, and any fix are deliberately pending.

## Scope and names

Issue #65 was reported after a two-player WAN run on published
`v0.1.0-beta.19`, protocol 86. This document calls the two machines **owner**
and **client B**. It intentionally omits client B's Windows username, account
identifiers, persona name, lobby identifiers, and local paths.

All source evidence is the read-only snapshot at
`/mnt/d/codex-evidence/netdrop-20260727/`. Generated analysis belongs under its
`investigation/` child.

Times below are the machines' local Eastern timestamps from the loader logs.
The report envelopes use UTC and agree after the four-hour offset.

## Evidence inventory and correlation

| Artifact | Machine and role | Relevant content |
|---|---|---|
| `ab5969ff-7112-43e7-aae1-88f2168bbce6` | client B, standalone host launch | 09:00 crash log, loader log, session status, and minidump |
| `6e6e7650-d1b1-4c0d-b4ac-90bf54dc3e19` | owner, host in the real two-player run | 10:44 crash log, loader log, session status, and minidump |
| `3306b42a-4794-4468-ac48-d3b3199d6528` | client B, joining the owner's run | 10:44 Send Logs capture, launcher transcript, loader log, and session status |
| `4be35c26-9a99-45e4-9a49-8121827217fa` | owner | 10:44 Send Logs capture, launcher transcript, loader/crash logs, and session status |
| `owner-local/solomondarkmodloader.log` | owner | byte-identical to the owner crash and Send Logs loader log |
| `owner-local/multiplayer-session-status.json` | owner | byte-identical to the owner crash and Send Logs status snapshot |

The four submitted ZIP SHA-256 values, in the order above where applicable,
are:

- client B Send Logs:
  `1a1dbab4c4e2f477bb678cfd5b4eb6a3dd4bb46b5fddf6320cb1d2dada257655`
- owner Send Logs:
  `94fe2db13ebd8620496a9031884e80e1504aa2c06f0200361094ee0333eb1962`
- owner crash:
  `ecb35ffb9b9904986a72041957f2665583a9b303de7343e7951fb8dfb8b5d5a3`
- client B crash:
  `5bbb2313a090a43d1c65f7f37e948e25af06b09befad6b9069b04a80b56adffd`

Both crash submissions carry the same protocol-86 `binary-layout.ini` hash,
`a87400eb63d3321508802ec795201cf9d2fc84c323fbbb246303e630a2e476a1`.
The published build manifest also matches between the two machines. The owner
crash and owner Send Logs copies of `loader.log` and `crash.log` are
byte-identical, so they are not independent observations of another crash.

## Timeline A: client B's 09:00 startup crash

This is a separate launch, not one end of the later WAN run.

| Local time | Observation |
|---|---|
| 08:59:59.478 | The loader attaches to client B's process. The launch is configured as a public host. |
| 09:00:00.079 | Loader startup completes. |
| 09:00:00.243–00.247 | The Steam lobby becomes ready with zero authenticated peers. |
| 09:00:00.701–00.719 | The stock main menu and its controls render. No run, wave, participant materialization, spell, projectile, damage, or minion event has occurred. |
| 09:00:00.750 | The loader logs that it suppressed a `WM_ACTIVATEAPP` deactivation. |
| 09:00:01.014 | The process faults in native `SolomonDark.exe` code at static `0x00441221`, reading address zero. |

The captured session status is `not-in-game` / `loading`, host-only, and has
zero authenticated peers. Therefore this crash cannot have caused, or been
caused by, a two-peer network disconnect. Its immediate focus-loss antecedent
remains relevant to dump comparison.

## Timeline B: the owner's two-player WAN run

### Join and run entry

| Local time | Owner | Client B |
|---|---|---|
| 10:40:56.409–10:40:56.710 | Loader attaches, creates a public lobby, and reports it ready. | Not launched yet. |
| 10:41:44.559–10:41:46.571 | Accepts client B and reports one authenticated peer. | Loader attaches, joins the owner's lobby, completes the protocol/build handshake, and reports one authenticated peer. |
| 10:42:09.828 | Switches from the hub toward Boneyard using run nonce `805260820` and starts the two-participant loading barrier. | Still in the hub. |
| 10:42:12.709–10:42:13.352 | Waits for client B. | Accepts the host seed and run nonce, switches to Boneyard, and starts its barrier view. |
| 10:42:17.725–10:42:17.768 | Releases the barrier at 2/2 visible participants and enters the run. | Accepts the authenticated release at 2/2 and enters the same run. |

The two retail `wave.txt` files are not identical in size: the owner reports
42 parsed waves and client B reports 46. The run nevertheless uses the owner's
host-authored seed and actor snapshots.

### Combat and replicated activity

- The first host-authored enemy batch appears at 10:42:43.344. The owner
  creates 47 stock type-1001 enemies through 10:43:13.607. Client B
  materializes the first 36 host actors through 10:43:06.512 before the
  host-to-client stream stalls.
- The owner records nine local primary cast starts. Client B records nineteen
  before its timeout, plus secondary casts. Both peers replay remote held-cast
  press/hold/release edges.
- Neither peer's gameplay log contains a native-minion, golem, imp, or summon
  lifecycle event. There is also no logged missing-primary-projectile catch-up
  materialization. The field run therefore does not support a minion
  materialization trigger.
- At 10:43:12.775 the owner's local HP crosses zero. The owner's five-second
  death presentation begins at 10:43:13.605, and spectator mode targets
  client B at 10:43:18.596.

### One-way transport failure

The logs prove an asymmetric failure rather than both processes disappearing
at once:

1. Client B's last accepted host world state is sequence 2839. At
   10:43:07.892 it is already holding that last state during a snapshot stall.
2. The owner reports persistent Steam gameplay send rejection with numeric
   result 25 beginning at 10:43:14.684. The cumulative rejection count climbs
   from 80 to 5,466 by 10:44:09.823.
3. Client B continues to originate primary casts and damage claims. The owner
   receives and processes those client-to-host packets, including cast
   sequence 19 through 10:43:36 and a later replayed backlog.
4. Because authoritative corrections no longer travel back, the owner reduces
   its remote view of client B from 41/50 HP at 10:43:10.076 to 0/50 at
   10:43:24.026, while client B continues playing and casting locally.
5. At 10:43:37.590, exactly 30 seconds after its last host packet, client B
   times the owner out, returns to host handshaking, clears the authoritative
   world apply state, resets the owner's participant epoch, and dematerializes
   the owner's remote wizard.

This is the reported disconnect. The client B Send Logs status later shows
`Handshaking`, zero authenticated peers, and both lobby members. The owner
status shows a host-only ready lobby with zero authenticated peers.

### Owner crash after the disconnect

| Local time | Observation |
|---|---|
| 10:43:37.590 | Client B declares the 30-second host timeout. |
| 10:43:40.725–00.733 | The owner receives a repeated hello and a backlog of client B cast/damage packets; casts are rejected because the owner's authoritative view has client B dead. |
| 10:44:07.663 | The last logged client B hello is accepted by the owner. |
| 10:44:09.823 | The owner's Steam send rejection counter reaches 5,466. |
| 10:44:10.528 | The owner logs another suppressed `WM_ACTIVATEAPP` deactivation. |
| 10:44:10.692 | The owner faults in native `SolomonDark.exe` code at static `0x004207E5`, reading address zero. |
| 10:44:12.934 | While crash capture is still unwinding the process, the Steam service thread publishes the now host-only lobby state. |

The last line is not evidence of a fresh process in this artifact. The captured
loader log has one attach, one launch token, and one startup. The crash report
records the same process lifetime through its eventual abnormal exit.

## Timeline verdict

The two minidumps are from **two distinct launch attempts**:

- `0x00441221` is a client B startup/main-menu crash with no peer.
- `0x004207E5` is an owner crash 33.102 seconds after client B declared the
  WAN timeout in the real two-player run.

They are not opposite ends of one simultaneous crash. The two native faults
may still share a focus-loss bug class: both are null reads shortly after the
loader suppresses `WM_ACTIVATEAPP` deactivation. Dump stacks and static caller
graphs must decide that question.

The timeline also disproves the initial minion-trigger lead for this field
capture: no minion or summon existed. It does not yet prove whether held-cast,
world-snapshot load, participant death, focus loss, or a stock path exposed by
those conditions owns either null. No code change is justified at this
checkpoint.
