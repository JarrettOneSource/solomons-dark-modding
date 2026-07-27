# Host-death continuity and player-count scaling

Date: 2026-07-26

## Scope

This investigation covers:

- #54, a beta.18 Steam-lobby report that enemies on the surviving client
  became glitchy, then stopped moving, after the remote host character died;
- #57, the request that multiplayer use the one-player enemy difficulty
  baseline.

The owner-provided client log was mined before running or changing the game.
The source snapshot is read-only at:

`/mnt/d/codex-evidence/beta18-owner-testing-20260726/sdmod/`

## #54 conclusion

Host player death is not an enemy-authority transition. The transport host
process remains the run, wave, and enemy authority while its local character
is dead and spectating. A three-minute no-golem loopback reproduction on
unmodified beta.18 retained continuous enemy simulation, snapshot delivery,
attacks, and 100% retargeting to the surviving client.

The field session contains a separate client-side enemy-materialization load
and an uninstrumented client-local golem. Its timeline does not support host
death alone as the cause:

- two app-thread gaps occurred at `19:31:01.636` and `19:31:02.336`, about
  35 seconds before host death;
- the initial replicated-enemy materialization burst began at
  `19:31:27.529`, 9.6 seconds before host death;
- the first `enemy pool catch-up` occurred at `19:31:32.563`, 4.6 seconds
  before host death;
- the remote host death epoch began at `19:31:37.152`;
- repeated new materializations expanded at `19:32:14.122`, 37 seconds after
  death, and recurring tick gaps followed;
- `ActorWorld_Tick held` began at `19:32:33.347`, immediately after a captured
  pause-menu surface at `19:32:33.221`. Those holds are the intentional shared
  menu-pause path, not a death/spectator authority path.

Across the field log there are 247 app-thread gaps (maximum 1281 ms), 97
enemy-pool catch-up entries, 193 queued and 193 completed stock-spawner
materializations, 126 shared-simulation holds, and six transient snapshot
stalls. Of those holds, 123 have the exact `player_ticks=0
non_player_actors_held=2` signature. Materialization continues through
`19:41:08`; it is not a one-time death transition.

The loader has no beta.18 minion/golem instrumentation, so the field log
cannot prove when the golem appeared or identify its actor. The owner reported
that lag started moments after summoning it. A client-local, unreplicated
minion can make the client's native enemy AI select geometry or a target that
does not exist in the host simulation while host snapshots continually put
those enemies back on the authoritative path. That interaction is consistent
with visual jitter and extra client work, but remains a bounded hypothesis,
not a proven log fact. Minion replication is owned by #53 and is deliberately
not patched here.

## Authority seam

The role checks do not consult local player vitality:

- `IsLocalTransportHost()` is based only on initialized transport role.
- `SendWorldSnapshot()` runs only for that transport host and
  `BuildLocalWorldSnapshot()` captures the run actors without requiring the
  host player to be alive.
- the client wave spawner remains suppressed by
  `ShouldSuppressClientAuthoritativeRunWaveSpawner()`; the dead host does not
  transfer wave authority.
- the death spectator state changes death presentation, camera targeting, and
  respawn bookkeeping. It does not mutate `g_local_transport.is_host`.
- `ActorWorld_Tick` is held only for level-up/Lua-time/shared-menu pause state.
  Local death spectator state is not one of those predicates.

Therefore an authority handoff or a special "dead host keeps ticking" patch
would alter the correct seam and mask the field interaction instead of fixing
it.

## No-golem beta.18 reproduction

Evidence:

`/mnt/d/codex-evidence/host-death-20260726/baseline-continuity/result.json`

The standard harness launched `hdt-host` and `hdt-client` on ports 48711 and
48712 with audio disabled. After a 15-second pre-death sample, the host died
organically and remained in spectator mode for 180 seconds.

Results:

- host-authority enemy path: 3844.13 units over 180.7 seconds;
- client-clone enemy path: 3816.98 units over 181.1 seconds;
- terminal-minute paths: 875.34 host and 892.64 client;
- pre-death snapshot cadence: 109.78 ms mean, 172 ms maximum;
- post-death snapshot cadence: 110.26 ms mean, 219 ms maximum;
- 706 post-death damage edges and 344 in the terminal minute;
- 1650 of 1650 post-death target samples selected the surviving client;
- zero app-thread tick gaps, snapshot stalls, enemy-pool catch-ups, manual
  materializations, or shared-simulation holds on either process.

Both-peer early and terminal backbuffers show the dead host spectating the
client and enemies actively surrounding/attacking the survivor:

- `artifacts/host-post-death-early.png`
- `artifacts/client-post-death-early.png`
- `artifacts/host-post-death-terminal.png`
- `artifacts/client-post-death-terminal.png`

This falsifies host death by itself as the beta.18 continuity failure and pins
the regression boundary for future changes.

## #57 native scaling trace

Fresh read-only Ghidra evidence is stored at:

- `/mnt/d/codex-evidence/host-death-20260726/ghidra/player-count-scaling.log`
- `/mnt/d/codex-evidence/host-death-20260726/ghidra/player-count-scaling-xrefs.log`

The recovered stock path is:

1. `0x00649F40` scans four gameplay slots and counts entries whose region/index
   word matches `arena + 0x78`. It returns an integer, not a float.
2. `0x00462410` and `0x004625B0` store that count at `arena + 0x8FE4`.
3. Wave spawning reaches `0x00463B50` from `WaveSpawner_Tick`
   (`0x0046D000`). After normal enemy construction, it integer-loads
   `arena + 0x8FE4` and multiplies spawned current HP at `actor + 0x174` and
   the related value at `actor + 0x178`.

That player-count path does not modify enemy damage, wave `SPAWN`,
`MAXENEMIES`, or group composition. Those counts and groups come from
`data/wave.txt`; damage uses the independent enemy config/global scalar path.

Before the policy change, a deterministic one-player versus two-participant
loopback measurement already read `arena + 0x8FE4 == 1` on both processes.
The loader's remote participant does not currently become an additional stock
gameplay slot. The same stock Skeleton fixture measured:

- current/max HP: 5000/5000 in both runs;
- native contact damage observed as an HP decrement: 2.9970703125 in both;
- one spawned Skeleton with identical composition in both.

Evidence:

`/mnt/d/codex-evidence/host-death-20260726/scaling-baseline-fixed-wave/result.json`

The requested product policy should nevertheless be explicit at the native
spawn seam. Pinning the integer at `arena + 0x8FE4` to one immediately before
every stock wave-spawner tick guarantees the solo HP baseline even if a future
participant rail uses additional stock slots. No wave-data rewrite is needed:
stock spawn count/composition and damage are already independent of this
field. The regression test must compare one participant with two and also
prove that a non-solo value is corrected before spawning.

## Implemented policy seam

`PinEnemyPlayerCountMultiplierToSolo()` writes integer `1` to
`arena + 0x8FE4` immediately before every call to the stock wave-spawner tick.
It runs before either the normal stock tick or the loader's pending
materialization drain, so every stock-created enemy observes the one-player HP
multiplier. The implementation does not alter wave records, enemy damage, or
spawn composition.

Post-change live evidence:

`/mnt/d/codex-evidence/host-death-20260726/scaling-post-fix/result.json`

The verifier deliberately wrote `2` to the stock player-count field before
spawning. Both the one-participant and two-participant runs corrected it to
`1` and produced the same fixture result:

- current/max Skeleton HP: 5000/5000 in both runs;
- observed contact damage: 2.998046875 solo and 2.994140625 with two
  participants, within the 0.01 sampling tolerance;
- one observed Skeleton with identical composition in both runs;
- audio disabled for both launches.

## Final host-death regression

Evidence:

`/mnt/d/codex-evidence/host-death-20260726/post-fix-continuity-7/result.json`

The final standard-harness run repeated the organic host death and observed the
surviving client for 180 seconds with audio disabled:

- host-authority enemy path: 1992.10 units over 180.7 seconds;
- client-clone enemy path: 1978.74 units over 181.2 seconds;
- terminal-minute paths: 498.94 host and 509.88 client;
- client snapshot cadence: 109.92 ms mean and 203 ms maximum;
- 640 post-death damage edges and 304 in the terminal minute;
- 1657 of 1657 post-death target samples selected the surviving client;
- zero app-thread tick gaps, snapshot stalls, enemy-pool catch-ups, manual
  materializations, or shared-simulation holds on either process.

Both peers' early and terminal backbuffers show the dead host spectating and
the stock Skeleton still moving and attacking the survivor. Cleanup stopped
only PIDs 14148 and 24780 after exact staged-executable path matches.
