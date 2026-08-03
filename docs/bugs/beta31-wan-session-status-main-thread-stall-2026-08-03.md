# Beta 31 WAN session-status main-thread stall

## Symptom

The beta.31 WAN arena pacing leg recorded a 547.138 ms Home present gap while
29 native wave enemies and both human peers were active. The same 60-second
window otherwise had a 0.347 ms median present gap, a 15.836 ms p99, no send
failures, and no NFO hard gap. This is a real visible freeze and fails the
pre-release requirement that the WAN pair have no lag or other issues.

The matching beta.30 arena window had no gap above 33.3 ms on Home and no gap
above 100 ms on NFO. The beta.31 stall therefore cannot be accepted as normal
scene pacing even though the affected status-publication code predates the
render cutover.

Evidence is retained outside the repository under:

- `D:\codex-evidence\wanverify-20260802\wan\beta31\flat\run1\arena\home-network-telemetry.jsonl`
- `D:\codex-evidence\wanverify-20260802\wan\beta31\flat\run1\arena\home-summary.json`
- `D:\codex-evidence\wanverify-20260802\wan\beta30\run9\arena\home-summary.json`

## Reproduction and attribution

The peers were connected over the real Home-to-NFO route, in the same flat
stock survival override, with 29 native enemies alive. No Lua command,
screenshot, or other verifier action ran during the measured window.

At the freeze, network telemetry recorded this exact sequence on the game
thread:

1. `transport_stage` reported `stage=publish` and `duration_us=485458`.
2. The enclosing `transport_tick` took 486129 us.
3. The next `present` reported `gap_us=547138`.
4. Nine already-arrived packets then drained with an oldest queue age of
   540812 us.

This rules out network latency as the initiating cause. The ingress worker kept
receiving packets while the game/service thread was blocked.

## Root cause

`ServiceLocalTransport()` calls `PublishLocalTransportRuntimeState()` on the
game thread. That function calls `PublishLocalSessionStatus()`, which rewrites
`.sdmod/multiplayer-session-status.json` at least every 500 ms even when its
semantic signature has not changed. `WriteMultiplayerSessionStatus()` performs
directory and truncating file-system operations synchronously. A slow host
file-system operation therefore blocks transport, simulation, and presentation
together.

The 485.458 ms `publish` stage is the direct measurement of that synchronous
path. Periodic status-file I/O on a render/service thread makes a storage or
filter-driver delay into an in-game freeze; faster prior writes merely hide the
same failure class.

## Required correction

Session-status serialization and file I/O must leave the game thread. The
publisher should submit a coalesced latest snapshot to one owned background
writer, retain the existing periodic heartbeat and semantic-change behavior,
and provide an explicit bounded flush during orderly shutdown. It must not
spawn unbounded work or permit an older snapshot to overwrite a newer one.

Acceptance requires:

- a contract test proving the gameplay publisher queues rather than writes;
- writer tests for coalescing, ordering, bounded shutdown flush, and write
  failure handling;
- the complete release battery;
- a repeat of the same WAN arena workload with no status-publication stall and
  no hard present gap on either peer.
