# Native enemy hit and death effects

Status: statically verified against retail `SolomonDark.exe` SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
This document owns the common hit-overlay ABI and the death-presentation
handoff for the eight enemy families used by retail Boneyard waves. Reward,
drop, and child-spawn authority remains in the shared enemy lifecycle.

## Result

Enemy hit feedback is not a five-frame additive white flash and does not reset
the current action. Positive primary or secondary damage arms two floats on
the live Actor. The common Actor tick removes `0.05` from each float per fixed
tick, so a hit refreshes a 20-tick latch. The common renderer draws the exact
current body/action pose normally, then redraws that pose in red with opacity
`min(remaining * intensity, 1)`. A damage context flag can suppress the second
latch, but it does not turn the surviving overlay into an additive blend.

Enemy death is a different ownership thread. The family presenter first
enters `Badguy::DeathCommon (0x004819D0)`, then removes the live body and
creates independent world-owned animation actors. Those actors keep their own
sprite, transform, velocity, height, alpha, clock, blend, and optional shadow.
The death body is therefore not a family-colored frame strip and a client may
not synthesize its lifetime from the retiring enemy snapshot.

## Common hit ABI

| Role | Address / field | Recovered behavior |
| --- | --- | --- |
| Damage reaction | `0x00627F80` | Positive primary/secondary damage writes both latches to `1`, intensity from the current damage context, and context RGBA. Context flag bit `8` suppresses the secondary latch. |
| Actor tick | `0x00624AC0`, Actor `+0x78/+0x80` | Subtract `0.05` per fixed tick and clamp at zero. A later hit writes `1` again. |
| Common Actor render | `0x00624B40` | Draw current pose, then redraw it red with alpha `min(actor+0x78 * actor+0x7c, 1)`, then restore render state. |
| Reaction dispatch | `0x00625150` | Orthogonal to the body/action clock; the hit latch does not restart locomotion or attack progress. |

The authoritative web representation therefore needs the remaining hit latch
or its exact derived alpha. It must preserve the current pose and apply a
source-alpha red redraw after the normal body. Five-tick decay, white tint,
additive blending, and action restart are rejected models.

## Independent effect actors

The family presenters use existing registered animation classes rather than a
single enemy-death class. The common classes relevant to Boneyard are:

- `Anim_Bouncer` constructor/tick/render `0x00453060/0x00456720/0x00456A60`;
- `Anim_Unbind` tick/render `0x00453020/0x00455A20`;
- `Anim_Banish 0x00458D50`;
- `Anim_SpriteArray 0x00453410`;
- `Anim_MoveFade`, `Anim_Fade_Perspective`,
  `Anim_Fade_Perspective_Clipped`, and `Anim_SmokyBouncer`;
- `ZAnim 0x005E03D0`, which owns its child effect.

`Anim_Bouncer` keeps world position, horizontal velocity, sprite, vertical
velocity, bounce velocity, opacity/lifetime, height, rotation, angular
velocity, shadow flag, retention, and scale. It skips every third world tick
while airborne. On an active tick it integrates horizontal velocity and
height, adds gravity `0.4`, advances rotation, and subtracts `0.015` from its
timer. Ground contact retains `0.65` of vertical velocity and, on a 50 percent
branch, the horizontal velocity. Disassembly at `0x004567D4..0x00456824`
shows that `RandomInt(2)` branch is drawn anew at every ground contact; it is
not a constructor-selected property of the Bouncer. A bounce weaker than
`-0.75` settles. The
renderer draws at `y + height`; enhanced effects add a black shadow at `y + 2`
with Y scale `0.75`. Alpha is `min(timer, 1)`.

`Anim_Unbind` is the common star flash. Boneyard deaths use BadGuys record 86
at `(enemy.x, enemy.y - 15)`, random rotation, and angular velocity in either
`[-5,-2.5]` or `[5,7.5]` degrees per tick. The common lethal-contact function
`0x0048A290` ORs Actor `+0x9C & 2` only when the transient secondary-damage
component at `0x0081C6EC` is nonzero. Each family presenter reads that bit and
selects the following exact Unbind clock:

| Presenter | Primary-only initial alpha | Secondary-present alpha | Alpha loss / tick |
| --- | ---: | ---: | ---: |
| Skeleton / Archer / Mage `0x0048D2A0` | `0.75` | `1.25` | `0.0225` |
| Imp `0x004824A0` | `1.0` | `1.25` | `0.025` |
| Zombie `0x004947B0` | `0.75` | `1.25` | `0.05` |
| Wraith `0x00495600` | `1.0` | `1.25` | `0.025` |
| Coffin `0x0049B310` | `0.75` | `1.25` | `0.045` |

The renderer clamps alpha to one. These are damage-component branches, not an
Enhanced Effects toggle. Demon and Maggot presenters do not create Unbind.

## Family presenters

| Family | Presenter | Exact created output |
| --- | ---: | --- |
| Skeleton / Archer / Mage | `0x0048D2A0` and sibling vtable entries | Shared death; absorption gate `0x0047BF70`; positional `skeleton_die.wav` at pitch `[0.8,1.0)`; shake `0.1`; normal shuffled BadGuys sequence `113,115,118,121,120,119,116,117,117`, or Enhanced Effects sequence `113,113,113,115,118,121,120,119,116,121,120,119,116,117,117,117,117,117`; random skull `1819..1822`; record-86 Unbind; equipment fragments from `92..109`, `2063..2066`, and special record `15/55` branches. Transfer `0x00462790` proves live `+0x230/+0x231/+0x233` are respectively the evaluated headgear, weapon, and armor choices. |
| Imp | `0x004824A0` | Shared death; absorption gate; a permitted split plays `ImpSplit` at `[0.9,1.1)` while an ordinary terminal branch plays `fireydeath` at `[0.8,1.0)`; record-86 Unbind; vtable helper `0x00478860` creates Banish/ZAnim and BadGuys `401..419` SpriteArray output. Split children are separate enemy actors, not visual debris. |
| Zombie | `0x004947B0` | Shared death; absorption gate; a rotten branch plays `zombiepoisonsplat` three times at `[0.9,1.05)`, followed by `zombiedie` and `zombie_die_groan` at `[0.8,1.0)`; BadGuys body fragments including `2088..2094` and `2293..2310`; record-86 Unbind; clipped perspective fade using DeadHawg 30. Rotten death also creates the authoritative poison-pool actor. |
| Wraith | `0x00495600` | Shared death; absorption gate; shared dissolve helper `0x0047F8D0`; BadGuys `113..121` fragments using Bouncer/SmokyBouncer, random skull `1819..1822`, record-86 Unbind, fixed-pitch `flash`, then three `bansheedie` calls (two at `[0.9,1.1)`, one at `[0.8,1.2)`). The dissolve helper creates 12 MoveFade rays, one FadeScale core, and 12 Bouncers. |
| Demon | tick `0x00487300`; terminal helper `0x00482930` | Death state 95 plays fixed-pitch `flash` and `demondies`; the terminal split helper additionally plays `fireydeath` at `[0.8,1.0)`, then creates Banish/ZAnim and a BadGuys `401..419` SpriteArray. Its configured Imp children remain independent authoritative actors. |
| Coffin | `0x0049B310` | Shared death; ground debris registration; `coffinbreak` at `[1.0,1.1)`; shake `0.2`; common bone/skull bouncers; `RandomInt(11)+40` bouncers from BadGuys `2013..2062`; `RandomInt(5)+12` additional coffin fragments drawn from the combined DeadHawg `114..144` / BadGuys `2067..2069` list; record-86 Unbind. |
| Maggot | `0x0049C830` | Shared terminal path with reward suppressed; absorption gate; one of three `Squish` cues and independently one of two `MaggotSqueak` cues, both at `[1.0,1.2)`; a BadGuys `2013..2062` Bouncer and tinted DeadHawg 28 Fade_Perspective at the current point, repeated at zero to two stored burst offsets; parent live-child accounting decrements. |

The exact Skeleton shatter order, equipment branches, Bouncer layout, and
asset extraction are independently pinned in
[`../skeleton-death-effects-re.md`](../skeleton-death-effects-re.md).

## Audio identity and Maggot burst offsets

The exact 233-entry audio catalog places `sounds\skeleton_die.wav` at registry
object `+0xDAC` (entry 79) and `sounds\skellyscream.wav` at the next object,
`+0xDD8` (entry 80). Disassembly at `0x0048D368` adds `0xDAC` before calling
`Sound::Play 0x00407CD0`; it therefore selects `skeleton_die`, not the adjacent
`skellyscream`. The pitch is `RandomFloat(0.2, unsigned) + 0.8`, or
`[0.8,1.0)`. This resolves the earlier decompiler-adjacency ambiguity.

Maggot registration `0x00487FD0` stores `Integer(3)` burst offsets, hence an
exact count in `[0,2]`. Each offset is a random unit direction from
`0x00410C50` multiplied by `RandomFloat(30, unsigned)`, so its radius is
`[0,30)`. They are not movement-history samples. `0x0049C830` emits one
DeadHawg-28 fade and one BadGuys `2013..2062` bouncer at the current position,
then repeats that pair at every stored offset. Before constructing those
effects it independently chooses one of Squish catalog entries 211..213 and
one of MaggotSqueak entries 199..200; both pitches are `[1.0,1.2)`. The squeak
gain also carries a `[0.25,0.5]` multiplier on native point attenuation.

## Positional audio and world feedback

Every family death sound above is a world-point request. The Arena vtable
resolves Region slot `+0x100` to `0x004621B0`. For visible world width `W`,
camera rectangle center `C`, source `P`, and `d = length(P - C)`, its gain is
one through `0.25W`, falls linearly to zero at `1.1W`, and remains zero after
that point. It supplies no pan. When the local Player alternate/death byte
`+0x160` is nonzero, the entire point gain is multiplied by `0.1`. Per-event
gain such as the Maggot squeak's `[0.25,0.5]` multiplier is applied after this
spatial result.

`Region::ApplyCameraShake 0x0063EEB0` is not a random displacement. The
Region constructor `0x00652830` initializes feedback magnitude and accumulator
`+0x8E04/+0x8E08` to zero. Once normal ticks establish the accumulator floor,
an impulse with requested intensity `I` writes
`magnitude = min(accumulator, 1) * I`, then adds the exact float
`0.20000000298023224` to the accumulator and caps it at `3.5`.
`Region::Tick 0x0063EFC0` subtracts `0.0025` from the accumulator each fixed
tick and floors it at `0.1`; it multiplies magnitude by `0.94` and writes zero
once the result is below `0.001`.

Arena render `0x0046EC80`, instructions `0x0046F100..0x0046F276`, consumes a
positive magnitude after semantic camera placement. It translates to the
local Player, calls the matrix scale builder `0x004030A0` with
`(1 + magnitude, 1 + magnitude, 1)`, and translates back. The result is a
uniform world-scale pulse anchored on the local Player; it does not move actor
authority, change aim, choose a random direction, or alter the semantic camera
rectangle. Skeleton, Archer, and Mage presenters request intensity `0.1`.
Coffin requests `0.2`. Multiple deaths in one period overwrite magnitude using
the then-current accumulator and continue raising that accumulator, matching
the native buildup rather than summing independent CSS shakes.

## Deterministic multiplayer contract

The host owns damage acceptance, the refreshed 20-tick hit epoch, family
death recipe selection, every cosmetic RNG result, and each created effect
actor. A snapshot carries the live hit overlay and the current state of every
surviving death-effect actor. Clients interpolate continuous transforms only.
They do not reroll debris, infer terminal output from HP, or restart retained
effects on late join. Terminal audio remains a run-scoped once-only semantic
event, separate from persistent visual samples.

## XP handoff boundary

The family baselines recorded by the enemy census are the actor reward values
*after* the native recipe-to-actor `*2` conversion. In other words, Skeleton
`10`, Imp `2`, and Wraith `4` must not be doubled again when the death-credit
listener runs. The Arena recipe scalar `0.425` yields the observed one-player
credits `4.25`, `0.85`, and `1.70` before receiver level/bonus scaling. The
complete award and shared level-up contract remains owned by
[`native-progression-and-skills.md`](native-progression-and-skills.md).

## Remaining evidence boundary

The stock constructor/tick ownership, exact family art sets, Skeleton physics,
per-contact Bouncer damping draw, per-family Unbind clocks, audio identity,
and family fan-outs above are closed. Full
numeric physics for Banish, SpriteArray, MoveFade, SmokyBouncer, Zombie's
clipped fade, and every Coffin/Maggot auxiliary branch remains open. A web port
may use named deterministic clocks for those classes, but it must preserve the
recovered class, art, fan-out, blend family, world ownership, stable identity,
and retirement semantics rather than falling back to a body-strip death pose.
