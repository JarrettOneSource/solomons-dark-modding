# Host-character-death enemy continuity

Date: 2026-07-28

Status: implemented and verified locally

## Contract

The process that started the run remains the enemy authority after its local
player character dies. Its wave spawner, enemy AI, damage resolution, and
replication must continue for every supported enemy class. A transport client
continues to render replicated enemy state and must not begin simulating bound
replicated enemies.

This deliberately excludes both authority handoff on character death and a
client-side simulation fallback.

## Pre-fix reproduction and instrumentation

The reproduction used two isolated local instances from commit
`877339586b2659698ec7c79dae8d989c02150a47`, ports `49911` and `49912`, and the
retail `GAME/data/wave.txt` schedule. The host character died during the active
wave through the queued retail `PlayerActor` native magic-hit handler. The
surviving player is called `client B` in committed material.

The first control run wrote a negative HP value directly. It did not enter the
native death-presentation lane and post-write enemies moved, so that run is not
accepted as a reproduction.

The faithful run entered host `DeathPresentation`, then spectator continuity,
while the authority id remained the host participant. Temporary authority-side
instrumentation recorded:

- each successful post-spawn return;
- target actor, ActorWorld group and slot, pending-initialize state, chase
  interval, and the actor fields consulted by the stock chase path;
- the first `Badguy_CommonChaseTick` and its cadence;
- entry to the generated-vector zero guard at `0x00473160`;
- the first `Badguy_MoveStep`;
- authoritative position at spawn, at at least `+100 ms`, and at at least
  `+500 ms`.

Three enemies spawned after native host-character death:

| Authority actor | ActorWorld slot | Spawn to first common chase | Common-chase calls by +500 ms | Generated-vector entries | Move-step entries | +500 ms displacement |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `0x113A62C8` | 19 | 1-16 ms | 49 | 0 | 0 | 0 |
| `0x113DD9C0` | 20 | 1-16 ms | 49 | 0 | 0 | 0 |
| `0x1153BD70` | 21 | 1-16 ms | 49 | 0 | 0 | 0 |

All three returned from spawn with pending initialization set, no target, and
bucket `-1`. Within 1-16 ms they completed initialization and the loader's
post-retail nearest-target extension selected `client B` in ActorWorld group
`1`, bucket delta `2048`. The first common-chase hook then observed the target
and normal tick cadence, but all three retained byte value `1` at
`actor + 0x68`. Every pre-death enemy sampled in the same run had
`actor + 0x68 == 0` and reached the generated-vector lane. The generated-vector
trace contained 256 calls from other live enemies (182 nonzero and 74 zero),
but no call whose actor was one of the three post-death actors.

The complete pre-fix result is
`/mnt/d/codex-evidence/hostfix-20260727/before-native-death-retail-wave.json`;
the paired loader logs preserve the post-spawn, chase, and sampling records.

## Exact first missing boundary

The first missing boundary is inside stock
`Badguy_CommonChaseTick (0x004835F0)`, before native movement-vector generation.
The tick is not absent: `Skeleton_Tick (0x00484B90)` continues calling it.
Target selection is not absent: the actors target the surviving client
character. ActorWorld insertion is also observable: the actors have group `0`
and valid slots `19` through `21`.

`Badguy_CommonChaseTick` checks `actor + 0x68` before the chase-vector lane.
While that byte is nonzero, ordinary ticks return immediately. Its periodic
refresh tick calls `MonsterPathfinding_SelectNearestTarget (0x00481A60)` and
then also returns. Therefore a stuck value of `1` permits retargeting but
prevents:

1. the virtual desired-direction calls;
2. the generated-vector zero guard at `0x00473160`;
3. `Badguy_MoveStep (0x00475FE0)`;
4. authoritative coordinate advancement and its replicated client view.

The exact writer/order explains why only the widened multiplayer target lane
fails. `MonsterPathfinding_SelectNearestTarget` writes `1` to `actor + 0x68`
before scanning. Retail commits only a group-zero candidate: it relocates the
hostile through `ActorWorld_RelocateHostileToGroupZero (0x0063F7A0)`, whose
registration tail clears `actor + 0x68`. After the host dies, retail rejects
the dead group-zero host and does not commit `client B` because that
participant is in group `1`. The loader correctly writes `client B` and bucket
delta `2048` after retail returns, but it does not complete the selector's
success contract by clearing the selector-pending byte. The next common-chase
tick therefore returns at the first branch above.

No new ActorWorld registration is missing: the enemy already has world, group,
and slot ownership. The missing operation is completion of a successful
extended target selection. The repair must complete that invariant for any
authority-owned hostile that receives a valid extended target, independent of
enemy class and without weakening the stock chase guard globally.

## Repair

The production change repairs the authority-side target-selection completion
boundary, not the client tick suppression and not an individual skeleton tick:

- after a validated extended authority target and bucket are successfully
  written, clear
  the stock selector-pending byte just as retail's successful group-zero
  selection does through its registration tail;
- do not clear the byte when selection fails or yields no target;
- apply the completion in the shared target-selection owner used by every
  hostile class and every authority maintenance path;
- preserve stock behavior for pending/unregistered actors and for transport
  clients;
- retain host authority, native AI, native damage, and ordinary replication.

`ApplyHostileTargetSelection` is the shared commit owner. It releases
`kActorRegisterTransientOffset` only after the target actor and bucket-delta
writes succeed. `ApplyNearestValidHostileTarget` selects and delegates to that
commit owner. The offset is declared, stored, and loaded through the ordinary
binary-layout seam. Native selector extension, invalid-target recovery, and
nearest-target maintenance therefore retain one completion contract for every
authority-owned hostile class without a spawn-path or skeleton special case.

The temporary diagnostics used to locate the boundary were removed from the
shipping source.

## Instrumented post-fix boundary confirmation

The same two-instance native-death reproduction was rebuilt with the repaired
boundary. Two enemies born after host-character death cleared both pending
initialization and `actor + 0x68`, entered native vector generation, and
reached `Badguy_MoveStep` within 47-70 ms of their first common-chase tick.
Their authoritative displacement at `+500 ms` was `35.90654` and `33.05825`
units, compared with exactly zero for every post-death actor in the pre-fix
capture.

The result is preserved in
`/mnt/d/codex-evidence/hostfix-20260727/after-boundary-death-retail-wave.json`
with its paired logs and screenshots.

## Organic acceptance

`tools/verify_multiplayer_host_death_continuity.py` runs the full retail wave
schedule. It kills the host character through the native damage lane during a wave,
without enemy isolation, forced target, forced arena, scripted teleport, or
client-side enemy simulation. It takes a live-enemy census only after the host
has reached HP zero, `DeathPresentation`, and `in-boneyard`; only an enemy
absent from that conservative death-boundary census can satisfy the
post-death-spawn assertion.

The passing run used the unmodified retail schedule
SHA-256 `363a985d79dc3ca28fb5ce519f56c436f5269a9bea1bedc7d1a825e8139499fc`
and observed:

- a post-death actor with pending-initialize `0`, selector-pending `0`, and a
  nonzero target on its first boundary sample;
- `542.1924` units of maximum authoritative displacement;
- `547.5632` units of maximum displacement in `client B`'s replicated view;
- a `1.0` target-success ratio for `client B`;
- `1,308` post-death native damage edges;
- `449` native damage edges during the terminal minute, covering all three
  twenty-second segments;
- `1,497 / 1,497` tracked client samples bound to the authority replica and
  zero simulation-eligible unbound samples.

The host and client samples each recorded zero barrier restarts, shared pauses,
teardown state, Game Over arming, authority changes, and wrong-session-state
samples. The preserved logs recorded zero canonical session teardowns, client
enemy-pool catch-up events, snapshot stalls, or host manual-spawn requests.
Static contracts continue to require bound client replicas to return before
stock `Badguy_MoveStep` and clients to suppress the authoritative wave spawner.

The four native-scale screenshots were inspected directly. Both host frames
show spectator mode following `client B`; both client frames show the dead
host character. The early and terminal views on both processes visibly show
the active skeleton pack converged on and striking `client B`.

The passing output is
`/mnt/d/codex-evidence/hostfix-20260727/acceptance.json`; its compact metrics
are in `acceptance-summary.json`, and the paired loader logs and four
backbuffer captures are under `acceptance/`.

## Movement-input finding

The same acceptance run held a real injected `D` key on `client B` across the
host-death transition. The native gameplay input pair is the input-intent
witness; the participant snapshot's movement-intent field is downstream
replication state and is not the local input source. The run recorded:

- input-intent magnitude `1.0` before and after host death;
- native actor movement-vector magnitude `0.9` before and after host death;
- `276.0004` units of client-character displacement while input was held.

The reported cannot-move symptom did not reproduce with real input. No
movement behavior was changed and no speculative movement patch was added.
The held-input chain remains regression coverage.

Existing death, enemy-authority, replication, and movement verifiers remain
required; this organic run complements rather than replaces them.

## Final validation

The completed source state passed:

- source organization: `624 / 624`;
- `Build-All.ps1 -Configuration Release`: zero warnings and zero errors;
- `Verify-Workspace.ps1 -Configuration Release` against the retail game:
  passed;
- Python unit discovery: `401 / 401`;
- static reverse-engineering contracts: `288 / 288`;
- Windows launcher contracts: `44 / 44`;
- the organic two-instance host-death continuity run described above.

The full transcripts, acceptance result, native-scale screenshots, and SHA-256
manifest are preserved under
`/mnt/d/codex-evidence/hostfix-20260727/`.
