# Beta.19 WAN disconnect and native crashes (2026-07-27)

Status: root causes proven and foundational fixes implemented; full release
battery pending. This document records the artifact inventory, peer-correlated
timeline, dump forensics, static reverse engineering, transport failure chain,
and the ownership fixes. No source fix was started before the findings were
committed.

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
2. The owner first reports Steam gameplay send rejection with numeric result
   25 at 10:42:07.596. That transient burst reaches 78 failures at
   10:42:10.618 and then recovers. A second burst is visible at
   10:43:14.684 with the cumulative count at 80; it never recovers and reaches
   5,466 by 10:44:09.823.
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
capture: no minion or summon existed. Dump and static analysis below resolve
the two nulls as stock D3D shutdown faults. The transport analysis resolves the
earlier disconnect separately.

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
identify the expected retail executable. The fault and frame-pointer chain
reported by CDB, converted to retail static addresses, is:

```text
0x004207E5  mov edx, dword ptr [eax]  ; eax == 0
0x004137D0
0x00412FB0
0x005A77A7
0x005B6993  hidden FPO frame recovered from the raw stack
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

## Static reverse engineering

Ghidra 12.0.3 analyzed the retail `SolomonDark.exe` from a read-only project
replica. Both fault addresses dereference the same native global:
`DAT_00B401E8`, which `config/binary-layout.ini` independently identifies as
`device_pointer_global`. It is the stock process-wide
`IDirect3DDevice9 *`. The nulls are not actor, participant, projectile, or
minion pointers.

### Device ownership and shutdown order

The relevant stock lifecycle is:

1. `FUN_0043FF70` calls `Direct3DCreate9` and
   `IDirect3D9::CreateDevice(..., &DAT_00B401E8)`.
2. `FUN_0040C690`, the native application run loop, starts asset work with
   `__beginthread(LAB_0040B550, ...)`.
3. The run loop polls virtual slot `+0xF4`, resolved through the owner's
   `MyApp` vtable to `FUN_0040DEC0`. That function returns the close flag at
   `DAT_00B40207`.
4. After the flag becomes nonzero, the run loop calls virtual slot `+0xF8`
   (`FUN_0040E430`) and proceeds to graphics teardown. That virtual function
   disposes another owned object and calls slot `+0xB4`; it does not join the
   asset worker.
5. At `0x0040D091` the run loop unbinds stage-zero texture state. It releases
   the D3D device and interface, then writes zero to `DAT_00B401E8` at
   `0x0040D0CF`.
6. `FUN_0068C500` returns after the run loop. CRT exit then destroys `MyApp`
   and its global bundle collection, whose texture cleanup still assumes the
   device exists.

The device global has 129 static references in 44 functions. Its initialization
is the `CreateDevice` out parameter above, and the only direct native write of
zero is the run-loop teardown at `0x0040D0CF`. The loader's D3D9 seam reads
the configured global to acquire the device and patches the live device's
`Reset` and `EndScene` vtable slots. It does not assign or clear the native
global.

### Client B fault at `0x00441221`

`0x00441221` is in `FUN_00441180`, the stock texture-slot allocation and
creation routine:

```asm
mov ecx, dword ptr [DAT_00B401E8]
mov edx, dword ptr [ecx]          ; fault: device == null
mov ecx, dword ptr [edx+0x5c]
call ecx                          ; IDirect3DDevice9::CreateTexture
```

`FUN_00441180` has one direct caller, texture upload routine
`FUN_00440F70`. Every direct call into that uploader is from the image loader
`FUN_00420140` (two sites) or its two adjacent image helpers
`FUN_00420640` and `FUN_004206A0`. The captured path resolves completely:

```text
FUN_00441180  texture allocation / CreateTexture
FUN_00440F70  texture pixel upload
FUN_00420140  image load
FUN_004130F8  image page-set load
FUN_004E0DD0  BadGuys atlas builder
LAB_0040B550  MyApp asset worker
native thread entry
```

The `BadGuys` identity is independently fixed by vtable `0x00799F14`,
constructor `0x005AC9D0`, and singleton `0x00819978`. The worker entry calls
`MyApp` vtable slot `+0xBC`, resolved to `FUN_005B69D0`, which dispatches
compiled asset/singleton builders including this atlas path.

The menu had already rendered, so the device was successfully initialized.
The asset worker was still uploading the BadGuys atlas when another thread
cleared the process-wide device during shutdown. The crash occurred 264 ms
after the deactivation log. The incomplete dump cannot prove which window
message initiated client B's close, but static ownership proves the immediate
defect: native teardown neither joins nor excludes the asset worker before
releasing and clearing the device.

### Owner fault at `0x004207E5`

`0x004207E5` is in `FUN_00420760`, the central stock SpriteBundle
texture-slot release routine:

```asm
mov eax, dword ptr [DAT_00B401E8]
mov edx, dword ptr [eax]          ; fault: device == null
mov eax, dword ptr [edx+0x104]
call eax                          ; IDirect3DDevice9::SetTexture(0, null)
```

Its complete direct-caller set is `FUN_00413760`, `FUN_00417290`,
`FUN_004174E0`, `FUN_00417200`, `FUN_00500B90`, and `FUN_005BED10`.
The dump selected the first path. Resolving the captured frames and the raw
stack gives:

```text
FUN_00420760  SpriteBundle texture-slot release / SetTexture
FUN_00413760  bulk SpriteBundle release
FUN_00412F70  SpriteBundle destructor
FUN_005A76D0  global bundle collection destructor
FUN_005B6500  MyApp destructor (return 0x005B6993)
CRT exit / native thread entry
```

`0x005B6993` is an optimized frame omitted by CDB's frame-pointer unwind but
present as the live return address on the raw stack. It is immediately after
the `FUN_005A76D0` call in the `MyApp` destructor. This closes the apparent
gap between the bundle destructor and CRT exit.

The owner dump supplies the lifecycle state, not merely a static possibility.
With its `+0x00600000` image relocation applied:

- `DAT_00B401E8` is zero;
- close flag `DAT_00B40207` is one;
- the `MyApp` object is live at `0x00E1F630` with vtable
  `0x0079A004` after removing relocation;
- its deep-pause, light-pause, and deactivated bytes at `+0xC23`,
  `+0xC24`, and `+0xC25` are all zero.

Stock window procedure `FUN_00443440` only queues activation state for
`WM_ACTIVATEAPP`; its close path sets `DAT_00B40207`. The loader focus bypass
changes a false `WM_ACTIVATEAPP` to true and clears the app's deactivated byte.
The dump confirms that those pause/deactivation fields were already clear.
The deactivation log is therefore a shutdown/focus-loss symptom, not the
owner crash trigger.

The owner exited the native run loop through its close state, which released
and cleared the D3D device. CRT destruction then called the SpriteBundle
release routine after that lifetime had ended. Its unconditional `SetTexture`
dispatch through the cleared global caused the fault.

### Static verdict

The two addresses are different manifestations of one stock shutdown-lifetime
class:

- a concurrent asset worker uses the D3D device after run-loop teardown;
- later static object destruction uses the D3D device after run-loop teardown.

Neither saved fault stack includes the loader, and none of the beta.18-to-.19
minion, projectile catch-up, damage-observer, or synthetic-participant paths
can reach either native chain. The crashes are real native defects, but they
occur while the processes are closing and do not explain why the owner's
host-to-client Steam stream failed roughly one minute earlier.

## Transport root cause

### What result 25 means

Steam defines EResult 25 as `k_EResultLimitExceeded`. The
[`ISteamNetworkingMessages`](https://partner.steamgames.com/doc/api/ISteamnetworkingMessages?language=english)
API used by the loader runs over `ISteamNetworkingSockets`; the underlying
[`SendMessageToConnection`](https://partner.steamgames.com/doc/api/ISteamNetworkingSockets?language=english#SendMessageToConnection)
contract documents `k_EResultLimitExceeded` when too much data is already
queued in the send buffer. This is a capacity/backpressure result, not a
remote process-crash indication.

The peer-correlated route changes and the two rejection bursts are:

| Transition | Owner | Client B | Result |
|---|---:|---:|---|
| initial direct or pending route | 10:41:46.563 | 10:41:46.571 | healthy |
| direct/pending to SDR | 10:42:10.585 | 10:42:10.967 | the 78-rejection burst stops |
| SDR to direct/pending | 10:42:18.578 | 10:42:18.977 | healthy |
| direct/pending to SDR | 10:42:45.605 | 10:42:46.011 | healthy |
| SDR to direct/pending | 10:43:07.604 | 10:43:07.021 | client receives its last host generation; permanent rejection follows |

The mirrored observations prove that these are real Steam route-state
transitions rather than one machine's logging error. They do not prove why
Steam changed routes. They do prove that a temporarily constrained route is a
reproducible field trigger for the loader's missing backpressure handling:
the first constrained period recovered on SDR, while the second did not
recover before the peer timeout.

### Why beta.19 fills the queue

The host's protocol-86 producer is both large and bursty:

- Beta.19 added a 56-byte native-minion state to every full actor and 16 bytes
  to every motion actor, including ordinary enemies whose minion state is all
  zero. `WorldSnapshotPacket` grew from 1,032 to 1,200 bytes and
  `WorldMotionSnapshotPacket` from 968 to 1,128 bytes.
- At the last 36-actor generation received by client B, each motion generation
  is four packets, or 4,512 bytes. At the 67 ms floor that is about
  67.3 kB/s before participant frames, state, loot, spell, cast, damage, and
  session traffic.
- By the host's later 47 actors, a motion generation is five packets, or
  5,640 bytes, which is about 84.2 kB/s at that floor.
- Full identity generations are reliable. A 36-actor generation is 12 packets
  or 14,400 bytes; a 47-actor generation is 16 packets or 19,200 bytes.
- The nominal reliable-identity interval is one second, but
  `identity_changed` bypasses that interval. Enemy creation, retirement, or
  actor-vector identity changes can therefore enqueue another complete
  reliable generation on the next 67 ms producer tick.
- Participant frames add a fixed 370-byte packet every 50 ms per participant.

The native-minion feature is not a semantic trigger in this run; no minion
existed. Its protocol-wide fixed-size expansion increased the baseline load
of every enemy generation. The unpaced identity-change path supplies the
bursts seen during rapid enemy creation and death.

### The ownership failure

`multiplayer_steam_gameplay_queue.cpp` owns the boundary between the game
producer and Steam's finite send buffer, but beta.19 does not implement that
ownership:

1. The game thread can queue 1,024 packets and the service thread removes up
   to 256 each 16 ms tick.
2. The service thread hands each removed packet to `SendMessageToUser`.
3. On every Steam rejection, it increments a counter and permanently discards
   the packet. It does not stop draining, retain reliable traffic, coalesce
   disposable snapshots, back off, inspect pending bytes, or reset a saturated
   peer route.
4. The producer therefore keeps submitting roughly a hundred packets per
   second into an already-full Steam buffer. The observed persistent rejection
   slope is approximately that rate.
5. Session keepalives bypass this gameplay queue. Client B's successful
   outbound keepalives and the owner's continued receipt of client traffic
   therefore do not contradict a saturated owner-to-client gameplay path.

`PumpNetworkMessages` refreshes the authenticated peer timer for any valid
received packet before gameplay application. Client B's exact 30-second
expiry proves it received no valid host packet, not merely that a world
fragment was rejected later by gameplay code.

### Disconnect chain

The complete field chain is:

```text
high-rate protocol-86 host snapshots
    + temporary Steam route capacity loss
    + unpaced reliable identity generations
→ Steam's owner-to-client send buffer reaches its limit
→ SendMessageToUser returns k_EResultLimitExceeded (25)
→ beta.19 discards every rejected gameplay packet and continues hammering
→ client B receives no host packet for 30 seconds
→ client B times out the owner and reports "network connection failed"
```

The foundational boundary is therefore the transport queue, not an actor
materialization hook. It must bound production during congestion, preserve
reliable delivery semantics, discard/coalesce only disposable state, and
restart a peer session when sustained saturation cannot clear before the
authentication timeout. Snapshot pacing must also apply to identity changes;
otherwise route recovery merely reopens the same flood.

## Relationship between the disconnect and crashes

Issue #65 contains two defect classes and two launch attempts:

1. Client B's 09:00 standalone launch closes while its asset worker is still
   uploading the BadGuys atlas. Native run-loop teardown releases and clears
   the D3D device; the worker dereferences that null in `CreateTexture` at
   `0x00441221`.
2. In the later WAN attempt, the independent transport chain above disconnects
   client B at 10:43:37.590. The owner process subsequently enters close
   teardown. The run loop again releases and clears the D3D device; CRT
   destruction dereferences that null in `SetTexture` at `0x004207E5`.

The owner dump proves close state but not which user or window action requested
close. Accordingly, the defensible combined chain is **disconnect, then
close, then stock D3D crash**. It is not crash, then peer disconnect. The
common native crash class still requires a single ownership fix because it
can fault both a concurrent asset worker and later global destructors.

## Foundational fixes

### Congestion ownership

The Steam gameplay boundary now has a per-peer outbound policy:

- `k_EResultLimitExceeded` starts a 250 ms backoff instead of a tight retry
  loop.
- A rejected reliable packet is retained ahead of later traffic for that peer.
- Disposable packets are reduced to the newest pending probe while the peer is
  congested. A congested peer cannot head-of-line block other peers.
- Any successful retry clears the pressure episode.
- Two seconds of continuous limit rejection emits one route-recovery event,
  well before the 30-second authentication timeout.
- Client congestion closes the failed host route and restarts the authenticated
  hello. Host congestion suspends only that peer, closes its route, and permits
  the existing validated keepalive/hello paths to reauthenticate it.
- A route reset discards the old session's queued packets at the peer-ownership
  boundary. Periodic reliable state and identity checkpoints repopulate the
  fresh session.

The producer was fixed at the same time. Reliable world identity is now
published at its bandwidth-limited checkpoint cadence even when actor identity
changes. Between checkpoints, disposable motion is projected onto the last
published identity: existing actors keep moving, while newly created or
retired actors wait at most one checkpoint interval for structural
publication. Thus structural churn cannot bypass the reliable budget, and
motion remains useful rather than freezing the whole world.

### Native D3D device ownership

The loader now owns one process-lifetime reference to the retail
`IDirect3DDevice9`. Installation validates the exact retail instruction

```asm
0040D0CF  89 1D E8 01 B4 00  mov [00B401E8], ebx
```

against the relocated device-global operand, retains the live device, replaces
that single clear with six NOPs, and republishes the retained pointer. The
stock run loop still releases its own reference. The device itself and its
global remain valid until process termination, after the asset worker and CRT
SpriteBundle destructors have finished.

This is intentionally process ownership, not a loader subsystem resource.
Releasing it during ordinary loader shutdown would recreate the same lifetime
inversion. It also avoids patching either crash instruction or adding
call-site null checks.

## Deterministic reproduction and targeted verification

Before the queue change, a Windows harness compiled the production
`multiplayer_steam_gameplay_queue.cpp` with an injected
`SendMessageToUser` result of 25. It queued one reliable packet and serviced
twice. The exact pre-fix result was:

```text
REPRODUCED: a reliable packet rejected with result 25 was removed permanently;
the second service pass had nothing to retry
```

The regression now injects the same result into the extracted production
policy and proves:

- temporary saturation retains and later delivers reliable traffic;
- disposable traffic coalesces without blocking another peer;
- sustained saturation emits exactly one route reset after two seconds;
- resetting that peer removes the old route's backlog;
- structural actor churn keeps motion compatible with the last published
  identity until the next reliable checkpoint.

The actual WAN route transition cannot be forced deterministically through
Steam on one local account. The result-25 boundary is therefore injected
directly, which is closer to the proven failure than delayed gameplay
application: the field client received no packet at all.

An isolated native launch used instance `ndrop-d3dguard`, with audio disabled,
under
`C:\sd-netdrop-20260727\runtime\instances\ndrop-d3dguard\stage`.
For exact owned PID 27264, read-only process inspection proved:

```text
device-clear instruction  90 90 90 90 90 90
device pointer global     0x04EA2760
```

The harness then posted `WM_CLOSE` only to that PID's main window. The process
exited normally, produced no minidump, and left a zero-byte crash log. No
owner installation or process was read, modified, or stopped.
