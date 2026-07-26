# WAN death and corpse rendering investigation

Date: 2026-07-26

## Scope and evidence

This investigation covers the two-machine Home PC to NFO GE-Proton lifecycle
acceptance from the July 2026 suite audit. The peers were separated by
26-28 ms RTT. The same lifecycle passed on loopback.

Primary evidence:

- `/mnt/d/codex-evidence/suite-audit-20260725/lifecycle-summary.json`
- `/mnt/d/codex-evidence/suite-audit-20260725/live-wan/lifecycle/host/result-final.json`
- `/mnt/d/codex-evidence/suite-audit-20260725/live-wan/lifecycle/client/result-final.json`
- `/mnt/d/codex-evidence/suite-audit-20260725/visual-review/lifecycle-contact-sheet.png`
- `/mnt/d/codex-evidence/suite-audit-20260725/visual-review/loading-boneyard-contact-sheet.png`
- `/mnt/d/codex-evidence/corpse-render-20260726/baseline/wan-host-r2/result-final.json`
- `/mnt/d/codex-evidence/corpse-render-20260726/investigation/direct-client-death-terminal/raw-hp-runtime-tick-probe.json`

## Root causes

### Remote corpse presentation is not an ordering-safe transaction

`ApplyNativeRemoteParticipantDeathPresentationState` only opens a remote
death epoch while the five-second `DeathPresentation` flag is still active.
If a native clone materializes, rematerializes, or first becomes writable
after that flag clears, the function explicitly clears terminal dispatch and
returns without ever driving the actor to its terminal corpse frame. That
produces the absent-corpse case.

The dead branch also runs before normal remote presentation reconciliation.
Once authoritative life reaches zero, late profile/equipment presentation
state can be present in the participant snapshot but never applied to the
corpse actor. WAN timing exposes this because actor materialization, visual
runtime construction, equipment snapshots, and the lethal snapshot can be
observed in different orders. Loopback normally finishes presentation
reconciliation first.

The black-host audit frame was not caused by a missing color packet or texture
upload. The NFO observer log and raw actor probes show the expected nonzero
primary and secondary color blocks, live visual objects, corpse selectors, and
terminal frame. A fixed-build client-death run reproduced the black corpse
after all of those states had converged. Moving the surviving observer close
to the corpse made the same actor immediately textured without changing its
visual objects or packet state; moving away made it black again.

The native render scalar at `actor + 0xCC` explains that distance-dependent
change. `FUN_00624B40` clears the scalar, queries the region light grid through
`FUN_0057E490`, then multiplies the actor render by the result. The remote
corpse read `0.0` while black and `1.0` when covered by the nearby survivor's
light.

The missing light is a specific stock branch, not a general region-grid or
asset failure:

- PlayerActor's light-submit vfunc is `FUN_005299A0` at `0x005299A0`.
- It submits the normal player light only when the animation-drive state at
  `actor + 0x160` is zero **or** the actor slot at `actor + 0x5C` is zero.
- A local dead owner has slot `0` and death drive `1`, so its corpse retains
  its normal light.
- A living remote clone has a nonzero slot and drive `0`, so it is also lit.
- A replicated remote corpse has both a nonzero slot and death drive `1`.
  That is the sole combination which skips the stock player light.

Live region-light records confirm the branch. The dying machine retained two
lights: the local corpse and the remote survivor. The observer retained only
the local survivor's light. The local corpse record also proves the exact
stock anchor follows actor heading at a 15-unit offset, with radius `2.6`,
intensity `1.0`, and flag `1`; this is the record produced by
`FUN_005299A0`, not a replacement light invented by the multiplayer layer.

WAN timing made this look like texture/order corruption because the remote
corpse remains temporarily illuminated by nearby participants and by the
camera positions used during the death transition. At the separated terminal
evidence positions, its own light is suppressed and the otherwise-correct
texture is multiplied by zero. The client corpse reported as absent is the
same failure at a darker background/position, compounded by the separate late
death-epoch materialization defect.

The first implementation detoured `FUN_005299A0` and temporarily presented a
committed remote corpse as slot zero when stock called that function. A
separated client-death rerun disproved the assumption that the detour alone
covered corpse persistence: the terminal frame was correct while the survivor
was nearby, but after restoring the survivor to 500 units away the remote
corpse again read `actor + 0xCC == 0.0`.

The missed call is deterministic. The tracked remote-death branches in
`HookPlayerActorTick` quiesce the binding and return without calling the stock
PlayerActor tick. The local dead owner is not a tracked remote binding and
continues through stock. `FUN_005299A0` is reached through that stock update
path, so a detour cannot restore a call which no longer occurs. Nearby
survivor light temporarily masked this gap in terminal captures.

The second implementation explicitly called the stock PlayerActor
light-submit method from the local-player scene-binding tick. A fresh,
separated WAN host-death run disproved that timing as well: the terminal
capture was correct while the survivor was nearby, but the persistent remote
corpse again read `actor + 0xCC == 0.0` and rendered black after the survivor
returned 500 units away.

`Arena::Render` at `FUN_0046EC80` establishes the actual per-frame ordering.
It calls `FUN_0057D4E0` first, which resets the frame's native light
collection; then it calls vtable slot `+0x30` on the arena light-source actor
list and submits miscellaneous lights; finally it makes the sole executable
call to `FUN_0057D5E0` before rendering the world objects which consume the
light grid. A scene-tick submission happens before `Arena::Render` and is
therefore discarded by the next `FUN_0057D4E0` reset. This is why calling the
right stock method at the wrong frame boundary did not survive to
`FUN_00624B40`.

The foundational renderer fix must preserve the real nonzero gameplay slot
and submit each committed remote corpse through its stock PlayerActor method
after the arena's per-frame light reset and before its one light-collection
finalize call. `FUN_0057D5E0` has exactly one caller, at `0x0046EE6C` in
`Arena::Render`, so a pre-finalize detour is the narrow native seam. The call
temporarily presents only the corpse's stock light method as slot zero,
taking the exact local-corpse branch and native anchor/parameters before
restoring the real slot. It does not force fullbright, write `actor + 0xCC`,
create a parallel light, depend on a suppressed remote PlayerActor tick, or
submit state that the arena immediately clears.
The death transaction must also remain terminal after the presentation
window, continue reconciling corpse-safe profile and wearable visual state
while dead, and suppress only the hand-held attachment.

The first fixed-build WAN host-death pass exposed one additional ordering
constraint before implementation was finalized. The NFO observer's first
lifecycle sample had already received zero replicated life while the Home
owner's native HP was still `0.10100000351667`. At that point the replicated
death-presentation tick and flag were both zero. Opening the durable death
epoch from life alone therefore drove the observer directly to terminal tick
150 about 0.9 seconds before the owner entered native death presentation.

Replicated zero life is not, by itself, the commit record for the visual
transaction: the damage-correction path can publish it before the owner's
native death handoff. The durable commit record already exists in the
presentation transaction. During active presentation the flag is set; after
the five-second window, `CurrentLocalDeathPresentationTick` continues
publishing the nonzero terminal-safe tick while spectating. Remote playback
must open a new epoch only after seeing the active flag or a nonzero
authoritative presentation tick, then keep that epoch alive from terminal
life until respawn. This still supports late materialization without allowing
an early life correction to start the corpse animation.

### Remote deaths detach the staff but never create the stock drop

The current remote death seam calls
`ReconcileNativeRemoteParticipantEquipmentLane(... attachment ..., 0)` and
stops there. It never creates the stock animation-bouncer used by native
player death, so a remote observer cannot render a dropped staff.

Ghidra analysis of `FUN_00534120` at `0x00534120` identifies the stock,
observer-safe sub-transaction:

- animation-bouncer constructor `0x00453060`
- staff/wand bouncer vtables `0x00793c4c` / `0x00793c74`
- staff/wand visual resolvers `0x004608d0` / `0x00460920`
- position and launch velocity copied from the dying actor
- insertion through the world animation-object lane at `world + 0x2c4`

Calling all of `FUN_00534120` is incorrect for a remote clone because it also
contains local participant removal and Game Over authority side effects. The
fix should reproduce only the one-shot bouncer creation at the remote death
epoch seam.

### The positive raw-HP sentinel is a real write-order defect

This is not IEEE-754 display noise. A 240-tick raw probe on the dead owner
measured a repeated `0.001` through `0.008` sawtooth with 39 reset edges and
no exact-zero samples.

`HoldLocalSpectatorDeathVitals` writes zero from the multiplayer service tick.
The first attempted correction reasserted zero after `PlayerActorTick`
(`FUN_00548B00`), but a fixed-build WAN raw probe still read `0.001`. Ghidra
then isolated the actual later writer: the progression object's independent
virtual tick `FUN_006614D0` adds
`DAT_007DE860 / DAT_00820230` to progression HP whenever
`progression + 0x8DE` (Regenerate active) is nonzero. Its vtable entry is
`0x007A0CDC`; it is not part of `PlayerActorTick`, so the earlier hook was on
the wrong side of the mutation.

That separate progression tick creates the small positive value until the
next multiplayer service write. This makes the strict owner-side zero-duration
gate timing-dependent even though peers correctly observe zero. The fix is to
reassert dead-owner vitals immediately after the local player's progression
tick, at the proven native mutation boundary.

A second WAN-only ordering defect was found in the client-death path. Host
corrections carried the host's earlier `life_max=5000` observation after the
test owner had locally changed its maximum to 50. The client rejected the
authenticated lethal correction because packet and native maximum differed
by more than ten percent. Life authority and local maximum ownership were
incorrectly coupled. The host correction should own current life; the
recipient's current native maximum remains the write maximum and clamp.

### Loading Boneyard was disabled by the WAN audit launch contract

The barrier did not complete too quickly. The audit's archived client barrier
ran for about 4.75 seconds. A fresh same-process WAN cycle in this
investigation ran for 5.15 seconds on Home and 5.18 seconds on NFO. Both are
far longer than the existing 750 ms `kTransitionPresentationMinimumMs` floor
and the 250 ms materialization-stability interval.

The missing title is instead deterministic from the launch configuration. Both
WAN wrappers explicitly set `SDMOD_MULTIPLAYER_QUICK_START` and its three
companion variables to the empty string. `InitializeMultiplayerJoinFlow`
returns `false` when that variable is disabled.
`GetMultiplayerJoinFlowPresentation` therefore always returns an invisible
presentation, including while the independent transport run-loading barrier
is active. Neither archived audit log contains
`Multiplayer join flow enabled`, a phase transition, or a first-render marker.
The repeated Home and NFO frame bursts contain the native fade-to-black
interval but no loader title, exactly as that disabled state requires.

The repository's focused lifecycle verifier launches with `quick_start=True`;
that is the supported contract which enables the join-flow cover and its
minimum-display floor. The WAN suite's manually driven wrapper deliberately
disabled the same facility while retaining the verifier's visual assertion.
This is an acceptance-harness mode mismatch, not a latency regression in the
barrier. Production code is left unchanged for this secondary finding.

## Planned foundational change

Treat remote death as a durable replicated presentation epoch:

1. establish it for every authoritative-dead participant after the
   presentation transaction is committed by its flag or nonzero tick,
   including late materialization;
2. reconcile corpse-safe presentation state regardless of packet order;
3. detach the live attachment and create exactly one stock-compatible dropped
   equipment bouncer per death epoch;
4. keep terminal corpse animation and registration state convergent until the
   participant becomes alive again;
5. reassert local dead-owner life after the native progression tick;
6. apply authenticated host life corrections against the recipient's current
   native maximum; and
7. submit committed remote corpse lights at the arena's native pre-finalize
   frame seam through the stock slot-zero PlayerActor method while restoring
   their real slot before returning.
