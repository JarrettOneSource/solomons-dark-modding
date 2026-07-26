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

The black-host audit frame was not caused by a missing color packet. The NFO
observer log and the raw actor probe show the expected nonzero primary and
secondary color blocks had already arrived. The failure is that the remote
death transition did not treat those visual selectors/colors and the corpse
frame as one convergent transaction. A later post-presentation probe showed
the same actor textured again, confirming transient application/transition
ordering rather than a permanently absent asset.

The fix must therefore make authoritative death terminal even after the
presentation window, continue reconciling corpse-safe profile and wearable
visual state while dead, and suppress only the hand-held attachment.

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

### Loading Boneyard's floor starts before a frame can be rendered

The barrier itself did not complete too quickly. The audit barrier lasted
about 4.7 seconds, while `kTransitionPresentationMinimumMs` is 750 ms and
materialization stability is 250 ms.

The 750 ms clock starts before the blocking native scene load. No EndScene
frame can display the loading overlay during that call. By the first
presentable Boneyard frame, the clock has expired and barrier acknowledgements
are ready, so the state can advance to Run before the text renders once.

The spec-consistent fix is to start the minimum-display interval on the first
actual rendered Loading Boneyard overlay frame, not on transition entry.

## Planned foundational change

Treat remote death as a durable replicated presentation epoch:

1. establish it for every authoritative-dead participant, including late
   materialization;
2. reconcile corpse-safe presentation state regardless of packet order;
3. detach the live attachment and create exactly one stock-compatible dropped
   equipment bouncer per death epoch;
4. keep terminal corpse animation and registration state convergent until the
   participant becomes alive again;
5. reassert local dead-owner life after the native progression tick;
6. apply authenticated host life corrections against the recipient's current
   native maximum; and
7. anchor the Loading Boneyard display floor to its first rendered frame.
