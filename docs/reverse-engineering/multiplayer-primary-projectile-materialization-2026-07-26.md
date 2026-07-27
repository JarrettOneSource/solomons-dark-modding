# Multiplayer primary-projectile materialization (2026-07-26)

## Scope

Live beta.18 WAN testing reported that a client-owned Earth Boulder dealt its
authoritative damage but never appeared on the host. Fireball remained visible
in the same ownership direction. The damage claim path is outside this
investigation; the unexplained client-Earth `3032.56` damage component remains
parked as issue #52.

This note records the remote visual lifecycle before changing it. Static
evidence came from the beta.18 executable and the multiplayer spell-effect
transport. Focused loopback evidence used only the `sfx` instances on UDP
ports `48611/48612`, with `audioDisabled=true` and exact staged-executable PID
cleanup.

## Native creator paths

The three stock primary projectile classes do not share one runtime layout:

| Type | Stock class | Dispatcher | Constructor | Tick | Draw |
| ---: | --- | ---: | ---: | ---: | ---: |
| `0x7D3` | MagicMissile | `0x0053CFE0` | `0x005E4990` | `0x005FD270` | `0x005E0460` |
| `0x7D4` | Fireball | `0x0053DC60` | `0x005E0970` | `0x005FDD90` | `0x006099C0` |
| `0x7D5` | Boulder | `0x00544C60` | `0x005FA270` | `0x00609D30` | `0x0060AC40` |

Fireball is a one-shot projectile. Its dispatcher creates and registers a new
`0x7D4` actor, seeds velocity at `+0x13C/+0x140`, and leaves that actor to own
flight and contact.

Boulder uses a persistent caster-owned handle instead. Its dispatcher creates
`0x7D5` only while `actor+0x27C` is the `0xFF` sentinel, registers the object,
then stores its world group/slot at caster `+0x27C/+0x27E`. Later dispatch
ticks resolve that same object and move/grow it until release. Boulder also
owns recursive rock collections beginning at `+0x13C`; those bytes are not
Fireball velocity. The `actor+0x5C == 0` retail creation gate is already
covered for gameplay-slot participants by the validated native cast-gate
patch at `0x00544C92`. Charge state therefore does not explain a source-side
Boulder that already dealt claim-backed damage.

Fresh decompilation for these paths is:

- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/ghidra-boulder-fireball-seams.log`

## Beta.18 remote materialization seam

The owner process enumerates scene actors in
`multiplayer_local_transport/spell_effect_sync.inl`.
`IsReplicatedSpellEffectNativeType` admits all three primary projectile types,
and `TryCaptureLocalSpellEffectState` assigns each source actor a stable
`effect_serial`. The resulting `SpellEffectSnapshot` is an unreliable visual
checkpoint, independent of the reliable cast-input stream and independent of
the damage-claim stream.

On the observer, `spell_effect_reconciliation.inl` first tries to bind that
serial to an actor already created by replicated stock casting. It classifies
`0x7D3`, `0x7D4`, and `0x7D5` as
`IsNativeReplayDrivenPrimarySpellEffect`, so snapshots deliberately do not
overwrite their native motion or collision lifecycle.

The catch-up materializer in `spell_effect_materialization.inl` does **not**
cover the same class:

- `TryCreateReplicatedSpellEffect` accepts only Ember `0x7D6` and Firewalker
  trail `0x7EE`;
- `ShouldMaterializeMissingReplicatedSpellEffect` requires the Ember or
  Firewalker type-specific runtime payload;
- a missing `0x7D3`, `0x7D4`, or `0x7D5` is consequently ignored on every
  snapshot for the lifetime of that serial.

This is the skipped seam. Primary projectile presentation has only one
materialization path: the observer must successfully replay the stock cast.
The snapshots advertise primary actors but cannot repair a missed or failed
native replay. Damage can still converge because client-native contact is
serialized through the separate claim path.

Fireball appearing in beta.18 does not provide a second path. It proves that
Fireball's native replay happened to create its observer actor. Earth exposes
the missing catch-up path because its long-lived, handle-owned creator has more
startup state than Fireball; once that primer produces no live handle, the
observer has no `0x7D5` for subsequent held-input ticks to grow or draw.

## Focused pre-fix observation

A mixed-profile loopback run (Fire host, Earth client) showed the healthy
branch of the same dependency:

- observer Boulder tick: `123` calls;
- observer Boulder draw: `133` calls;
- both peers converged on the same raw HP;
- the host screenshot contains the charged rock beside the remote client.

No snapshot materialization occurred; the stock replay actor alone supplied
those tick/draw calls. This does not invalidate the WAN report. It demonstrates
why the defect is conditional: beta.18 is correct only when the single native
replay path succeeds.

Evidence:

- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/boulder-observer-trace.json`
- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/boulder-observer-trace/earth/client_casts/cast-01/chosen-host.png`

## Fix boundary

The repair belongs in the shared spell-effect materialization seam:

1. admit the complete primary projectile class (`0x7D3..0x7D5`) after a short
   native-replay grace period;
2. create a non-authoritative presentation actor through the stock factory and
   world registration paths;
3. seed each class according to its real layout instead of treating
   `+0x13C/+0x140` as universal motion;
4. drive snapshot-created actors from authoritative presentation snapshots and
   retire them on the matching terminal serial;
5. prefer and transfer to a late stock replay actor if one subsequently
   appears, preventing duplicate long-lived visuals.

Native replay remains the first choice. The fallback owns presentation only:
it must not synthesize damage, alter spell balance, or replace the source
contact/claim lifecycle.

## Implemented ownership model

The shared reconciler now admits the complete primary-projectile class:
MagicMissile `0x7D3`, Fireball `0x7D4`, and Boulder `0x7D5`. It gives native
cast replay one 16 ms spell-effect snapshot interval to create the actor. If
no compatible actor exists after that interval, the loader creates and
registers a presentation actor through the same stock factory/world seams used
by the existing Ember and Firewalker catch-up path.

The snapshot binding records whether its actor was created by that catch-up
path. Natural actors retain stock transform, motion, collision, and teardown
ownership. Snapshot-created actors follow the authoritative transform and are
retired with the terminal serial. A late natural actor replaces a
snapshot-created binding after the presentation actor is marked for stock
removal.

The class layouts remain distinct:

- MagicMissile receives its scalar internal heading at `+0x13C`;
- Fireball receives velocity at `+0x13C/+0x140`;
- Boulder does not receive either write because those offsets begin its
  recursive rock ownership.

`config/binary-layout.ini` therefore exposes
`gameplay.offsets.magic_missile_heading` separately even though its numeric
offset equals Fireball's first motion field. Static RE contracts reject a
return to universal primary-projectile motion writes.

The constructors' stock defaults keep catch-up actors presentation-only.
MagicMissile and Fireball begin with zero damage payload state, while Boulder
is never run through its release finalizer. Authoritative damage remains on
the source contact/claim path.

## Post-fix live evidence

The first instrumented post-fix loopback cast reproduced the reported missing
native-replay branch directly. The host had no natural Boulder binding; one
snapshot interval later its registry reported:

- `snapshot_materialized=true`;
- owner gameplay slot `1`;
- `effect_serial=1`;
- authoritative position error `0.0`.

The host backbuffer showed the charged rock beside the client-owned caster.
That evidence is preserved at:

- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/boulder-post-fix-direct-catchup-first-run.json`
- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-boulder/screenshots/trial-01/host-observer.png`

The isolated regression then repeated the direct catch-up path five times.
Every trial reported a snapshot-created `0x7D5` in slot `1` with zero position
error, and every host/client screenshot visibly contained the rock. All five
launches used `audioDisabled=true`, the `sfx` prefix and ports
`48611/48612`, followed by exact staged-executable PID cleanup:

- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-boulder/primary-materialization-isolated-5x.json`
- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-boulder/isolated-5x-contact-sheet.png`

A separate five-cast, single-session client-to-host damage matrix retained
exact peer convergence in every cell and recorded observer Boulder tick/draw
calls for every cast. The raw HP deltas were `3014.8784179688`,
`2956.0327148438`, `2957.5737304688`, `1.541015625`, and
`3013.3374023438`; both peers agreed to `0.0` difference each time. This
preserves both the documented fixed-170-frame native baseline and the parked
issue-#52 client-origin magnitude family. This investigation did not reveal
the source of that magnitude and made no damage change.

- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-boulder/earth-client-damage-matrix-5x.json`
- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-boulder/earth-damage-5x-contact-sheet.png`

Finally, fresh client-origin Fire, Water, Air, and Ether captures show the
same effects on both peers. Water, Air, and Ether damage matched the prior
converged matrix classes; Fire reproduced the already-documented intermittent
zero-contact cell while still showing Fireball on both peers.

- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-other-elements/other-elements-contact-sheet.png`
- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-other-elements/`
