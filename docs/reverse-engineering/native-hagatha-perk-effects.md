# Native Hagatha perk gameplay effects

This report owns the gameplay behavior behind Hagatha's 28-row perk catalog.
The catalog names, prices, tooltip presentation, and transaction path remain in
[`native-hagatha-perk-catalog.json`](native-hagatha-perk-catalog.json); this
document owns downstream mechanics, runtime state, and lifecycle.

## Scope and provenance

- Retail image: Solomon Dark 0.72.5, 4,723,200 bytes, SHA-256
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
- Preferred image base: `0x00400000`.
- Static source: canonical `SolomonDark/ SolomonDark.exe` Ghidra project through
  the read-only replica wrapper.
- Supporting runtime evidence: the committed two-owner Steam Hagatha perk,
  derived-stat, damage-modifier, and runtime-correction matrices.
- Web gap reproduced 2026-08-23: all 27 obtainable purchases succeeded, but
  only selectors `0,1,3,4,9,17,19,21,23,27` reached their claimed effect.

No runtime address or injected process is used for the new instruction facts.

## Owner and lifecycle

`ActorProgression_ApplyHagathaPerk 0x0066EF70` is the common producer. It
rejects duplicate non-Tonic selectors, appends the selector to progression
`+0x7C0/+0x7C4`, sets byte `+0x7CC+selector`, initializes Cheat Death or the
two until-hurt bytes when applicable, and invokes refresh `0x0065F9A0`.

The complete durable/runtime fields are:

| Field | Offset | Meaning |
| --- | ---: | --- |
| selector array/count | `+0x7C0/+0x7C4` | ordered owned outcomes |
| flag base | `+0x7CC` | byte per selector 0..27 |
| capacity | `+0x800` | 3, 6, or 9 |
| Serendipity active | `+0x73C` | one-way true-to-false runtime state |
| Reverie active | `+0x73D` | one-way true-to-false runtime state |
| Cheat Death enabled/charges | `+0x81C/+0x820` | owned marker and 0/1 charge |
| melee multiplier | `+0x6F4` | Staff/melee lane, separate from spell damage |
| push strength | `+0x818` | actor collision strength |

Ownership, spent charges, and spent until-hurt bytes are participant-private
progression state and survive region replacement. The native multiplayer
correction path makes the host authoritative for the one-way runtime edges.

## Complete selector matrix

| ID | Member | Exact native consequence and owner |
| ---: | --- | --- |
| 0 | Life Charm | refresh `+0x74 *= 1.25`; current HP preserves its old ratio |
| 1 | Mana Charm | refresh `+0x80 *= 1.25`; current MP preserves its old ratio |
| 2 | Speed Charm | movement `+0x90` and cast speed `+0x94` each `*= 1.100000023841858` |
| 3 | Item Charm | useful-item candidate bound `*= 0.75` |
| 4 | Gold Charm | Gold candidate bound `*= 0.75`; final amount `*= 1.25` |
| 5 | Seeker's Charm | owner-local player renderer `0x0052A640` draws procedural lines to ground Gold, item Sacks, and magical Bonus actors |
| 6 | Revelation Charm | skill increment/set `0x00660320/0x00660580` clamps the affected rank to at least 2; purchase refresh also clamps selected concentration A/B |
| 7 | Cheat Death Charm | one charge; lethal damage restores `0.5 * maximum HP` and consumes the charge before death begins |
| 8 | Perky Charm | dormant catalog row; retail PerkShop offer construction excludes it |
| 9 | Scatter Curse | Orb candidate bound `*= 0.5`; Orb value-bonus flag enabled |
| 10 | War Charm | offensive spell mana factor `*= 0.75` |
| 11 | Curing Charm | poison damage lane only `*= 0.5` |
| 12 | The Last Word Charm | player death tick 200 invokes common Mindblast at scale 15, radius 825, damage 5000; completed-run tick 300 sweeps ground Sacks and Gold into the retained run output |
| 13 | Spellwelder's Charm | cache refresh `0x006623F0` calls the active Weld recombiner whenever components refresh; without the flag the constructed Weld remains frozen |
| 14 | Weird Caster Charm | purchase grants one random unlearned category-2 row if fewer than two are learned; offer builder `0x0067CB70` enables the discipline-root secondary bias |
| 15 | Drinker's Charm | health writer consumes one Health Potion at HP `<= -10`; mana writer consumes one Mana Potion only when a cost would underflow and `cost < maximum MP`, then retries once |
| 16 | Glass Cannon Curse | outgoing spell, outgoing melee, and incoming physical/magic/poison lanes each `*= 2` |
| 17 | Sorceror's Charm | one current-offer reroll or deferred choice; existing report owns the offer barrier details |
| 18 | Focus Charm | secondary recharge rate `*= 1.25` |
| 19 | Disfiguring Curse | enables the third ring sink |
| 20 | Bare Hands Charm | only with no weapon: spell damage `*= 1.149999976158142`, mana factor `*= 0.8500000238418579` |
| 21 | Split Mind Charm | two independent concentration selections |
| 22 | Curse Bosses | damage `*= 3` for native target types 1008 DemonSkull, 1009 Demon, 1010 DireFaculty, and 1011 Heartmonger only |
| 23 | Arcane Attractor Charm | magical-upgrade candidate bound `*= 0.800000011920929` |
| 24 | Serendipity Charm | active byte makes spell damage `*= 3`; positive remaining damage clears both until-hurt bytes |
| 25 | Reverie Charm | active byte makes offensive spell mana cost zero; the same hurt edge clears it |
| 26 | Brute's Charm | melee damage `*= 3`; actor push strength `*= 2` |
| 27 | Tonic | capacity `+3`, at most twice, maximum 9; Tonic bypasses the duplicate-list rejection, so its ordered selector may appear twice; common apply still sets ownership byte 27 on the first purchase |

## Missing-family instruction closure

### Seeker presentation

Player post-main vslot `+0x24 -> 0x0052A640` runs only for the local player and
only when selector 5 is owned. For each eligible ground actor at distance strictly greater than 100:

```text
d = min(distance, 300)
direction = normalize(target - player)
alpha = 0.75 + 0.5 * sin((2 * gameTick + 35 * actorId) degrees)
segment 1 = player + direction*35 -> player + direction*50
segment 2 = player + direction*50 -> player + direction*(d*0.5)
width = 3
RGB = (0.85, 0.73, 0.44)
```

Segment one fades transparent-to-gold and segment two gold-to-transparent.
The path is source-alpha and belongs after the player's main world painter but
before later post-world managers. It consumes no gameplay RNG and is never
replicated as state; each owner derives it from authoritative loot positions.

### Revelation and Weird Caster

Both normal rank increment and direct-rank writers clamp the one affected row
to rank 2 when selector 6 is present; rows already above two remain unchanged.
Refresh does not upgrade the entire old book. It separately checks the selected
concentration IDs at `+0x86C/+0x870` so buying the charm repairs rank-one A/B.

Selector 14's purchase refresh counts learned category-2 rows. Below two, it
builds the ascending unlearned category-2 set, consumes one shared
`Integer(count)`, and learns that row. Revelation composes naturally because
the ordinary rank writer handles the grant. Offer construction skips its
ordinary category-2 focus suppression and gives discipline-root secondary rows
the recovered duplicate weighting.

### Spellwelder

An active native Weld is a constructed cached object at progression `+0x750`.
`Skills_Wizard::RebuildCaches 0x006623F0` calls its virtual recombiner only when
selector 13 is set. Therefore component ranks are frozen at construction for an
uncharmed player; recomputing from live component ranks for everyone is not
equivalent. All ten authored build component tables share this rule.

### Drinker, until-hurt, and Cheat Death order

Health mutation `0x0052AC80` first writes/clamps HP. At HP `<= -10`, it invokes
`0x005296A0`, which finds and consumes one Health Potion through the ordinary
inventory activation path. Mana mutation `0x0052B150` invokes `0x00529710`
only when the requested cost would underflow and is strictly below maximum MP;
one Mana Potion is consumed and the same debit is evaluated again.

Player damage `0x0052F540` applies Glass and Curing to their distinct lanes,
then clears Serendipity and Reverie together only if positive damage remains.
Drinker has already had the chance to rescue lethal HP. If the player is still
lethal, Cheat Death consumes one charge and writes half maximum HP. This order
is observable and authoritative.

### Last Word

`PlayerWizard::Tick 0x00533520` invokes `0x00645B50` at death tick 200. The
call passes presentation scale 15 and raw damage 10000. The common helper uses
query scale 55 and damage factor 0.5, producing radius 825 and damage 5000.
It owns the complete existing Mindblast presentation and audio:
`magicshieldexplode`, `bigfire` at pitch 1, and `bigfire` at pitch 0.8.

At completed-run tick 300, `0x005C9670 -> 0x005BE320` passes selector 12 as
the ground-sweep gate. It credits every ground Gold actor and moves the held
item from every ground Sack into the retained named Sack inserted into Luthacus
storage. Orbs, Bonus actors, and unrelated world objects are not swept. Claimed
actors are removed, making the operation one-shot.

## Web parity consequences

- Keep merchant transactions and effect consumers separate; purchase is the
  authoritative producer but not the implementation of the effect.
- Persist and replicate Cheat Death charges and the two active bytes.
- Persist a six-rank Weld component snapshot beside an active build, updating
  it only under Spellwelder refresh.
- Keep spell and melee multipliers distinct. Feed Brute push strength into both
  Hub and Boneyard actor physics.
- Apply Glass before defense/shield resolution and clear until-hurt after the
  remaining-damage boundary.
- Derive Seeker locally from replicated loot and reuse the existing complete
  Mindblast actor/presentation/audio family for Last Word with parameter
  overrides.

No member is blocked by the browser platform.
