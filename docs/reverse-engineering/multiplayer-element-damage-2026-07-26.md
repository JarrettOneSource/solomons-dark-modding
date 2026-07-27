# Multiplayer element damage investigation (2026-07-26)

## Scope

The July suite audit found that stock-wave-enemy HP did not change for Water in
either cast direction and did not change for host-origin Earth. Client-origin
Earth did change authority HP. Fire was intermittent on loopback. In every
cell, the peers agreed on the final raw HP and the visual spell objects were
present on both peers.

This investigation used the audit's exact-PID matrix harness against an
isolated `eldmg` loopback pair on ports `48101` and `48102`. Baseline results
are under:

- `/mnt/d/codex-evidence/element-damage-20260726/baseline/water/result.json`
- `/mnt/d/codex-evidence/element-damage-20260726/baseline/earth/result.json`

They reproduced the audit exactly: Water was `0.0` in both directions, while
Earth was `0.0` host-origin and `3013.3374023438` client-origin.

## Native seams

Fresh read-only Ghidra output is saved at
`/mnt/d/codex-evidence/element-damage-20260726/investigation/ghidra-damage-seams.log`.
It confirms:

- Frost Jet dispatches through `0x00543860`. At `0x00544143` it calls the
  native cone query `0x00641B10` with the caster's `actor+0x18/+0x1C` origin,
  `actor+0x6C` heading, a level-1 range of approximately `205`, and mask
  `0x1082`. Only returned actors proceed to the native damage-context and
  contact path.
- Boulder dispatches through `0x00544C60`. The handler creates type `0x7D5`,
  seeds its position and heading from the caster, and advances the live object
  along that heading. `0x005E5450` is its native release finalizer; the fired
  object subsequently owns collision and radius damage through the stock
  world query `0x00642090`.
- Fireball dispatches through `0x0053DC60`, creates type `0x7D4`, and seeds
  projectile position and flight from the caster heading.
- Enemy HP mutation remains behind `Badguy::Contact` at `0x0048A290`.
  Commit `ceb5732` correctly observes that callback for client-origin native
  damage and serializes the exact HP transition. It cannot serialize a spell
  that never reaches native contact.

## Root cause

The manual-spawner primary-target contract pinned the intended target and
world-space aim at primary startup and around the control-brain update, but
did not pin it at the per-tick spell-dispatch boundary. Stock code can refresh
the local actor's native facing from the OS cursor between those boundaries.
The multiplayer packet capture correctly derived its direction from the pinned
world-space aim, so remote presentation faced the target, while the local
native damage spell continued using the stale cursor-derived `actor+0x6C`.

The live host Water trace proves the split:

- packet aim: `(1800,1800)` from caster `(1624,1800)`, direction `(1,0)`;
- native caster heading at dispatch: `260.695770` instead of east (`90`);
- `0x00641B10` ran 170 times from `(1624,1800)` with that wrong heading;
- `Badguy::Contact` ran zero times and raw HP stayed `5000.0`.

The trace is in
`/mnt/d/codex-evidence/element-damage-20260726/investigation/trace-water-host-r2/result.json`.
Rebinding the caster's spatial cell did not change the zero result, excluding
stale grid membership as the cause.

Earth's directionality is the same split seen from the other side. The remote
replay uses the packet's correct eastward direction. Therefore a client-origin
cast can create an authority-side correctly aimed Boulder, while a host-origin
cast relies on the host's wrongly aimed local native Boulder and the client
observer is forbidden to apply damage. The runtime logs record remote Boulder
heading `90.000008` while the corresponding local queued cast recorded the
stale heading.

Lightning did not expose this defect because `62518de` independently
normalizes Lightning's post-query target handle to the organically aimed live
enemy. Ether is target-seeking. Fireball, Frost Jet, and Boulder remain
heading-owned and therefore share the missing last-boundary pin.

## Fix boundary

The foundational fix is to honor the already-authorized manual-spawner pinned
target immediately around every local spell-dispatch call: apply the pinned
world-space target/facing before stock dispatch, then restore it after stock
returns so packet capture and the next tick observe the same aim. This changes
no damage scalar, query radius, projectile speed, or balance data. It also
leaves normal player input and solo play untouched because the pin API is
active only during explicit manual-spawner scripted-cast grace.

## Post-fix live result and Fire disposition

The dispatcher-boundary fix closed both primary defects:

- Water: host `4.2333984375`, client `4.2084960938`;
- Earth: host `1.541015625`, client `3034.1020507812`.

Air remained `4.2333984375` / `4.18359375` and Ether remained
`1.2001953125` / `1.1000976562`. Every reported value converged exactly on
both peers. Raw results and both-peer screenshots are under
`/mnt/d/codex-evidence/element-damage-20260726/post-fix/`.

The remaining Earth magnitude became issue #52. Its 2026-07-27 follow-up
proved client-only loader inflation: the host's packet-driven replay used an
unrelated `1956` primary-stat normalization constant and applied a second
native contact beside the client's stock claim. The correction leaves stock
damage unchanged and makes the controlled host/client Earth endpoints
bit-identical; see
[`earth-boulder-damage-formula-2026-07-27.md`](earth-boulder-damage-formula-2026-07-27.md).

Fire shares the stale-heading symptom, and the fix removed the host-origin
intermittency: five consecutive host casts each dealt exactly `4.0`. It did
not close the whole Fire defect. The five client-origin casts were
`4.0, 0.0, 0.0, 8.0, 4.0`. Each successful or failed result still converged
exactly on both peers, so the remaining client-only misses occur after correct
aiming and before or within the client native-contact claim path. That residual
is not the Water/Earth last-dispatch-boundary defect and needs a dedicated
Fireball collision/contact investigation. No Fire-specific damage, retry,
fallback, or synthetic application was added here.
