# Native projectile and spell mechanics

- Status: **G2 closed by static RE plus live solo goldens**
- Campaign: `spellre-20260804`
- Live-capture source SHA: `1b9d454da60afefa2cb5f01a0f6e8ce829efebe6`
Canonical fixture: `tests/fixtures/webgame/projectile-goldens.json`

This document is the browser-rebuild contract for the five native primary
elements: Ether, Fire, Air, Water/Frost, and Earth. It separates gameplay
actors from transient render actors, and it treats a native tick as one
distinct `local_player_tick_count` observed from `runtime.tick`. Duplicate Lua
callbacks for the same native tick are discarded in the fixture.

The findings combine read-only headless Ghidra work in the campaign replica
with live `spr-*` solo sessions. No gameplay behavior changed and no new
runtime probe seam was needed. The captures used the existing Lua exec,
`sd.world`, `sd.debug`, `sd.input`, and manual-run enemy seams. An independent
Frost start/stop capture used real foreground Windows mouse input.

## Shared cast pipeline

The stock input-to-primary path is:

1. The player action ticks at `0x0044B370`, `0x0044B580`, or `0x0044B770`
   consume the held/released primary state.
2. They call the `PlayerWizard` virtual at slot `+0x58`, implemented at
   `0x00550180`.
3. Casting action modes `3`, `6`, and `9` enter the primary dispatcher at
   `0x0054CAF0`. That dispatcher invokes the equipped item virtual at `+0x68`
   and selects the handler by native skill id.
4. One-shot handlers create their gameplay actor through
   `GameObjectFactory_Create` at `0x005B7080`, set group/owner state, and
   register the actor through `0x0063F6D0`. Held handlers instead repeat their
   query and application work on every action tick.

| Element | Skill id | Primary handler | Gameplay representation |
| --- | ---: | --- | --- |
| Ether / Magic Missile | `8` | `0x0053CFE0` | factory type `0x7D3`, constructor `0x005E4990` |
| Fire / Fireball | `16` | `0x0053DC60` | factory type `0x7D4`, constructor `0x005E0970` |
| Air / Lightning | `24` | `0x0053F9C0` | retained-target hitscan; no projectile actor |
| Water / Frost Jet | `32` | `0x00543860` | held cone query; no projectile actor |
| Earth / Boulder | `40` | `0x00544C60` | factory type `0x7D5`, constructor `0x005FA270` |

The common emitter helper at `0x0053B830` takes its origin from the active
wizard cast glyph, not merely from the actor center. It chooses a directional
glyph from the current cast animation using integer frame selection equivalent
to `((animation_frame + 7) / 15) % 24`, scales the glyph-local point by the
wizard actor scale at `+0x74`, and adds the wizard world position. This is why
two otherwise identical Fire casts can occupy visibly different emitter lanes.
Browser parity must derive the emitter from the current directional cast frame
before applying the element-specific offsets below.

## Mechanics at a glance

| Element | Origin and initial motion | Contact shape and cadence | Lifetime / repeated-hit rule |
| --- | --- | --- | --- |
| Ether | cast glyph emitter plus local `(0,+10)`; aim probe `100` units forward; speed `3 * (1 + mSpeed/100)` | actor radius `15`; target proximity every tick with `6`-unit probe; terrain every fifth tick using a five-tick lookahead | no fixed timer found; contact consumes unless pierce remains; an age over `200` changes the candidate mask |
| Fire | cast glyph emitter plus local `(0,+10)`, then `20` units along aim; velocity is aim unit vector times `4.5` | actor radius `22.5`; candidate query radius `20` every tick in the current spatial cell; terrain every fifth tick with five-tick lookahead | no fixed timer found; first impact removes the Fireball; status/area work is dispatched before removal |
| Air | cast origin to retained target/aim line; instantaneous, so no velocity or spread | line/world clip at `0x00524D70`; target/chain query every held tick at `0x00641340` | exists only while the primary is held; each chained hop scales the next damage by `0.6`; a render-only fade lives `10` ticks |
| Water/Frost | cast origin and aim define a rank-scaled cone; instantaneous, so no velocity | rank-1 query reach is `205` world units; candidate cone `0x00641B10`, mask `0x1082`, then per-target LOS; contact every held tick | start/sustain/stop channel; render particles outlive their source tick for about `32`–`33` ticks |
| Earth | charged actor is held at the cast emitter, then released straight along aim at speed `3` | held radius `15`; release radius is charge-scaled; recursive collision/query `0x00620B60` runs every flight tick | held until release even after full charge; no fixed flight timer found; distinct-target ledger allows residual pool to hit more than one target |

None of the three materialized primary projectiles has ballistic gravity or a
vertical arc. Ether can steer toward a target; Fire and released Earth advance
in the horizontal world plane. Air and Frost are query volumes, not actors
whose paths should be integrated.

## Ether: Magic Missile

`0x0053CFE0` asks `0x005B7080` for type `0x7D3`. The actor ticks at
`0x005FD270` and draws at `0x005E0460`.

The initial point is the common glyph emitter with local `(0,+10)` applied.
Target acquisition probes `100` units ahead of the caster. Initial speed is

```text
speed = 3 * (1 + mSpeed / 100)
```

and the rank-1 and controlled rank-2 captures both retained `3.0` world units
per native tick. When more than one missile is emitted, directions alternate
symmetrically around aim. The normal angular step is `20` degrees; when the
quantity is below four, the step is `30` degrees. This fan is the only initial
spread. Homing/turn work then runs on every tick.

The gameplay actor radius is `15`. The target-proximity pass runs every tick
with the native `6`-unit probe constant. Terrain is tested every fifth tick
against a five-tick forward segment. There is no recovered hard lifetime: both
rank fixture windows contain `604` consecutive native ticks. Once age exceeds
`200`, the candidate mask broadens from `2` to `6`; that is a search-policy
transition, not expiration.

Pierce is held in the actor byte at `+0x161`. A zero value makes the first
accepted contact remove the missile. A positive value is decremented; speed
and remaining damage are scaled, the actor is advanced beyond the contact,
and it retargets without selecting the same contact as though it were new.
Thus browser code must not model every Magic Missile as unconditionally
single-hit.

## Fire: Fireball and residual fire

`0x0053DC60` creates type `0x7D4`. The Fireball ticks at `0x005FDD90`, impacts
at `0x005E5160`, and uses the projectile draw paths at `0x006099C0` and
`0x005E50D0`.

The handler starts from the common cast glyph emitter plus local `(0,+10)`,
then advances the spawn point `20` world units along the normalized aim vector.
It stores that unit vector in the projectile and advances it by the native
double constant `4.5` each tick. There is no random angular spread.

The actor collision radius is `22.5`. Every tick it queries a `20`-unit target
probe, but the candidate enumeration is restricted to the projectile's current
spatial cell. Geometry is tested every fifth tick with a five-tick lookahead.
This cell restriction plus the directional glyph emitter explains the misses
documented in
[`multiplayer-fireball-contact-2026-07-26.md`](multiplayer-fireball-contact-2026-07-26.md):
the miss traveled for `128` ticks without entering impact, while successful
client casts reached one native impact and exactly `4.0` damage. The apparent
`8.0` sample there was two retained serialized `4.0` contacts, not a double
Fireball impact.

There is no fixed Fireball timer in the recovered tick. The live unobstructed
rank-1 and rank-2 paths each remain materialized for all `399` captured ticks.
An accepted actor or terrain impact calls `0x005E5160`, seeds the primary
contact, invokes the fire/status helper `0x00624300`, optionally performs the
area lane, dispatches through `0x0063E7D0`, and removes the Fireball. The
per-tick Fireball trail is transient `Anim_FireParticle`/`ZAnim` presentation;
it is not a persistent `Fire_Goodguy` gameplay actor.

The new contact golden observed one `4.0` HP transition at a projectile-to-
target-center distance of `30.5124151`. The target took no additional HP
damage during the following `499` observed ticks. That observation constrains
HP application only: the impact still calls the native fire/status helper, so
the browser must not erase non-HP status or area semantics merely because this
stationary skeleton fixture showed no later HP decrement.

### `Fire_Goodguy` (`0x7EE`) trail actors

`Fire_Goodguy` is a separate positive-lifetime gameplay actor. Factory type
`0x7EE` constructs at `0x005E76C0` on top of the Fire base constructor
`0x005E7130`; it ticks at `0x005FF050`, applies its area/contact pulse at
`0x005FF1D0`, and draws at `0x00610F90`.

Its native fields establish these semantics:

- animation phase `+0x140` advances by `0.25` per tick;
- lifetime `+0x144` starts at `2.0` and falls by `0.01` per tick, for `200`
  native ticks;
- alpha `+0x148` rises by `0.05` per tick to `1.0`;
- scale is stored at `+0x150`, damage at `+0x158`, and draw alpha at `+0x15C`;
- while damage is positive, every tick divisible by three performs a
  `32 * scale` radius contact pass and dispatches through the same fire helper
  and contact lane. A target that remains inside may therefore be hit on more
  than one pulse.

This is the positive-lifetime trail actor observed by the botmana campaign.
The corrected stock secondary dispatcher at `0x0054CC50` creates live damaged
`0x7EE` actors while Firewalker remains active; Fire Wall also creates them.
The earlier byte-toggle experiment described in
[`beta32-bot-mana-and-lone-target-handoff-2026-08-04.md`](../bugs/beta32-bot-mana-and-lone-target-handoff-2026-08-04.md)
did not reproduce that stock path. A browser implementation must preserve the
distinction between Fireball's cosmetic particles and these damaging residual
actors.

## Air: Lightning

`0x0053F9C0` performs the Air primary directly. It does not call the gameplay
object factory for a projectile. The caster retains a primary target, clips the
aim/target segment against the world through `0x00524D70`, queries chained
targets through `0x00641340`, and applies contact on every sustained handler
tick. There is consequently no spawn radius, velocity, projectile lifetime,
or ballistic spread to emulate.

The browser contract is a per-tick ordered ray/chain:

1. recompute the cast origin and the retained target/aim endpoint;
2. clip the primary line against world geometry;
3. apply the primary contact if eligible;
4. select eligible chained contacts in native order, excluding already-used
   targets; and
5. multiply the next hop's damage by native double `0.6`.

The channel exists while primary input remains held. Releasing it stops new
contact queries immediately. `Anim_FadeLightning` is render-only: its lifetime
and alpha start at `1.0`, fall by `0.1` per tick, and therefore persist for ten
ticks after emission. It increments its procedural angle by `1` per tick and
uses the mesh builder at `0x00536380`; it has no atlas sprite id.

The fixture records the ray state on every native tick at rank 1 (`229` rows)
and controlled rank 2 (`259` rows), rather than inventing a projectile actor.

## Water: Frost Jet channel

The Water primary is the Frost channel at `0x00543860`. Like Air, it is a held
query and creates no gameplay projectile. The handler derives a cast origin
and forward direction, builds its rank-scaled cone, enumerates candidates with
`0x00641B10`, and uses group mask `0x1082` for the normal player-owned path.
Rank 1 reaches `205` world units (`180` base plus the `25` rank contribution).
Each candidate then passes an individual line-of-sight check before contact.
The complete query and damage application repeat every held native tick.

The absence of a projectile radius is intentional. The parity equivalent is
the native cone reach/width plus per-target LOS, not a moving circle. There is
also no velocity, gravity, pierce counter, or independent gameplay lifetime.
Multiple targets can be contacted in the same tick because the handler walks
the eligible cone list.

### Start, sustain, and stop

The exact audio/selection state machine remains the one established in
[`multiplayer-frost-channel-stop-2026-07-26.md`](multiplayer-frost-channel-stop-2026-07-26.md):

- Water selection is `0x20`; the primary skill is `32`, with progression entry
  `1012`.
- Selecting Water first calls the stop routine harmlessly at zero refcount,
  then starts `sounds\iceloop__loop` at `0x00549BB2` in audio registry slot
  `+0x182C` (live registry index `161`).
- Sustained ticks leave primary id `32`, loop active, and refcount `1` while
  executing the cone/contact handler once per native tick.
- Release must publish the real `0x20 -> 0` transition. `0x00549725` stops the
  same loop, leaving active false and refcount zero. Current and previous
  selection live at player offsets `+0x270` and `+0x274`.

The previously accepted multiplayer stop latencies were `16`, `16`, `31`,
`16`, and `16` ms, all inside one `50` ms snapshot interval. This campaign's
deterministic 150-tick rank-1 timeline ran exactly `1500` ms from native start
to native stop and recorded one harmless pre-start stop plus one release stop.
The independent real-mouse run recorded primary `0 -> 32 -> 0`, one start, one
stop, active duration `110` ms, and final refcount zero.

`Anim_FrostJetEffect` and `Anim_FrostJetEffect_Over` are transient visual
actors emitted during sustain. Their initialized lifetime is about `1.25`
plus a small random term and drops by `0.04` per tick, yielding about `32`–`33`
ticks of visual persistence. Their lifetime must not extend contact: gameplay
ends on the input stop edge.

## Earth: Boulder

`0x00544C60` creates type `0x7D5`. Construction is at `0x005FA270`, the held
and flight tick is `0x00609D30`, release finalization is `0x005E5450`, recursive
collision/contact is `0x00620B60`, and drawing is at `0x0060AC40`.

The Boulder is created at the cast emitter and remains held there while charge
grows. Release gives it a normalized aim vector and constant speed `3.0`.
There is no random spread, gravity, or arc.

### Exact charge-time to magnitude curve

Charge is a float32 field at `Boulder + 0x74`. At construction:

```text
C[0]      = float32(0.18)
growth    = float32((wizard + 0x2A0) * 0.5 * cast_speed)
C[n + 1]  = min(1.0, float32(C[n] + float32(growth * 0.0025)))
```

For the neutral rank-1 fixture, `(wizard + 0x2A0) == 1` and
`cast_speed == 1`, so `growth == 0.5` and each recurrence adds float32
`0.00125`. The recurrence, rather than an algebraically simplified decimal,
is the exact browser contract because every addition rounds to float32.

| Requested input hold | Charge updates before release/full | Exact observed magnitude | Release/full timing |
| ---: | ---: | ---: | --- |
| `2` frames | `97` due to the stock minimum casting action | `0.30124989151955` (`0.301249892` serialized) | first flight at fixture row `97` |
| `170` frames | `170` | `0.39249980449677` (`0.392499804` serialized) | first flight at row `170` |
| full (`700`-frame held window) | `656` to clamp | `1.0` | first full row `655`, `6547` ms after the first sampled row; released at row `700` |

The prior live gate in
[`multiplayer-earth-charge-baseline-2026-07-26.md`](multiplayer-earth-charge-baseline-2026-07-26.md)
reported `charge == max_charge == 1.0` after `6.583` seconds. The small wall-
clock difference is input/sample-boundary timing; both observations pin the
same 656-update float32 curve. A controlled rank-2 170-frame capture reached
the identical `0.392499804` charge, confirming that rank changes spell
magnitude/damage inputs but not this neutral charge recurrence.

While held, actor collision radius stays `15`. Finalization scales body radii
to `500 * C`. The immediate release/contact lane uses `45 * C` (`50 * C`
times `0.9`); if the actor survives into its normal flight collision tick,
`0x00620B60` updates the collision radius to `75 * C`. Thus the three
unobstructed first-flight rows record radii `22.5937424`, `29.4374847`, and
`75.0`, while the full-charge immediate-contact golden records the earlier
release radius `45.0`.

Flight collision is evaluated every native tick. A per-Boulder target list at
`+0x200` prevents the same target from consuming the pool twice. A successful
contact reduces the reusable damage pool; if a positive pool remains, the
Boulder can continue and contact a different target. That is residual
multi-target behavior, not same-target periodic damage. There is no recovered
fixed flight expiration.

Damage scaling from charge is already derived bit-exactly in
[`earth-boulder-damage-formula-2026-07-27.md`](earth-boulder-damage-formula-2026-07-27.md).
This document deliberately does not derive it again. The accepted post-fix
host golden endpoints are `0.90625` for the two-frame input,
`1.5390625` for the 170-frame hold, and exactly `10.0` at full charge. The new
full-charge contact fixture independently observes exactly `10.0` at charge
`1.0`, release radius `45.0`, and projectile-to-target-center distance
`51.8984223`.

## Damage application path and accepted goldens

All spell-specific handlers converge on the existing native application ABI:

1. `0x006246F0` clears/seeds the shared contact globals at
   `0x0081C6E0..0x0081C6F8`.
2. The handler writes source, element flags, magnitude lanes, and effect
   metadata. Fire additionally calls `0x00624300`; Earth prepares its two
   contact lanes in `0x00620B60`.
3. `0x0063E7D0` validates same-world contact and invokes target virtual slot
   `+0x4C`.
4. A normal enemy receives that call in `Badguy::Contact` at `0x0048A290`,
   where resistances/status and HP application occur.

The multiplayer ownership/materialization boundary remains documented in
[`multiplayer-primary-projectile-materialization-2026-07-26.md`](multiplayer-primary-projectile-materialization-2026-07-26.md).
It is possible for observer presentation materialization and authoritative
damage convergence to have different outcomes; browser code must not use a
sprite's existence as proof that damage was or was not applied.

These are cited golden numbers, not new derivations:

| Element/window | Existing accepted golden | New solo contact cross-check |
| --- | --- | --- |
| Fire one-shot | exactly `4.0` in `multiplayer-fireball-contact-2026-07-26.md` | `4.0`, error `0`, epsilon `0.000001` |
| Ether window | host `1.2001953125`, client `1.1000976562` in `multiplayer-element-damage-2026-07-26.md` | `1.1999969`, error `0.0001984125`, epsilon `0.00025` |
| Air 170-tick window | host `4.2333984375`, client `4.18359375` in `multiplayer-element-damage-2026-07-26.md` | `4.2502594`, one-tick error `0.0168609625`, epsilon `0.026` |
| Water/Frost 170-tick window | host `4.2333984375`, client `4.2084960938` in `multiplayer-element-damage-2026-07-26.md` | `4.2502594`, one-tick error `0.0168609625`, epsilon `0.026` |
| Earth host contacts | `0.90625`, `1.5390625`, `10.0` in `earth-boulder-damage-formula-2026-07-27.md` | full `10.0`, error `0`, epsilon `0.000001` |

Air and Frost apply roughly `0.025` per native tick in these rank-1 sustained
windows. Their epsilon admits exactly one input-sampling tick because the old
multiplayer and new solo 170-frame windows straddle that boundary. It is not a
general damage tolerance. One-shot epsilon instead covers only float32 text
round-trip/HP storage.

## Presentation hooks for browser parity

The native projectile/effect draw paths ultimately submit `Puppet`/`ZAnim`
glyphs to the world queue. Browser ordering must therefore preserve actor
world position, Y/bias sort, culling, tint, alpha, and light behavior described
in [`world-sprite-render-pipeline.md`](../re/world-sprite-render-pipeline.md).
Drawing the following frames as a screen-space overlay is not equivalent.

| Mechanic | Native sprite/atlas hook | Frame cadence / ownership |
| --- | --- | --- |
| Ether missile | `BadGuys[53]` | gameplay actor position/heading; world-queued |
| Fireball | main `BadGuys[255..266]`; auxiliary `BadGuys[110..112]` | main frame `(age_ticks / 3) % 12`: 3 ticks/frame, 36 ticks/cycle; cosmetic particles are separate transients |
| Air lightning | no atlas entry | procedural mesh at `0x00536380`; fade lifetime/alpha `1.0`, minus `0.1` per tick |
| Frost Jet | core `BadGuys[30]` and `[28]`; handler extras `[32]` and `[14]` | a new transient may be emitted on each sustain tick; each remains about 32–33 ticks |
| Boulder | body `BadGuys[86]`; debris `[168..171]`; auxiliary `[18]`, `[2008..2010]` | body scale follows live charge; do not replace it with a fixed-size frame animation |
| `Fire_Goodguy` | `DeadHawg[46..77]` | phase `+0.25`/tick (four ticks per integer phase); alpha ramps independently |

The sprite ids identify native array entries, not standalone image filenames.
The browser asset bridge must map them through the recovered atlas/texture
registration data while retaining the world-queue semantics.

## Golden fixture contract

`tests/fixtures/webgame/projectile-goldens.json` records the live evidence in
columnar tick tables (`columns`, `rows`, `count`) to keep repeated field names
out of the large fixture. Its header pins:

- instance names `spr-fire-r1-world`, `spr-ether-r1`, `spr-earth-r1`,
  `spr-air-r1`, `spr-water-r1`, and the five `spr-*-contact` sessions;
- source SHA `1b9d454da60afefa2cb5f01a0f6e8ce829efebe6`;
- local UDP `52281`, unused peer port `52282`, and
  `SDMOD_DISABLE_AUDIO=1`;
- Lua-exec/runtime-tick capture plus deterministic existing input seams, with
  a separate real-mouse Frost run;
- `runtimeSourceSeamAdded: false`;
- the controlled live rank-entry write used only to reach rank 2; and
- epsilons: `0.0001` world unit for serialized float32 trajectories, `16` ms
  for Windows tick timestamps, element-specific contact values shown above.

It contains rank-1 and rank-2 tick series for Ether and Fire actors, Air rays,
and Frost channel state; three rank-1 Earth charge/release series plus a
rank-2 170-frame series; the independent Frost mouse timeline; and contact
events with world distances and resulting HP changes. These are browser
goldens, not runtime automation instructions: tests should compare the
reimplemented mechanics to the stored native tick sequence within the header's
explicit epsilon and should never silently widen it.

## Evidence inventory

- Live raw captures and launch/cleanup records:
  `D:\codex-evidence\spellre-20260804\live\` and
  `D:\codex-evidence\spellre-20260804\lifecycle\`
- Read-only headless Ghidra transcripts:
  `D:\codex-evidence\spellre-20260804\static\ghidra-primary-dispatchers.log`,
  `ghidra-primary-constants.log`, `ghidra-projectile-lifecycles.log`,
  `ghidra-projectile-constants.log`, `ghidra-effects-and-application.log`, and
  `ghidra-remaining-ambiguities.log`
- Repository fixture:
  `tests/fixtures/webgame/projectile-goldens.json`
