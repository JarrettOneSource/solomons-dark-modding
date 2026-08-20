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

The two limits have different executable ownership. Offer predicate
`0x0065ED00` stops ordinary permanent offers once the permanent rank reaches
`mCapLevel`; apply helper `0x00660320` and Mindstar refresh hard-clamp only at
`mMaxLevel`. A Creativity Insight double-apply can therefore take `cap-1` to
`cap+1` when max permits, after which the row is no longer ordinarily offered.
Property reader `0x0065D540` clamps every requested array index to
`[0,length-1]`, so short arrays repeat their terminal value. In particular,
Embers to Imps ID 19 uses `mManaCost[8]=62` for every effective rank at least
eight; it never reads out of bounds or interpolates.

### Level-up card art and text ABI

`0x006720F0` renders each ordinary offer as Skills record 13, record 164 in the
skill root tint, frame record 5, then the icon shadow/main pair. The eight
packed root tints, in root order Ether, Fire, Air, Water, Earth, Body, Mind,
Arcane, are `#FFE5FF`, `#FFCBCB`, `#E5FFFF`, `#CBCBFF`, `#CBFFCB`, `#FFE5CB`,
`#CBD8FF`, and `#E5E5E5`. Advanced rows retain their actual root tint rather
than sharing a generic advanced color.

Centered text wrapper `0x004A57C0` does not itself change case. The ordinary
offer uses the compiled uppercase display name resolved for its row, while the
quick description preserves source case from the CFG. This split is also
capture-proved: `RING OF FIRE 2` uses the uppercase medium advance 135, while
`blast all` / `surrounding` / `enemies` use lowercase advances 82/116/69. At
the observed card top `302.5`, the ordinary card lanes are:

- medium name at Y `452.5`, maximum width 140, with rank suffix appended;
- skill-font family at `452.5 + measured wrapped-name height`;
- body-font lowercase `primary cast` for category 1 or `secondary cast` for
  category 2 at Y `582.5`; other categories leave this lane empty;
- medium quick description in pure white, no shadow, maximum width 140,
  vertically centered around Y `532.5`.

Name, family, and classification draw opaque black at `(+1,+1)` before the
root-tinted main pass. Medium height is 16 with a 17-pixel line step. Family
strings deliberately retain the spaces left after removing the compiled root
labels: ` ETHER`, ` FIRE`, ` AIR`, ` WATER`, ` EARTH`, `BODY `, `MIND `, and
`ARCANE `. The extracted lowercase medium glyphs visually read as small caps;
changing the provided case changes advances and is not equivalent. Welding
replaces the ordinary record-164 tint with its split mesh and uses the special text
contract in [`spell-welding.md`](spell-welding.md).

That classification call is a static card-function ABI, not yet a proved
visible level-up-offer lane. The same-SHA sealed Ring-of-Fire offer capture has
no classification pixels at Y `574..583`, although row 21 is category 2 and the
Wizard path constructs `secondary cast`. Current offer-surface parity must
suppress this lane until a targeted live call/clip-state capture resolves the
runtime condition; name, family, and white description are directly visible.

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
| Meditation `58` | Converts `mSeconds` to idle-delay ticks at `+0x884` and stores `mValue - 1` at `+0x890`; `+0x888/+0x88C` hold idle elapsed/activity ramp. `0x006614D0` increments elapsed, calls `0x00656640` once elapsed reaches the delay, then decrements the activity ramp toward zero. The helper applies `+0x98 * multiplier / tickRate`, where `multiplier=mValue` at zero ramp and `1+(mValue-1)*0.25` while the ramp is positive. |
| Battle Mage `59` | Initializes scalar `+0x3D4` to `1 - mValue/100`. |
| Focus `60` | Initializes recharge scalar `+0xD0` to `1 + mValue/100`. |
| Siege Mage `61` | Initializes its combat scalar `+0xF8` to `1 + mValue/100`. |
| Resist Magic `62` | Adds `mValue/100` to resistance accumulator `+0xA4`. |
| Creativity `63` | Raises level-up choices from three to four and lowers the native picker eligibility requirement by two; concentrated Insight is detailed below. |
| Health Up `64` | `maxHP(+0x74) = baseHP(+0x6C) + mValue`. |
| Enchant Staff `65` | Adds `mDamage` to both staff-melee damage accumulators `+0xC4/+0xC8`. Property reader `0x0065D540` clamps rank indices to the last authored value; the declared rank 15 therefore reuses `mDamage[14]=36` instead of reading out of bounds. |
| Telekinesis `66` | Stores `mValue * 1.25` in pickup-range scalar `+0xCC`. |
| Rush `67` | Its learned `mValue` is read by the movement path; concentration modifies the refreshed movement multiplier at `+0x90`. |
| Deflect `68` | Writes `mValue` to `+0xB8` only while item type `0x1B5C` (staff) is equipped. |
| Resist Poison `69` | Adds `mValue/100` to duration-resistance accumulator `+0xA8`. |
| Faster Caster `70` | Initializes cast-speed scalar `+0x94` to `1 + mValue/100`. |
| Fortunate Flailing `71` | Read at staff-attack selection time; it does not create a permanent refreshed scalar. |
| Teleport `48` | Refreshes cooldown cap/current fields at row-relative `+0x1568/+0x1564`. |
| Phasing `15` | Refreshes cooldown cap/current fields at row-relative `+0x6F8/+0x6F4`. |
| Regenerate `79` | While toggle `+0x8DE` is active, `0x006614D0` adds `1.5 / tickRate` to current HP `+0x70` per tick. Together with the generic health-regeneration lane below, the exact per-update total is `(1.5 + (+0x9C)/10) / tickRate`, capped at max HP. |

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
| Meditation `58` | Activity hook `0x00659A40` increments ramp `+0x88C` up to the configured delay and ordinarily resets idle elapsed `+0x888`. Concentration suppresses only that elapsed reset, so walking/acting retains the exact quarter-strength bonus while the positive ramp counts down. |
| Battle Mage `59` | `+0x3D4 -= mConcentration/100`. |
| Focus `60` | `0x00661F40` rolls `0..99`; rolls `75..99` bypass normal recharge, giving the documented 25% instant-recharge branch. |
| Siege Mage `61` | `+0xF8 += mConcentration/100`. |
| Resist Magic `62` | `+0xA4 += mConcentration/100`. |
| Creativity `63` | On a level-up roll, `RandomInt(5) == 1` gives one eligible offered skill an Insight marker; selecting it applies that skill twice. |
| Enchant Staff `65` | Staff-action scalar `action + 0x34` is multiplied by the executable constant `1.75`. The CFG says “2x Attack Speed”; the shipped constant is not 2.0. |
| Telekinesis `66` | Doubles `+0xCC`. |
| Rush `67` | `+0x90 *= 1 + mConcentration/100`. |
| Deflect `68` | The refresh switch still performs its harmless missing-`mConcentration` read, but the actual advertised effect is event-owned in `PlayerActorMagicDamage 0x00548150`: after a successful Deflect, concentration slot 16 or 20 containing ID 68 (or active Mind Chug) reflects five times the positive physical damage to a nearby non-null source. |
| Resist Poison `69` | `+0xA8 += mConcentration/100`. |
| Faster Caster `70` | `+0x94 += mConcentration/100`. |
| Fortunate Flailing `71` | Multiplies damage for any non-normal proc by `1.2`. |

The refresh-side `0x0065D540` read does return zero for the property absent
from the CFG, but it is not the reflection owner. Raw retail instructions in
`PlayerActorMagicDamage 0x00548150` close the separate contact-time branch:
`0x005481A6` draws `RandomInt(100)`, `0x005481AF` loads the refreshed Deflect
chance at progression `+0xB8`, and `0x005481BC` misses when the draw is at
least the truncated chance. A success turns/faces the wizard and requests the
swipe feedback at `0x005481C4`; `0x00548274..0x005482D7` then checks both
concentration slots for ID 68 or the timed Mind Chug override. With a non-null
nearby source and positive physical damage, `0x0054837B` multiplies by the
double constant `5.0` at `0x007DE8D8`, rewrites source/target context, and
calls the damage endpoint `0x0063E7D0` on the original source at
`0x005483A3`. The old “inert Deflect” conclusion came from stopping at the
refresh switch and is superseded by this event-time consumer.

The swipe request uses the exact pitch `1+RandomFloat(1,signed)`.

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
Firewalker reserves its scalar `mHoard` as an absolute MP amount (stock value
50). Mindstar and Regenerate reserve `maxMP * mHoard / 100`. The summed
absolute MP hoard is stored at actor progression `+0x740`.
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

The automatic admission and contact geometry are now instruction-closed.
`PlayerActorTick 0x00548B00` scans the existing contact list in stored order
and starts only when the first target has strict absolute heading delta below
50 degrees. The StaffMelee constructor always consumes `Float(.05)` after the
proc selection, stores progress `0.1+draw`, then consumes `Integer(8)` and
multiplies by `1.35` only on result two. Its marker is progress three and its
strict end is progress above eight. The two pose programs are
`0,4,5,6,6,6,6,6,6` and `0,1,2,3,3,3,3,3,3`; the player alternates those
banks after every melee construction. StaffSpin consumes one
`RandomSign(1)` word, turns exactly 20 degrees per tick, holds pose three, and
contacts after 18 ticks when its 360 countdown reaches zero. Concentrated
Enchant Staff multiplies StaffMelee progress by 1.75 and does not accelerate
StaffSpin.

`PlayerWizard_StaffContact 0x0053B9F0` owns three exact target shapes, rotated
by the wizard heading and translated to its root:

| Selector | Damage target footprint and selection |
| ---: | --- |
| 0 normal, 1 Knockback, 2 Disable | trapezoid `(-40,-70),(40,-70),(30,0),(-30,0)`; if effective Enchant Staff rank is zero, consume `Integer(candidateCount)` and retain one candidate, otherwise retain the full ordered list |
| 3 Critical | larger trapezoid `(-60,-105),(60,-105),(45,0),(-45,0)` and retain every flag-2 actor whose center is inside |
| 4 Whirl | strict circle radius 100 through `0x00642090`, whose exact test is `distanceSquared < 100^2 + targetRadius^2` |

The trapezoids are constructed once in `PlayerWizard_Ctor 0x0052B4C0` from
the float constants at `0x00785900/0x00793F6C/...` and transformed through
`0x00402CC0/0x00403120/0x00404850`; they are not approximated cones or
touching circles. Contact damage is
`max(1, Skills_Wizard_DamageResolver(row65,mDamage))`. Critical multiplies
that by three; any concentrated non-normal proc multiplies by 1.2. Every
non-Whirl target receives `min(total,2*total/count)` and Whirl receives the
full total per target.

The callback then runs a second, ordered pass over physically contacting
targets that still satisfy strict heading delta below 50 degrees. Its RNG is
after the optional rank-zero damage-candidate selector. Per target it consumes
`Float(1)` and writes `target+0x22C = -(1+draw)`, then signed `Float(.1)` and
plays registry offset `0xEB4`, `sounds\\staffhitwood`, at pitch `1+draw` with
point gain. The recovered `+0x22C` gameplay consumer is Imp vertical velocity.
Ether (`player+0x5C == 0`) alone then consumes `Float(200)` and succeeds when
the draw is nonzero and `<= progression+0xC8`, the secondary Staff-damage
accumulator. Success attaches `Mod_Knockback 0x1B6D`: normalized direction
away from the player, displacement six, duration five, and no damage.

For a contacted Skeleton whose live weapon selector `+0x231` is five, the
same successful Ether branch calls `0x00484EA0`. That helper plays registry
offset `0x13E4`, `sounds\\pikebreak__stream`; writes selector zero and calls
`0x00484B30` to rebuild an unarmed action program; creates one additive
perspective BadGuys 15 fade 75 units along Skeleton heading at scale three,
alpha one, loss `.025`; and writes the Region to the Skeleton color (white),
alpha one, loss `.1`. The Region write is full-screen feedback, not a light.

The helper also creates exactly seven world-owned BadGuys 55 `Anim_Bouncer`
children. Construction consumes one `Float(360)` angle seed and, per child,
the four base-constructor draws `Float(3), Float(20), Float(360), Float(10)`,
then radial `Float(10)` and signed `Float(10)` for the next angle: 50 words in
total. Initial velocity is the heading unit scaled `(1.5,1)`; position uses
radial `15+draw` plus an X-only two-velocity lead. Opacity starts at
`2*.75 = 1.5` and loses `.015` per tick. Each child is linked and receives one
immediate `Anim_Bouncer_Tick 0x00458D80`; later contacts consume `Float(10)`,
`Integer(3)`, optional `Float(.2)+Integer(4)`, then `Integer(2)`, with `.65`
bounce/damping. Draw `0x004540B0` emits one BadGuys 55 sprite at height with
alpha clamped to one; there is no shadow, tint, scale override, or light.

Selectors 1, 3, and 4 also create `Knockback 0x7E9` with distinct native
queries: Knockback uses an 80-degree radius-100 arc and 150 units of retained
push, Critical a 60-degree radius-100 arc and 50 units, and Whirl the full
radius-100 circle and 50 units. `Knockback_Tick 0x00600220` applies
collision-aware `min(remaining,10)` displacement to its construction-time
target list. On terminal update it attaches 200-tick Dazzle and consumes one
signed `Float(45)` heading perturbation per surviving target.

The marker always plays registry 86 `sounds\\staffswoosh` at
`1+(actionRate-0.10000000149011612)`. This is the same exact double stored at
`0x007849E8` and added before the constructor rounds its base action rate to
float32; the separate `0x007849F0` value `.05000000074505806` is only the
random jitter bound. Raw `.rdata` bytes also pin the rare acceleration double
at `0x007849E0` to `1.350000023841858`. Proc feedback is additional and
point-attenuated:
selector 1 plays registry 50 `Knockback` at `1+signed Float(.1)`; selector 2
plays registry 21 `DisableEnemy` at pitch one; selector 3 plays registry 18
`CriticalHit` at `1+signed Float(.1)`; selector 4 plays registry 83
`spinattack` simultaneously at pitches `1`, `.9`, and `1.1`.

The complete contact VFX membership has no world-light writer:

- Knockback and Critical each construct an `Anim_SmokePuff` using BadGuys 15
  25 units along the wizard heading, alpha one, alpha loss `.05`, and scale
  eight. Its constructor still consumes the overwritten `Float(.05)` loss and
  a `Float(2)` angular-rate draw before the handler sets the final loss.
- Disable constructs exactly 50 additive BadGuys-45 MoveFades. One
  `Float(360)` seeds the angle; each child then consumes `Integer(5)+20` for
  the next angle, `Float(3)+3` speed, and `Float(.75)+.25` scale. It begins at
  the mean damaged-target position plus three velocity steps, uses alpha 1.5,
  loss `.05`, velocity factor `.92`, and the wizard element tint.
- Critical additionally constructs one additive BadGuys-40 MoveFade at
  `(player.x,player.y-15)`, velocity five along heading, scale four, alpha two,
  loss `.25`, and the element tint.
- Whirl constructs one additive perspective BadGuys-88 fade at the player,
  with `Float(360)` rotation, scale three, alpha 1.25, loss `.1`, and the
  element tint.

## Telekinesis downstream consumer closure

The complete non-stack read census of refreshed progression `+0xCC` contains
only Orb `0x005E62E0`, Gold `0x005E66B0`, Sack `0x005E6B50`, and Bonus
`0x006039C0`. Row 66 stores float32 `mValue*1.25`; rank-zero/rank-one authored
values one/five therefore produce `1.25/6.25`, and concentration doubles the
stored result. Equipment FX_ORBPULL writes the independent `+0xBC` multiplier.

Orb pull radius is strict `60 * +0xCC * +0xBC`, capture radius is strict
`20 * +0xCC`, and each qualifying slot advances the same actor another 1.5
units in slot order. Gold/Sack use strict `30 * +0xCC`; Bonus uses strict
`20 * +0xCC`. Gold alone, when `+0xCC > 1.25999999`, consumes
`Integer(15)` and captures only on result one. Telekinesis itself creates no
actor, VFX, light, or audio request; only the existing reward actor's movement,
pickup child, cue, and retirement edge become reachable at a larger distance.
Goodie and Ether Drain do not consume `+0xCC`.

## Raise Golem and Iron Golem

Raise Golem is skill-ID case `45` in `0x0054CC50`. It creates factory type
`0x7F4`, writes `mHP` to current/max HP `+0x170/+0x174`,
`mDamage1` to `+0x1F0`, `mDamage2` to `+0x1F4`, copies owner/world
identity, and ignores cursor aim: exact `RandomSign(45)` chooses a point 100
units along the caster's current heading plus or minus 45 degrees, native
resolver `0x00645910` collision-adjusts it with radius 25 and scenery mask
`0x205`, and the summon starts facing back toward `casterFacing+180`. Learned
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
| `8` Magic Missile | `0x0053CFE0` | `0x7D3 MagicMissile` | Creates children `i=0..N-1` with `step=N<4?30:20`, `base=aim+(N even?step/2:0)`, and heading `base+(-1)^i*i*step`; all share one cast-time damage roll. Stores nearest-target group/slot, common speed `3*smartFactor`, child turn input `2*smartFactor*0.75^i`, pierce state, and owner flags. Visual scale remains one. |
| `16` Fireball | `0x0053DC60` | `0x7D4 Fireball` | Creates one aimed fireball; writes damage and Fireball-family secondary payload scalars at `+0x150..+0x15C`, randomized payload state at `+0x160/+0x164`, and three compact proc fields at `+0x168..+0x16E`. |
| `1000` Ether + Fire | `0x0053E6A0` | `0x7DE FireMissile` | Reads the rebuilt weld vector at progression `+0x774`; creates its quantity in an alternating fan and writes damage, inherited speed/turn scaling, secondary fire payload, bounce/proc state, and randomized seed at `+0x158..+0x178`. |
| `1001` Ether + Water | `0x0053F3C0` | `0x7E0 FrostMissile` | Uses the same weld-vector fan/target contract; writes damage and speed/turn scaling plus cold-area and slow payload fields at `+0x168/+0x16C`. |
| `1002` Ether + Air | `0x0053EDB0` | `0x7DF BallLightning` | Uses the same weld-vector fan/target contract; writes damage, inherited speed/turn scaling, electric payload magnitude/duration, and inherited missile state at `+0x168..+0x170`. |
| `1009` Air + Earth | `0x00545FC0` | `0x7E5 GroundSpark` | Creates a central spark and, outside the alternate/bot path, two side sparks. Each receives heading-derived motion plus vector-derived damage/effect fields at `+0x1A0..+0x1B0`. |
| `80` Plane Orb | inline in `0x0054CAF0` | `0x7EF PlaneOrb` | Creates one aimed orb, copies caster group/world identity, derives `+0x154` from equipped-item state, registers it, emits the exact 27-child `0x0052D360` birth burst, requests `distortreality` at Region point gain and `lightningstart` at pitch `2.0` with the same gain, then writes Region alpha `0.1`. |

The three Ether-derived welded missile handlers all read the normalized vector,
not six CFG files at cast time. They consume the vector's first eight values,
randomize damage between its first two entries, alternate heading around the
aim angle, decay per-projectile homing turn input across the fan, and acquire the nearest
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
| `24` Lightning | `0x0053F9C0` | Traces a beam from the cast origin, retains or reacquires a target, dispatches repeated contact, creates `Mod_Stun (0x1B6A)` when the learned stun scalar is active, applies the Disintegrate proc through transient damage flag `0x4`, emits `Anim_FadeLightning` wrappers, and uses `0x00641340` for the learned chain count. |
| `32` Frost Jet | `0x00543860` | Builds a widening cone, emits `Anim_FrostJetEffect`/`_Over`, queries actors through `0x00641B10`, applies damage, pushback, and `Mod_ColdSlow (0x1B69)`. Its learned branches emit `Anim_Hail`, run the Cold Aura circle query, and add Harden armor up to its configured maximum. |
| `40` Boulder | `0x00544C60` | Creates one persistent `Boulder (0x7D5)`, stores its group/slot handle, then repositions and re-aims it every cast tick. Gargantuan's `mSize` writes boulder `+0x1FC`; Rock Surge's `mChance`/`mManaCost` can move the active rock forward and invoke its surge behavior. |
| `1003` Fire + Air | `0x005408F0` | Reuses the Lightning beam/chain geometry, adds the normalized fire payload to the contact globals, can attach `Mod_Stun`, and emits the lightning fade chain. |
| `1004` Water + Air | `0x00541870` | Combines cone and chaining selection, creates frost/chaining animations, and can attach both `Mod_ColdSlow` and `Mod_Stun` before contact dispatch. |
| `1005` Fire + Water | `0x00542D20` | Emits `Anim_SteamJetEffect`/`_Over` stream actors and applies the normalized cone push. Their tick `0x0045B940` creates `Mod_Steamed (0x1B6C)` and dispatches the stored damage payload. |
| `1006` Ether + Earth | `0x00545360` | Creates a persistent `EBoulder (0x7E1)`, copies normalized damage, duration, size/split and related fields through `+0x230`, and retains it through the common group/slot handle. Its active path emits `Anim_BoulderBit` fragments and can arm recursive child splitting. |
| `1007` Fire + Earth | `0x0052BB60` | Emits `Anim_Iceblast` presentation at the aimed point and periodically creates randomized `Meteor (0x7E2)` actors. Each meteor receives normalized damage/fire payload fields at `+0x160..+0x17C`; impact behavior belongs to the Meteor lifecycle. |
| `1008` Water + Earth | `0x00545C20` | Creates a persistent `Hailstones (0x7E4)`, copies normalized damage, duration, size and impact fields through `+0x220`, retains its group/slot identity, and continuously follows the cast origin/heading. |

### Organic remote Lightning target and damage invariants

Organic raw-HP validation on 2026-07-25 separated two problems that the earlier
pinned-target harness could not expose. On the beta.17 release `bd9c47f`, a host
tap dealt `0.300001140` damage in twelve approximately `0.025` contacts and a
host sustained cast dealt `2.500000451` across moving real-wave enemies. The
equivalent client-origin tap and sustained casts dealt exactly `0.0` authority
HP damage. A post-beta.17 repeat at `5d3582a` reproduced the zero client cells
while the host sustained total varied organically to `3.225002016`. The client
sent the intended enemy network ID and the authority resolved it, but one
captured client Lightning actor still held group `100`, slot `452` in
`actor+0x164/+0x166`; the actual replicated run enemy was a normal world actor
in group `0`, slot `10`.

The requested `4b316be..bd9c47f` history contains no first-bad commit. Both
client-origin cells were already zero at `4b316be`, remained zero at
`28ed954`, and remained zero at `bd9c47f`. In particular, `28ed954`'s
stock-owned primary transitions and single pre-stock release edge did not cause
the organic failure. A temporary theory that its pure-primary primer latches
suppressed the dispatcher was also disproved and was not retained. The earlier
positive client result had explicitly pinned `+0x164/+0x166`, bypassing the
broken acquisition path.

`0x0053F9C0` refreshes or retains the Lightning target through `0x0052BA80`.
That refresh unconditionally saves the prior `+0x164/+0x166` handle and calls
`0x00529AD0`; it restores and validates the prior handle only when the new query
returns the sentinel. A correction at `SpellCast_018` entry is therefore too
early: a successful bad client query necessarily overwrites it. The
`0x0052BA80` prologue is eight whole bytes
(`SUB ESP,10h; PUSH EBX; PUSH ESI; PUSH EDI; MOV EDI,ECX`) and is the exact
post-query, pre-consumption hook seam.

`0x00529AD0` clears `+0x164/+0x166`, builds the angle/range query, and asks
`0x00641500`/`0x00522F50` for a native spatial-cell candidate. A handle below
group `100` indexes the ordinary world actor buckets. Group `100` instead
selects a special scenery list, so a replica-only group `100` handle cannot
reach the real run enemy's `0x0063E7D0` contact/damage callback.

For either local multiplayer origin, the loader resolves the naturally aimed,
alive wave enemy when `SpellCast_018` begins. The nested `0x0052BA80` hook runs
stock acquisition first, then normalizes only the returned native handle to
that real actor's group and slot before `0x0053F9C0` tests and resolves it.
Covering both origins is required: a post-tap host sustained cast was observed
to select group `100`, slot `42`, which resolved to a Gravestone (`2029`) at
`895.8655,514.5286` while the organic aim target was the live wave enemy at
`1020.5078,121.4300`; authority HP remained unchanged for the entire hold.
This does not pin a test target: the resolver uses the same player position,
heading, range, and alignment query as organic cast packet targeting. Stock
still owns the acquisition call, cast duration, primary transitions, and the
release edge. Solo retains the unmodified stock path.

A second defect was visible after acquisition was controlled. Over equal
170-frame holds, the host produced `170` damage contacts (`4.250259420`), while
the client-origin path produced only `119` contacts (`2.975181589`) on the
authority. The client damage bridge had two asynchronous snapshot samplers
constructing overlapping absolute-HP claims. Later no-op or stale claims could
overtake real contacts, so event count depended on packet/snapshot timing.

The damage bridge now observes the exact bound enemy HP immediately before and
after each native badguy-damage callback. It accepts only callbacks whose
resolved source participant is the local client, associates the enclosing
native spell dispatcher skill (including the first immediate contact), and
serializes one absolute authority claim at a time while accumulating subsequent
native contacts. A delayed stock effect outside the cast-association window
retains the pre-existing wire-skill `0` fallback because the exact native
callback still proves its damage source is the local participant. Snapshot
reconciliation still rolls local presentation back to authority state, but no
longer authors a competing damage claim. The authority remains the only process
that applies and republishes accepted HP.

That exact-callback bridge exposed a narrower serialization race on the
post-`f12c19a` candidate. The client observed and sent all `170` contacts as
`44` accumulated claims totaling `4.250265000`, with no rejection or retry, but
the authority applied only `3.525215000`. Five packets were accepted with
identical before/after authority HP, and two early packets applied only part of
their claimed delta. For example, client claim 16 targeted `38.824928` after
HP while authority HP was already `38.649918`; claim 23 targeted `38.299896`
while authority HP was `38.124886`. This proves the loss occurred after the
native damage callback and before the authority write, not in Lightning's
contact cadence.

The accumulator's `reference_hp` is the serialization cursor for absolute-HP
claims. It was cleared as soon as one authority snapshot reached that cursor.
Because identity fragments can assemble for up to `500` ms and world
presentation intentionally runs `150` ms behind, an older, higher-HP snapshot
could then become the baseline for the next claim. The host correctly made the
stale absolute target a no-op, but the client had already removed the whole
batch from `pending_damage`. The cursor now remains authoritative throughout
active damage and is released only after `750` ms of quiescence with no claim
in flight. This preserves idempotent absolute-HP retry semantics, permits later
host-authored HP increases after the bounded hold, and does not alter stock
cast start, sustain, or release timing.

The replicated-event acceptance gate pairs its Earth audio-event comparison
with a fixed-window Lightning damage check. It samples the authority's raw enemy
HP field on every runtime tick for equal `170`-frame local- and remote-origin
holds, requires positive damage in both cases, and permits at most two `0.025`
damage contacts or two percent total-damage divergence. Organic tap and
sustained acceptance remains a separate no-pin gate so target acquisition
cannot be hidden by the controlled parity fixture.

On the cursor fix, the controlled authority target fell from
`40.000000000` to `35.749740601` in both origins. Local-origin Lightning
produced `170` raw writes totaling `4.250259420`; client-origin Lightning
produced the same `170` contacts coalesced into `45` authority writes totaling
`4.250259411`. The damage delta was `0.000000009`, with zero contact-count
delta. The subsequent organic, unpinned real-wave matrix read positive raw
authority damage in every cell: solo tap `0.300001140`, solo sustained
`4.250003293`, host tap `0.300001140`, host sustained `1.749999243` while its
moving target remained in contact for 70 ticks, client tap `0.300001144`, and
client sustained `4.200003121` across three naturally acquired enemies. Every
captured Lightning handle in that matrix resolved to ordinary world group `0`;
the semantic/raw HP maximum error was `0.0`.

Disintegrate is not a separate projectile or persistent effect actor. On a
qualifying Lightning contact, `0x0053F9C0` reads the rounded chance at
progression `+0x8D2`; a successful percentile roll ORs `0x4` into the
transient damage-event flags at `0x0081C6E4` before common contact dispatch.
`Badguy_Contact (0x0048A290)` tests that bit and forces the target's HP to zero
when its post-hit health is below 20 percent of maximum, matching the shipped
skill description. The flag is scoped to that damage event and is distinct
from the skeleton absorption-death flag `0x100`.

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
| `11` | Call Leviathan | Creates `Leviathan (0x7F2)` at the resolved aimed point. Ordinary casts select an integer appendage count in `[1,mQuantity]`; the complete Bug-Master outfit forces the configured maximum and doubles this spell's damage. The owner builds the corresponding authored one-through-five appendage layout, registers it, and lets the 1600-update active branch spawn targeted `EtherBolt (0x7F3)` children on each appendage's independent 75..100-update cadence. |
| `12` | Planewalker | `0x00548700` toggles the state. Enabling allocates `Mod_Planewalker (0x1B75)`, writes `mDuration*100`, attaches it, saves the previous selected spell at wizard `+0x308`, forces selected spell `80` (Plane Orb), and clears Ether Blast charge. Casting while active removes the modifier; removal/expiry restores selection and owns the off edge. |
| `15` | Phasing | `0x0052A0B0` tests distances `80..270` in 10-unit increments, relocates to the first collision-clear point, updates world membership, and emits the `BadGuys[53]` traversal effect plus `phase` audio only on success. All 20 failures leave position and presentation unchanged. No separate cooldown is written by this helper. |
| `21` | Ring of Fire | Calls `0x0063F920`, which creates the ring's `MovingFire (0x7E6)` segments and final `Shockwave (0x7E7)` from the supplied damage/owner flags. |
| `23` | Firewalker | Toggles progression byte `+0x8DC`; enabling it immediately creates one damage-enabled `Fire_Goodguy (0x7EE)` without advancing the periodic geometry counter. While enabled and outside player mode `2`, the player tick emits another patch on every global tick divisible by ten. Those periodic patches cycle their contact-geometry byte `true,false,false`; every patch still owns the exact seven-word randomized birth, DeadHawg fire animation, lifetime, and ambient loop. Refresh adds scalar `mHoard=50` as an absolute MP reserve at `+0x740`, not a percentage of max MP. |
| `27` | Magic Storm | Creates `StormCloud (0x7F0)` at the aimed point, copies caster/world identity, damage range and arc state, and registers the persistent cloud. |
| `30` | Prismatic Shock | `0x00645540` creates one caster-attached `Anim_PrismaticSpray`, performs a mask-`2` radius-350 hostile query immediately, and allocates/attaches `Mod_Prismatic (0x1B76)` through the contact ABI for every returned target. |
| `35` | Ring of Ice | `0x00644460` creates three `Anim_Iceblast` bursts, the radial debris field, and `FreezeWave (0x7E8)` with configured damage, owner identity, and optional item-effect flag. |
| `41` | Earthquake | Creates `Earthquake (0x7F1)` at the caster position and writes the configured duration before registration. |
| `45` | Raise Golem | Enforces the one/two-summon limit, ignores cursor aim, consumes signed 45-degree placement plus the shared radius-25 elliptical collision resolver, creates `Golem (0x7F4)` facing 180 degrees back from the committed caster facing, writes HP and both damage values, and folds learned Iron Golem reflection into the summon; see the detailed summon section above. |
| `46` | Stoneskin | Constructs `Mod_StoneSkin` directly through `0x006237A0`, writes configured duration, and attaches the reference to the caster; it does not create a world projectile. |
| `48` | Teleport | Calls `0x00644A00` at the source, asks world virtual `+0x12C` for a destination, writes that non-null point to the wizard, then calls `0x00644A00` again at the destination. Arena `0x00465440` owns the shuffled 100-unit safety-grid selection and radius-40 collision adjustment; indoor Regions return `(0,0)` through `0x00508900`. Aim is not an input to this virtual. |
| `49` | Magic Circle | `0x0063FDE0` creates/index-registers `MagicCircle (0x7EA)` at the aimed point with `mSlow`, color, and ownership state. Every ten ticks the circle attaches `Mod_CircleSlow (0x1B70)` to eligible enemies. The local player gains `mana_recovery * 2 / game_timing_scale` MP per callback. The HP branch is stock-inert: it computes `HP + health_regeneration * 2 / game_timing_scale`, compares that candidate with current HP instead of max HP, and writes current HP unchanged for ordinary positive regeneration. |
| `50` | Magic Trap | Creates `MagicTrap (0x7F5)`. It derives an element selector from the current stock primary or weld build before damage lookup. Selector `0..4` resolves effective-rank primary `8,16,24,32,40`; Ether consumes one inclusive `FloatRange(mDamage1,mDamage2)`, while the other four read their selected skill's single `mDamage` without a damage draw. It stores `f32(base*trap mDamage)` and registers the armed trap at the aimed point. The air selector attaches one target-owned `Mod_ElectricBurn`: 100 damage updates at `trapPayload/100`, max-remaining-duration merge with replacement payload, one Region light with radius `0.5+S(0.25)` and intensity one plus `electric__loop` renewal per update, and no lightning sprite because the trap fixes chain count to zero. |
| `51` | Dampen | `0x00648DF0` queries hostile magic in a rectangle, removes guided/fire/dark missile actors, disrupts hostile caster actions, and dispels shields when `RandomInt(100) < 0x33` (51/100 outcomes, despite the authored 50% display text); it then starts action mode `21` (`Action_PlayerWizard_CastSpin`) at half normal action damage. |
| `54` | Magic Shield | Combines Magic Shield `mAbsorb` with Explosive Shield factor `mDamage/100` and calls the wizard's virtual `+0x64` to install/refresh shield state. Break callback `0x00546650` multiplies the installed absorb pool by that factor for its radial contact (rank 1: `25*0.5=12.5`); it is not a flat Explosive Shield damage value. |
| `72` | Acid Rain | Creates `AcidRain (0x7FE)` at the aimed point, writes configured damage and caster/world identity, then registers the persistent rain actor. |
| `73` | Fire Wall | Builds a 300-unit line perpendicular to aim and creates eleven `Fire_Goodguy (0x7EE)` patches at 30-unit intervals including both endpoints. Patch scale follows `0.8+0.6*sin(pi*d/300)`, each birth adds an unsigned `RandomFloat(10)` radial offset in a random unit direction, life is overwritten with scalar `7` (700 ticks under the shared `-0.01/tick` recurrence), and the creation loop forces `+0x160=1` on every patch so all eleven own common Fire-patch contact. Creation requests `ignite` then `fireballhit`. |
| `74` | Ether Drain | Creates `EtherDrain (0x807)`, writes `mDamage / 100` as the radius-20 contact scalar, resolves the aimed origin through the world, and registers its 1,000-active-tick radius-512 pressure field. Constructor `0x005F8360` derives that countdown as `100 ticks/s * 10 s`; tick `0x0061CF20` decrements it once per fixed tick. Candidate identities refresh through the class-owned arrays; nonempty Gold/Sack containers are protected from center capture. The actor renews `PlaneCross__Loop`; the associated `crunchdrain` registry entry still lacks a recovered playback callsite. |
| `76` | Call Comet | Calls `0x0063FD00`, which creates `Comet (0x80C)` with Permafrost-scaled freeze seconds at `+0x13C` and damage at `+0x140`; impact converts the former to FreezeWave ticks and uses the latter as damage. |
| `77` | Turn Undead | `0x00647EF0` first reuses registry 52 `sounds\levelup` twice with point-derived gain and exact pitches `2.0` and `3.0`, then queries a strict 500-diameter/mask-2 area and acts only on `Skeleton (0x3E9)`, `SkeletonArcher (0x3EA)`, `SkeletonMage (0x3EB)`, and `Zombie (0x3EE)`. It turns both heading lanes away from the cast point, writes `round(mFlee*100)` as the target-owned countdown at `+0x20C`, and scales attack strength once when the old field still holds the untouched `<=-9000` sentinel. The common hostile tick decrements positive countdowns. The cast also creates 35 BadGuys-record-48 fade/scale children for exactly 20 ticks; this reuse is separate from the same sound asset's gain-1 level-transition owner at `0x00528A20`. |
| `78` | Mindstar | Toggles progression byte `+0x8DD`, writes the cyan Region feedback lane, plays the shared stream, and refreshes progression state. No projectile, player-attached sprite, or world actor is allocated. |
| `79` | Regenerate | Toggles progression byte `+0x8DE`, writes the orange Region feedback lane, plays the shared stream, and refreshes progression state. No projectile, player-attached sprite, or world actor is allocated; regeneration then runs from player progression/tick state. |

### Complete right-click presentation and lifecycle contract

[`native-secondary-ability-catalog.json`](native-secondary-ability-catalog.json)
is the machine-readable closure artifact for these exact 23 category-2 rows.
It joins each row to its complete authored rank table, targeting mode,
factory/modifier identities, fixed-tick cadence, atlas records, audio registry
identity and file hash, authority boundary, and teardown rule. It is generated
only from the checked-in skill/audio catalogs plus the recovered dispatcher
and actor contracts; its source executable is the 4,723,200-byte retail image
with SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

### Native secondary belt presenter

The catalog's top-level `belt_presentation` closes the shared HUD owner for all
23 rows. `BeltButton::Present` (`0x005D3E10`) owns eight 53 x 53 slots, resolves
their default right-mouse/number-key bindings, and draws the input hint only
when the slot has content. Keyboard hints are black Fonts group-8 labels over
the horizontally sized `UI.22` three-piece plaque; right mouse is `UI.100`.
Both paths retain the native lower-viewport clipping.

Cooldown presentation is a dark-red `(0.5,0.1,0.1,0.75)` 53 x 53 square
radial fan over `[360*(1-remaining/capacity),360]`, split at crossed 45-degree
boundaries. Painter order is cooldown square fan first, skill icon second.
Cooling icons use white base alpha `0.25`; ready icons enter at white base alpha
`0.75`, and the Hub independently installs the quarter-RGB scene multiplier.
The presenter never tests any of the four toggle-state bytes, so active
Planewalker, Firewalker, Mindstar, and Regenerate icons do not brighten, pulse,
or otherwise diverge from their cooldown/ready state.

The presentation census is not a generic particle substitution:

| Skill IDs | Native presentation owner |
| --- | --- |
| `11,27,41,45,49,50,72,74,76` | A persistent world actor owns its own scale/alpha or body state, child-animation cadence, ambient renewal, and terminal fade/impact. |
| `21,35,73` | The cast helper creates the complete radial/linear child set immediately; `MovingFire`, `Fire_Goodguy`, `Shockwave`, or `FreezeWave` then own their separate lifetimes and contacts. |
| `12,23,46,54,78,79` | Player/progression or a target-owned modifier owns the visible state. Toggle-off, expiry, overload, absorbed-hit, and shield-break are real presentation edges, not silent data changes. |
| `15,30,48,51,77` | The helper emits registered additive children at the accepted world point. Dampen alone also queues mode `21` CastSpin, whose phase advances `2.5` per tick and completes on strict `phase > 180` after 73 action ticks. |

The exact visual anchors are `BadGuys[11,22,39,343..372]` for
Leviathan/EtherBolt, `BadGuys[53]` for Phasing, `DeadHawg[46..77]` for both
moving and persistent friendly fire, `BadGuys[75,11,45]` plus the loose
repeat-wrapped `images/etherplane.png` mesh for Plane Orb,
`BadGuys[58,111,10,11]` for Prismatic Shock,
`DeadHawg[114,121]` plus `BadGuys[72]` for Ring of Ice,
`DeadHawg[200..202]` plus
`BadGuys[2008..2010,62]` for Earthquake, `Golem[1..208]` plus the supplemental
Golem rows listed in the catalog, `BadGuys[90]` for Teleport,
`BadGuys[48,7]` for Magic Circle (centered spin-away ring particles and a
player-attached recovery pulse respectively),
`BadGuys[111,112,15,85,16,158..167,17,74]` for Magic Trap's armed body,
shadow, independently fading shimmer, and terminal burst,
`BadGuys[10,11,48]` for Dampen,
`BadGuys[49,68,15,158..167,17,74]` plus `DeadHawg[2,18]` for the Magic Shield
shell, 20-particle break, Explosive Shield composite, and light-only Shockwave,
`BadGuys[75,38,10,11,36]` plus `DeadHawg[177..179]` for the Ether Drain
parent, clouds, free debris, capture pulse, and captured-object flare, and
`DeadHawg[5,203..207,6]` plus `BadGuys[51,15]` for Call Comet. These records
are world-painter inputs with their recovered additive/depth modes; skill
icons remain the separate `Skills` rows in the catalog.

Audio is likewise lifecycle-owned. Long-lived actors renew ambient wrappers
(`PlaneCross`, `lowfire`, `rainfall`, `steadywind`, `earthquake`, or `comet`)
while live, and teardown merely stops renewal. One-shots/streams fire on their
native cast, strike, assembly, hit, break, impact, toggle, or expiry edge.
Snapshots never replay them. The complete asset/event lists and registry
hashes are recorded per member in the catalog and summarized in
[`native-audio-events.md`](native-audio-events.md#secondary-and-advanced-right-click-events).

Magic Shield break callback `0x00546650` specifically plays `popshield`,
spawns exactly 20 `Anim_FadeAdditive` children from `BadGuys[68]` at `y-35`
with scale `2+Float(0.25)` and alpha `0.5+Float(0.75)`, conditionally dispatches
the Explosive Shield radial contact and complete 502-word visual program, and
only then clears absorb and explosion state. The helper's two half-payload
contact lanes sum to the full configured payload at the target. `Mod_StoneSkin`
is separate: its `+0x1C/+0x20/+0x24`
callbacks at `0x00624490/0x006244C0/0x00626840` all route through the
`stoneskin` one-shot after the modifier apply, refresh, and removal callbacks;
natural expiry therefore requests it exactly once. The unrelated loaded
`stoneskinhit` and general `stonebreak` samples are not assigned to those
modifier callbacks. Apply callback `0x00624490` also sets actor material flag
`+0x138 |= 1`. Player renderer `0x0054BA80` reflects that flag through global
byte `0x00819E5D`; the wizard body/equipment compositors, including the path at
`0x00538F30`, enable their material pass and set RGBA exactly
`(0.5, 0.5, 0.5, 1.0)` before drawing, then restore white and the previous
renderer state. Stoneskin is therefore a grey material treatment on every
composed wizard body/equipment layer, not a separate particle sprite.

Mindstar and Regenerate are also a deliberate shared-audio pair. Dispatcher
calls `0x0054FF05` and `0x0054FFD4` both request
`sounds\\mindstar__stream`, then toggle `+0x8DD` or `+0x8DE` and immediately
run progression refresh. The complete two dispatcher branches contain no
allocation or actor-registration call: their only visual presentation is the
Region feedback write, cyan `(0, 0.5, 1, pointGain)` for Mindstar and orange
`(1, 0.5, 0, pointGain)` for Regenerate, both with loss `0.1`. Consequently
neither toggle owns a caster flash, player overlay, projectile, or persistent
world sprite, and Regenerate does not own a separate healing-loop sample.

The absence of other IDs from this switch is meaningful. Upgrades such as
More Missiles, Chaining, Embers, Chill Wind, Hail, Rock Surge, Cold Aura,
Gargantuan, and Iron Golem are consumed by their primary or summon handlers;
body/mind entries are passive progression modifiers. They do not each own a
separate castable projectile factory case.

Chill Wind is nevertheless a complete mixed actor/projectile consumer inside
the Water primary handler `0x00543860`. The ordinary query mask is `0x1082`.
Arrow constructor `0x005E1000` writes actor flag `0x80`; Firebolt and
GuidedMissile write `0x100` and do not enter this branch. For every returned
`0x80/0x1000` target, the handler calls virtual `+0x64` with float32
`mPushback*0.3199999928474426` and the cast-heading unit vector. Arrow vslot
`0x005E5EC0` accumulates that scalar at `+0x178`; every learned rank begins at
`mPushback=10`, so the first eligible contact crosses one, retires the Arrow,
and registers a record-2 `Anim_SpinAway` (`0x0079D530`). The child starts with
life 6 and loss 0.1, moves by the supplied unit vector while damping it by
float32 0.98, and consumes `Float(360)`, `Float(1)`, then the sign word for its
initial rotation and signed `1+magnitude` angular velocity. Low-mana Water's
mask is `0x2`, so it never tumbles projectiles.

### Status ownership details

`Mod_Planewalker` is native factory type `0x1B75`. Its apply callback
`0x00623800` sets target flag `+0x138 |= 0x10`; its removal/expiry callback
`0x00623810` enters `0x0052F470`, which restores player-side plane state. The
generic modifier merge callback `0x00626A60` keeps the greater remaining
duration when another modifier of the same type is attached. This explains why
the cast helper saves the former spell selection and forces Plane Orb: Plane
Orb is the active plane-side primary, while the modifier owns entry/exit.
Plane Orb is a complete sibling lifecycle inside this right-click system: its
1,000-tick countdown (999 active-branch updates before fade starts at age
1,000), terminal scale fade, textured center-fan/annulus pass,
27-particle birth burst, enhanced per-update mote, two birth sounds, and
low-alpha Region flash remain owned by runtime primary 80 rather than the
modifier body.

Prismatic Shock and the elemental trap effects use the same modifier factory
and reference-counted attachment ABI as the primary missiles. Magic Trap's
selector adds `Burn (0x1B73)` for fire, `ElectricBurn (0x1B6B)` for air, and
`ColdSlow (0x1B69)` for water; ether/earth retain the trap's direct contact
payload without one of those three modifier branches. The air branch writes
ElectricBurn duration `100`, damage `trapPayload/100`, chain count zero,
scalar one, and the trap group. Its merge callback keeps the greater remaining
duration while replacing those payload fields. Each live tick consumes signed
`Float(.25)` for a target light of radius `.5+jitter` and intensity one, renews
`electric__loop`, consumes `Integer(3)` plus conditional `Float(.5)` on result
one, and applies the stored damage. Chain count zero bypasses every
`Anim_FadeLightning` allocation, so adding a target lightning sprite would be
non-native.

## Closure result

The 82-ID catalog, rank/refresh ABI, passive and concentration formulas,
primary/weld dispatch, secondary/advanced switch, staff proc table, spawned
factory types, modifier IDs, art selection, and principal object lifecycles
are mapped. Generic child-animation art and ownership are closed in
[native-projectiles-and-effects.md](native-projectiles-and-effects.md#animation-wrapper-art-and-ownership-abi):
the caller chooses a fixed atlas destination and the wrapper borrows it, so
there is no hidden per-animation asset registry left to recover.

The isolated runtime pass confirmed native gameplay-world construction,
enemy materialization, and resident atlas ownership. The optional cast sample
had no selected spell pointer and is not used as evidence. Exact persistent-
effect and golem-reflection contracts remain grounded in the decompiled
branches and native contact ABI above. Enemy- and item-owned uses of the same
modifiers are tracked in their respective passes instead of being duplicated
here.

## 2026-08-15 pure-primary low-mana branch closure

### Shared debit semantics and timing

The five pure-primary handlers call shared mana helper `0x0052B150` with a
negative requested cost and `rejectIfInsufficient=0`. The helper stores
`max(0,currentMP-cost)` and returns one when that post-debit value is `<=0`.
Consequently the return is an **underpowered** selector, not a cast-acceptance
result:

- MP strictly greater than cost spends the full cost and selects normal;
- MP exactly equal to cost spends the full cost and selects underpowered;
- MP between zero and cost spends the remainder and selects underpowered; and
- zero MP spends zero but still selects underpowered.

There is no fractional scale based on the missing-mana percentage. Ether and
Fire call the helper at the Staff emission marker, after their wind-up. Air,
Water, and Earth call it on every sustained handler tick. An earlier action-
start debit or a channel stop at zero therefore changes native behavior.

### Per-handler consequences

| Handler | Underpowered damage/state branch | Suppressed adjacent branches |
| --- | --- | --- |
| Ether `0x0053CFE0` | Multiply direct damage by `.5`; force quantity one; multiply speed by `.8` (`3 -> 2.4`); combine the `.75` turn control with that speed scalar for effective turn input `2 -> 1.2`; set projectile byte `+0x160`. | Pierce/bounce payload fields `+0x161/+0x164` are not populated. |
| Fire `0x0053DC60` | Multiply direct damage by `.5`; zero secondary Fire scalars `+0x154/+0x158/+0x15C`; set projectile byte `+0x168`. | Proc/status fields `+0x16A..+0x16E` are not populated. |
| Air `0x0053F9C0` | Multiply contact damage by `.5`; pass underpowered as factory parameter nine to `0x00531640`; use endpoint scalar `.5`; set lightning-loop gain `.75`. | Hurricane state/progression, chain helper `0x00641340`, Disintegrate, and Stun are all gated out. The initial target/contact still resolves. |
| Water `0x00543860` | Multiply contact damage by `.5`; use actor mask `0x2` rather than `0x1082`; force weak ColdSlow scalar `.75`; set ice-loop gain `.5`. | Widen/push are zero; Over, Hail, Permafrost scaling, Cold Aura, and Harden are gated out. Entering the weak branch invokes Harden cleanup `0x00529840` when necessary. |
| Earth `0x00544C60` | Still constructs `Boulder (0x7D5)`. While charge is below one, each underpowered tick halves both stored release bases. When current charge is strictly above `.3`, it zeros the growth field; below that edge the actor keeps growing until it crosses. | There is no weak-alpha Boulder flag. The weak branch changes charge/damage evolution and owns a periodic fizzle. |

Earth's repeated halves are intentional: a zero-MP hold exponentially reduces
the stored base while remaining near minimum release charge. Release computes
float32 `baseCharge=base*charge`, then `quadratic=baseCharge*charge`, caps at
`base*1.25`, and floors the final damage at `.25`. This floor is the terminal
damage rule; it must not be applied to each held-tick intermediate.

The branch audit followed each weak flag through its draw/tick/contact consumer
and adjacent learned paths. Ether/Fire impacts do not read their flight-only
flags. Air source glow is independent. Water's environmental mask lane is
removed even though rank-one web enemies normally expose flag `0x2`. These are
ownership boundaries, not permission to apply one generic half-alpha/half-
damage rule across all effects.
