# Native spell-welding system

## Result

Spell welding is implemented as a special level-up choice layered on the
ordinary 0x70-byte skill catalog. It does not concatenate two arbitrary spell
objects. The native game selects one of ten allowed cross-element primary
spell pairs, records a synthetic build ID from 1000 through 1009, and rebuilds
the wizard's active primary-spell stat vector from the learned levels and CFG
properties of six component skill rows.

This document covers the retail `SolomonDark.exe` whose SHA-256 is
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Names are descriptive unless an exact CFG/property name is quoted.

## Relevant skill object layout

The wizard-specific skills object uses vtable `0x007A0CD4`; the base skills
vtable is `0x0079FEFC`. Important wizard overrides are:

| Slot | Function | Role |
| ---: | ---: | --- |
| `+0x74` | `0x0067CB70` | Build the level-up option set and possibly inject welding. |
| `+0x94` | `0x00665FF0` | Refresh the special weld entry's displayed icon/selector. |
| `+0x98` | `0x00665F10` | Map a skill choice to its displayed Skills-atlas ID. |
| `+0x9C` | `0x006566A0` | Activate the selected weld build. |
| `+0xA0` | `0x00666020` | Resolve component pairs and rebuild active primary stats. |

The skill catalog is created at `0x00674EE0`. It creates 80 entries and loads
`data\\wizardskills\\<resolved-name>.cfg`; entry stride is `0x70`. The name
resolver is `0x00657C00`. The special welding skill is ID `0x34` (52), backed
by `spell_welding.cfg`.

Relevant progression fields are:

| Offset | Meaning | Evidence |
| ---: | --- | --- |
| `+0x20` | pointer to 0x70-byte skill-entry array | Used by all level/prerequisite accesses. |
| `+0x24` | entry count | Bounds check before indexed access. |
| `+0x774` | active primary stat-vector pointer | Cleared/rebuilt by `0x00666020`. |
| `+0x778` | active primary stat-vector count/capacity state | Checked before vector growth. |
| `+0x844` | selected/current synthetic weld build ID | Set by option roll and consumed on activation/render. |
| `+0x870` | one exceptional skill/unlock ID | Used by general eligibility checks. |
| `+0x878` | feature/equipment-effect bit field | Bit `0x800` enables Weld Calling behavior. |

The finer names of nearby fields remain subject to the broader progression
layout pass; the offsets and accesses above are confirmed.

## Allowed primary pairs

The base primary skills are:

| Element | Skill ID | Native name |
| --- | ---: | --- |
| Ether | 8 | Magic Missile |
| Fire | 16 | Fireball |
| Air | 24 | Lightning |
| Water | 32 | Frost Jet |
| Earth | 40 | Boulder |

`0x0067CB70` excludes skill `0x34` from its ordinary candidate loops. Once the
weld-specific eligibility gates pass, it builds candidates only for pairs
whose two base primary skills are learned, chooses one randomly, and stores the
synthetic ID at `+0x844`. The ten possible pairs are:

| Build ID | Elements | Base primary IDs |
| ---: | --- | --- |
| 1000 / `0x3E8` | Ether + Fire | 8 + 16 |
| 1001 / `0x3E9` | Ether + Water | 8 + 32 |
| 1002 / `0x3EA` | Ether + Air | 8 + 24 |
| 1003 / `0x3EB` | Fire + Air | 16 + 24 |
| 1004 / `0x3EC` | Water + Air | 32 + 24 |
| 1005 / `0x3ED` | Fire + Water | 16 + 32 |
| 1006 / `0x3EE` | Ether + Earth | 8 + 40 |
| 1007 / `0x3EF` | Fire + Earth | 16 + 40 |
| 1008 / `0x3F0` | Water + Earth | 32 + 40 |
| 1009 / `0x3F1` | Air + Earth | 24 + 40 |

IDs are initialized in native code before filtering, but no same-element pair
is placed in this random candidate set. A flag-controlled path also prevents
the prior/current weld from being offered again.

## Activation and six-component recipes

Selecting the special level-up entry reaches `0x00671470`, which invokes
vtable slot `+0x9C` with the build at `+0x844`, refreshes skills, then invokes
slot `+0x94` to refresh presentation. `0x006566A0` expands the build into six
skill IDs and calls `0x00666020`:

| Build | Primary A | Primary B | Upgrade A1 | Upgrade B1 | Upgrade A2 | Upgrade B2 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 8 | 16 | 10 | 18 | 9 | 17 |
| 1001 | 8 | 32 | 10 | 34 | 9 | 33 |
| 1002 | 8 | 24 | 10 | 25 | 9 | 26 |
| 1003 | 16 | 24 | 18 | 25 | 17 | 26 |
| 1004 | 32 | 24 | 34 | 25 | 33 | 26 |
| 1005 | 16 | 32 | 18 | 34 | 17 | 33 |
| 1006 | 8 | 40 | 10 | 43 | 9 | 42 |
| 1007 | 16 | 40 | 18 | 43 | 17 | 42 |
| 1008 | 32 | 40 | 34 | 43 | 33 | 42 |
| 1009 | 24 | 40 | 25 | 43 | 26 | 42 |

The apparent floating-point signature produced by the decompiler is wrong for
the component arguments: these are integer skill IDs passed in registers and
stack slots.

## Stat reconstruction

`0x00666020` first maps the selected component pair to a build ID. Mixed pairs
map to 1000..1009. Same-element primaries map to five stock synthetic IDs:

| Build ID | Stock primary |
| ---: | --- |
| `0x3F2` | Ether |
| `0x3F3` | Fire |
| `0x3F4` | Water |
| `0x3F5` | Air |
| `0x3F6` | Earth |

It then clears/rebuilds the vector at `+0x774/+0x778`. For each build case it
queries named properties from component skill configs through `0x005290F0`.
Confirmed property names include:

```text
mDamage        mManaCost      mQuantity       mSpeed
mArcs          mStunAmount    mPushback       mWiden
mStrength      mSpeedUp
```

The mixed cases combine the two primaries and their learned upgrade rows into
one normalized primary-spell description. The stock cases use the same output
path, which is why the cast system can consume a welded and unwelded primary
through one active-stat interface. Global balance constants are applied during
normalization, so the live vector is derived state, not a byte-for-byte copy of
CFG values.

The exact meaning and ordering of every float in that output vector is being
closed alongside the primary spell dispatcher. The important confirmed
contract is that component levels/config values are authoritative and the
vector is regenerated when the build or relevant skills change.

## Weld Calling and item effects

If progression `+0x878` has bit `0x800`, `0x00666020` scans eligible component
rows. An unlearned row is promoted to level 1 when its entry carries the native
component-eligible flag at `+0x29` and it is not a primary-kind row. This is the
behavior named `FX_WELDCALLING` in the item parser: **Weld +unlearned
components**.

The native item-effect name table at `0x00571560` includes:

| Effect ID | Display/effect name |
| ---: | --- |
| `0x25` | Energize Weld Components |
| `0x26` | Enhance Weld Effect |
| `0x27` | +Bias Skills for Welding |

`items.cfg` parsing recognizes `FX_MAXWELD`, `FX_WELDCALLING`, and
`FX_WELDEFFECT`. Their precise destination fields and formula contributions
are tracked as part of the item/equipment pass; the Weld Calling bit behavior
above is already confirmed.

## Eligibility and presentation

General skill eligibility is implemented by `0x0065E830` and `0x0065EBA0`.
It accounts for global unlock bytes for late catalog entries, already-learned
state, player level, at-least-one prerequisite groups, and all-required
skill/level pairs stored in the 0x70-byte entry. Welding adds its own learned
primary-pair and prior-offer filters in `0x0067CB70`.

The special row's help text path returns `TWO ATTACK SPELLS TO COMBINE`
(`0x0067BE60`). `0x00665F10` maps skill `0x34` to one of Skills-atlas display
IDs `0x51..0x5A` according to build 1000..1009; normal skills use their entry's
display selector at `+0x30`. `0x00665FF0` refreshes that selector after skill
state changes.

The level-up weld presentation is built at `0x00671810`: it selects the mixed
build's element colors and art, then adds randomized overlay color treatment.
`0x006720F0` renders component rows with names and learned levels. This UI is a
view of the current synthetic build and component skills; it does not own the
cast-time stats.

## Custom-content boundary discovered here

The stock system is closed over ten hard-coded pair cases and fixed native
skill IDs. New CFG files alone cannot add an eleventh weld recipe: selection,
six-component expansion, presentation-ID mapping, and stat reconstruction all
contain compiled switches/tables. Art replacement can change the ten existing
weld icons if the Skills bundle ABI is preserved. Arbitrary new welds require
a loader-owned registry and hooks at all four native decision points, or a
complete replacement of the welding layer.
