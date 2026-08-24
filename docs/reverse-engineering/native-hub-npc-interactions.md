# Native Hub NPC interactions

Status: **closed for the retail survival Hub**, 2026-08-24. All addresses are
preferred-image addresses in the unmodified retail `SolomonDark.exe` 0.72.5,
4,723,200 bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
loaded in the canonical read-only Ghidra project `SolomonDark` at image base
`0x00400000`.

This report closes the interaction content deliberately left open by the G8
Hub/economy pass. It owns the survival-Hub dialogue graph, the three
`ChatExtend` services (`Boast`, `BookReview`, and `SellSpell`), their state
effects, the optional Tyrannia/Skorcha actor, and the downstream Boast result.
Trader inventories and transactions remain owned by
[`native-hub-and-economy.md`](native-hub-and-economy.md).

## Evidence and provenance

| Evidence class | Exact source | Finding |
| --- | --- | --- |
| Retail image | `SolomonDarkAbandonware/SolomonDark.exe`, identity above | All functions, vtables, globals, offsets, constants, and xrefs below refer to the same preserved executable. |
| Runtime-loaded dialogue | Beta 0.72.5 `data/dialogue/survival.txt`, SHA-256 `5e792f4dc692667d0ecaa4e7304202f11d2d1cdc664820b97be83145fa3b2d67` | `Game` loads this aggregate through `0x005CDC70`; it is authoritative when it differs from the retained per-speaker authoring files. |
| Selector content | `books.txt` SHA-256 `d7ca0a36c2fe6af90a4a950d5ff3dab7638f43640de97684eb6a7583a02b24a1`; `spellfacts.txt` SHA-256 `1d78d408664ea830465e7e5a8b56df2c6373cb4f6685dc025a1a6d0f90ab0e17`; `narration.txt` SHA-256 `5a80f605f8fcac7fc634f8234d5b0a0173d3d4aa563dc076cc6d1b4dbc649174` | Complete BookReview rows, Teacher explanations, Painting/eulogy lines, Boast eulogies, and interruption lines. |
| Fresh static trace | `Game` ctor `0x005CC800`, dialogue loader `0x005CDC70`, survival Region builder `0x0050B720`, Courtyard constructor `0x00514EE0`, special dispatcher `0x004FB890`, common NPC action `0x00501800` | Recovers every actor, dialogue node, command edge, name owner, construction path, and Courtyard reconstruction boundary. |
| Conditional-gate instructions | `0x004736D0`: `MOV AL,1; RET`; `0x00461F60`: `XOR AL,AL; RET`; builder calls at `0x0050BD0C/0x0050BDD9` | Machinimbus is unconditional in retail 0.72.5. The second constant-false branch controls an extra non-actor Region initialization call, not an unlockable NPC. |
| Fresh class trace | `Chat` ctor/update/render/input `0x004F5D90/0x004FFEE0/0x004F9380/0x004FFBC0/0x004FFC40`; `ChatExtend` render `0x004F7BA0`; selector functions listed below | Recovers modal replacement, scrolling, row selection, prices, feedback, and teardown. |
| Fresh downstream trace | Boast select `0x004FC340`; failure `0x005CB110`; potion/equipment/secondary/mana writers `0x005CB810/0x00577760/0x0054CC50/0x0052B150`; Levelup `0x00656B50/0x0066F920`; terminal award `0x005BC400` | Closes all five challenge branches, one-shot failure, automatic choice, Wave-30 contract, and score bonus. |

The retained per-speaker files are useful authoring witnesses but are not the
runtime dialogue source. For example, the retained Annalist file contains an
`Interesting how?` question and the retained Scavenger file contains
`Outfit me Randomly`; the survival builder does not append either row. The web
port must follow the compiled builder plus the aggregate, not merge every
retained line into a larger invented menu.

## System boundary and complete membership

Native system: **named survival-Hub interaction**, beginning at a named actor or
Painting hit, continuing through `Chat`, an optional `ChatExtend` selector or
shop replacement, and ending at response completion, back, distance, Region
replacement, state mutation, or downstream Boast resolution.

| Member | Native owner | Disposition |
| --- | --- | --- |
| Hagatha dialogue, price question, PerkShop command | type 5001; `WITCH_INTRO/WITCH_Q`; `!BUYPERKS` | exact-port required; trader transaction already closed by G8 |
| Fomentius dialogue and Shop command | type 5004; `POTIONGUY_INTRO`; `!BUYPOTIONS` | exact-port required; transaction already closed |
| Provokatus dialogue and five-row Boast service | type 5003; `ANNAL_INTRO`; `!BOAST`; `Boast/BoastBox` | exact-port required, including all challenge effects |
| Luthacus dialogue and InventoryShop command | type 5005; `SCAVENGER_INTRO`; `!INVENTORY` | exact-port required; storage transaction already closed |
| Skorcha optional dialogue and three dismissals | type 5007 `Tyrannia`; `ENFORCER_INTRO` and dismiss 1..3 | exact-port required with generated membership/placement |
| Professor Machinimbus dialogue, question, and eight-row SellSpell service | type 5008; `TEACHER_INTRO/TEACHER_Q`; `!SPELLS`; `SellSpell/SellSpellBox` | exact-port required; actor is unconditional because its apparent gate returns one |
| Declarius dialogue and two questions | type 5017; `MEMORATOR_INTRO/Q1/Q2/DISMISS` | exact-port required |
| Paintings `0,1,100,3,4,5,6,7,8,9` | type 5018; `0x00506190/0x00506100`; narration table | exact-port required; 100 deliberately has no static `SAY_EULOGY_100` row |
| Professor Semicus dialogue and 26-row BookReview service | type 5013; `LIBRARIAN_INTRO`; `!BOOKS`; `BookReview/BookBox` | exact-port required; actor and 26 initial rows are unconditional in survival, including one-shot Lace removal |
| Shlorio dialogue, price question, and DowsingShop command | type 5016; `DOWSER_INTRO/DOWSER_Q`; `!DOWSE` | exact-port required; transaction already closed |
| Archchancellor dialogue, equipment question, dismissal | type 5012; `ARCH_INTRO/ARCH_Q/ARCH_DISMISS` | exact-port required |
| roaming Students | type 5002, no-op action slot `0x0055C300` | out-of-system: native noninteractive ambient actors |
| StoreRoom | fixed Region with no named actor | out-of-system: no native NPC producer |
| Solomon Dig | type 5009 Arena prelude | out-of-system: separately closed encounter/dialogue state machine |
| recipe-authored `GameNPC` | type 5015 | out-of-system: Boneyard scripting family, not a compiled Hub named actor |
| story-only Polisher, Annalist2, standing/desk Arch variants and `_0/_1` graphs | alternate builder `0x00513BE0` | out-of-system for the Website survival game; complete static membership remains documented in the Hub report |
| dormant `ANNAL_Q`, `!RANDOMEQUIP`, targeted Dowsing | data with no normal-survival builder/dispatcher producer | out-of-system; must not be exposed as retail behavior |

No member is blocked by the browser platform.

## Dialogue ownership and state machine

`Game::Game` (`0x005CC800`) initializes the compiled NPC display names. The
survival actors resolve to `The Archchancellor`, `Provokatus`, `Fomentius`,
`Hagatha`, `Declarius`, `Shlorio`, `Luthacus`, `Professor Semicus`,
`Professor Machinimbus`, and `Skorcha`. The last name is not the C++ class name:
Tyrannia's actor stores dialogue pointer `Game+0x21A4`, and `Chat::Render` reads
its title at dialogue `+0x54 = Game+0x21F8`, the compiled `Skorcha` String.

The common action `0x00501800` allocates the 400-byte `Chat`, passes the actor
and actor `+0x154` dialogue tree to `0x004F5D90`, attaches it as the active UI,
and sets actor `+0x170 = 1`. `Chat` owns one of three phases:

1. a scrolling answer at 0.125 pixels per 100-Hz tick (0.8 accelerated);
2. the live question/command list; or
3. a randomly selected dismissal when the graph has no live question.

Natural completion or Skip calls `0x004FFB00`. A regular question calls
`0x004FD6A0`, streams its answer, then returns to the same question list. A
command whose answer begins with `!` calls dispatcher `0x004FB890`; that
replaces `Chat` with its service rather than stacking a second actionable UI.
Done/back runs the dismissal/close path. `0x004FCB40` clears actor engagement,
active speech, input ownership, and the current `Gameplay+0x1C08` Chat pointer.
The common actor tick `0x00505010` additionally closes on Region loss or
`distance_squared > 5 * radius^2 + 1500`.

### Compiled survival graph

| NPC | Intro key | Live regular questions | Live command | Dismissal |
| --- | --- | --- | --- | --- |
| Hagatha | `WITCH_INTRO` | `WITCH_Q` (`Charm Prices?`) | `Buy Charms and Curses` -> `!BUYPERKS` | direct close |
| Fomentius | `POTIONGUY_INTRO` | none | `Buy` -> `!BUYPOTIONS` | direct close |
| Provokatus | `ANNAL_INTRO` | none (`ANNAL_Q` is not appended) | `Boast` -> `!BOAST` | direct close |
| Luthacus | `SCAVENGER_INTRO` | none | `Examine Items` -> `!INVENTORY` | direct close |
| Skorcha | `ENFORCER_INTRO` | none | none | uniformly selected from `ENFORCER_DISMISS1..3` |
| Machinimbus | `TEACHER_INTRO` | `TEACHER_Q` (`Spell Testing?`) | `Per$uade` -> `!SPELLS` | direct close |
| Declarius | `MEMORATOR_INTRO` | `MEMORATOR_Q1` (`This memorial?`), `MEMORATOR_Q2` (`These mages?`) | none | `MEMORATOR_DISMISS` |
| Semicus | `LIBRARIAN_INTRO` | none | `Inquire about Books` -> `!BOOKS` | direct close |
| Shlorio | `DOWSER_INTRO` | `DOWSER_Q` (`Dowsing Prices?`) | `Dowse` -> `!DOWSE` | direct close |
| Archchancellor | `ARCH_INTRO` | `ARCH_Q` (`Equipment?`) | none | `ARCH_DISMISS` |

Inline `*...*` emphasis is part of the ExactText input. The aggregate's
spelling, capitalization, punctuation, repeated spaces, and trailing spaces are
content, not copy-edit opportunities.

## Conditional actor gates and discoverability

The normal survival builders contain only one conditional named-actor producer:
Skorcha/Tyrannia. Semicus is constructed unconditionally in Library case
`0xFA4` at `(512,595)`. Machinimbus appears to sit behind a call at
`0x0050BD0C`, but the callee `0x004736D0` is exactly `MOV AL,1; RET`; every
retail Courtyard therefore constructs the Teacher at `(576.5,710.5)`. His
eight offer rows are progression-gated, not the actor.

The nearby call to `0x00461F60` is not another NPC gate. That function is
exactly `XOR AL,AL; RET`, so the guarded call to Region initializer
`0x005001E0` is unreachable and the following unconditional call still runs.
The three bytes `0x0081A3CA..CC` can suppress the Annalist, Hagatha, and
Luthacus action bubbles during Region construction, but do not suppress those
actors or their action callbacks; their wrappers at `0x005018A0/B0/C0` clear
the corresponding byte and tail-call the common Chat action.

Story-phase Polisher/Arch/alternate dialogue members are selected by the
separate builder `0x00513BE0` and `Gameplay+0x1CD8`. They are not unlockable
members of the normal survival Hub and must not be injected into that census.

## Provokatus and `Boast`

`Boast` uses vtable `0x00790A24`, ctor/render/action/update
`0x004F7D20/0x004F7DC0/0x004FC340/0x004FFD50`. Its `BoastBox` subobject uses
vtable `0x00790794`, ctor/populate/render/action
`0x004F6C00/0x004F99F0/0x004FDEC0/0x004F7FE0`.

The population is exactly five rows in this order:

| ID | Selector label | Stored boast text | Confirmation key | Failure producer |
| ---: | --- | --- | --- | --- |
| 0 | `POTIONS ARE FOR PEASANTS!` | `"I can do this entire mission without drinking a single potion of any kind!"` | `ANNAL_POTIONBOAST` | successful use of Item_Potion type 7001, any of its six subtypes (`0x0056D1B0 -> 0x005CB810`) |
| 1 | `I'M TOO MACHO FOR MAGIC!` | `"A true magician does not wear magical clothing, rings, or other implements!"` | `ANNAL_ITEMBOAST` | applying a nonempty magical equipment-effect list (`0x00577760`) |
| 2 | `SECONDARIES ARE SISSY!` | `"The learned wizard need not cast secondary spells at all!"` | `ANNAL_SECONDARIESBOAST` | entering the secondary dispatcher `0x0054CC50`, before its spell switch |
| 3 | `I AM ONE WITH THE MAGIC!` | `"A master sorceror does not choose magic, the magic chooses him!"` | `ANNAL_RANDOMBOAST` | no ordinary failure; player ctor/reset `0x0065F5B0` sets actor `+0x2D`, and each LevelupScreen chooses `Integer(option_count)` after 100 ticks |
| 4 | `I NEVER RUN OUT OF MANA!` | `"A profound practicioner of magic never allows his mana pool to empty!"` | `ANNAL_MANABOAST` | a mana debit for which `current + delta < 0` (`0x0052B150`); an exact zero is not failure |

Selection writes the signed byte at `Gameplay+0x1D44`, copies the exact stored
text to `Gameplay+0x1D48`, and streams the matching Annalist confirmation. The
surface closes after 100 ticks. `Chat` teardown then creates a native `Notebox`
stating:

```text
To succeed at your boast, you must
survive until at least Wave 30
```

`Gameplay+0x1D80` is the one-shot failure bit. `0x005CB110` changes it only
from zero to one and creates `FAILED "<stored boast text>"`; later violations
do not create another failure box. The selected ID, text, failure bit, and
success bit are serialized by the resumable Game serializer
`0x005CE3D0`/`0x005BC400`, not by the durable `darkdata` profile.

At the terminal survival boundary, `0x005BC400` sets
`Gameplay+0x1D81 = 1` only when a boast is selected, the failure bit is clear,
and the run score is valid. It replaces score with
`trunc(float(score) * 1.100000023841858)`. A failed or absent boast receives no
multiplier. The Wave-30 wording is the user-facing admission contract. The
success bit also suppresses Declarius's random `SAY_BADEULOGY_0..7` tail.

## Professor Semicus and `BookReview`

`BookReview` uses vtable `0x00791184`, ctor/update/render/action
`0x004FA090/0x004FFDC0/0x004F80B0/0x004F5310`. `BookBox` uses vtable
`0x00790864`, populate/render/action
`0x004FC550/0x004FE6F0/0x004FA290`.

`0x005CDC70` loads all 26 `books.txt` records and, in survival mode, enables
every availability byte at `Gameplay+0x22F8`. Their fixed order is:

0. Merdalf's Hex Handbook Vol One: Elementus Ether
1. Ethics and Magic: A Moral Philosophy
2. The Mythology of Theft: Fire
3. The Magenta Man's Burden
4. The Book of A Thousand Madnesses
5. The Brothers Karagrimm
6. Elementus Air (For Dullards)
7. A Solstice Story
8. Feeling Chill: Frost Magic
9. MacBlandish
10. Wizards in History: The Mild Embarrassment
11. Wizards in History: The Great Censure
12. Wizards in History: We Didn't Need Two Moons
13. The Rime of Sovereign Sea
14. How to Win Friends and Immolate People
15. Merdalf's Hex Handbook Vol Five: Elementus Earth
16. How to Train Your Chosen One
17. The Discipline Arcane: Index
18. Vie Spells Forbade
19. Ral Qursia: The Noble Archchancellor (An Autobiography)
20. Elemental Welding (For Dullards)
21. Meditation: Mastering the Mind
22. Discipline of the Body
23. The Sorcerer's Supremacy
24. The Economicon
25. Lace! The Scarlet Witch's Stocking

`BookBox` hashes each record key into the native Books-atlas record, displays
the title, and scrolls the complete row list. Selecting a row closes the picker
after 100 ticks, streams that record's complete `books.txt` response, and
returns to Semicus's live Chat choices. `BOOK25_LACE` is a durable one-shot:
when chosen, `0x004FA290` sees `LACE!`, sets profile byte
`DAT_0081A435` (`profile+0x105`), and calls profile save `0x005BE0B0`.
Subsequent BookReview construction omits only the `_LACE` row. It is present
before that flag, not unlocked by it.

## Professor Machinimbus and `SellSpell`

`SellSpell` uses vtable `0x00790B04`, ctor/update/render/action
`0x004F82D0/0x004FA3B0/0x004FA460/0x004F90C0`. `SellSpellBox` uses vtable
`0x00790934`, populate/render/action
`0x004F8480/0x004FECB0/0x004F91D0`.

The row table is fixed and complete:

| Skill ID | Name | Price | Quick description |
| ---: | --- | ---: | --- |
| 72 | ACID RAIN | 3000 | A modified version of Magic Storm that produces a shower of hot acid. |
| 73 | FIRE WALL | 3500 | Calls up a flaming wall that burns enemies as they pass through it. |
| 74 | ETHER DRAIN | 4200 | Opens a hole into a quadrant of the ether that sucks. |
| 75 | IRON GOLEM | 5000 | Upgrades your golem with iron spikes that reflect physical damage. |
| 79 | REGENERATE | 5100 | Magically supplements your visceral recovery node for quicker healing. |
| 78 | MINDSTAR | 5300 | Supplements your cognitive nexus with magical force. |
| 77 | TURN UNDEAD | 6100 | Weakens nearby undead and causes them to flee the caster. |
| 76 | CALL COMET | 10000 | Calls a frozen ball of ice down from the firmanent. |

Rows whose `0x00B3BDD8..0x00B3BDDF[id-72]` unlock byte is already one are
omitted. `SellSpellBox::Action` calls the common gold mutation
`0x005A7C60(-price, 0)`. Insufficient gold retains the picker, leaves the row
locked, and plays `badaction`. Accepted payment selects the row; `SellSpell`
sets the corresponding unlock byte, closes after 100 ticks, streams the full
`spellfacts.txt` explanation, and makes that skill eligible to the ordinary
progression/loot/offer paths. If no rows remain, the body says exactly
`ALL SPELLS\nALREADY BOUGHT!`.

The unlock flags gate progression at `0x00579E90`, `0x0065E830`, and
`0x0065EBA0`; buying a spell does not immediately grant a rank or bind a belt
slot. It unlocks future acquisition.

## Optional Skorcha/Tyrannia

Every normal Courtyard construction calls `Integer(3)` and creates type 5007
only when the result is one. A second `Integer(3)` chooses one of these exact
placements:

| Variant | Position | Extra authored state |
| ---: | ---: | --- |
| 0 | `(1437.5, 732.5)` | default |
| 1 | `(1637, 403.5)` | actor `+0x17C = -1`; Luthacus `+0x15C = 1` |
| 2 | `(669, 705.5)` | default |

The first two rows correct an earlier decompiler-order transcription error.
Raw stores in `0x0050B720` write actor X at `+0x18` before Y at `+0x1C`:
variant 0 writes globals `0x00792F8C = 1437.5` and
`0x00792F88 = 732.5`; variant 1 writes `0x00792F94 = 1637` and
`0x00792F90 = 403.5`; variant 2 writes `0x00792454 = 669` and
`0x00792F98 = 705.5`. Reading the globals in ascending-address order had
silently swapped X/Y for variants 0 and 1. All three are ordinary Courtyard
resident coordinates owned by the normal camera bank.

The actor has radius 10. Constructor/tick/render are
`0x00502450/0x0050B1F0/0x0051C560`; art is College records `510..516`.
The render instructions split that art into two independently registered
banks: actor `+0x178` selects `Game+0x2644/+0x2648` records `510..512`, while
`round(actor+0x144)` selects `Game+0x2654/+0x2658` records `513..516`. Both
passes use actor `+0x17C` as horizontal scale; the second placement writes
`-1`, and the constructor initializes the other placements to `+1`.
The four-record hat bank uses the inherited animator at actor `+0x13C`: while
idle, `Integer(200)==2` starts a sweep at
`float((Float(3)+1.0)*0.45)` degrees per tick; the stored phase advances to
180 and the render index is nearest-integer
`sin(phase*pi/180) * (4.0-0.01)`. Index four is the vector's blank resized
apex, while indices zero through three select College `513..516`.
Every `Integer(10)+20` ticks, the actor chooses a new one of three gesture
states, rejecting the immediately previous state. The dialogue title is
`Skorcha`, the intro is `ENFORCER_INTRO`, and completion chooses uniformly from
the three compiled dismissal nodes. Presence, placement, animation state, and
dismissal belong to that Courtyard instance. Stock destroys and reconstructs
Region actors on a room switch, so a later Courtyard entry performs a fresh
pair of population draws. A shared web Hub must keep one authoritative result
while at least one participant occupies the Courtyard, destroy it when the
Courtyard becomes empty, and reroll on the next zero-to-one occupancy edge;
clients must never reroll independently.

## Paintings and Declarius

Painting action `0x00506190` finds the room Memorator and passes the exact
Painting `+0x174` index to `0x00506100`. Static rows are
`0,1,3,4,5,6,7,8,9`; index 100 is deliberate and has no static
`SAY_EULOGY_100` entry. Declarius walks/turns toward the active portrait and,
after the principal line, adds one uniformly selected
`SAY_BADEULOGY_0..7` unless the current run's Boast success bit is set. Walking
away can select `SAY_EULOGY_INTERRUPT1..4` through the common speech lifetime.

This edge is not the ordinary `Chat` engagement path. The Painting keeps its
recovered radius-15 hit body beside the paired radius-40 solid, then its action
override directly starts the Memorator-owned eulogy. Consequently the
Painting itself does not enter the common radius-15 Chat teardown calculation;
using that calculation as a controller proximity gate makes all ten targets
unreachable behind their paired solids. A web controller prompt may use the
paired radius 40 for reachability while the pointer hit remains the exact
radius-15 actor circle.

The Website's current static portrait labels may reproduce rows 0,1,3..9.
Index 100 must remain empty unless the Website has a concrete archived-wizard
producer; it must not be silently normalized to missing index 2.

## Multiplayer and persistence consequence

Retail has one local Game/profile. The portable owner is the initiating
participant:

- dialogue and selector focus are presentation-local and block only that
  participant's input in the Website's accepted live-Hub policy;
- gold payment, advanced unlocks, Lace one-shot state, active Boast, failure,
  automatic choice, success, and score bonus are host-authoritative and
  participant-private;
- Lace is durable profile state;
- advanced spell unlocks live with the participant's progression book;
- active Boast ID/text/failure/success live with the current resumable wizard
  and reset when that wizard is retired for the next run; and
- optional Skorcha membership/placement is authoritative Courtyard-instance
  state, regenerated on each authoritative Courtyard construction rather than
  participant-local render state or durable save state.

## Validation contract

- Assert every compiled survival actor and Painting index, and assert the
  explicit noninteractive/out-of-system membership.
- Assert every runtime aggregate line/key and every selector row, not samples.
- Exercise every regular question, command replacement, selector response,
  dismissal, back, distance, Region change, and teardown branch.
- Exercise all five Boast failures, exact-zero mana nonfailure, one-shot
  Notebox behavior, automatic 100-tick choice, Wave-30 success, and truncating
  1.1 score award.
- Exercise all 26 books, Lace's present-then-absent durable transition, all
  eight Teacher prices, insufficient gold, accepted unlock, already-owned
  omission, and all-bought state.
- Exercise all three Skorcha placements/gesture states, both absent/present
  authoritative populations, shared occupancy retention, last-exit teardown,
  next-entry reroll, and Hub-resume reconstruction.
- Browser acceptance must open every named NPC, every selector family, one
  representative book and every Teacher/Boast mutation family, and must capture
  empty page-error, console-error, and failed-response arrays.

## Conditional-population closure receipt

The final manifest-identical Mac candidates passed the registered Loader
static-RE suite `499/499` and the Website's complete supported gate, including
59 Hub UI tests. Chrome 151 on Apple M2 Metal proved initial Skorcha absence,
Library exit/re-entry, authoritative variant-0 reconstruction and prompt, all
20 named interactions, and separate variant-1/variant-2 conversations with
empty page, console, and failed-response arrays. Semicus's Library/BookReview,
Machinimbus's always-present actor and gated spell rows, and Provokatus's
five-row Boast selector were visible in the continuous journey.
