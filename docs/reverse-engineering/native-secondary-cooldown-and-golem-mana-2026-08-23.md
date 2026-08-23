# Native secondary cooldown and Golem mana correction

## Scope and provenance

This report reopens the category-2/right-click ability gate documented on
2026-08-20. That pass followed the two shipped `mCooldown` CFG properties but
did not sweep the hard-coded `Skills_Wizard` constructor writes for the other
21 category-2 rows. The resulting claim that those rows had zero capacity was
false.

Evidence is from retail Solomon Dark 0.72.5, preferred image base
`0x00400000`, size `4,723,200`, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`:

- fresh read-only Ghidra replica decompilation of `Skills_Wizard` construction
  `0x00674EE0`, dynamic refresh `0x00661530`, belt input `0x005D5600`,
  dispatcher `0x0054CC50`, arming `0x00661F40 -> 0x0065EDE0`, recurrence
  `0x00656E70`, and `BeltButton::Present 0x005D3E10`;
- direct float dumps of the constructor constants named below;
- the checked-in 15-class raw progression-book captures in
  `tests/fixtures/webgame/class-loadout-goldens.json`, where every row is a
  byte-authenticated 0x70-byte stock record; and
- shipped Raise Golem and Iron Golem CFG rows plus property resolver
  `0x005290F0 -> 0x0065D540` and composite mana resolver `0x006600F0`.

The Ghidra instructions and compiled constants are primary evidence. The raw
progression-book captures independently corroborate every fixed capacity.

## Complete cooldown-capacity table

`Skills_Wizard 0x00674EE0` writes these float capacities at
`book + skillId*0x70 + 0x68`. The values are already native fixed ticks.
`0x00661530` subsequently replaces Phasing and Teleport with their ranked CFG
values times 100 and clamps current cooldown to the smaller of its old current
and new capacity.

| ID | Ability | Capacity owner | Native ticks | Neutral seconds | Accepted-cast arming |
| ---: | --- | --- | ---: | ---: | --- |
| 11 | Call Leviathan | `0x007A0CBC` | 833 | 8.33 | row + common |
| 12 | Planewalker | `0x00786C18` | 2,500 | 25 | both on and off: row + common |
| 15 | Phasing | ranked `mCooldown*100` | rank 1: 100 | effective 1.5 | row is cleared below common; common fan |
| 21 | Ring of Fire | `0x00786C18` | 2,500 | 25 | row + common |
| 23 | Firewalker | `0x00784CF8` | 50 | effective 1.5 | on: row clears below common; off: no arm |
| 27 | Magic Storm | `0x007A0CC8` | 1,250 | 12.5 | row + common |
| 30 | Prismatic Shock | `0x007A0CC8` | 1,250 | 12.5 | row + common |
| 35 | Ring of Ice | `0x00786C18` | 2,500 | 25 | row + common |
| 41 | Earthquake | `0x00786C18` | 2,500 | 25 | row + common |
| 45 | Raise Golem | `0x00786C18` | 2,500 | 25 | row + common |
| 46 | Stoneskin | `0x00786C08` | 10,000 | 100 | row + common |
| 48 | Teleport | ranked `mCooldown*100` | ranks 1..8: 6,000/3,000/1,500/1,000/500/400/300/100 | 60/30/15/10/5/4/3/effective 1.5 | row + common; rank 8 row clears below common |
| 49 | Magic Circle | `0x00786C18` | 2,500 | 25 | row + common |
| 50 | Magic Trap | `0x0078CC68` | 625 | 6.25 | row + common |
| 51 | Dampen | `0x00785CF0` | 2,000 | 20 | row + common plus CastSpin |
| 54 | Magic Shield | `0x00786C18` | 2,500 | 25 | row + common |
| 72 | Acid Rain | `0x00786C18` | 2,500 | 25 | row + common |
| 73 | Fire Wall | `0x007A0CC4` | 277 | 2.77 | row + common |
| 74 | Ether Drain | `0x007A0CC0` | 3,750 | 37.5 | row + common |
| 76 | Call Comet | `0x007A0CC8` | 1,250 | 12.5 | row + common |
| 77 | Turn Undead | `0x007A0CCC` | 1,875 | 18.75 | row + common |
| 78 | Mindstar | `0x00784CF8` | 50 | no cast cooldown | dispatcher returns false; no arm/action |
| 79 | Regenerate | `0x00784CF8` | 50 | no cast cooldown | dispatcher returns false; no arm/action |

Direct constant values are `150` at `0x0078489C`, `2,500` at
`0x00786C18`, `625` at `0x0078CC68`, `2,000` at `0x00785CF0`, `1,875` at
`0x007A0CCC`, `50` at `0x00784CF8`, `1,250` at `0x007A0CC8`, `277` at
`0x007A0CC4`, `3,750` at `0x007A0CC0`, `833` at `0x007A0CBC`, and `10,000`
at `0x00786C08`.

## Gate, reset, clock, and HUD contract

`Game::ActivateBeltEntry 0x005D5600` rejects pause, no-interrupt action,
positive progression-wide current, or positive selected-row current before
calling `PlayerWizard +0x6C`. A true dispatcher return calls
`Skills_Wizard +0x80`. Outside the exact concentrated-Focus 75..99 roll,
`0x0065EDE0` copies selected capacity to selected current, clears every active
row current strictly below the 150-tick common capacity, and arms the common
current to 150.

`0x00656E70` subtracts the native maximum of Focus/global and category-item
recharge factors once per 100-Hz stock update, clamping each current at zero.
Full rejuvenation clears the common current and every category-2 row current;
rank refresh only changes Phasing/Teleport capacity and clamps their current;
owner death/session teardown destroys the actor-private book. Capacity is not
recomputed from browser frames or snapshot frequency.

`BeltButton::Present 0x005D3E10` first requires selected capacity greater than
zero. It chooses the larger of row current and common current. A positive row
uses row capacity as denominator; otherwise common current uses 150. The
existing square-fan geometry, dark-red RGBA, painter order, and cooling icon
alpha apply to all armed rows above. The three dispatcher-false branches do
not create a fan because neither current is armed.

At neutral recharge, real elapsed seconds are exactly `ticks / 100`. Focus or
an equipped category recharge effect intentionally shortens that time by the
recovered per-update subtraction. A host that schedules more than 100 updates
per wall second would be a web clock defect, not part of the native formula.

## Raise Golem mana cost

Both `PlayerWizard::SecondaryDispatch 0x0054CC50` case 45 (cost path around
`0x0054E4E0..0x0054E4F7`) and `Skills_Wizard::ResolveManaCost 0x006741B0`
unconditionally read `mManaCost` for Raise Golem 45 and Iron Golem 75, add the
two raw values, and call `0x006600F0` once with skill ID 45.

`0x005290F0` supplies the row effective rank to `0x0065D540`; that resolver
clamps negative ranks to zero, clamps high ranks to the last authored element,
and indexes rank zero normally. Iron Golem's authored array is 50 in every
slot, including rank zero. Rank-one composition is exactly `10+50=60` before
the shared resolver. Therefore learning Iron Golem changes reflection
but does not introduce the 50-MP component: it is already part of every Raise
Golem cast.

| Raise Golem effective rank | Raw Raise Golem | Raw Iron Golem | Raw total before shared modifiers |
| ---: | ---: | ---: | ---: |
| 1 | 10 | 50 | 60 |
| 2 | 20 | 50 | 70 |
| 3 | 30 | 50 | 80 |
| 4 | 40 | 50 | 90 |
| 5 | 50 | 50 | 100 |
| 6 | 60 | 50 | 110 |
| 7 | 70 | 50 | 120 |
| 8 | 80 | 50 | 130 |
| 9 | 90 | 50 | 140 |
| 10..12 | 100 | 50 | 150 |

The otherwise-unlearned rank-zero row would resolve `8+50=58`, but the belt
cannot invoke an unlearned Raise Golem. `0x006600F0` applies the shared flat
reduction, minimum-before-multipliers rule, applicable row/equipment factors,
and final near-zero clamp once to the combined raw cost. Raise Golem is not
Battle-Mage/offensive flagged, so that factor does not apply. Resolving the two
components independently is not equivalent.

Magic Storm 27 + Magic Tornado 28 and Magic Shield 54 + Explosive Shield 55
use the same raw-sum-then-single-resolver ownership. A correction to Golem's
composition must correct those sibling aggregate branches in the same pass.

## Validation receipt

- Final Mac static RE suite: `python3 tests/re/run_static_re_tests.py --ci`,
  `493/493` contracts pass on the exact Mod Loader candidate.
- Final Mac Website gate: `/opt/homebrew/bin/bash ./scripts/validate.sh`, exit
  zero; the affected pretest set passes `239/239` and the broad Boneyard set
  passes `1386/1386`.
- Built WebGL2 Boneyard Golem measurement: exactly 2,500 authoritative ticks
  and 25,048.728583 ms from cast-event tick to zero, blocked half-time input,
  accepted post-zero input, cap/current/common `2500/2497/147` at the first
  browser observation, and net `59.6` MP after intervening native recovery
  against an exact 60-MP cast debit.
- Built WebGL2 Boneyard membership measurement: all 23 rows agree with the
  table above; every dispatcher-true member has its square fan, while Mindstar
  and Regenerate have no armed current/fan. Page, console, and failed-response
  arrays are empty in both decisive receipts.
