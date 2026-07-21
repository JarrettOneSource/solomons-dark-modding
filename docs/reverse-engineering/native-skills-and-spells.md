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

## Cast routing recovered so far

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

## Remaining closure work

The config/art catalog is complete. The active pass now assigns every learned
secondary and advanced skill to its application site, spawned class or status
modifier, constructor, tick, render/effect destinations, collision/damage
logic, sound triggers, and teardown. That method matrix is intentionally not
declared complete from config names alone.
