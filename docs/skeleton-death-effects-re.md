# Skeleton death effects reverse engineering

Status: statically verified against `SolomonDark.exe` SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
The atlas record mapping is parser-verified and every extracted PNG is
pixel-verified against `BadGuys.png`.

## Result

The skeleton does not play a conventional frame-strip death animation. Its
death presenter removes the live actor through the shared enemy-death path,
then constructs a shatter from independently moving sprite objects:

1. Submit the death position for positional feedback.
2. Play `sounds\skellyscream.wav` with a random pitch in `[0.8, 1.0]`.
3. Add a small `0.1` world-feedback impulse.
4. Spawn and shuffle 9 base bone fragments, or 18 with `ENHANCED EFFECTS`.
5. Spawn any body/weapon-specific fragments selected by actor bytes
   `+0x230`, `+0x231`, and `+0x233`.
6. Spawn one of four random skull sprites.
7. Spawn a rotating, fading white star flash 15 units above the corpse.

The minimum normal payload is therefore 9 bone bouncers, 1 skull bouncer,
and 1 fading star. The minimum enhanced payload is 18 bone bouncers, 1 skull,
and 1 fading star.

## Native path

| Role | Address/evidence |
| --- | --- |
| Skeleton type id | `0x3E9` |
| `Skeleton::vftable` | `0x00786604` |
| Death presenter vtable slot | `+0x50` |
| Skeleton death presenter | `0x0048D2A0` |
| Shared enemy death handler | `0x004819D0` |
| Alternate absorption gate | `0x0047BF70` |
| Alternate `Anim_Sucked` builder | `0x0061DC20` |
| Extra skeleton variant branch | `0x0048CDC0` |
| Special weapon-5 branch | `0x00484EA0` |
| `Anim_Bouncer` constructor | `0x00453060` |
| `Anim_Bouncer` tick | `0x00456720` |
| `Anim_Bouncer` render | `0x00456A60` |
| `Anim_Unbind` tick/render | `0x00453020` / `0x00455A20` |
| `BadGuys` bundle builder | `0x004E0DD0` |

`0x0048D2A0` first calls the shared death handler. If that handler declines the
normal presentation, none of the skeleton-specific payload below is built.
Reward/drop selection remains in the shared handler and is not part of the
visual effect.

## Base shatter sprites

The presenter reads the nine-record vector at `BadGuys` bundle-object
`+0x46CC`. The builder trace maps it to serialized `BadGuys.bundle` records
`113..121`.

Normal mode pushes this record sequence, then shuffles it:

```text
113, 115, 118, 121, 120, 119, 116, 117, 117
```

With the setting labeled `ENHANCED EFFECTS` enabled, it pushes this sequence,
then shuffles it:

```text
113, 113, 113, 115, 118, 121, 120, 119, 116,
121, 120, 119, 116, 117, 117, 117, 117, 117
```

Record `114` exists in the backing vector but this presenter never selects it.
Record `117` is deliberately duplicated twice in normal mode and five times in
enhanced mode.

Each base fragment starts from a random angle. Its velocity is derived from the
angle with a `1.5` multiplier on X, its spawn position is displaced by a random
`15..25` multiple of that velocity, and the native code applies a further
`2 * velocity.x` X displacement. Fragment scale is multiplied by `1.2`. The
next fragment angle advances by `72` degrees plus a signed random offset of up
to `10` degrees.

After the base fragments, the presenter always chooses one skull from the
four-record vector at bundle-object `+0x49FC`, serialized records `1819..1822`.
The skull uses a random radial direction and a velocity magnitude multiplier of
`2.0`.

## `ENHANCED EFFECTS`

The controlling byte is `0x00B3BCAD`. The settings renderer binds that byte to
the literal UI label `ENHANCED EFFECTS` at `0x0079C174`; it is not a guessed
quality flag.

For ordinary skeleton bouncers, enhanced mode:

- doubles the base fragment count from 9 to 18;
- enables a black, vertically squashed shadow copy at a `+2` Y offset; and
- replaces the bouncer timer `2.0` with `10.0`.

The timer is clamped to `1.0` for rendering opacity, so the fragment remains
opaque until the timer falls below `1.0`, then fades. The timer decrement is
`0.015` per active update.

## Bouncer physics and rendering

`Anim_Bouncer` is a `0x50`-byte object. The fields relevant to a faithful
reimplementation are:

| Offset | Meaning | Initial/default value |
| --- | --- | --- |
| `+0x14/+0x18` | world X/Y | supplied by presenter |
| `+0x1C/+0x20` | horizontal velocity X/Y | supplied by presenter |
| `+0x24` | sprite pointer | selected `BadGuys` record |
| `+0x28` | current vertical velocity | `-(random[0,3] + 2)` |
| `+0x2C` | bounce velocity | same as `+0x28` |
| `+0x30` | lifetime/opacity timer | `2.0`, or usually `10.0` enhanced |
| `+0x38` | height above ground | `-random[0,20]` |
| `+0x3C` | rotation in degrees | `random[0,360]` |
| `+0x40` | angular velocity | `random[0,10] + 1` |
| `+0x44` | shadow enabled | false |
| `+0x48` | bounce retention | `0.65` |
| `+0x4C` | scale | `1.0` |

While airborne, the object skips its motion/physics/fade update every third
world tick. On active ticks it:

- adds horizontal velocity to position;
- adds vertical velocity to height;
- adds gravity `+0.4` to vertical velocity;
- adds angular velocity to rotation; and
- subtracts `0.015` from the lifetime/opacity timer.

At ground contact, bounce velocity is multiplied by `0.65` and copied back to
the current vertical velocity. A 50% branch also damps both horizontal velocity
components by `0.65`. Once the upward bounce is weaker than the `-0.75`
threshold, all movement and angular velocity are zeroed. The object deletes
itself when its timer reaches zero. It can also be deleted by the native terrain
collision test.

The renderer draws the sprite at `(x, y + height)` with its rotation and scale.
When shadowing is enabled it first draws a black copy at `(x, y + 2)`, using
full X scale and `0.75` Y scale. Both draws use the timer clamped to `1.0` as
alpha.

## Always-spawned star flash

The final non-bouncer effect is an `Anim_Unbind` using inline bundle-object
record `+0x4210`, serialized record `86`:

- position: `(actor.x, actor.y - 15)`;
- initial rotation: random `0..360` degrees;
- initial alpha: `0.75`, or `1.25` when actor flags `+0x9C & 2` is set
  (rendering clamps it to `1.0`);
- alpha loss: `0.0225` per tick; and
- angular velocity: either `-5..-2.5` or `5..7.5` degrees per tick.

This is the bright three-point star in the extraction sheet. It fades and
rotates; it is not an animation strip.

## Conditional equipment and variant effects

The visual labels below describe the exact extracted crops. The offsets,
accepted values, selected records, and spawned native classes come directly
from the executable.

| Actor field | Trigger | Confirmed payload |
| --- | --- | --- |
| `+0x230` | values `1`, `2`, `4`, `5` | One random record from pairs `92/93`, `94/95`, `96/97`, or `98/99`; `Anim_Bouncer`, scale `1.2`. |
| `+0x231` | values `1..4` | One weapon bouncer: record `2063` sword, `2064` mace, `2065` flail, or `2066` axe. |
| `+0x231` | value `5` | One scale-3 additive flash using record `15`, seven bouncers using record `55`, a world color/feedback write, then actor timers `+0x30 = 20` and `+0x1B0 = 70`. |
| `+0x233` | nonzero on type `0x3E9` | Five bouncers: one random record from each pair `100/101`, `102/103`, `104/105`, `106/107`, and `108/109`; plus a scale-3 additive flash using record `15`, placed 35 units above the actor with duration argument `25`. |

The `+0x231 == 5` fragment timer is `2.0 * 0.75 = 1.5`; enhanced mode adds
its shadow but does not replace that timer with `10.0`.

## Alternate absorption death

Before playing the shatter, `0x0048D2A0` calls `0x0047BF70`. That gate scans
the gameplay scene's registered Player list at `scene +0x13A8/+0x13B4`.
When transient damage-event flag `0x100` is active and a Player is within
squared distance `1600` (40 world units), normal skeleton shatter is
suppressed. `0x0061DC20` instead builds an `Anim_Sucked` object from the dying
enemy's current visual and targets the nearby Player. The bit is propagated
through the shared damage-event flag word rather than enabled by a static
global toggle. The executable supplies no gameplay-facing label for bit
`0x100`, so the numeric ABI is authoritative and this document does not invent
a collector or spell name.

## Audio and world feedback

The sound-table builder loads:

- `sounds\skeleton_die.wav` into sound object `+0xD80`; and
- `sounds\skellyscream.wav` into the next sound object, `+0xDAC`.

The skeleton death presenter calls `+0xDAC`, so its confirmed cue is
`skellyscream.wav`, despite the adjacent, plausibly named `skeleton_die.wav`.
The cue is mono 16-bit PCM at 44.1 kHz and is 1.605125 seconds long. The pitch
argument is uniformly randomized from `0.8` to `1.0`.

After sound playback, the presenter calls `0x0063EEB0` with `0.1`. That writes
the scene's damped feedback fields at `+0x8E04/+0x8E08`: the accumulator rises
by `0.2` up to `3.5`, while its visible magnitude is based on the accumulator
clamped to `1.0` times `0.1`. This is the camera/world-shake channel:
`Region_Tick (0x0063EFC0)` damps `+0x8E04` and zeros it below threshold, while
the fixed-room and Arena render paths consume `+0x8E04` in their world/camera
transform. The skeleton death therefore contributes a confirmed `0.1` shake
impulse.

## Extracted assets and reproducibility

The raw, exact-pixel crops, contact sheet, and mapping manifest are in
[`docs/assets/skeleton-death-effects/`](assets/skeleton-death-effects/).
The contact sheet enlarges tiny fragments with nearest-neighbor scaling only;
the individual PNGs retain their original atlas dimensions.

Regenerate them from the retail assets with:

```bash
python3 tools/extract_skeleton_death_effects.py
```

Rebuild the serialized-record-to-runtime-object mapping from Ghidra with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `
  "& { & '.\scripts\Invoke-GhidraHeadless.ps1' `
  -ScriptPath '.\tools\ghidra-scripts\trace_bundle_sprite_loads.py' `
  -ScriptArguments @('0x004E0DD0') }"
```

For SDR, reproduce or synchronize the chosen sprite ids, initial angles,
velocities, enhanced-effects flag, and optional actor variant bytes. Allowing
each peer to consume its own random stream would produce visibly different
fragment selections and trajectories.
