# Native survival combat lifecycle contract

## Scope and evidence boundary

This report is the integration contract for the Website `/game` survival
combat cutover. It joins the already recovered Solomon Dig encounter, wave
timeline, eight retail wave-enemy families, player progression, primary spells,
death/spectator ownership, and Game Over session flow. It does not replace the
specialist reports linked below; it records their causal ordering, exact values
needed by the web authority, bounded approximations, and unresolved evidence.

Addresses refer to retail Beta 0.72.5 `SolomonDark.exe`, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Static evidence came from the analyzed Ghidra project and read-only replicas.
Live evidence and generated catalogs are identified by the specialist reports:

- [Solomon Dig and wave director](native-solomon-dig-and-wave-director.md)
- [enemy behavior](native-enemy-behavior.md)
- [enemy animation state](native-animation-state.md)
- [enemy target acquisition](native-enemy-target-acquisition.md)
- [movement and fixed tick](native-movement-and-tick.md)
- [projectiles and effects](native-projectiles-and-effects.md)
- [primary spell mechanics](native-projectile-and-spell-mechanics.md)
- [progression and skills](native-progression-and-skills.md)
- [player death and spectator](native-player-death-spectator.md)
- [Game Over and session semantics](native-game-over-session-semantics.md)

## Native ownership thread

```text
late Dig-program proximity
  -> Solomon target/control/dialogue state
  -> SOLOMON RUNS event
  -> Arena TimeLine and Spawners
  -> evaluated immutable enemy config
  -> mutable ActorWorld enemy brain
  -> target, movement, action, projectile/contact
  -> enemy HP <= 0
  -> family terminal outputs and reward
  -> ActorWorld retirement
  -> authoritative live count releases the TimeLine pause
  -> player HP <= -10
  -> one death epoch and corpse presentation
  -> individual spectator while another eligible player lives
  -> all-eligible-dead terminal command
  -> Boneyard Game Over
  -> post-run front end
  -> Create/loadout with retained choices, explicitly reconfirmed
```

The wave timeline owns schedule selection and spawn requests. It does not own
live enemy transforms, action state, HP, projectiles, death effects, or
retirement. `ActorWorld` owns those actors and the live monster/boss counts
observed by the TimeLine pause predicates. Maggot construction explicitly
cancels the inherited Badguy-count increment, so Coffin-owned children remain
ActorWorld members but not TimeLine monster-count members. The Website must
preserve that separation: a wave director emits deterministic spawn intents and
observes the authoritative counted-enemy store; it must not keep a second
mutable enemy list or add Maggots to the wave predicate.
Actor and spell stores separately own ordinary contact retirement, recovered
terminal lifetimes, and any explicitly documented web safety horizon.

At 100 Hz, the integrated Website authority order is:

1. accept and gate participant input;
2. advance player movement and Boneyard collision;
3. advance Solomon and emit the one run edge;
4. refresh targets and step every pre-existing enemy, Maggot, enemy projectile,
   action marker, terminal output, and due retirement;
5. give the wave director that post-retirement live count, then materialize its
   spawn intents; newly materialized actors do not step until the next tick;
6. apply enemy contacts, statuses, and rewards to the player-owned stores;
7. advance primary spells, debit accepted mana, and resolve spell world/enemy
   contacts;
8. apply recovery and poison, enter player death epochs, emit the tick-159
   burst, and transition completed corpses to spectator;
9. evaluate the all-eligible-dead Game Over edge; and
10. publish compact state plus monotonic semantic events.

This order is an implementation contract assembled from native owners. The
stock executable does not expose it as one universal function, so family-
specific marker ordering remains authoritative where recorded below.

## Solomon-to-combat handoff

Solomon type `0x1391/5009` is owned by constructor `0x00481C20` and dispatcher
`0x0048A8B0`. Contact is enabled only while the 29-entry Dig program cursor is
strictly greater than 19. The closest same-Arena participant satisfying the
strict predicate is acquired:

```text
((solomon.x - player.x) / 1.5)^2
+ ((solomon.y - 10 - player.y) / 1.25)^2 < 10000
```

Only that participant is control-locked. The four uniformly selected hello
streams last 7.826508, 5.695306, 5.539342, and 7.343220 seconds. Native state 2
waits for both the global dialogue owner and queue to drain, then restores
control and begins the 25-tick retreat hold. `LAUGH1` lasts 2.463016 seconds;
`GETHIMBOYS` lasts 2.441088 seconds. State 3 adds `0.5` acceleration per tick.
The first positive-motion tick selects a seeded `-15/+15` deflection, enters
state 4, and fires trigger 15 `SOLOMON RUNS`. That edge, not proximity or
speech completion, starts the TimeLine.

Fresh read-only decompilation on 2026-08-22 pins the player-combat admission
edge to that same transition. State 2 body `0x0047D450` restores the selected
participant's paired controls and writes Arena `+0x902A`, but it does not call
the trigger dispatcher. State 3 body `0x0047D570` consumes the 25-tick hold,
then advances the retreat accumulator while Solomon remains in state 3. Only
when the accumulator becomes strictly positive does it write state 4 and call
`0x0068B6D0(Arena+0x8528, 15)` before constructing the escape path and cycling
walk program. The preserved no-wave live probe independently observed that a
left-click remained inert before the stock combat-prelude sequence and
latched a cast after that sequence. The Website consequence is one
authoritative gate: movement and primary-skill selection remain available,
but staff action admission, primary emission admission, and all category-2
cast inputs stay sealed through digging, turning, speaking, retreat hold, and
state-3 acceleration. They open on the state-4/`SOLOMON RUNS` tick itself.

Custom/mod Arenas without the retail Solomon actor are not members of this
gate. Existing action objects, cooldown recurrence, effect teardown, and world
presentation continue to tick; the gate suppresses new player-combat
admission rather than pausing the ActorWorld.

State 4 follows a precomputed 4096-unit collision-clipped path, starts at speed
2, adds `0.05/tick`, hops with `-3` then `+0.25/tick`, resets to `-2` on
landing, moves on its final tick, and retires after 515 ticks. Generated script
also locks the camera for four seconds and destroys off-camera objects.

The web port may use the exact PCM duration as the completion oracle for
Solomon's isolated serialized cue queue. It must identify encounter and cue
event cursors by run nonce, stop streams at run teardown, and resolve target
death/disconnect instead of wedging the turning state. The native 4096-ray
destination, global-dialogue interaction, camera script, and host migration
during the encounter remain open evidence and must be named as approximations.

## Enemy construction and evaluated defaults

`MonsterRecipe::Sync 0x0063E890` feeds `MonsterSetup_Parse 0x004AFBC0`, then
`BuildEnemyConfig 0x0046B390`, factory/application, placement, and ActorWorld
registration. Build an immutable evaluated config first; mutable actors copy
from it. The eight retail wave defaults before flags and Arena scalars are:

| Family | Type | HP | Primary damage | Base chase | Attack speed | Scale |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Skeleton | 1001 | 5 | 3 | 1 | 1 | 1 |
| Skeleton Archer | 1002 | 5 | 4 | 1 | 1 | 1 |
| Skeleton Mage | 1003 | 5 | 3 | 0.8 | 1 | 1 |
| Imp | 1004 | 1 | 3 | 1 | 1 | 1 |
| Zombie | 1006 | 105 | 35 | 1 | 1 | 1 |
| Wraith | 1007 | 2 | 4 | 1 | 1 | 1 |
| Demon | 1009 | 400 | 20 | 1 | 1 | 1 |
| Coffin | 1013 | 100 | no default write | 1 | 1 | 1 |

Coffin defaults are maximum Maggots 20, child HP 2, child damage 2, and child
poison 0. The product Loader pins the native player-count HP multiplier to one.
The Website should likewise avoid an invented multiplayer HP scalar until a
separate product rule is approved.

The exact wave-flag transforms recovered at `0x0046B390` are:

- `HPUP`/`HPDOWN`: HP times 1.5/0.5;
- `STRONG`/`WEAK`: primary, secondary, tertiary, and extra damage lanes times
  1.5/0.5;
- `FAST`: chase times 1.25;
- `SLOW`: chase and attack speed times 0.5;
- `BURNING`: chase and attack speed times 1.5 and burning enabled;
- `XPBONUS`: XP lane 2;
- `HELM`, `HORNED`, `HOODED`: headgear 1/2/3 and HP +6/+10/+3;
- `LEADING`, `SCATTERSHOT`, `RANDOMSHOT`: Archer accuracy/multi-shot modes
  1/2/3;
- `RANGEUP`, `RANGEDOWN`, `RANGEEASY`: family range modes 2/1/3;
- `SHIELD`, `SHIELDOTHERS`: self/other shield health 50 and interval 10;
  `SHIELDSTRONG` multiplies both shield-health lanes by 9 and `SHIELDFAST`
  halves the interval;
- `SPLIT`: remaining split depth 1..2. `SPLITMANY` uses
  `q = trunc((wave - 25) / 5)` and inclusive range `[q + 1,q + 3]`: a first
  draw below two writes two, otherwise a second independent draw from that
  range is the depth. Retail waves 35/42 therefore produce depth 3..5/4..6;
- `MANYMAGGOTS`: maximum 50; `STRONGMAGGOTS`: child HP/damage 5;
- `POISONARROW`: secondary damage primary times 3; `FIREARROW`: secondary
  damage primary;
- `ARMOR`: `(HP + 10) * 2`;
- `SWORD`, `MACE`, `FLAIL`, `AXE`: `(HP + 10) * 2`, primary damage
  +15/+25/+35/+18;
- `PIKE`: `(HP + 35) * 2`, primary damage +25;
- `CASTFIRE`, `CASTLIGHTNING`, `CASTFROST`, `CASTPOISON`: primary damage
  times 8/4/2/8;
- `ROTTEN`: poison-punch damage primary/6, pool damage primary/5, duration 10;
- `DEATHIMPS`: 5; `DEATHIMPSMANY`: 15;
- `ARMORMAYBE`: the constructor's random armor selection;
- `NOSKELETONS` and `MORESKELETONS`: their recovered family-policy lanes,
  with the latter also clearing self-shield and rotten state in the Website
  evaluated config.

Arena scalar lanes then multiply HP, four damage/duration lanes, chase,
attack speed, and XP. Source-only `IGNITE` and `IMMORTALIZE` are accepted by
the retail dialect but ignored at this builder and must not gain invented web
behavior.

Constructor collision radii are Skeleton `20-RandomFloat(8)`, Archer 20,
Mage 25, Imp `10-RandomFloat(2.5)`, Zombie `25-RandomFloat(8)`, Demon 35, and
Coffin 45, followed by recipe scale. Wraith's inherited radius is unresolved.
These are actor collision radii, not attack reach.

## Targeting, movement, and family actions

`0x00481A60` selects the nearest living eligible gameplay candidate in the
same ActorWorld. A death drive at actor `+0x160` makes a corpse ineligible.
Refresh is host-owned and bounded by the recovered 3/10-tick path-mode cadence,
the missing-target path, and common 25-tick lane. A target reference on the
wire must use semantic participant identity, never a peer-local ActorWorld
slot.

Common movement uses:

```text
S = badguy+0x1A4 * actor+0x70 * actor+0x120
delta = normalized_direction * 0.25 * S * cadence_ticks
```

Normal hostile eligibility is every two ticks; compensated family states use
5/10/15-tick cadences. World motion passes separation `0x0047CB20`, wrapper
`0x00475FE0`, and `MoveStep 0x00525800`. Browser interpolation may smooth the
published transform but cannot choose targets, advance actions, or infer
contacts.

Living players, enemies, and owned child actors participate in the same native
actor-circle contact domain. The Website must therefore put players, enemies,
and Maggots in one deterministic dynamic-contact set when either side moves
and commit every resolved displacement. Running the solver only for hostile
movement would let a player pass through a stationary enemy and would not
preserve the shared native collision contract.

Exact 100 Hz action boundaries at attack speed 1 are:

| Action | ID | First active marker | Completion | Recovery |
| --- | ---: | ---: | ---: | ---: |
| Skeleton claw | `0x0E` | tick 32 | tick 57 | 25 ticks |
| Skeleton weapon | `0x0F` | tick 36 | tick 97 | 61 ticks |
| Skeleton pike | `0x10` | tick 16 | tick 97 | 81 ticks |
| Archer shot | `0x11` | tick 155 | tick 190 | 35 ticks |

Skeleton markers can fire more than once; a live claw witness produced three
separate 3-damage callbacks at ticks 133, 134, and 161. Damage is therefore a
semantic action-marker event, not an animation-state Boolean. Mage action
`0x12` uses variable short/long programs with marker 25/31 and strict end
41/47 at rate `0.253125012*(1+roll)*attackSpeed`.

Entering windup does not permanently authorize a later hit. A melee action
stages the semantic target identity that began the action. At every damaging
marker, authority must re-check that staged identity is still the same living,
eligible target and is still inside the family contact/reach geometry. A
target that dies, disconnects, leaves reach, or is replaced by reacquisition
takes no marker damage. Exact per-family weapon shapes remain open; the named
center-distance Website bounds below are the temporary marker-time geometry.

That temporary geometry must remain coherent with the recovered native actor
response. `MoveStep` separates overlapping circles to
`actorRadius + targetRadius + 0.1`; the `0.1` is part of the shared native
collision contract, not optional render clearance. Website melee eligibility
therefore uses the greater of the named center reach and that complete settled
contact distance. Omitting the `0.1` leaves Skeletons, Imps, and some Zombies
permanently outside their own marker reach after ordinary collision response,
making player-forced transient overlap the only path to damage.

Confirmed family ownership beyond the Skeleton template is:

- Imp: flying approach/contact/cooldown; terminal split.
- Zombie: approach, action `0x17`, knockback; `ROTTEN` poison punch and death
  pool.
- Wraith: approach/orbit/retreat/attack, retreat `200+RandomInt(601)`, exact
  post-attack cooldown 50, alpha/fade state.
- Demon: approach, DemonBomb, recovery, terminal radial Imp split.
- Coffin: hidden/closed, rise/hold, opening, open. The opening edge invokes
  Maggot helper `0x00479C30` exactly three times; open state uses the recovered
  charge/probability emission program independently of the active-child cap. A
  Maggot emerges ballistically, enters inactive or active admission, and only
  an active child can bite once before its own death. Every lane is cleaned up
  when its stored Coffin parent no longer resolves.

Exact generalized marker/cooldown programs for Imp and Wraith remain separate
open rows. Zombie and Demon are closed by their later supersessions. The
2026-08-27 Coffin/Maggot supersession also closes charge-based emission, launch
segments/headings, active/inactive admission, count policy, and parent teardown;
the former bounded replenishment/emergence permission is revoked.

## Active Archer, Mage, and Wraith modifiers

The retail modifier lanes are runtime behavior, not definition-only metadata:

- Archer consumes arrow payload, accuracy mode, extra-arrow count, and range
  mode independently. Normal/fire/poison arrows remain distinct; `LEADING`,
  `SCATTERSHOT`, and `RANDOMSHOT` change authoritative aim rather than merely
  relabeling the projectile.
- Mage consumes element, range mode, self-shield toggle/strength, ally-shield
  toggle/strength, and their shared interval. Fire, lightning, frost, and
  poison must reach their projectile/direct-contact/status owners. Shield
  damage is absorbed before HP, and self/ally shields remain separate lanes.
- Wraith contact owns Dazzle; its orbit/fade brain does not reduce Dazzle to a
  generic cooldown or presentation-only timer. The independent burning lane
  likewise owns an attached fire effect rather than an inert config bit.

The Dazzle timing is exact native evidence. Wraith tick `0x00486C30`
constructs `Mod_Dazzle` type `0x1B6E`, initializes progress at modifier
`+0x1C = 0`, and writes duration `+0x14 = 0x32` (50 ticks).
`Mod_Dazzle::Tick 0x00623490` advances progress by the merged
`+0x20 = 1 / duration`, clamps it to one, and multiplies the target actor's
shared movement/status scalar at `+0x120` by that progress. The result is a
50-tick recovery ramp whose first affected movement tick is `1/50` and whose
last is `50/50`, not a 50-tick stun or constant slow.

The Website authority must consume all of these evaluated fields in actor,
projectile, shield, and player-status state. Exact native Archer angular/range
formulas and Mage range, shield-interval units, and temporary effect clocks
remain open; the explicit deterministic bounds below cover only those numeric
gaps. They do not make any modifier inert and do not weaken the exact Dazzle
ramp.

## Projectiles, contacts, and player resources

Archer creates Arrow `0x7DA`; Mage creates Firebolt `0x7EB`, GuidedMissile
`0x7EC`, or direct/status effects; Demon creates DemonBomb `0x7F7`; Rotten
Zombie creates PoisonPool `0x806`. Native contact seeds the context globals
through `0x006246F0` and dispatches `0x0063E7D0`; it is not equivalent to a
client calling `target.damage(number)`. The web port may express the same
ownership as a typed authoritative contact kernel, but projectile spawn,
impact, status, audio, and retirement must be discrete replicated events.

Fresh progression starts at HP 50 and MP 100. Native general recovery at
100 Hz is MP `10/100 = 0.1/tick`, capped at `maxMP-hoardedMP`, and HP
`1/(100*10) = 0.001/tick`. Level-up refills HP and MP. Rank-one primary costs
are Ether 6, Fire 12, Air 12/second, Frost 12.5/second, and Boulder 12/second.

Each primary spell's effective skill-book rank, not merely its permanent rank,
indexes the catalog mana and damage arrays. One-shot Ether and Fire pay on the
actual Staff emission marker and capture their rank-indexed payload then. Air,
Frost, and Earth invoke the debit on every active handler tick. Shared helper
`0x0052B150` is called with `rejectIfInsufficient=0`: it spends the available
remainder, clamps MP to zero, and returns underpowered when post-debit MP is
`<=0`. Exact-cost, partial-cost, and zero-MP pure-primary casts therefore all
materialize through a fixed weak branch; only a strictly positive post-debit
balance produces the normal branch. This supersedes the former bounded web
rule that rejected insufficient mana. Exact welded-spell debit and weak-branch
rules remain separately unresolved and must not be inferred from the pure
primaries.

Boulder captures the rank-indexed release base on its held actor. Its native
release finalizer is not linear `base*charge`: after weak/release ticks mutate
the stored base, it uses
`max(0.25,min((base*charge)*charge,base*1.25))`. Rank-one constants are
fixtures, not runtime authority after an upgrade.

Primary rank-one values already recovered are Ether random 1..2, speed 3,
radius 15 and homing/probe; Fire damage 4, speed 4.5, radius 22.5 and one
impact; Air and Frost damage 2.5/second with 205 reach; Boulder damage 10 times
the recovered charge-derived multiplier. Ordinary world/contact retirement
wins first. The Website additionally retains the PoC's 500-tick flight horizon
as an explicit resource-safety bound; it is not native lifetime evidence and
must not be described as recovered timing.

## Enemy and player death

Enemy damage clamps current HP to its maximum, subtracts prepared damage, and
tests `currentHP <= 0`. Family death then emits child/status/debris/audio and
reward outputs before ActorWorld removes the marked actor. Wave live count must
fall only after that terminal bookkeeping/presentation boundary. XP is awarded
once to the owning progression; family one-player baselines are Skeleton/
Archer/Mage 10, Imp 2, Zombie 210, Wraith 4, Demon 800, Coffin 200, Maggot 0.

Skeleton-family terminal presentation is an immediate body-to-shatter handoff,
not a generic corpse strip. Other exact or partial terminal owners are the
Imp split, Zombie DeadHawg/poison pool, Wraith fragments/flash, Demon records
55..61 plus split, and Coffin break ranges plus DeadHawg debris. Where exact
non-Skeleton cadence is unresolved, keep an explicit family terminal phase
long enough to deliver the recovered outputs; do not retire on the lethal
contact tick.

Player HP is allowed below zero. The lethal threshold is `HP <= -10`, which
arms a one-tick terminal countdown; zero displayed HP alone is not death.
Player death virtual `0x00534120` starts one death epoch, clears active casts
and attachments, creates one staff/wand bouncer, and sets death drive
`+0x160=1`. Dead input must be rejected before dispatch/publication.

The four-frame corpse selector holds the initial frame through death tick 152,
then selects frame 1 at 153..155, frame 2 at 156..158, and frame 3 from 159.
Fresh read-only decompilation of player death tick `FUN_00533520` confirms that
tick 159 also emits a finite `Anim_FadeMoveAdditive_Perspective` burst. That
edge sets the Arena red scalar to `0.25`, clears the burst object's grid byte
at `+0x36`, and writes render bias `+0xA0 = -1000`. Its texture pointer is
`DAT_00819978 + 0x7E0`; with the BadGuys table header `0x38` and record stride
`0xC4`, this resolves to BadGuys record 10. The closed constructor emits
exactly 18 actors at base angles `0,20,...,340` degrees with signed jitter
bounded by 8 degrees, radius `15 + RandomFloat(5)`, and speed
`3 + RandomFloat(1)`. Each starts at scale `(0.5,0.2)`, tint
`(0.5,0.5,0.5,1)`, damping `0.9`, and alpha one. Alpha loses `0.1` before
each move, so ages one through nine draw at `0.9..0.1` and age ten retires.
The Website must consume the `(run, player, death epoch)` tick-159 edge once
and render the complete record-10 set additively without late-join replay.
Its stable per-epoch random samples are a documented authority policy for the
unavailable process-global RNG position, not an open numeric approximation.
Negative internal HP may be clamped to zero in the protocol/HUD only when an
explicit life/death component carries the authoritative epoch and tick.

One dead multiplayer participant spectates while another eligible participant
lives; the world and waves continue. Only all eligible run participants dead
produces one host-authored, replay-safe terminal event for that run nonce.

## Game Over, run reset, and Website deviation

Retail Arena terminal `0x004633D0` performs audio actions then calls
`Game_OnGameOver 0x005CB570`. Boneyard mode is fade-only. Its entry black
starts at one, loses `0.025` per tick, and becomes clear at tick 40 while the
terminal Arena remains resident. `GameOver::Tick` synthesizes acceptance when
its Boneyard counter becomes exactly 1000; no mouse, keyboard, controller, or
multiplayer input owns that edge. The accepted-state branch runs on that same
tick, so the separate exit-black lane begins at `0.0025`, not zero, and adds
`0.0025` per tick. Exact black is reached at exit tick 400, the renderer arms
the close gate there, and a later tick follows stock cleanup through
MainMenu/Hall of Fame and then Create. The preceding element/discipline are
preselected, but explicit confirmation is required on Create. Game Over
retires a run; it does not tear down the loader lobby or transport.

The Website product request intentionally shortens the visible post-run path:
after automatic Game Over completion it returns directly to the retained-choice
Create/loadout screen in the same authenticated session. This is a deliberate
product deviation from the native Hall-of-Fame/MainMenu lineage. It must still
preserve the native Boneyard entry/hold/automatic-exit recurrence, retained
preselection, explicit loadout confirmation, and a fresh run nonce.

The Website also retains the player's learned progression/stat books when that
same-session loadout is confirmed. A native fresh Create generation after the
multiplayer match lifecycle starts base progression and does not retain prior
learned ranks merely because element/discipline are preselected. Retaining the
book is therefore a second deliberate Website product deviation, distinct from
the shortened visible route.

A new run must reset Solomon and event counters, wave state, actors/children/
projectiles, casts/channels, gates, player placement/cast/life/status, entity
replication baselines, interpolation histories, renderer views, event cursors,
and audio loops/streams. It retains session/lobby membership and identity, the
preceding loadout as preselection, and—under the explicit deviation above—the
progression books.

## Hit and terminal-effect ownership

The full native evidence is in
[native-enemy-hit-and-death-effects.md](native-enemy-hit-and-death-effects.md)
and the Skeleton extraction is independently pinned in
[skeleton-death-effects-re.md](../skeleton-death-effects-re.md). Common Actor
damage reaction `0x00627F80` writes the live hit latches to `1`; Actor tick
`0x00624AC0` subtracts exactly `0.05` per fixed tick. Actor render
`0x00624B40` then redraws the current action pose red with ordinary alpha
`min(remaining * intensity, 1)`. The latch is a 20-tick refreshed overlay. It
does not select a replacement frame, restart an action, become additive, or
use the Website's former five-tick white flash.

Death removes the living body and registers independent world effect actors.
The recovered family presenters create Bouncer, Unbind, Fade/MoveFade,
SmokyBouncer, Banish, SpriteArray, and ZAnim-owned output with their own stable
identity, art, transform, clock, blend, shadow, and retirement. Skeleton,
Archer, and Mage use the shipped-default Enhanced Effects shatter sequence
`113,113,113,115,118,121,120,119,116,121,120,119,116,117,117,117,117,117`,
a random skull `1819..1822`, record-86 Unbind, and evaluated equipment debris.
Ordinary enhanced Bouncers start with timer `10`, draw a black shadow at
`y+2` with Y scale `.75`, lose `.015` alpha per active update, and make a fresh
50-percent horizontal-damping RNG draw on every ground contact. The Skeleton
pike exception keeps timer `1.5` while retaining the shadow.

Unbind consumes the lethal secondary-damage bit rather than the Enhanced
Effects toggle. The current Website damage producer has no native secondary
component and must use the exact primary-only clocks: Skeleton family
`.75/.0225`, Imp `1/.025`, Zombie `.75/.05`, Wraith `1/.025`, and Coffin
`.75/.045` for initial alpha/loss per tick. A future secondary component must
carry the lethal bit explicitly and select initial alpha `1.25`; it may not be
inferred from spell element or final HP. Demon and Maggot do not create
Unbind.

Every death recipe and cosmetic RNG result is host-authored. Persistent effect
actors replicate as entity state so a late subscriber sees their current
sample without replaying their birth. Family sound, feedback, reward, child
spawn, and retirement edges remain ordered run-scoped events. The living actor
is not retained as a synthetic death-strip owner.

## Replication and presentation consequence

Each enemy is a first-class replicated entity with a stable type descriptor
and compact dynamic sample. Immutable descriptor data includes family,
evaluated flags/config, scale/radius, cosmetic construction variants, and
spawn identity. Dynamic samples include position, heading, target semantic ID,
brain/action/pose clocks, HP, alpha/articulation state, hit feedback, and death
epoch/tick. Shield current/maximum health and persistent attached-effect state
are authoritative dynamic lanes; they cannot be inferred from HP or rebuilt as
empty arrays on a client. Projectiles must preserve their normal/fire/cold/
poison payload subtype, owner, stable identity, and kinematic state. Maggots
must preserve Coffin ownership plus emergence/trajectory, bite/death, vertical,
and hit-feedback state. Player snapshots must preserve authoritative cold,
Dazzle, and poison status counters so host movement and client presentation
refer to the same status epoch.

Monotonic run-scoped events carry attack contacts, impacts, audio, rewards,
death starts, and Game Over. Persistent effects such as burning, shields, and
the bounded Mage lightning sample belong in replicated state; one-shot impact,
terminal, and audio consequences belong to semantic events. In particular,
the Skeleton/Archer/Mage terminal edge owns registry entry 79 / object
`+0xDAC`, `sounds\\skeleton_die`, at randomized pitch `[0.8,1.0)`; entry 80
`sounds\\skellyscream` is the adjacent `+0xDD8` object and is not the
presenter's call. A client scene
consumes that host event once rather
than inferring it from interpolated HP or replaying retained history on late
join.

Clients interpolate only continuous transforms and pose clocks. They do not
select targets, regenerate missed event cadence, infer death from HP, or replay
historical audio on late join. Descriptor baselines are keyed by run nonce and
support spawn, retire, periodic keyframe, gap recovery, and stale-frame
rejection. Protocol decoding must fail closed when a required modifier,
projectile payload, shield, status, Maggot phase, or effect lane is missing or
malformed; zero/default reconstruction and unconditional `effects: []` are not
compatibility behavior. A schema unable to carry those lanes requires an
explicit version change before shipping. Client event cursors are run-scoped
and consume each new semantic event exactly once.

## Named Website completion bounds (not native evidence)

The 2026-08-14 Website cutover uses the following deterministic policies only
where the native programs above remain open. These values make the requested
survival loop complete; none is promoted to recovered retail timing:

- locomotion advances one gait pose per 2 world units;
- unresolved direct-action programs are Imp contact marker/end/cooldown
  `6/11/18` and Wraith drain marker/end/cooldown `4/9/50`. Demon bomb is now
  recovered as selector array `[0,0,0,1,1,1,1,1,0]`, rate
  `0.09375 * attack_speed`, marker 4, and strict end 8. Zombie beat is now
  recovered as selected-arm pose thresholds 50/100, locomotion threshold 80,
  hit marker 100, completion 125, and constructor rate
  `(0.9 + RandomFloat(0.25)) * attack_speed`. A deterministic network port can
  serialize that constructor roll without claiming the retail global RNG
  sequence.
  Coffin is excluded from this direct-action list: it uses the exact
  three-helper opening edge and the exact charge/admission child program below;
- Archer range modes 0/1/2/3 use bounded `(minimum, maximum)` bands
  `(120,240)`, `(80,180)`, `(180,320)`, `(100,320)`; Mage modes use
  `(100,220)`, `(70,165)`, `(150,300)`, `(80,300)`. Archer leading projection
  is capped at 60 ticks, scatter/random offsets are `+/-12`/`+/-25` degrees,
  extra-arrow spacing is 4 degrees, and at most eight extra arrows are
  accepted. These are web bounds, not recovered native formulas;
- center-distance attack reaches are Demon 180, Imp 28, Skeleton 36, Archer
  240, Mage 220, Wraith 52, and Zombie 48; melee marker eligibility is the
  greater of that family bound and
  `actorRadius + targetRadius + nativeSeparationEpsilon` as required above;
- terminal presentation windows are Demon 49, Imp 19,
  Skeleton/Archer/Mage 24, and Wraith/Zombie 36 ticks;
- enemy projectile `(speed, contact radius, lifetime, homing)` programs are
  Arrow `(5,8,300,false)`, Firebolt `(4.5,10,300,false)`, Guided Missile
  `(3,12,400,true)`, Demon Bomb `(2.5,18,400,true)`, and stationary Poison Pool
  `(0,35,1000,false)`;
- Coffin's opening edge requests three helpers. Its exact open-state follow-up
  uses `ratio=charge/(baseSpeed*timeScale)`: ratio below one emits three, while
  ratio at least one emits one when `Float(ratio)<1`; charge adds `0.025` to a
  cap of ten. Births are not capped. Maggot ballistic emergence selects one of
  the two recovered launch segments/headings after retained `+/-1` X scale and signed
  `Float(15)` rotation, mirrors heading for negative scale, and consumes two
  independent `Float(8)` offsets. Its `Float(5)` visual phase advances by
  float32 `0.25` modulo five while height-dependent gravity/bounce runs; there
  is no 24-tick duration. Landing promotes only when active
  count is below the configured maximum and `Integer(5)==3`; otherwise the
  first 30 inactive children remain noncombat and later failed admissions
  retire. An invalid or non-Coffin parent retires every child lane. Active
  children retain the already recovered one-bite/poison/death contract;
- bounded modifier clocks are 300 ticks at movement scale 0.5 for Mage frost,
  three seconds for Archer/Mage poison, 100 ticks per Mage shield-interval
  config unit with ally range 240, and four ticks for the Mage lightning
  effect sample. The Wraith's 50-tick Dazzle ramp is exact native evidence,
  not part of this bounded list;
- Wraith collision radius is 20. Imp splitting is exact rather than a web
  bound: each permitted death emits two children at one-lower depth, the
  pre-pair live-Imp guard is 68, and persistent Imp construction is capped at
  70;
- overlapping poison keeps the strongest damage-per-tick lane and the longest
  remaining duration, rather than claiming an unrecovered native stacking
  rule;
- the swept Boulder combat/world tie-break uses a point path (radius 0) because
  the exact native Boulder collision radius remains open; and
- player spell projectiles retire after ordinary contact/world resolution or,
  failing that, the explicit 500-tick safety horizon described above.

Changing any bound requires updating this report, the Website parity ledger,
and focused actor/config/combat tests together.

## Open evidence and acceptance boundary

The remaining native gaps are:

1. exact action programs for Imp and Wraith;
2. numeric physics for non-Skeleton Banish/SpriteArray/MoveFade/SmokyBouncer
   branches beyond the recovered class, art, fan-out, and ownership. Wraith
   body opacity, Imp flight presentation, Zombie articulation, and Demon
   joint/bob clocks are closed by renderers `0x00496220`, `0x00492E10`,
   `0x00493390`, and `0x00498BA0` plus their constructor/tick writers;
3. Wraith inherited collision radius and family-specific attack reach;
4. upgraded Health Up/Mana Up HUD denominators;
5. exact debit edges for every primary handler and welded build;
6. exact Archer range/aim formulas, Mage range/shield interval units, and
   unresolved elemental status/effect clocks;
7. global dialogue overlap, Solomon's 4096-ray/camera script, and unusual
   same-Arena re-entry;
8. host migration during encounter, combat, or terminal arbitration;
9. custom Boneyard TimeLine/boss scripting.

Those gaps permit named, deterministic, family-specific web timings needed to
make the requested survival loop playable. They do not permit client authority,
unlabeled or unbounded retirement, generic family reskins, snapshot-inferred
semantic events, dropped modifier fields, zero-filled status/effect/shield
state, or claims of exact native timing. Acceptance requires upgraded primary
ranks to change both debit and captured damage, marker-time target/reach
falsifiers, two-way player/enemy and player/Maggot separation, active runtime
tests for every retail Archer/Mage/Wraith modifier, exact Coffin charge and
Maggot admission/count/one-bite/parent cleanup, strict replication round trips,
and at least one host event driving a scene effect exactly once. Those focused
contracts sit alongside protocol lifecycle/recovery, two-client spectator/Game
Over, asset/record, audio-event, and real Chromium end-to-end coverage, followed
by the Website's canonical validation gate.
