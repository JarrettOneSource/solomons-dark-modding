# WAN client lag spikes

Status: mechanisms proven; correction proven over the same WAN path

## Problem

Clients intermittently see the game freeze or jump forward while the host
continues normally. The client recovers without reconnecting. Local loopback
tests cannot establish the cause because they do not exercise WAN latency,
loss, reordering, or path-MTU behavior.

The investigation starts from release `v0.1.0-beta.22`
(`580cb938f179f3fe7f4a3b8361f87b41f4367c7f`). No transport behavior changes
are allowed until an unfixed build reproduces the symptom over the real WAN
path and its mechanism is identified from captured data.

## Test path

The reusable runner is `tools/verify_remote_latency_wave5.py`. It accepts an
owner-scoped JSON configuration; `tools/remote_latency_wave5.example.json`
documents the fields without committing either machine's address.

The two required directions are:

1. A: Windows host on UDP 50311 and NFO client on UDP 51512.
2. B: NFO host on UDP 51511 and Windows client B on UDP 50312.

Direction B carries the greater acceptance weight because the client rendering
and applying authoritative state is the real Windows game. If direction A
cannot cross the Windows-side NAT, its failed attempts and packet evidence are
retained; the harness never changes either firewall.

Each successful session uses the retail wave schedule and this supported flow:

1. host and client B form a 2/4 human-equivalent lobby;
2. the host loads a fire/skirmisher bot named Ember and a
   water/striker bot named Brook, producing a 4/4 roster on both peers;
3. the host calls `sd.hub.start_testrun`;
4. both peers enter the Boneyard and the host invokes the supported
   `sd.hub.trigger_solomon_dig` action, which drives the real client-side
   Solomon Dig and readiness path;
5. both peers are observed through wave 5.

This deliberately uses the real Solomon Dig path. It exercises the same
client readiness, transition, and wave-start behavior as the beta.22 dig fix
instead of bypassing those seams with direct wave-start calls.

For every wave, the runner captures both backbuffers and records peer wave
state, participant vitals, bot state, and replicated enemy state. The client
must show enemy movement, stock hit feedback, and a synchronized roster. The
run also forces one Ember death through the host-native damage path and proves
death and respawn on both peers. Both bots must issue accepted combat casts.

## Telemetry

`SDMOD_NETWORK_TELEMETRY=1` enables an asynchronous JSONL stream at
`.sdmod/logs/network-telemetry.jsonl`. It is disabled by default. The writer
uses a bounded queue and a background file writer so telemetry file flushes
are not performed in the transport or rendering path.

Each event has a UTC file-time value, a process-local monotonic microsecond
value, and a thread ID. The runner measures the NFO-minus-local clock offset
before and after each session. Packet sequence numbers are the primary
cross-machine correlation key; adjusted wall time is secondary.

The stream records:

- every datagram send and receive: packet kind, sequence, byte size, endpoint,
  result, socket error, and whether the IPv4 payload exceeds 1472 bytes;
- receive arrival gap, forward sequence delta, inferred missing packets,
  reordering, and duplicates;
- dispatch acceptance and apply duration for every received packet;
- receive-batch packet/byte counts, duration, terminal socket error, and the
  app-thread packet/time caps;
- app-thread transport tick gap and duration, queued-event depth, packets and
  bytes sent in the tick, largest datagram, and oversized-datagram count;
- slow app-thread transport stage name and duration, emitted only when a stage
  exceeds 5 ms;
- world-snapshot age at apply, stale-hold state, actor
  create/remove/match/write counts, and apply duration;
- reliable gameplay event send/retransmit age, pending count, in-flight
  window, acknowledgement, and retirement count for participant hit feedback
  and vitals corrections;
- EndScene start-to-start gap and hook duration;
- loader logger caller mutex wait, queue depth/drop count, caller duration,
  and asynchronous writer flush duration. The analyzer also accepts the
  original synchronous `logger_write` rows so unfixed and fixed captures stay
  directly comparable.

The packet, transport-stage, world-apply, and present telemetry schema is held
constant between unfixed and fixed sessions. Logger rows change from
`logger_write` to `logger_enqueue`/`logger_flush` as part of removing synchronous
caller I/O; the analyzer normalizes both forms.

## Hypotheses and decision tests

| Hypothesis | Evidence that would support it | Evidence that would reject it |
|---|---|---|
| Catch-up burst apply after a receive gap | A hard client gap ends in a large receive batch whose packet or world apply consumes the stall | Apply and batch time remain small compared with the observed stall |
| WAN fragmentation of oversized UDP datagrams | Missing sequences are disproportionately datagrams over 1472 bytes; the host sends them continuously while the client never receives them; loss begins with larger wave snapshots | Oversized packets arrive at the same rate as small packets and stalls contain no size-correlated loss |
| Socket receive-buffer overflow during spawn bursts | Host send bursts exceed the client socket buffer/drain rate, receive batches hit the 64-packet cap, and loss follows queue pressure | Socket capacity and drain stay well above the captured bursts, with no batch-cap hits |
| Loss-recovery or acknowledgement stall | Pending recovery queues grow, retransmit ages stretch across the spike, and an ACK retires the queue at recovery | Recovery queues and retransmit ages remain bounded or no reliable event is pending during spikes |
| Send-side batching or coalescing | The host itself emits a large inter-send gap or a single high-count/high-byte transport tick matching the client symptom | Host packet send cadence remains continuous across the client receive gap |
| Blocking client I/O | Logger mutex/flush time or another measured apply call consumes the present/transport gap | All measured client hot-path durations remain far below the stall |
| Rendering stall on the NFO CPU renderer | Present gaps occur without receive or transport gaps and with continuous snapshot application | Direction B reproduces the gameplay stall on the Windows client, or the NFO continues presenting while network state freezes |

An arrival gap is only labeled a network receive stall when the sender's
sequence-correlated trace shows continued sends through the interval. A
present gap alone is not sufficient.

## Unfixed result

Four complete, unfixed sessions crossed the real Windows-to-NFO WAN path:
two in each direction. All four reached at least wave 8, passed every roster,
vitals, bot combat/death/respawn, enemy movement, hit-feedback, and screenshot
gate, then left the NFO ports and process scope clean. Their machine-readable
summary is
`/mnt/d/codex-evidence/netlag-20260728/before/aggregate.json`; the individual
packet correlations are the four `telemetry-analysis.json` files below
`before/direction-{a,b}/run-{01,02}`.

Across all four sessions, the client traces contain 41 present gaps at or
above 150 ms and 145 raw receive gaps at or above 150 ms. Of the latter, 38
are hard client app-thread transport stalls; 107 are ordinary sender-idle
intervals and are excluded from the hard-stall count. The aggregate maximum
present gap is 1,460,711 us, the maximum hard transport stall is 1,299,401 us,
client arrival p99 is 122,811.5 us, packet-apply p99 is 757.46 us, and
receive-batch p99/max are 17/64 packets. Direction A's NFO CPU renderer is a
known frame timing confound, so the causal analysis gives direction B's real
Windows client greater weight.

### Proven client-stall mechanism

Direction B reproduced nine hard Windows-client present gaps in two sessions.
Two were isolated render-present gaps. Seven were coupled to an app-thread
transport gap and ended by draining 9 to 64 queued packets:

| Run | Present gap | Receive/app gap | Host max send gap | Recovery batch | Batch/apply cost |
|---|---:|---:|---:|---:|---:|
| B-01 | 1,317,143 us | 1,299,401 us | 38,101 us | 64 | 2,304/158 us |
| B-01 | 160,647 us | 198,264 us | 111,870 us | 9 | 395/32 us |
| B-01 | 840,427 us | 847,778 us | 111,371 us | 36 | 1,345/32 us |
| B-01 | 642,772 us | same 847,778 us episode | 111,371 us | 36 | 1,345/26 us |
| B-02 | 1,047,848 us | 1,080,912 us | 76,109 us | 64 | 2,696/173 us |
| B-02 | 613,982 us | 620,405 us | 120,853 us | 27 | 1,182/72 us |
| B-02 | 790,092 us | 789,201 us | 100,038 us | 37 | 1,453/60 us |

The strongest B-01 event is sequence-correlated: the host kept sending every
38.1 ms or less while the Windows client performed no transport tick for
1.313 s, then received/applied the 64-packet per-tick maximum in 2.304 ms.
The host-to-client trace lost only one 374-byte datagram in B-01 and none in
B-02. The stall therefore was not caused by WAN loss, host send interruption,
or expensive catch-up application.

The static call chain explains the trace:

1. `DetourAppMainTick` calls `PumpGameplayMainThreadWork`;
2. that calls `TickGameplayTransportOnAppThread`;
3. that calls `TickLocalTransport`;
4. `ReceivePackets` performs `recvfrom` and dispatch directly on that same
   app thread, stopping after `kMaxPacketsPerTick == 64`.

Consequently, any stock game-thread pause also stops UDP socket draining. The
host remains healthy and continues sending, which exactly matches the owner's
"host sees nothing wrong" observation. When the client app thread returns, it
replays an old-state burst, producing the visible stale-then-jump recovery.

The hard present gaps in these captures occur during stock scene transition,
Boneyard reading, and participant materialization before wave 1. No
150-ms-or-greater Windows present gap occurred during steady wave combat.
Moving network ingress off the app thread will prevent transport staleness and
the bursty recovery, but it cannot and must not be represented as removing
the underlying stock scene-loading/render pause itself.

### Independently proven WAN-MTU fault

Both B sessions also expose a separate transport-class defect. Every periodic
client-to-host kind-31 `ParticipantProgressionBookSnapshot` was sent as a
1,704-byte UDP payload and was absent at the NFO host: 16/16 in B-01 and 16/16
in B-02. Other packets crossed the path, and DF probes established a 1,472-byte
maximum IPv4 UDP payload. These oversized datagrams require IP fragmentation;
their 100% sequence-correlated loss over this WAN path proves that beta.22
cannot rely on fragmentation. The loss is not temporally responsible for the
captured hard client stalls, but it is a foundational reliability fault in the
same transport and must be corrected globally rather than special-casing
kind 31.

### Independently proven recovery-congestion fault

The beta.22 hit-feedback channel uses cumulative acknowledgement, but its
sender retransmits *every* unacknowledged 80-byte event every 100 ms. That is
not a bounded recovery policy: an acknowledgement delay of one interval turns
a pending queue of `N` events into approximately `10N` recovery datagrams per
second.

The unfixed successful captures already contain this signature. With the NFO
as the CPU-rendered client, A-01 retained as many as 47 hit-feedback events
and sent 375 new events plus 791 retransmissions; A-02 retained 42 and sent
396 new plus 738 retransmissions. Those are retransmission-to-new-event ratios
of 2.11 and 1.86. The faster Windows clients in B-01/B-02 acknowledged sooner,
but still retained 8/11 events.

A direction-B correction-validation diagnostic then drove a sustained
47-enemy combat backlog before the recovery policy itself had been changed.
The NFO host emitted 47,006 kind-33 hit-feedback datagrams in 168 seconds:
1,227 first sends and 45,779 retransmissions, a 37.31 retransmission ratio.
The pending queue reached its hard limit of 256. The Windows receiver queue
then filled to 2,048 packets and recorded 33,892 ingress drops. Critical
participant frames were starved behind cosmetic retransmissions, both peers
timed out, and the host game otherwise continued. Named-stage telemetry
localized host work to `outbound_corrections`, which reached 52.826 ms. The
run is retained as the non-acceptance diagnostic
`after/harness-shakedown/direction-b-run-03-recovery-congestion-collapse`.

This proves a positive-feedback loop: delayed acknowledgement grows the
pending set; all-pending retransmission multiplies traffic and app-thread send
work; that load delays apply/acknowledgement further; the channel eventually
starves its own liveness packets. The symptom is client-visible while the host
gameplay remains healthy, and ordinary recovery resumes when the queue has not
yet crossed the collapse point.

### Hypothesis disposition

- **Catch-up burst:** confirmed as the recovery shape, not the source of the
  original pause. Up to 64 packets replay after ingress stops, but the largest
  measured batch costs only 2.696 ms.
- **WAN fragmentation:** independently confirmed for every 1,704-byte
  progression snapshot; not correlated with the direction-B client stalls.
- **Socket overflow:** rejected for these spikes. Windows reported a
  65,536-byte receive buffer, the largest observed backlog fit within it, and
  B-02 had zero host-to-client sequence loss.
- **Recovery/ACK stall:** rejected as the cause of the seven original
  transition stalls, then independently confirmed as a sustained-combat
  congestion mechanism. Unfixed direction-A sessions reached 42-47 pending
  events; the later stress capture reached 256 and amplified 1,227 first sends
  into 45,779 retransmissions.
- **Host batching/coalescing:** rejected. The host keeps a 38.1–120.9 ms send
  cadence through the seven app-thread episodes.
- **Blocking loader I/O/apply:** rejected for the original seven transition
  stalls, then independently confirmed in a correction-validation run. A
  synchronous log flush consumed 180.820 ms inside one packet apply.
- **Render-only stall:** confirmed for two of nine direction-B hard present
  gaps and for much of direction A's CPU-rendered noise, but rejected as the
  explanation for the seven sequence-correlated transport backlogs.

### Independently proven synchronous-log stall

Once the receiver worker and bounded app-thread apply were active, B-04
captured a different hard Windows-client spike without conflating it with
network arrival:

- host kind-16 sequence 7959 reached the receiver worker normally;
- the app thread spent 181,408 us applying it;
- 181,074 us of that apply was one ordinary `Log` call, including a
  180,820-us `ofstream.flush`;
- the receive worker continued filling the queue while the app thread was
  blocked, the receive batch lasted 181,596 us, and the matching present gap
  lasted 343,407 us.

This is exact stage accounting, not correlation by wall clock: the packet
apply, logger call, receive batch, transport stage, and present rows share the
same process monotonic timeline. The capture is retained at
`after/harness-shakedown/direction-b-run-04-synchronous-logger-blocking-spike`.
It proves that ordinary diagnostic output was another member of the same
client-stall class. Moving only transport reads off-thread would still leave
game-state application vulnerable to arbitrary storage latency.

The first asynchronous implementation also had a C++ ownership defect:
`Log()` called `g_log_stream.is_open()` while the writer thread wrote and
flushed that same `std::ofstream`. The caller held the queue mutex, but the
writer intentionally did not hold it during I/O, so that read was a data race
on the stream object. Two consecutive validation shakedowns while that defect
was present ended in an access violation in the stock object-manager tick and
then Windows heap-corruption exception `0xc0000374`. The first stack does not by
itself prove that the stream race caused either failure, so neither run is
counted as acceptance evidence. They are quarantined under
`after/harness-shakedown/direction-b-run-05-stock-object-manager-stale-entry`
and
`after/harness-shakedown/direction-b-run-06-async-logger-stream-race-heap-corruption`.
The corrected implementation gives the stream exclusively to the writer thread;
callers consult only mutex-protected writer state. Four subsequent full WAN
sessions completed without a crash, heap event, or nonempty crash artifact.

## Foundational correction

The correction has four transport-wide requirements:

1. A dedicated local-UDP ingress worker continuously drains the socket into a
   bounded raw-datagram queue. Packet parsing and all game-state mutation stay
   on the app thread, which consumes the queue with explicit per-frame packet
   and time budgets. This decouples network arrival from stock game pauses and
   prevents one giant recovery apply.
2. The local-UDP wire format gains transport-level fragmentation and
   reassembly under a conservative 1,200-byte datagram ceiling. Every send
   passes through that ceiling; no packet kind is allowed to emit an oversized
   UDP datagram directly. Reassembly is bounded by message count, bytes, and
   age, and only a complete original datagram enters normal dispatch.
3. Cumulative-ACK event delivery uses a real bounded send window. At most
   eight hit-feedback events may be in flight, each app-thread tick may send
   at most four, and only the oldest unacknowledged event is eligible for
   retransmission. Once that gap is acknowledged, the window advances. This
   preserves ordered, exactly-once presentation without the beta.22
   all-pending resend amplification.
4. Ordinary loader logging uses a bounded asynchronous queue. The game,
   transport, and render threads only timestamp, retain the crash-tail copy,
   and enqueue. One writer thread exclusively owns file and debugger output.
   Explicit flush/shutdown drains the queue; queue exhaustion is bounded and
   observable instead of blocking a caller.

Telemetry will distinguish receiver-thread arrival, ingress queue depth/drop,
app-thread queue age, apply budget exhaustion, fragment send/reassembly, and
wire datagram size. The protocol version will be bumped because beta.22 peers
cannot interpret the fragment envelope.

## Fixed result

The transport correction was first acceptance-tested as DLL SHA-256
`a0fedbac37fbf968167cbedd9ef75749dd7f8ce64b976fd46fd9412d0c660f2b`
and verified byte-identical in the local package, the NFO incoming stage, and
the NFO launcher package. Four complete fixed sessions then crossed the same
path: A-01/A-02 and B-07/B-08. Every session reached wave 8, captured both
peers for waves 1-5, kept the 4/4 roster and vitals synchronized, showed
advancing client enemies and client hit feedback, forced and observed bot
death/respawn, and ended with both differently elemented bots alive and
fighting.

The aggregate machine-readable comparison is
`/mnt/d/codex-evidence/netlag-20260728/before-after-comparison.json`:

| Metric, four sessions per build | Unfixed beta.22 | Fixed | Change |
|---|---:|---:|---:|
| successful wave-five sessions | 4/4 | 4/4 | unchanged |
| hard client transport stalls | 38 | 0 | -38 |
| worst hard transport stall | 1,299,401 us | 0 us | -1,299,401 us |
| client wire-arrival p99 | 122,811.5 us | 106,305.9 us | -16,505.6 us |
| per-packet apply p99 | 757.46 us | 1,080.82 us | +323.36 us |
| worst per-packet apply | 21,240 us | 11,133 us | -10,107 us |
| receive-batch maximum | 64 packets | 16 packets | bounded |
| oversized client datagrams | 66 total | 0 | -66 |
| host-to-client missing packets | 87 total | 0 | -87 |

The mixed-direction per-packet p99 is slightly higher because the fixed
consumer deliberately spreads queued work across frames and includes the NFO
CPU client. It remains 1.081 ms, the worst apply is nearly halved, and no
apply episode qualifies as a hard transport stall.

All final wire payloads are at most 1,200 bytes. The formerly lost 1,704-byte
kind-31 snapshots reassemble successfully, no final session records an ingress
drop, and the sequence-correlated host-to-client spans are complete:

- A-01: 6,666/6,666;
- A-02: 8,272/8,272;
- B-07: 6,734/6,734;
- B-08: 7,370/7,370.

The recovery window never exceeds eight in-flight events. Even when total
pending work temporarily exceeds the window, only the bounded prefix can send
and only its oldest gap can retransmit; the 45,779-retransmit collapse does not
recur.

The fixed captures contain 55 present gaps at or above 150 ms, all classified
as render/scene work rather than receive/apply stalls. Direction A's
CPU-rendered NFO client accounts for 35. Direction B accounts for 20 and has
zero sender-continuous client transport gaps. Present count therefore is not
used as a proxy for transport health. B-07 provides the strongest separation:
the asynchronous writer itself encountered a 594,955-us disk flush, while
client logger callers remained at 61 us p99 and 13,404 us maximum, packet
ingress continued, and no hard client transport stall occurred.

Visual inspection of all 40 wave images, not only harness predicates, confirms
both peers render the same progressing arena, fire/water participants, moving
enemies, active casts/hit states, and stable HUD/vitals through wave 5. Contact
sheets are retained under
`/mnt/d/codex-evidence/netlag-20260728/visual-review`.

### Exact final-build rerun

The final source adds the permanent fail-closed per-request Lua-exec target
needed by the reusable controller without changing the corrected transport
policy. The WAN-tested package DLL SHA-256 is
`44fe0cb32a47127fbb7054344e47f7f2fafdaac4b17daca22457da4863b81418`.
That value was verified byte-identical in:

- `bin/Release/Win32/SolomonDarkModLoader.dll`;
- the local launcher package;
- the isolated local fixed-launcher directory;
- `/root/sd-netlag-20260728/incoming/SolomonDarkModLoader.dll`;
- the isolated NFO launcher package.

MSVC does not produce a stable whole-file hash for this project: the final
clean `Build-All` and `Verify-Workspace` rebuilds changed the COFF timestamp,
debug-directory timestamps, and RSDS PDB GUID. The DLL sizes and section
layouts remained identical. PE-aware normalization of only those metadata
fields gives the tested and both clean-rebuild binaries the same SHA-256,
`f2a7642f37d0b768b259d3b3ec0ef8a2dc17a159c683a5de7b4003232ef79d15`;
all 25-26 differing bytes fall inside those fields. The raw offsets,
`objdump` header diff, and normalized-hash reports are retained under
`gates/tested-vs-*-rebuild-*`.

The exact DLL then reran both directions over the same WAN route:

| Exact run | Client machine | Highest wave, host/client | Hard client transport stalls | Present gaps >=150 ms | Arrival p99 | Apply p99/max | Batch max | Largest UDP payload | Missing in correlated spans |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A-13 | NFO CPU renderer | 8/8 | 0 | 12 | 225,569.48 us | 1,073.46/4,823 us | 16 | 1,200 B | 0/0 |
| B-12 | Windows renderer | 9/9 | 0 | 4 | 116,719.45 us | 398/952 us | 16 | 1,200 B | 0/0 |

Both exact-build runs pass every wave-five predicate: 4/4 synchronized roster,
different fire/water bot elements, accepted bot combat casts, host-native bot
death plus converged respawn, moving client enemies without a step over the
350-unit rejection threshold, stock client hit feedback, synchronized final
vitals, and all ten wave screenshots. The real client-side Solomon Dig flow
starts the retail waves. When wave 2 stopped changing for the 20-second organic
combat window, the harness's host-authority enemy-retirement assist cleared
the remaining 2.5-HP enemies; later waves advanced normally. This is recorded
as scenario control rather than transport recovery.

The four Windows-client present gaps in B-12 are not sender-continuous receive
stalls: the sequence-correlated host gaps match the receive gaps, packet apply
never exceeds 952 us, ingress drops remain zero, and both packet directions
have zero missing sequences. The asynchronous logger independently absorbs a
288,378-us file flush while its Windows game-thread callers remain at 39 us
p99 and 89 us maximum. The stock present pause remains measurable, but it no
longer stops socket ingress, blocks the caller on disk, or produces an
unbounded catch-up apply.

Wave screenshots are captured inside the `wave.started` event on each peer,
then transferred and validated only after the processes stop. Native-resolution
inspection of A-13 and B-12 confirms live Boneyard frames, stable HUD/vitals,
client B, Ember's fire effect, Brook's water effect, visible wave-2 skeleton
packs, and changing actor/camera positions through wave 5. The exact-build
contact sheets and written visual gate are
`visual-review/a13-exact-wave-contact.png`,
`visual-review/b12-exact-wave-contact.png`, and
`visual-review/exact-build-review.md`.

## Release validation

The final source tree passes:

- `Check-SourceOrganization.ps1`: 642 source/header fragments;
- `Build-All.ps1 -Configuration Release`: clean native rebuild with zero
  warnings and zero errors, plus launcher, UI, and updater publication;
- `Verify-Workspace.ps1 -Configuration Release` against the specified retail
  game directory: isolated zero-mod staging passed;
- `python3 -m unittest discover -s tests -p 'test_*.py'`: 453/453;
- `python3 tests/re/run_static_re_tests.py`: 290/290;
- Windows launcher contracts: 45/45;
- remote-latency harness tests: 40/40;
- all six standalone native contract binaries: content registry, mod-settings
  vectors (74 vectors/56 rules), multiplayer runtime state, world-motion
  fragment merge, Steam send-queue policy, and x86 hook relocation.

## Operational isolation

The NFO host is accessed only through the existing `nfoservers-root` Windows
OpenSSH alias. All staged files, Proton data, prefix state, processes, and
evidence live below `/root/sd-netlag-20260728`. The production website,
database, service, web-server configuration, and the `steamvnc` tenant are
outside the test scope. Baseline and final socket/process snapshots are part of
the evidence, and teardown validates process identity before stopping only the
test-owned processes.
