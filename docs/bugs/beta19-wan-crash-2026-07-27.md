# Beta.19 WAN disconnect and native crashes (2026-07-27)

Status: investigation in progress. This checkpoint records the completed
artifact inventory, peer-correlated timeline, and native dump forensics.
Static reverse engineering, root-cause proof, and any fix are deliberately
pending.

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

## Dump forensics

The two submitted dump files are not equally complete. The owner's 10:44 dump
is a valid 17-stream minidump. Client B's 09:00 dump contains a valid header,
exception record, and x86 exception context, but its 17-entry stream directory
was never populated and its thread/module descriptor region is zero. CDB
therefore rejects the original client B file before selecting a process.

The incomplete client B dump was not edited. A generated investigation copy
reconstructed only the directory entries whose payload locations can be
proved from the minidump format, plus the single fault-thread descriptor
needed by CDB. CDB then read the original exception record and register
context. No stack, module, or memory content was invented. The source and
generated-copy SHA-256 values are:

- client B original:
  `0518e283fa0060d2f5d0a1ef3f9f48906d058c3366d318435cd544242b7f8ae2`
- client B recovered investigation copy:
  `1e0a45463370b4575d47fafdcdb4bd2d3f63f378468c20bce3a43f9fb92aabac`
- owner original:
  `ddee4b2ac08d04c2de22c935387a2126cfa90c8f350e5edb6c85251fa8b2b7b5`

The recovered copy deliberately remains outside the repository under the
evidence snapshot's `investigation/` directory.

### Client B, 09:00

CDB independently recovers the exception as thread 23676, `0xC0000005`, read
of address zero:

```text
eax=00000800 ebx=01118c80 ecx=00000000 edx=ffffffff
esi=00000000 edi=04f80280
eip=00d41221 esp=1096fa8c ebp=1096faa8
```

The game image was rebased to `0x00D00000`, making the instruction's retail
static address `0x00441221`. The faulting bytes are:

```asm
mov edx, dword ptr [ecx]  ; ecx == 0
push 0
push 1
push eax
mov eax, dword ptr [ebp+8]
push eax
push ecx
mov ecx, dword ptr [edx+0x5c]
call ecx
```

Because dbgcore did not finish the stream directory, CDB cannot recover client
B's stack memory or loaded-module list from the dump. The crash handler's
frame-pointer walk was captured synchronously before dump writing and supplies
the complete available native chain. Every non-system frame maps to
`SolomonDark.exe`; converting each module offset to the retail static image
gives:

```text
0x00441221  fault
0x00440F88
0x004205C2
0x00413348
0x004E0E73
0x0074AB14  native thread entry
KERNEL32!BaseThreadInitThunk
ntdll!RtlUserThreadStart
```

The separate generic stack capture begins inside the loader's crash logger,
then reaches the same native frames. Loader frames are crash-reporting
machinery, not callers of `0x00441221`.

### Owner, 10:44

CDB opens the owner's original dump directly. `!analyze -v` classifies it as
`INVALID_POINTER_READ_c0000005_SolomonDark.exe!Unknown`, with a read of
address zero on thread 9684:

```text
eax=00000000 ebx=00e1f800 ecx=ffffffff edx=0134f000
esi=00e6df00 edi=00000002
eip=00a207e5 esp=0153f728 ebp=0153f734
```

The game image was rebased to `0x00A00000`. Its timestamp
(`0x581A0BF3`), checksum (`0x00483B1C`), and image size (`0x007AC000`)
identify the expected retail executable. The fault and full native chain,
converted to retail static addresses, are:

```text
0x004207E5  mov edx, dword ptr [eax]  ; eax == 0
0x004137D0
0x00412FB0
0x005A77A7
0x0074812F
0x007487BE  native thread entry
KERNEL32!BaseThreadInitThunk
ntdll!RtlUserThreadStart
```

The fault thread is the game's native thread; no loader DLL frame is on its
exception-context call chain. The later all-thread view shows the same thread
inside `MiniDumpWriteDump` through the loader exception filter because dump
capture runs synchronously after the saved exception context. Steam's overlay
appears only in that post-fault dump-writing walk. Neither the loader nor the
overlay is a caller of the faulting instruction.

### Dump verdict

The dumps confirm two direct null virtual-interface dispatches in the retail
executable, on two different native call chains. They do **not** support the
triage suggestion that the owner crash has `esi == 0`; in the saved context,
`esi` is nonzero and `eax` is the null dispatch receiver. Client B has both
`ecx == 0` at the dispatch and `esi == 0`.

Dump evidence alone cannot name the two stock functions or prove whether a
loader hook caused either state. That requires resolving every native frame
and caller edge against the retail binary before any fix is considered.
