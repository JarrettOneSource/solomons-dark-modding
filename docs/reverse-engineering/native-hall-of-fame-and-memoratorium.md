# Native Hall of Fame and Memoratorium memorial system

Status: closed for the retail executable with preferred image base `0x00400000`.
The executable used for static analysis and the clean populated observation has
SHA-256 `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

## Scope and method

This report joins two native consumers that were previously documented apart:

- the front-end `HallOfFame` controller and its scrollable `HallOfFameBox`;
- the Mortuary/Memoratorium's ordinary memorial presentation and adjacent
  eulogy/portrait branches; and
- the generic shipped `Social` leaderboard file loader, which is nearby in
  name but has no call edge into the Hall of Fame.

Evidence combines read-only Ghidra decompilation, raw x86 instructions, the
committed pristine Hall fixture, the stock atlas/bundle records, and a clean
direct launch seeded only with the retail distribution's own
`sandbox/halloffame.dat`. No loader DLL or mod was present in that populated
observation. The observed process was PID `18232`; the executable remained at
its preferred image base.

## Hall controller and collection ownership

| Owner | Address / record | Recovered role |
| --- | --- | --- |
| `HallOfFame` vtable | `0x00799334` | outer front-end controller |
| outer constructor | `0x00598120` | constructs the controller and child box |
| outer build | `0x005A07A0` | lays out the scroll box and Main Menu control |
| outer tick | `0x00589CD0` | integrates close progress and reinstalls Main Menu |
| outer continue | `0x00589DB0` | starts close only while the close rate is zero |
| `HallOfFameBox` vtable | `0x00799264` | scrollable entry collection and row input |
| box constructor/load | `0x005A13A0` | loads entries, materializes wizard views, sorts, and caps |
| box tick | `0x00589DD0` | advances entry/scroll presentation |
| row activation | `0x005981A0` | toggles one row's expanded state and recomputes extent |
| box render | `0x005A2C80` | collapsed wizard summary and expanded record details |
| death/archive writer | `0x005BC400` | appends the completed wizard record and writes `halloffame.dat` |

The outer close transition is exact: input writes rate `1.0` only when it is
currently zero. Tick integrates `progress += rate * dt`, clamps negative
progress, and installs Main Menu only after progress exceeds `1.0`. Entry-fade
input is therefore a no-op at the application surface even if a lower-level
call returns.

`HallOfFameBox` materializes the persisted wizard records, orders them by the
integer at wizard offset `+0x30`, and retains at most 100. Clean observation
identifies that sort key as the rendered `AWESOMENESS` value. The insertion
loop at `0x005A25F0..0x005A266D` stops when
`existing.awesomeness <= incoming.awesomeness`; an equal incoming record is
therefore inserted before the equal records already traversed. Because the
archive writer appends the current record, equal scores are newest-first, not
a stable oldest-first tie. The cap removes the lowest non-current entry first;
the current completed wizard is not silently discarded while the list is
reduced.

## Hall run-stat writers

The archive call at `0x005BC400` does not derive Awesomeness from experience.
It copies the already-authoritative `Game` counters into the Hall record:

| Hall field | Runtime source |
| --- | --- |
| monsters killed `WizardData+0x2C` | `Game+0x1C34` |
| Awesomeness `WizardData+0x30` | `Game+0x1C38` |
| elapsed ticks `WizardData+0x34` | `Game+0x28` |
| wave `WizardData+0x38` | local Arena wave `+0x8FF0` |
| awesomest-kill name `WizardData+0x40` | `Game+0x1CB0` |

The Time field is the Game-wide 100-Hz clock, not an Arena-entry duration.
Every base `Region::Tick` increments `Game+0x28` at `0x0063F223..0x0063F228`,
so normal Hub preparation is included. Local Player death tick
`PlayerActor+0x1BC` calls the archive writer at exactly decimal `300`
(`0x00533DCF..0x00533DE0`). The serialized value consequently includes the
three-second death presentation through that archive edge.

The same writer temporarily replaces two live PlayerActor fields before
serializing the wizard composite, then restores them afterward:

```text
portraitHeading = float32(180 + Float(65, signed))  // 115..245 degrees
portraitScale   = float32(0.85 + Float(0.15, unsigned)) // 0.85..1.0
```

The instruction spans are `0x005BC437..0x005BC488` and
`0x005BC48B..0x005BC4B8`; constants are exact float/double values
`65`, `180`, `0.15000000596046448`, and `0.8500000238418579`. These three
native RNG words and the resulting pose belong to the archived row. A Hall
renderer that reuses the corpse's last heading or fixes every portrait scale
to one is not reading the stock record.

Every staged contact returns through the shared Region callback
`0x0063E7D0` (84 direct callsites). When the contacted actor's virtual `+0x4C`
reports the newly accepted lethal state, that branch immediately calls the
awesomest-kill writer `0x005C9F40`, awards the enemy's experience, adds one
kill through `0x005C9430`, and finally calls the Awesomeness writer
`0x005C94E0` with base value one. Those are separate counters; experience is
not a score proxy.

`0x005C94E0` applies the following exact integer score recipe while an Arena is
active:

```text
pulseGate = trunc(min(regionPulseAccumulator + 0.5, 1.0))  // 0 or 1
points = basePoints * pulseGate

if local player is not in its alternate/death state:
    if currentHealth < 0: points *= 3
    else if currentHealth / maximumHealth < 0.1: points *= 2

streakMultiplier = clamp(
    floor((playerLevel * 100 + killStreak) / (playerLevel * 100)),
    1,
    5,
)
points *= streakMultiplier
awesomeness += points
```

Without an Arena, the raw base value is added. The health threshold is the
double at `0x007849E8`, exactly `0.10000000149011612`; the half-rounding term
at `0x007DE808` is exactly `0.5`. Potion use (`0x0056D1B0` subtype family
`0x1B59`) resets `Game+0x1CCC` through `0x005CB810` before applying the potion.

The awesomest-kill path compares the enemy's constructed maximum health at
actor `+0x170` against `Game+0x1CAC`. Once a prior positive maximum exists it
increments the kill streak before the comparison. A new maximum first awards
`71 + Integer(5) * playerLevel` through the same multiplier recipe, then
stores the exact formatted enemy name and maximum. The subsequent connected
death still adds the ordinary base-one award and kill count. The complete
formatter covers Skeleton equipment/burning variants, Archer headgear and
Fire/Poison variants, all four Skeleton Mage elements, Imp/Green Imp, Zombie
and Rotten Zombie, Wraith, The Discorporeal, Lesser Demon/Legion, Dire
Faculty, Heartmonger, Putrid/Tainted Coffin, Maggot, Spider, and Deep Portal.
The Coffin split is live actor `+0x238`, copied from recipe `+0x90`: zero
poison damage formats as Putrid and a positive Maggot-poison payload as
Tainted; it is not the max-Maggot field at actor `+0x22C`.

Awesomeness shares the Region pulse accumulator at `+0x8E08`; this is the
same state consumed by Arena world scaling, not a private Hall combo meter.
`Region::Tick 0x0063EFC0` subtracts `0.0025` per 100-Hz tick with a `0.1`
floor. `Region::ApplyCameraShake 0x0063EEB0` adds float32
`0.20000000298023224`, capped at `3.5`, after writing the presentation
magnitude. The complete ordinary death-presenter membership is:

| Later death presenter | Pulse request(s) |
| --- | --- |
| Skeleton / Archer / Mage `0x0048D2A0` | `0.1` |
| Imp `0x004824A0` | `0.05` when the two-child split is accepted; otherwise `0.1` |
| Zombie `0x004947B0` | `0.1` |
| Wraith `0x00495600` via shared dissolve `0x0047F8D0` | `0.1`, then `0.1` |
| Demon terminal helper `0x00482930` | `0.2` |
| Coffin `0x0049B310` | `0.2` |
| Dire Faculty `0x0049E8F0` | `0.2` |
| Heartmonger `0x0049FB60` | `0.2` |

Absorbed/sucked deaths take the shared dissolve branch and its single `0.1`
request instead of the family payload. Maggot retirement suppresses the
reward path. The Website survival roster exposes the first eight ordinary
families through Coffin; Dire Faculty, Heartmonger, the story bosses, external
portal actors, and absorbed-death producer remain separate product surfaces.

The order is material: the lethal-contact callback and both score writes occur
before that actor's later family death presentation requests its pulse. A kill
therefore reads the accumulator left by prior presentations; it does not count
its own pulse. The new-maximum bonus reads the pre-XP player level, experience
is then awarded, and the ordinary base-one call reads the resulting post-XP
level. This ordering is visible at `0x0063E81D..0x0063E85C` and must remain one
host transaction.

`0x005BC400` has one adjacent story-boast adjustment: a completed authored
Annalist boast multiplies the accumulated score by `1.100000023841858` and
truncates it before serialization. The ordinary survival path has boast index
`-1`, so this does not modify survival records. It belongs with the Hall's
already-dispositioned story/boast row branch rather than the Website survival
score.

## Hall row contract

The stock row has two visible states.

Collapsed:

- one-based rank (`#1`, `#2`, ...);
- the live serialized wizard composite;
- wizard name;
- `LEVEL <n> <discipline>`; and
- `AWESOMENESS: <n>`.

Class-title lookup `0x00658B40` drains the complete element-root by
discipline-root table (`body=5`, `mind=6`, `arcane=7`):

| Element | Body | Mind | Arcane |
| --- | --- | --- | --- |
| Ether | Sage | Seer | Occultist |
| Fire | Warlock | Pyromancer | Fire Mage |
| Air | Stormcaller | Astrologer | Storm Mage |
| Water | Icebinder | Thaumaturge | Frost Mage |
| Earth | Ritualist | Channeler | Earth Mage |

The fallback outside those 15 rows is `WIZARD`; valid Website loadouts never
need that invalid-selector fallback.

Expanded survival record:

- `SURVIVAL`;
- `TIME` and `WAVE`;
- the three highest learned skills, including icon and rank;
- `MONSTERS KILLED` and `AWESOMEST KILL`; and
- the authored 3-by-3 `PERKS USED` grid.

The renderer also has the compiled story/boast branch: boast text, failed,
succeeded, and not-accomplished states. That branch is data-bearing native
behavior, not another leaderboard metric.

The clean populated sample showed:

```text
#1 VOLUSIUS
LEVEL 1 SEER
AWESOMENESS: 91

SURVIVAL
TIME: 0:05:39
WAVE: 1
MONSTERS KILLED: 17
AWESOMEST KILL: SKELETON
```

The pristine committed fixture correctly shows the same frame with no entry
rows. Empty is a valid collection state, not a loading error.

## Global leaderboard adjacency

Retail has a separate generic `Social` singleton at `0x00B40600`, vtable
`0x007DE2FC`. Constructor `0x004452B0` owns two lists:

- `PointerList<SmartPointer<Leaderboard>>` at `Social+0x24`; and
- `PointerList<SmartPointer<Achievement>>` at `Social+0x3C`.

Loader `0x00445480` enumerates `social\`. It parses
`social\__achievements.dat` into achievements and every other accepted file
into a `Leaderboard` record containing a name plus a
`PointerList<SmartPointer<HighScore>>`. The shipped content tree has neither a
`social` directory nor any leaderboard file. An exhaustive direct-reference
scan of `0x00B40600..0x00B40654` found only construction, destruction, config
initialization, and this loader; the Hall constructors/renderers never touch
the Social block.

Therefore retail ships a dormant generic file format, not an online Hall of
Fame. A Website-global board is a product extension. It should reuse the
Hall's visible metrics and ordering vocabulary, but must not claim that the
retail Hall queried a server.

## Memoratorium consumer closure

The ordinary Mortuary composition is:

1. record 0 architecture before world actors;
2. ten Painting composites: record 3, portrait `14+id`, record 7, and optional
   record 8 at Painting-relative `(10,15)`;
3. the 16-heading Memorator body/head bank `28+i` plus `44+2i` and ordinary
   question marker 27;
4. 50 additive record-1 flames;
5. every normal world actor/effect consumer; and then
6. record 5 submitted three consecutive times at the room center after a
   five-unit vertical registration adjustment.

The record-5 pass is instruction-level, not an atlas-xref inference. At
`0x0050F45C`, `0x0050F4DE`, and `0x0050F567`, `ECX` is loaded from the
Memoratorium singleton and advanced by `0x40C`, the exact record-5 field. The
three calls at `0x0050F4D3`, `0x0050F55C`, and `0x0050F5E5` submit the same
registered `71 x 54` white memorial glow. Its world root is the room center,
`(512,507)` for the normal `1024 x 1024` Mortuary. The previous room report
recorded record 5 as effect-owned but the Website port implemented only the
record-1 flame family; that silent member caused the reopened room report.

The adjacent stateful branches remain distinct:

- portrait id `-1` selects blank easel record 4;
- portrait ids `0..9` select bundled records `14..23`;
- ids `>=100` load `Portraits\portrait<id>` and draw the raw captured image;
- marker bits select the urn overlay record 8;
- nonzero `Region+0x8F10` drives the Memorator eulogy state machine at
  `0x00513090`, including records 2, 6, and 7; and
- `Annalist2` uses records 11..13 in the alternate story population.

The normal new-game values remain portrait ids `0..9` and marker bits
`0,1,1,1,0,1,1,0,0,1`. The Website survival loop has no story campaign, so
the `Annalist2` replacement and story-only population are outside that product
surface. The ordinary glow, portrait, marker, Memorator, flame, collision, and
transition members are not optional.

## Implementation consequences

- Keep local browser history at the native 100-entry cap, descending
  Awesomeness order, and newest-first equal-score insertion.
- Replicate the authoritative run counters rather than reconstructing score
  from experience or retained client events. Use the same complete
  death-presenter pulse membership for Arena feedback and the score gate.
- Start Time with the Game/Hub lifecycle, freeze it at local death tick 300,
  and archive the writer-selected heading/scale from the same RNG stream.
- Preserve all collapsed and expanded survival fields. Website-global views
  may additionally sort those same records by wave, kills, or survival time,
  but those are explicit web views rather than invented retail behavior.
- Treat global submission and public query as Website ownership. Account
  authentication alone is not score provenance: the backend must bind the
  account id into the consumed server admission, the authoritative host must
  seal the completed row, and the API must verify that signed receipt against
  the caller. Guests and cheat-tainted runs remain local-only.
- Track initial and live `Enable Cheats` state at the host. Enabling it during
  an authoritative connection permanently revokes that connection's global
  eligibility; disabling it later does not restore eligibility. An accepted
  authoritative Lua execution independently revokes it. Any ineligible party
  participant taints the shared run.
- Treat the current client-held save document as untrusted provenance. Its
  schema validates shape but carries no server attestation, so a resumed
  lineage remains local-only rather than turning a forged save into a signed
  global score.
- Use the serialized wizard's element and heading for its row portrait instead
  of substituting an unrelated account avatar.
- Render Memoratorium record 5 as the exact extracted registered asset, three
  additive submissions at `(512,507)`, after normal actors/effects.
- Do not route the Hall through the dormant Social file loader, and do not
  describe that loader as a network service.

## Validation contract

- Collection tests cover empty, newest-first ties, all four visible metrics, the
  100-entry cap, idempotent run identity, and every expanded survival field.
- Score-kernel tests cover the pulse gate, every family pulse request, both
  health multipliers, the capped level-scaled streak multiplier, potion reset,
  new-maximum RNG bonus, exact variant names, and bonus-before-base ordering.
- Archive tests cover the Game-wide clock, death tick 300, signed heading draw,
  scale draw, RNG advancement, and one-time immutable pose.
- API tests cover signed server provenance, authenticated account binding,
  guest/body/signature/account tamper rejection, strict enums and bounds,
  idempotency, public reads, and independent Awesomeness/wave/kills/time
  ordering. Host tests cover clean receipt issuance plus anonymous, resumed,
  initial-cheat, live-cheat, and accepted-console withholding.
- Browser tests enter Hall from the stock main-menu control, exercise local and
  global boards, expand a row, scroll, and return through the Main Menu control
  without page or console errors.
- Mortuary tests assert record-5 identity, size, count `3`, position `(512,507)`,
  additive blend, and late painter depth, then the real room journey captures
  the settled 1600-by-900 scene.

## Validation receipt

- Static/native tooling: the focused binary-layout identity contract passed
  against the root and staged Solomon Dark Beta `0.72.5` layouts after the Hall
  address additions, and `run_static_re_tests.py --ci` passed `489/489` after
  refreshing the class-loadout fixture's provenance hash for that intentional
  layout-file change. The recovered addresses remain relative to preferred
  image base `0x00400000`; the analyzed executable SHA-256 is
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
- Website canonical gate: `./scripts/validate.sh` exited zero on 2026-08-21.
  Its current-main receipts include backend integration `12/12`, Boneyard
  prerequisite `158/158`, Boneyard/game `1048/1048`, parties `13/13`, Hall
  `15/15`, and successful production build/bundle/media gates. The same matrix
  passed from Windows, including the shared-Hub monotonic-expiry branches.
- Browser proof: the current Windows Hall journey exercised local history,
  expansion, all four global boards, newest-first equal Awesomeness, account
  attribution, and Main Menu return with no console/page errors. The current
  authoritative Hub journey entered Mortuary along six collision-safe
  waypoints, observed both fades, settled at `(512,904)`, captured the complete
  ordinary compositor including the triple record-5 glow, returned to the
  Courtyard, and reported no console/page errors.
- Evidence roots: clean stock Hall captures are in
  `C:\\codex-validation\\sdr-hall-filled-20260820`; current web captures are in
  `C:\\Users\\User\\Documents\\GitHub\\SB Modding\\Solomon Dark\\.codex-windows-validation\\hall-fame-memoratorium-20260820-root`.
