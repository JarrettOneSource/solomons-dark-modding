# Native skills and spells

## Catalog result

The retail build has 82 compiled skill IDs. IDs `0..79` each resolve to one of
the 80 shipped `data/wizardskills/*.cfg` files; ID `80` is the runtime Plane
Orb row and ID `81` is a reserved/special-presentation row. The complete parsed
catalog is [`native-skill-catalog.json`](native-skill-catalog.json), generated
by `tools/build_native_skill_catalog.py`. It preserves every description,
quick description, display-stat format, bonus format, cap/max level, numeric
expression, evaluated value array, source filename, and source SHA-256.

Native identity is fixed in two places:

- `0x00657C00` maps integer IDs to names;
- `0x00674EE0` constructs the 0x70-byte entries, installs compiled metadata and
  prerequisites, and loads `data\wizardskills\<name>.cfg`.

The CFG parser recognizes 43 distinct properties. A CFG can tune arrays that
native code already queries, but adding an eighty-first file does not create a
new ID, picker entry, handler, projectile class, or icon selector.

## IDs, configuration properties, and art

The normal icon selector is initialized from the skill ID. `0x00665F10` feeds
that selector into the Skills atlas array whose serialized records are
`27..122`, so the stock icon record is `27 + selector`. Record `108` is both
the reserved selector 81 and the first of the special weld presentation
selectors; weld builds 1000..1009 select IDs `0x51..0x5A`, corresponding to
records `108..117`.

The cap/max column is `mCapLevel / mMaxLevel`. Element and discipline rows have
descriptions but no numeric cap/max table in their CFG.

| ID | Name | Family | Cap / max | Skills record | Tunable value properties |
| ---: | --- | --- | ---: | ---: | --- |
| 0 | Element of Ether | element | — | `27` | — |
| 1 | Element of Fire | element | — | `28` | — |
| 2 | Element of Air | element | — | `29` | — |
| 3 | Element of Water | element | — | `30` | — |
| 4 | Element of Earth | element | — | `31` | — |
| 5 | Body Discipline | discipline | — | `32` | — |
| 6 | Mind Discipline | discipline | — | `33` | — |
| 7 | Arcane Discipline | discipline | — | `34` | — |
| 8 | Magic Missile | ether | 20 / 25 | `35` | `mManaCost`, `mDamage1`, `mDamage2` |
| 9 | Smart Missiles | ether | 5 / 10 | `36` | `mSpeed`, `mManaCost` |
| 10 | More Missiles | ether | 8 / 12 | `37` | `mQuantity`, `mManaCost` |
| 11 | Call Leviathan | ether | 5 / 10 | `38` | `mDamage`, `mQuantity`, `mManaCost` |
| 12 | Planewalker | ether | 8 / 12 | `39` | `mDuration`, `mManaCost` |
| 13 | Piercing | ether | 3 / 8 | `40` | `mPierces`, `mLoss`, `mManaCost` |
| 14 | Ether Blast | ether | 4 / 6 | `41` | `mCharges` |
| 15 | Phasing | ether | 1 / 1 | `42` | `mManaCost`, `mCooldown` |
| 16 | Fireball | fire | 20 / 25 | `43` | `mDamage`, `mManaCost` |
| 17 | Embers | fire | 5 / 10 | `44` | `mManaCost`, `mDamage`, `mFragments` |
| 18 | Explode | fire | 6 / 12 | `45` | `mManaCost`, `mDamage`, `mRadius` |
| 19 | Embers to Imps | fire | 8 / 12 | `46` | `mDamage`, `mManaCost` |
| 20 | Immolate | fire | 5 / 8 | `47` | `mDamage`, `mManaCost` |
| 21 | Ring of Fire | fire | 5 / 10 | `48` | `mDamage`, `mManaCost` |
| 22 | Burn | fire | 3 / 8 | `49` | `mDamage` |
| 23 | Firewalker | fire | 3 / 8 | `50` | `mDamage`, `mDuration`, `mHoard` |
| 24 | Lightning | air | 20 / 25 | `51` | `mDamage`, `mManaCost` |
| 25 | Chaining | air | 6 / 12 | `52` | `mArcs`, `mManaCost` |
| 26 | Stun | air | 5 / 10 | `53` | `mStunAmount`, `mManaCost` |
| 27 | Magic Storm | air | 5 / 10 | `54` | `mDamage1`, `mDamage2`, `mManaCost` |
| 28 | Magic Tornado | air | 5 / 10 | `55` | `mSpeed`, `mDuration`, `mManaCost` |
| 29 | Hurricane | air | 5 / 10 | `56` | `mDamage1`, `mDamage2`, `mManaCost` |
| 30 | Prismatic Shock | air | 3 / 8 | `57` | `mDuration`, `mManaCost` |
| 31 | Disintegrate | air | 3 / 8 | `58` | `mChance`, `mManaCost` |
| 32 | Frost Jet | water | 20 / 25 | `59` | `mDamage`, `mManaCost` |
| 33 | Chill Wind | water | 5 / 10 | `60` | `mPushback`, `mManaCost` |
| 34 | Cone of Ice | water | 6 / 11 | `61` | `mWiden`, `mManaCost` |
| 35 | Ring of Ice | water | 5 / 10 | `62` | `mDamage`, `mManaCost` |
| 36 | Harden | water | 5 / 10 | `63` | `mArmorPlus`, `mMaxArmor`, `mManaCost` |
| 37 | Cold Aura | water | 4 / 10 | `64` | `mPercent`, `mRadius`, `mManaCost` |
| 38 | Hail | water | 5 / 10 | `65` | `mDamage1`, `mDamage2`, `mToHit`, `mManaCost` |
| 39 | Permafrost | water | 1 / 1 | `66` | `mSlowdown` |
| 40 | Boulder | earth | 20 / 25 | `67` | `mDamage`, `mManaCost` |
| 41 | Earthquake | earth | 5 / 10 | `68` | `mDuration`, `mManaCost` |
| 42 | Hasten Rocks | earth | 5 / 10 | `69` | `mSpeedUp`, `mManaCost` |
| 43 | Bind Rocks | earth | 5 / 10 | `70` | `mStrength`, `mManaCost` |
| 44 | Rock Surge | earth | 3 / 8 | `71` | `mChance`, `mManaCost` |
| 45 | Raise Golem | earth | 8 / 12 | `72` | `mHP`, `mDamage1`, `mDamage2`, `mManaCost` |
| 46 | Stoneskin | earth | 3 / 10 | `73` | `mDuration`, `mManaCost` |
| 47 | Gargantuan | earth | 3 / 8 | `74` | `mSize`, `mManaCost` |
| 48 | Teleport | arcane | 3 / 8 | `75` | `mCooldown`, `mManaCost` |
| 49 | Magic Circle | arcane | 3 / 8 | `76` | `mSlow`, `mManaCost` |
| 50 | Magic Trap | arcane | 8 / 12 | `77` | `mDamage`, `mManaCost` |
| 51 | Dampen | arcane | 1 / 1 | `78` | `mManaCost` |
| 52 | Spell Welding | arcane | 1 / 1 | `79` | — |
| 53 | Flash | arcane | 1 / 1 | `80` | `mChance`, `mDuration` |
| 54 | Magic Shield | arcane | 7 / 12 | `81` | `mAbsorb`, `mManaCost` |
| 55 | Explosive Shield | arcane | 1 / 1 | `82` | `mDamage`, `mManaCost` |
| 56 | Mana Up | mind | 8 / 12 | `83` | `mValue` |
| 57 | Channel Mana | mind | 5 / 10 | `84` | `mValue`, `mConcentration` |
| 58 | Meditation | mind | 3 / 8 | `85` | `mValue`, `mSeconds` |
| 59 | Battle Mage | mind | 6 / 11 | `86` | `mValue`, `mConcentration` |
| 60 | Focus | mind | 1 / 1 | `87` | `mValue`, `mConcentration` |
| 61 | Siege Mage | mind | 5 / 10 | `88` | `mValue`, `mConcentration` |
| 62 | Resist Magic | mind | 3 / 8 | `89` | `mConcentration`, `mValue` |
| 63 | Creativity | mind | 1 / 1 | `90` | — |
| 64 | Health Up | body | 8 / 12 | `91` | `mValue` |
| 65 | Enchant Staff | body | 10 / 15 | `92` | `mDamage` |
| 66 | Telekinesis | body | 1 / 1 | `93` | `mValue` |
| 67 | Rush | body | 3 / 8 | `94` | `mValue`, `mConcentration` |
| 68 | Deflect | body | 1 / 1 | `95` | `mValue` |
| 69 | Resist Poison | body | 3 / 8 | `96` | `mConcentration`, `mValue` |
| 70 | Faster Caster | body | 5 / 10 | `97` | `mValue`, `mConcentration` |
| 71 | Fortunate Flailing | body | 4 / 9 | `98` | `mChance` |
| 72 | Acid Rain | advanced | 5 / 10 | `99` | `mDamage`, `mManaCost` |
| 73 | Fire Wall | advanced | 5 / 10 | `100` | `mDamage`, `mManaCost` |
| 74 | Ether Drain | advanced | 5 / 10 | `101` | `mDamage`, `mManaCost` |
| 75 | Iron Golem | advanced | 4 / 8 | `102` | `mReflect`, `mManaCost` |
| 76 | Call Comet | advanced | 5 / 10 | `103` | `mFreeze`, `mDamage`, `mManaCost` |
| 77 | Turn Undead | advanced | 5 / 10 | `104` | `mFlee`, `mWeaken`, `mManaCost` |
| 78 | Mindstar | advanced | 3 / 8 | `105` | `mHoard` |
| 79 | Regenerate | advanced | 3 / 8 | `106` | `mHoard` |
| 80 | Plane Orb | runtime only | — | `107` | no CFG |
| 81 | Reserved/special | runtime only | — | `108` | no CFG; shared with first weld selector |

## Progression refresh and rank ABI

`Skills_Wizard` uses vtable `0x007A0CD4`. The methods that rebuild or
consume learned-skill state are:

| Vtable slot | Method | Recovered role |
| ---: | ---: | --- |
| `+0x04` | `0x00660210` | refresh thunk |
| `+0x08` | `0x006614D0` | specialized per-tick progression update |
| `+0x4C` | `0x00661530` | passive-stat/rank refresh |
| `+0x50` | `0x00661E40` | temporary Mindstar rank boost |
| `+0x54` | `0x006639D0` | clear toggles after mana overload |
| `+0x58` | `0x00656F60` | first equipment/stat pass |
| `+0x5C` | `0x00657310` | second equipment/stat pass |
| `+0x60` | `0x0067C360` | feature/equipment modifiers |
| `+0x64` | `0x006623F0` | spell caches, concentration, golem cap, and mana hoards |
| `+0x6C` | `0x00659A40` | Meditation activity/reset hook |
| `+0x74` | `0x0067CB70` | level-up option roll |
| `+0x78` | `0x006741B0` | mana-cost resolver |
| `+0x80` | `0x00661F40` | concentrated Focus recharge roll |
| `+0xA0` | `0x00666020` | primary/weld stat-vector builder |

The skill table begins at progression `+0x20`, has a compiled count at
`+0x24`, and uses the 0x70-byte rows described above. Row `+0x20` is the
permanent learned rank; row `+0x22` is the effective rank used during the
current refresh. Base refresh `0x0065F5B0` copies every permanent rank to its
effective rank before calling the equipment pass and Mindstar method. This is
why Mindstar can raise effective ranks without permanently modifying the
save-facing rank.

`ActorProgressionRefresh (0x0065F9A0)` preserves the current/max HP and MP
ratios, invokes the passive and equipment passes, validates both selected
primary and concentration entries, applies the `+0x60` and `+0x64` derived
passes, restores the ratios against the newly calculated maxima, and finally
clamps the values and updates dependent UI state. Max HP is at `+0x74`, max
MP at `+0x80`; current HP and MP are `+0x70` and `+0x7C`.

Mindstar byte `+0x8DD` makes `0x00661E40` walk IDs `8..78` (excluding
`78` itself). Every learned row receives one temporary effective rank,
clamped to the compiled maximum recovered through that row's property table.

## Passive body and mind skills

`0x00661530`, `0x006614D0`, and their direct consumers establish the
following native state. Names for scalar fields describe their proven
consumer, not an inferred C++ source name.

| Skill | Native state/application |
| --- | --- |
| Mana Up `56` | `maxMP(+0x80) = baseMP(+0x78) + mValue`. |
| Channel Mana `57` | Multiplies mana-recovery scalar `+0x98` by `1 + mValue/100`. |
| Meditation `58` | Converts `mSeconds` to idle-delay ticks at `+0x884`; stores `mValue - 1` at `+0x890`; `+0x888/+0x88C` hold idle elapsed/ramp state. `0x00656640` applies `((bonus + 1) * +0x98) / tickRate` MP recovery after the ramp. |
| Battle Mage `59` | Initializes scalar `+0x3D4` to `1 - mValue/100`. |
| Focus `60` | Initializes recharge scalar `+0xD0` to `1 + mValue/100`. |
| Siege Mage `61` | Initializes its combat scalar `+0xF8` to `1 + mValue/100`. |
| Resist Magic `62` | Adds `mValue/100` to resistance accumulator `+0xA4`. |
| Creativity `63` | Raises level-up choices from three to four and lowers the native picker eligibility requirement by two; concentrated Insight is detailed below. |
| Health Up `64` | `maxHP(+0x74) = baseHP(+0x6C) + mValue`. |
| Enchant Staff `65` | Adds `mDamage` to both staff-melee damage accumulators `+0xC4/+0xC8`. |
| Telekinesis `66` | Stores `mValue * 1.25` in pickup-range scalar `+0xCC`. |
| Rush `67` | Its learned `mValue` is read by the movement path; concentration modifies the refreshed movement multiplier at `+0x90`. |
| Deflect `68` | Writes `mValue` to `+0xB8` only while item type `0x1B5C` (staff) is equipped. |
| Resist Poison `69` | Adds `mValue/100` to duration-resistance accumulator `+0xA8`. |
| Faster Caster `70` | Initializes cast-speed scalar `+0x94` to `1 + mValue/100`. |
| Fortunate Flailing `71` | Read at staff-attack selection time; it does not create a permanent refreshed scalar. |
| Teleport `48` | Refreshes cooldown cap/current fields at row-relative `+0x1568/+0x1564`. |
| Phasing `15` | Refreshes cooldown cap/current fields at row-relative `+0x6F8/+0x6F4`. |
| Regenerate `79` | While toggle `+0x8DE` is active, `0x006614D0` adds `1.5 / tickRate` to current HP `+0x70` per tick. |

The general progression tick `0x00660220` also decrements timed power-up
fields `+0x824` (Damage x4) and `+0x828` (treat concentration-dependent
runtime branches as selected). It recovers MP by `+0x98 / tickRate`, capped
at `maxMP - hoardedMP`, and HP by `+0x9C / (tickRate * 10)`, capped at
max HP.

## Concentration

The local concentration collection at `0x00819E70` is queried at indices
`16` and `20` for the two selected slots. Actor-indexed paths use
`16 + participantSlot` and `20 + participantSlot`. Most direct combat
branches also accept timed override `progression + 0x828`; the Creativity
picker branch is a notable exception and checks index `16` directly.

The refresh switch at `0x00661FD0` and the individual action paths implement:

| Concentrated skill | Exact executable effect |
| --- | --- |
| Channel Mana `57` | `+0x98 *= 1 + mConcentration/100`. |
| Meditation `58` | `0x00659A40` stops resetting idle elapsed `+0x888` while the wizard walks or acts, allowing the lesser moving/acting recovery ramp to persist. |
| Battle Mage `59` | `+0x3D4 -= mConcentration/100`. |
| Focus `60` | `0x00661F40` rolls `0..99`; rolls `75..99` bypass normal recharge, giving the documented 25% instant-recharge branch. |
| Siege Mage `61` | `+0xF8 += mConcentration/100`. |
| Resist Magic `62` | `+0xA4 += mConcentration/100`. |
| Creativity `63` | On a level-up roll, `RandomInt(5) == 1` gives one eligible offered skill an Insight marker; selecting it applies that skill twice. |
| Enchant Staff `65` | Staff-action scalar `action + 0x34` is multiplied by the executable constant `1.75`. The CFG says “2x Attack Speed”; the shipped constant is not 2.0. |
| Telekinesis `66` | Doubles `+0xCC`. |
| Rush `67` | `+0x90 *= 1 + mConcentration/100`. |
| Deflect `68` | Reads missing property `mConcentration` and adds the resulting zero to `+0xA8`, the Resist Poison accumulator. No physical-reflection branch exists for selected ID `68`. This makes the CFG text “Reflects physical damage x5” nonfunctional in this executable. |
| Resist Poison `69` | `+0xA8 += mConcentration/100`. |
| Faster Caster `70` | `+0x94 += mConcentration/100`. |
| Fortunate Flailing `71` | Multiplies damage for any non-normal proc by `1.2`. |

`0x0065D540` returns zero for a property absent from a CFG, which is the
instruction-level reason the Deflect branch is inert. A search of all direct
ID-`68` comparisons found no second selected-ID handler that implements the
advertised reflection.

### Creativity Insight eligibility

The level-up screen constructor `0x00658620` initializes its Insight ID at
`screen + 0xFC` to `-1`. After the normal option roll, `0x0066F920`
requires concentration slot `16` to equal `63`, then succeeds only when
`RandomInt(5) == 1`. It filters the displayed option list using the following
native predicates:

1. if progression vtable `+0x30(optionId)` is true and the option's effective
   rank is zero, the option is skipped;
2. the current effective rank must be less than the option's compiled maximum
   minus two.

One remaining candidate is selected randomly and its skill ID is stored at
`+0xFC`. If the candidate list is empty, the field remains `-1`. The
machine code also compares the *option index* to `0x34`, not the option ID;
with three or four displayed choices this test never excludes Spell Welding.
The apply handler `0x00671470` compares the chosen ID to `+0xFC` and calls
`PlayerAppearance_ApplyChoice (0x00660320)` a second time on a match.

## Derived spell caches and mana hoards

`Skills_Wizard::RebuildCaches (0x006623F0)` materializes frequently consumed
CFG values:

| Offset | Source | Proven consumers/meaning |
| ---: | --- | --- |
| `+0x744/+0x748` | Flash `53` | chance and duration |
| `+0x890` | Meditation `58` | recovery bonus used by `0x00656640` |
| `+0x894/+0x898` | Firewalker `23` | damage and duration |
| `+0x89C` | Burn `22` | damage |
| `+0x8A0/+0x8A4/+0x8A8` | Hail `38` | damage range and to-hit |
| `+0x8AC/+0x8B0` | Cold Aura `37` | `1 - percent/100` and radius |
| `+0x8B4` | Permafrost `39` | `1 + slowdown/100` |
| `+0x8B8/+0x8BC` | Harden `36` | max armor and armor gain per tick |
| `+0x8C0/+0x8C4` | Piercing `13` | rounded pierce count and `1 - loss/100` |
| `+0x8C8` | Ether Blast `14` | rounded charge count |
| `+0x8CC` | Magic Missile family | cached value consumed by the mana resolver |
| `+0x8D0` | Ether primary line | sum of effective ranks for IDs `8,10,9,13,14,15,12` |
| `+0x8D2` | Disintegrate `31` | rounded chance |
| `+0x8D4/+0x8D8` | Hurricane `29` | two damage values |

The principal consumers are the primary handlers at `0x0053CFE0`,
`0x0053F9C0`, `0x00543860`, `0x00548B00`, `0x0054CAF0`, and the
effect paths `0x00541870`, `0x0054CC50`, `0x005F5C80`, and
`0x00624300`. Serialization `0x0067C830` writes the principal derived
fields in this block, including Firewalker state `+0x8DC`, so the
serialization boundary does not need to re-interpret every CFG property.

Toggle bytes `+0x8DC/+0x8DD/+0x8DE` are Firewalker, Mindstar, and Regenerate.
Each active skill reserves
`maxMP * mHoard / 100`; the normalized sum is stored at `+0x740`.
If the hoard exceeds max MP, `0x006639D0` clears the toggles, reserved and
current mana, and shows “Overloaded Mana!” for the local player.

`0x006741B0` is the mana-cost resolver, not a damage routine. It writes the
display/cache value at skill-row `+0x60` for the explicit cast IDs and weld
builds, then aggregates component costs for upgraded and welded spells.

## Staff melee, Enchant Staff, and Fortunate Flailing

`0x00537AA0` is entered only with equipped staff type `0x1B5C`. It reads
Fortunate Flailing `mChance`, rolls a float in `[0,100]`, and on success
selects one of four uniformly distributed outcomes. Failure uses selector
`0` and an ordinary `Action_PlayerWizard_StaffMelee`; outcome `4` uses
`Action_PlayerWizard_StaffSpin`, while outcomes `1..3` use the melee
action with a stored proc selector.

| Selector | Native outcome |
| ---: | --- |
| `0` | normal staff hit |
| `1` | Knockback: creates the `Knockback (0x7E9)`/impulse presentation path |
| `2` | Disabling Hit: scales target `+0x120` by `0.75` and, for actor-flag bit `1`, target `+0x1B4` by `0.5` |
| `3` | Critical Hit: multiplies base hit damage by `3` |
| `4` | Whirl: uses the spin action and a circular target query |

The constructors/ticks are `0x0044AE50/0x0044B580` for
`Action_PlayerWizard_StaffMelee` (vtable `0x00784A00`) and
`0x00448750/0x004487D0` for `Action_PlayerWizard_StaffSpin` (vtable
`0x00784564`). Concentrated Fortunate Flailing scales all selectors
`1..4` by `1.2`; concentrated Enchant Staff independently multiplies the
action timing scalar at `+0x34` by `1.75`.

## Raise Golem and Iron Golem

Raise Golem is skill-ID case `45` in `0x0054CC50`. It creates factory type
`0x7F4`, writes `mHP` to current/max HP `+0x170/+0x174`,
`mDamage1` to `+0x1F0`, `mDamage2` to `+0x1F4`, copies owner/world
identity, and places the summon at a collision-adjusted target point. Learned
Iron Golem `75` sets byte `+0x210` and writes `mReflect/100` to
`+0x214`.

Progression feature bit `+0x878 & 0x08` controls the summon limit. With the
bit clear, casting expires every existing golem owned by that wizard before
creating the new one: the effective cap is one. With the bit set, one existing
golem is retained; if two are already present, the lower-HP one is expired
before the replacement is spawned: the effective cap is two.

The class constructor/init/tick are `0x005F57E0`, `0x005F5B40`, and
`0x00615CD0`. Contact method `0x00607F60` ignores hits before summon age
`+0x208` reaches 400, then subtracts contact primary plus secondary damage
from HP. For an Iron Golem, a nearby actor source with actor-flag bit `1`
receives reflected primary damage `incomingPrimary * +0x214`, attributed to
the golem. HP at or below zero marks the summon for removal and starts
`0x00619730` death presentation.

The Golem atlas records `1..208` supply its assembled body-part arrays.
Direct supplemental art comes from BadGuys records `15,62,86,238..245,
2008..2010`, UI record `23`, and DeadHawg records `78..87`. Iron state
`+0x210` changes the assembled tint/piece treatment and the colors used for
the DeadHawg death fragments. The full actor lifecycle is also recorded in
[native-projectiles-and-effects.md](native-projectiles-and-effects.md).

## Cast routing

`PlayerActorTick` (`0x00548B00`) owns the cast state machine. It uses two
different native routes:

- `0x00548A00` dispatches sustained/current primary handlers from
  `actor+0x270`;
- `0x0052DA80` selects/starts one-shot/current actions through `0x0044F5F0`
  and scales the returned action object's damage. It is not itself a
  projectile allocator.

The sustained dispatcher cases already recovered are:

| Selected ID/build | Elements/spell | Handler |
| ---: | --- | ---: |
| `0x18` | Lightning | `0x0053F9C0` |
| `0x20` | Frost Jet | `0x00543860` |
| `0x28` | Boulder | `0x00544C60` |
| `1003` / `0x3EB` | Fire + Air | `0x005408F0` |
| `1004` / `0x3EC` | Water + Air | `0x00541870` |
| `1005` / `0x3ED` | Fire + Water | `0x00542D20` |
| `1006` / `0x3EE` | Ether + Earth | `0x00545360` |
| `1007` / `0x3EF` | Fire + Earth | `0x0052BB60` |
| `1008` / `0x3F0` | Water + Earth | `0x00545C20` |

The one-shot/current-action damage scaler recognizes Magic Missile (`8`),
Fireball (`16`), Plane Orb (`80`), and weld builds `1000`, `1001`, `1002`, and
`1009`. Together the two paths cover the ten mixed primary builds. Their
component/stat reconstruction is documented in
[spell-welding.md](spell-welding.md); ownership and cleanup are documented in
[spell-cast-cleanup-chain.md](../spell-cast-cleanup-chain.md).

## Action objects are presentation state, not spell objects

`0x0044F5F0` is the shared action selector. It allocates an `Action_*` object,
places it in an eight-byte reference-counted wrapper through `0x00528FD0`, and
registers that wrapper through `0x00641000`. The selector is shared by the
player, ordinary enemies, and bosses; its complete compiled mode table is:

| Mode | Native RTTI action |
| ---: | --- |
| `1` | `Action_PlayerWizard_StaffMelee` |
| `2` | `Action_PlayerWizard_StaffSpin` |
| `3` | `Action_PlayerWizard_StaffCast1` |
| `4` | `Action_PlayerWizard_StaffCast2` |
| `5` | `Action_PlayerWizard_StaffConstant` |
| `6` | `Action_PlayerWizard_HandCast1` |
| `7` | `Action_PlayerWizard_HandCast2` |
| `8` | `Action_PlayerWizard_HandConstant` |
| `9` | `Action_PlayerWizard_WandCast1` |
| `10` | `Action_PlayerWizard_WandCast2` |
| `11` | `Action_PlayerWizard_WandConstant` |
| `12` | `Action_Badguy_Point` |
| `13` | `Action_Badguy_Pause` |
| `14` | `Action_Skeleton_Claw` |
| `15` | `Action_Skeleton_WeaponAttack` |
| `16` | `Action_Skeleton_PikeAttack` |
| `17` | `Action_Skeleton_ShootArrow` |
| `18` | `Action_Skeleton_ThrowSpell` |
| `19` | `Action_Skeleton_CastShield` |
| `20` | `Action_Skeleton_CastShieldOther` |
| `21` | `Action_PlayerWizard_CastSpin` |
| `22` | `Action_PlayerWizard_Sweep` |
| `23` | `Action_Zombie_Beat` |
| `24` | `Action_Demonskull_Bite` |
| `25` | `Action_Demon_Spit` |
| `26` | `Action_Demonskull_EyeLasers` |
| `27` | `Action_Demonskull_MouthBeam` |
| `28` | `Action_Demonskull_SpitFire` |
| `29` | `Action_Demonskull_Scream` |
| `30` | `Action_Demonskull_Flair` |
| `31` | `Action_Faculty_Throw` |
| `32` | `Action_Faculty_TwoHandThrow` |
| `33` | `Action_Faculty_CastLightning` |

The first-cast ticks (`0x0044B370`, `0x0044B580`, and `0x0044B770`) advance
their animation timeline, choose a randomized animation selector for actor
`+0x238`, and call the owner's virtual `+0x58` when the action reaches its
armed frame. `PlayerWizard` installs `0x00550180` in that slot. Its cases update
cast pose, color, cooldown, and active-action state; for action modes `3`, `6`,
and `9` it calls `0x0054CAF0`. Those modes are staff, bare-hand, and wand
variants of the same first-cast action. `0x0052DA80` chooses among them from
the currently held item: staff type `0x1B5C` uses mode `3`, no held item uses
mode `6`, and another held caster item uses mode `9`.

This separates three native layers which must not be conflated:

1. `Action_*` owns animation timing and pose selection;
2. `PlayerWizard` owns selected-skill and active-cast state;
3. the cast handler creates and initializes the concrete projectile/effect.

## One-shot primary creation and initialization

`0x0054CAF0` is the proven one-shot dispatcher. It first invokes the equipped
item's virtual `+0x68`, then selects the handler below. World objects are
created by `GameObjectFactory_Create (0x005B7080)`, assigned the caster's
group/owner identity, and registered through `0x0063F6D0`. The missile,
fireball, and GroundSpark paths also test the initial world segment and route
an obstructed spawn through the object's impact/removal callback; Plane Orb
uses its separate attachment path.

| Selected ID/build | Handler | Created type | Initialization contract |
| ---: | ---: | --- | --- |
| `8` Magic Missile | `0x0053CFE0` | `0x7D3 MagicMissile` | Creates the learned quantity in an alternating heading fan; stores nearest-target group/slot, randomized damage, speed/turn scales, bounce/pierce state, and owner flags. |
| `16` Fireball | `0x0053DC60` | `0x7D4 Fireball` | Creates one aimed fireball; writes damage and Fireball-family secondary payload scalars at `+0x150..+0x15C`, randomized payload state at `+0x160/+0x164`, and three compact proc fields at `+0x168..+0x16E`. |
| `1000` Ether + Fire | `0x0053E6A0` | `0x7DE FireMissile` | Reads the rebuilt weld vector at progression `+0x774`; creates its quantity in an alternating fan and writes damage, inherited speed/turn scaling, secondary fire payload, bounce/proc state, and randomized seed at `+0x158..+0x178`. |
| `1001` Ether + Water | `0x0053F3C0` | `0x7E0 FrostMissile` | Uses the same weld-vector fan/target contract; writes damage and speed/turn scaling plus cold-area and slow payload fields at `+0x168/+0x16C`. |
| `1002` Ether + Air | `0x0053EDB0` | `0x7DF BallLightning` | Uses the same weld-vector fan/target contract; writes damage, inherited speed/turn scaling, electric payload magnitude/duration, and inherited missile state at `+0x168..+0x170`. |
| `1009` Air + Earth | `0x00545FC0` | `0x7E5 GroundSpark` | Creates a central spark and, outside the alternate/bot path, two side sparks. Each receives heading-derived motion plus vector-derived damage/effect fields at `+0x1A0..+0x1B0`. |
| `80` Plane Orb | inline in `0x0054CAF0` | `0x7EF PlaneOrb` | Creates one aimed orb, copies caster group/world identity, derives `+0x154` from equipped-item state, registers it, and triggers the cast sound/world-flash path. |

The three Ether-derived welded missile handlers all read the normalized vector,
not six CFG files at cast time. They consume the vector's first eight values,
randomize damage between its first two entries, alternate heading around the
aim angle, decay per-projectile scaling across the fan, and acquire the nearest
eligible actor through `0x00641160`. Consequently a custom weld implementation
must reproduce the vector ABI or replace these handlers; swapping projectile
art alone does not create a new weld behavior.

## Sustained primary behavior

Sustained casts run every player tick while the cast remains armed. Ray/cone
handlers keep target identity in wizard `+0x164/+0x166`; persistent Earth
actors keep world group/slot identity in `+0x27C/+0x27E`. The latter is looked
up on each tick and released by `0x0052F3B0`, so it is an identity handle rather
than a raw actor pointer.

| Selected ID/build | Handler | Native behavior and owned effects |
| ---: | ---: | --- |
| `24` Lightning | `0x0053F9C0` | Traces a beam from the cast origin, retains or reacquires a target, dispatches repeated contact, creates `Mod_Stun (0x1B6A)` when the learned stun scalar is active, emits `Anim_FadeLightning` wrappers, and uses `0x00641340` for the learned chain count. |
| `32` Frost Jet | `0x00543860` | Builds a widening cone, emits `Anim_FrostJetEffect`/`_Over`, queries actors through `0x00641B10`, applies damage, pushback, and `Mod_ColdSlow (0x1B69)`. Its learned branches emit `Anim_Hail`, run the Cold Aura circle query, and add Harden armor up to its configured maximum. |
| `40` Boulder | `0x00544C60` | Creates one persistent `Boulder (0x7D5)`, stores its group/slot handle, then repositions and re-aims it every cast tick. Gargantuan's `mSize` writes boulder `+0x1FC`; Rock Surge's `mChance`/`mManaCost` can move the active rock forward and invoke its surge behavior. |
| `1003` Fire + Air | `0x005408F0` | Reuses the Lightning beam/chain geometry, adds the normalized fire payload to the contact globals, can attach `Mod_Stun`, and emits the lightning fade chain. |
| `1004` Water + Air | `0x00541870` | Combines cone and chaining selection, creates frost/chaining animations, and can attach both `Mod_ColdSlow` and `Mod_Stun` before contact dispatch. |
| `1005` Fire + Water | `0x00542D20` | Emits `Anim_SteamJetEffect`/`_Over` stream actors and applies the normalized cone push. Their tick `0x0045B940` creates `Mod_Steamed (0x1B6C)` and dispatches the stored damage payload. |
| `1006` Ether + Earth | `0x00545360` | Creates a persistent `EBoulder (0x7E1)`, copies normalized damage, duration, size/split and related fields through `+0x230`, and retains it through the common group/slot handle. Its active path emits `Anim_BoulderBit` fragments and can arm recursive child splitting. |
| `1007` Fire + Earth | `0x0052BB60` | Emits `Anim_Iceblast` presentation at the aimed point and periodically creates randomized `Meteor (0x7E2)` actors. Each meteor receives normalized damage/fire payload fields at `+0x160..+0x17C`; impact behavior belongs to the Meteor lifecycle. |
| `1008` Water + Earth | `0x00545C20` | Creates a persistent `Hailstones (0x7E4)`, copies normalized damage, duration, size and impact fields through `+0x220`, retains its group/slot identity, and continuously follows the cast origin/heading. |

The factory creation portions of the three persistent Earth handlers are
guarded by caster group byte `+0x5C == 0` and an empty active handle. The code
therefore distinguishes the locally materializing caster from presentation of
another caster; this guard must be preserved or deliberately replaced by a
multiplayer spell protocol.

## Secondary and advanced spell dispatcher

`PlayerWizard` vtable `+0x6C` is `0x0054CC50`. Its second argument is a skill
ID, not an animation or factory ID. Every compiled top-level case is listed
below. Each mana-using case fetches the skill's configured mana cost, calls the
common spend/gate helper, and returns false without materializing the effect if
the payment fails.

| Skill ID | Skill | Native creation/application path |
| ---: | --- | --- |
| `11` | Call Leviathan | Creates `Leviathan (0x7F2)`, resolves a target point in front of the caster, writes configured damage/quantity state, registers it, and lets Leviathan spawn `EtherBolt (0x7F3)` children. |
| `12` | Planewalker | `0x00548700` toggles the state. Enabling allocates `Mod_Planewalker (0x1B75)`, writes `mDuration`, attaches it, saves the previous selected spell at wizard `+0x308`, and forces selected spell `80` (Plane Orb). Disabling routes through the modifier-removal helper. |
| `15` | Phasing | `0x0052A0B0` walks forward along the cast heading in collision-tested increments, accepts the first clear point within 20 probes, updates the wizard position/world membership, and emits the phase traversal effect. No separate cooldown is written by this helper. |
| `21` | Ring of Fire | Calls `0x0063F920`, which creates the ring's `MovingFire (0x7E6)` segments and final `Shockwave (0x7E7)` from the supplied damage/owner flags. |
| `23` | Firewalker | Toggles progression byte `+0x8DC`; enabling it creates `Fire_Goodguy (0x7EE)` and disabling it refreshes progression state. The player tick emits the trail while enabled. |
| `27` | Magic Storm | Creates `StormCloud (0x7F0)` at the aimed point, copies caster/world identity, damage range and arc state, and registers the persistent cloud. |
| `30` | Prismatic Shock | `0x00645540` creates the cast-wave presentation, performs a rectangular hostile query, and allocates/attaches `Mod_Prismatic (0x1B76)` through the contact ABI for every returned target. |
| `35` | Ring of Ice | `0x00644460` creates three `Anim_Iceblast` bursts, the radial debris field, and `FreezeWave (0x7E8)` with configured damage, owner identity, and optional item-effect flag. |
| `41` | Earthquake | Creates `Earthquake (0x7F1)` at the caster position and writes the configured duration before registration. |
| `45` | Raise Golem | Enforces the one/two-summon limit, creates `Golem (0x7F4)` at a collision-adjusted point, writes HP and both damage values, and folds learned Iron Golem reflection into the summon; see the detailed summon section above. |
| `46` | Stoneskin | Constructs `Mod_StoneSkin` directly through `0x006237A0`, writes configured duration, and attaches the reference to the caster; it does not create a world projectile. |
| `48` | Teleport | Calls `0x00644A00` around the world virtual `+0x12C` relocation query and writes the accepted destination back to the wizard. |
| `49` | Magic Circle | `0x0063FDE0` creates/index-registers `MagicCircle (0x7EA)` at the aimed point with `mSlow`, color, and ownership state. Every ten ticks the circle attaches `Mod_CircleSlow (0x1B70)` to eligible enemies and boosts local-player healing and mana recovery. |
| `50` | Magic Trap | Creates `MagicTrap (0x7F5)`. It derives an element selector from the current stock primary or weld build, derives base damage from that primary, multiplies it by `mDamage`, and registers the armed trap at the aimed point. |
| `51` | Dampen | `0x00648DF0` queries hostile magic in a rectangle, removes guided/fire/dark missile actors, disrupts hostile caster actions, and performs the CFG's 50% shield-dispel test; it then starts action mode `21` (`Action_PlayerWizard_CastSpin`) at half normal action damage. |
| `54` | Magic Shield | Combines Magic Shield `mAbsorb` with Explosive Shield state and calls the wizard's virtual `+0x64` to install/refresh shield state. |
| `72` | Acid Rain | Creates `AcidRain (0x7FE)` at the aimed point, writes configured damage and caster/world identity, then registers the persistent rain actor. |
| `73` | Fire Wall | Builds a line perpendicular to the aim vector and creates a series of `Fire_Goodguy (0x7EE)` patches along it, each carrying configured wall damage and caster ownership. |
| `74` | Ether Drain | Creates `EtherDrain (0x807)`, writes configured per-tick damage, resolves the aimed origin through the world, and registers it. |
| `76` | Call Comet | Calls `0x0063FD00`, which creates `Comet (0x80C)` with the configured freeze and damage values at the selected point. |
| `77` | Turn Undead | `0x00647EF0` queries the area and acts only on `Skeleton (0x3E9)`, `SkeletonArcher (0x3EA)`, `SkeletonMage (0x3EB)`, and `Zombie (0x3EE)`. It turns each away from the cast point, writes the flee heading/state, scales its attack strength by `mWeaken` when not already stamped, and records the current tick for the flee interval. |
| `78` | Mindstar | Toggles progression byte `+0x8DD`, refreshes progression state, and produces the activation presentation; no projectile class is allocated. |
| `79` | Regenerate | Toggles progression byte `+0x8DE`, refreshes progression state, and produces the activation presentation; regeneration then runs from player progression/tick state. |

The absence of other IDs from this switch is meaningful. Upgrades such as
More Missiles, Chaining, Embers, Chill Wind, Hail, Rock Surge, Cold Aura,
Gargantuan, and Iron Golem are consumed by their primary or summon handlers;
body/mind entries are passive progression modifiers. They do not each own a
separate castable projectile factory case.

### Status ownership details

`Mod_Planewalker` is native factory type `0x1B75`. Its apply callback
`0x00623800` sets target flag `+0x138 |= 0x10`; its removal/expiry callback
`0x00623810` enters `0x0052F470`, which restores player-side plane state. The
generic modifier merge callback `0x00626A60` keeps the greater remaining
duration when another modifier of the same type is attached. This explains why
the cast helper saves the former spell selection and forces Plane Orb: Plane
Orb is the active plane-side primary, while the modifier owns entry/exit.

Prismatic Shock and the elemental trap effects use the same modifier factory
and reference-counted attachment ABI as the primary missiles. Magic Trap's
selector adds `Burn (0x1B73)` for fire, `ElectricBurn (0x1B6B)` for air, and
`ColdSlow (0x1B69)` for water; ether/earth retain the trap's direct contact
payload without one of those three modifier branches.

## Remaining closure work

The 82-ID catalog, rank/refresh ABI, passive and concentration formulas,
primary/weld dispatch, secondary/advanced switch, staff proc table, spawned
factory types, modifier IDs, and principal object lifecycles are statically
mapped. This subsystem remains short of the phase-wide `Complete` label only
for indirect child-animation record joins and isolated live checks of the
highest-risk persistent effects, golem reflection, and native bugs documented
above. Enemy- and item-owned uses of the same modifiers are tracked in their
respective passes instead of being duplicated here.
