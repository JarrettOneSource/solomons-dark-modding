# Client-initiated Solomon Dig interaction completion

Date: 2026-07-28

Status: implemented, live-proven, and fully validated

## Contract

A machine that begins a native modal interaction owns that interaction through
its native completion boundary. Multiplayer authority may own and replicate the
interaction's world side effects, but it must not destroy the initiating
machine's native interaction owner before that owner has run its paired
completion callback.

For the Solomon Dig encounter this means:

- the initiating player's movement remains locked while the native dialogue is
  open;
- Solomon state 2 performs the stock controller restore on the initiating
  machine;
- the host remains the only wave and enemy authority;
- a host-authoritative client continues suppressing its native wave spawner;
- authority retirement of the local Solomon actor may proceed after the native
  completion boundary, not before it.

This is the ownership rule for client-initiated native interactions whose
completion side effects are authority-mediated. It is not permission to clear
input gates from a timer or to reset controllers globally.

## Owner incident

The owner reproduced the symptom twice as the transport client: the owner
approached Solomon, initiated the encounter while the host did not, and could
not move after wave combat began.

The preserved incident log establishes the transition at session start:

- the owner's last local movement footstep was at `18:49:46.546`;
- at `18:49:52.894`, the active authority snapshot caused the client to queue
  its run/wave lifecycle;
- at `18:49:52.895`, the same snapshot application directly unregistered
  `Solomon_Dig` actor `0x1A106460`, native type `0x1391`;
- at `18:49:52.907`, the client's arena was already at active wave 1.

Those records are lines 535-557 of
`/mnt/d/codex-evidence/hostdeath-20260727/final-read/solomondarkmodloader-post-resume.log`.
They place destruction of the local interaction owner in the wave-start
transition itself.

The later non-invasive capture ruled out the loader's death, pause, barrier,
collision, registration, speed, and movement-block gates. It also observed
zeroes in the public cast/primary flag bytes. That capture did not hold a
movement key and did not inspect the native controller's current/saved pair, so
it could not identify this earlier incomplete transaction.

The flag bytes are not themselves proof that the transaction completed.
Native `Chat` destruction at `0x004FCB40` and other native UI paths can write
the bytes directly. The controller restore and callback are edge-triggered
inside `0x005C7300`; a later byte value of zero does not prove that callback
ran. The invariant in this design is the paired native completion call, not a
permanently asserted flag.

## Native interaction owner

`Solomon_Dig` is native type `0x1391` (factory id 5009), constructed at
`0x00481C20`. Its main tick/dispatcher is `0x0048A8B0`.

Recovered interaction fields are:

| Actor field | Meaning |
| --- | --- |
| `+0x220` | Solomon interaction state |
| `+0x2A0` | a gameplay participant has been acquired |
| `+0x2A4` | selected gameplay slot |

The state dispatcher is:

| State | Native body | Role |
| ---: | --- | --- |
| 0 | `0x00481FC0` | idle/proximity acquisition |
| 1 | `0x0047D0F0` | face the selected participant and queue narration |
| 2 | `0x0047D450` | wait for dialogue completion, then release controls |
| 3 | `0x0047D570` | combat prelude and retreat setup |
| 4 | `0x004857B0` | retreat movement |

While state is below 3, `0x0048A8B0` scans the four gameplay slots. A nearby
slot is recorded at `+0x2A4` and acquisition is recorded at `+0x2A0`.

Only slot 0 is local to the current process. When the nearby participant is
slot 0 and the local dialog gate is not already asserted, the dispatcher:

1. dispatches arena action mode `0x0E` through `0x0068B6D0`;
2. calls `0x005C7300(gameplay, 1, 0)`;
3. calls `0x005C7390(gameplay, 1, 0)`;
4. records the local Solomon interaction target.

A remote gameplay slot can advance that machine's Solomon rail, but it does
not enter the slot-0-only local dialog lock branch. This distinction explains
why the non-initiating host remains movable when client B initiates.

## Exact lock and normal unlock

`0x005C7300` owns the dialog-side local controller transaction:

- it asserts `gameplay + 0x1ABD`;
- it replaces the current controller value at `gameplay + 0xF0` with zero;
- it invokes the controller callback reached through the object at
  `gameplay + 0x8C`;
- it zeroes the associated vector at `gameplay + 0x108/+0x10C`.

Its normal release call is `0x005C7300(gameplay, 0, 0)`. That call:

- clears `gameplay + 0x1ABD`;
- restores `gameplay + 0xF0` from the saved value at `gameplay + 0x224`;
- invokes the same controller callback so native input consumption resumes.

`0x005C7390` performs the analogous primary-control transaction:

- block byte `gameplay + 0x1ABE`;
- current/saved pair `gameplay + 0x1BC/+0x228`;
- vector `gameplay + 0x1D4/+0x1D8`;
- callback owner at `gameplay + 0x158`.

Solomon state 2 is the owner of the paired completion. Once the native
dialogue pointer at `0x008199FC` is null and the queued-line count at
`0x00819A1C` is zero, `0x0047D450` runs, in order:

1. `0x005C7300(gameplay, 0, 0)`;
2. `0x005C7390(gameplay, 0, 0)`;
3. `arena + 0x902A = 1`;
4. `Solomon + 0x220 = 3`.

The state write comes after both restores. Therefore state 3 is the first
retirement-safe interaction state.

The downstream state-3 rail starts the combat prelude and state 4 drives
Solomon's retreat. `ArenaStartWaves` at `0x00465C00` owns the actual wave
counter/active transition. It releases the primary transaction through
`0x005C7390(gameplay, 0, 0)`, but it does not call the dialog-side
`0x005C7300(gameplay, 0, 0)`. Wave activation cannot substitute for Solomon
state 2's completion.

## Multiplayer failure

The host remains the world, wave, and enemy authority. On a connected client,
`ShouldSuppressClientAuthoritativeRunWaveSpawner` and
`HookWaveSpawnerTick` intentionally suppress the client's stock wave spawner
while a fresh host Run snapshot exists. This design does not change that rule.

When client B initiates the native encounter:

1. client B's local `Solomon_Dig` selects gameplay slot 0, asserts the native
   modal, and owns the pending state-2 completion;
2. the host's corresponding Solomon rail sees client B in a nonzero gameplay
   slot, so it does not assert the host's local dialog controller;
3. the host advances the encounter, starts the authoritative wave, and no
   longer includes Solomon in its authoritative run-static set;
4. client B applies that snapshot;
5. generic extra-run-actor cleanup calls `RemoveReplicatedRunActor`;
6. that function directly invokes `CallActorWorldUnregisterSafe` on client B's
   local Solomon actor;
7. the destroyed actor can no longer tick state 2, so
   `0x005C7300(gameplay, 0, 0)` never restores the initiating client's saved
   controller or invokes its callback.

The error is at the ownership boundary between authority reconciliation and a
locally owned native modal. Wave authority is correct. Client wave-spawner
suppression is correct. Directly retiring the local completion owner is not.

## Pre-fix reproduction

The required reproduction ran from untouched main
`6ff6b439c2777ef60a8f5e3743ef08cec75d04fb` in two isolated staged instances
on ports `50211/50212`, with `SDMOD_DISABLE_AUDIO=1`.

The harness used the real proximity path:

- it did not call `sd.gameplay.start_waves()`;
- it moved client B to the live `0x1391` actor;
- stock `0x0048A8B0` acquired client B and called the native lock;
- a temporary client-process-only instruction restored immediately after the
  race delayed the body of Solomon state 2 while all loader, transport, and
  authority snapshot ticks continued.

The delay makes the owner's dialogue-duration race deterministic without
inventing an input lock or changing product files. The interaction acquisition,
lock calls, host side effect, snapshot removal, and post-removal movement path
are all the real paths.

Observed before authority retirement:

- `Solomon + 0x2A0 = 1`;
- `Solomon + 0x2A4 = 0`;
- state reached 2;
- `gameplay + 0x1ABD = 1`;
- current dialog controller `gameplay + 0xF0 = 0`;
- saved dialog controller `gameplay + 0x224 = 20`;
- movement attempted while the modal was open displaced client B by exactly
  zero, as required.

The host independently reached Solomon state 4 with target slot 1, kept its
local dialog gate open (block byte zero), and started wave 1. The client
received and rendered the authority wave, then its Solomon actor disappeared
through snapshot cleanup.

The `0x005C7300` trace contained exactly one call:

- lock arguments `(1, 0)`;
- no release call `(0, 0)`.

After restoring the untouched state-2 instruction, the actor was already gone.
Client B still had current/saved dialog controller values `0/20`. A 240-frame
movement drive completed at the injection surface but produced:

- peak native movement vector `0.0`;
- real displacement `0.0`.

The result is
`/mnt/d/codex-evidence/digfix-20260727/baseline-repro.json`; its compact result
is `baseline-repro-summary.json`, with paired host/client logs.

## Control cases

The non-initiating host is not locked by client B's interaction because the
host selected remote slot 1 and never entered the slot-0 local lock branch.
This was visible in the pre-fix reproduction: its local dialog block remained
zero and its current/saved dialog controller pair remained `20/20`.

When the host initiates, it selects its own slot 0, but authority snapshot
application does not retire the host's local run-static actor. The stock
state-2 completion remains present and restores the host normally. Client B is
the non-initiating machine in that control and must not acquire local
completion ownership.

An unmodified same-dialogue-branch client control and a divergent five-line
client dialogue control both completed normally when state 2 ran before
authority retirement. Each trace contained the paired lock and unlock, and
post-dialog movement reached a nonzero native vector and real displacement.
Those controls are preserved beside the baseline reproduction.

## Foundational repair

World-snapshot reconciliation will recognize a pending locally owned native
interaction completion before directly unregistering an unmatched run actor.

For `Solomon_Dig`, completion is pending only when all recovered facts hold:

- native type is `0x1391`;
- `+0x2A0` says a participant was acquired;
- `+0x2A4` selects local gameplay slot 0;
- `+0x220` is a valid state below 3.

The predicate deliberately does not use the public gate bytes. They can be
rewritten independently and are not the transaction owner.

While the predicate is true, authority reconciliation records the actor as
unmatched but defers destructive retirement. Native dialogue remains modal and
stock state 2 remains the only code that releases it. When dialogue completes,
the same native tick invokes both real restore callbacks and then advances to
state 3. The next authority snapshot may retire the now-safe actor normally.

The implementation will not:

- call either native unlock function from reconciliation;
- write controller values, movement vectors, or gate bytes;
- use a timer or force-clear fallback;
- preserve a client wave spawner;
- move wave authority off the host;
- ignore all run-static retirement;
- special-case only the observed process address.

Future authority-mediated native interactions can extend the same ownership
predicate with their own recovered completion boundary. The reconciliation
rule remains generic: authority cannot destroy a local native transaction
owner before that transaction reaches its proven completion state.

## Implementation

The recovered fields are layout-backed as
`solomon_dig_interaction_state`,
`solomon_dig_participant_acquired`, and
`solomon_dig_target_gameplay_slot`.

`IsLocalNativeInteractionCompletionPending` reads those fields only for native
type `0x1391`. Snapshot reconciliation calls it immediately before generic Run
actor retirement. A true result records the unmatched binding and defers that
one destructive operation. The predicate becomes false after the stock state-2
body runs both controller restores and writes state 3, so the next snapshot
uses the existing retirement path.

The implementation does not inspect or write a gameplay gate, invoke an unlock
function, introduce a timer, change wave ownership, or change client wave
spawner suppression.

## Post-fix live proof

The dedicated verifier ran three fresh two-instance pairs from the patched
Release build on ports `50211/50212`, with audio disabled. The initial green
record is `/mnt/d/codex-evidence/digfix-20260727/postfix-live.json`. The same
three scenarios were rerun after the Release build and full source integration
on commit `986d0c6`; the final record is
`/mnt/d/codex-evidence/digfix-20260727/postfix-live-final-sha.json`. Both
report `ok=true`.

Lua bot polish then landed on main. The branch was rebased onto
`d52a4ee8669f3b7e5813a03aa90f1b9ad38cd6d3`, and the integrated implementation
commit `96e7282` was rebuilt and run through the full battery again. Its fresh
three-pair record is
`/mnt/d/codex-evidence/digfix-20260727/postfix-live-integrated-main-d52a4ee.json`
and also reports `ok=true`.

In the client-B real-NPC case:

- 90 applied movement-intent frames while the modal was open produced native
  vector `0.0` and displacement `0.0`;
- the host moved 228 units during client B's modal, with a peak native vector
  of `0.9`;
- host wave 1 replicated to client B while client B's original Solomon owner
  remained locally acquired in state 2;
- after another second of authority snapshots, the same owner was still
  present and its dialog controller remained current/saved `0/20`;
- the native dialog-gate trace contained one lock and no unlock before release,
  then one lock and one unlock after release;
- client B's controller restored to current/saved `20/20`, the dialog block
  cleared, and the Solomon actor retired only after that completion;
- 180 applied post-completion intent frames reached a peak native vector of
  `0.9` and produced 170 units of real displacement;
- the host remained movable after completion as well.

In the host real-NPC control, the modal still suppressed host movement, the
native trace contained the paired lock/unlock, authority wave 1 replicated,
and both machines produced nonzero native vectors and real displacement after
completion.

In the Lua `start_waves` regression, authority wave 1 replicated without
either machine acquiring a dialog block. Both machines produced a peak native
vector of `0.9` and real displacement.

Every pair cleanup record matched the exact staged executable path and stopped
only its launcher-returned host and client-B PIDs.

## Verification

Static contracts cover the layout-backed Solomon state/acquisition/target
offsets, the local-slot and pre-state-3 predicate, and its placement before
`RemoveReplicatedRunActor`. They reject direct unlock calls, controller writes,
and time-based release logic in the reconciliation seam.

The completed two-instance verifier covers:

1. client B initiates through the real Solomon proximity path, with a
   deterministic state-2 delay:
   - movement remains locked while the modal is pending;
   - host movement remains functional;
   - the host starts waves and the client receives them;
   - reconciliation retains the client-B Solomon completion owner;
   - after the delay is released, the trace contains the exact stock unlock;
   - the actor then retires;
   - injected intent reaches a nonzero native vector and real displacement;
2. the host initiates through the real NPC path:
   - the host's stock unlock runs;
   - both machines remain movable;
   - waves remain host-authored and replicated;
3. the ordinary Lua `start_waves` path:
   - its wave behavior is unchanged;
   - neither machine acquires a stranded interaction controller.

All game launches use disabled audio, the isolated `digfix` instance group, and
ports `50211/50212`. Cleanup is limited to launcher-returned PIDs whose staged
executable paths match the isolated worktree.

The completed full battery is:

- source organization: `626 / 626`;
- `Build-All.ps1 -Configuration Release`: zero warnings and zero errors;
- `Verify-Workspace.ps1 -Configuration Release` against the specified retail
  game directory: passed;
- Python unit discovery: `406 / 406`;
- static reverse-engineering contracts: `289 / 289`;
- Windows launcher contracts: `45 / 45`;
- final dedicated two-instance verifier: all three scenarios passed.
