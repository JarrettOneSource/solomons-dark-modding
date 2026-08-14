# Solomon Dark Boneyard scripting

This document recovers the retail Boneyard scripting ABI: `TriggerControl`,
`Trigger`, `CodeLine`, `ScriptThread`, `TimeLine`, `TimeLineEvent`, `Spawner`,
and the recipe objects referenced by those systems. It also maps the stock
Bonedit authoring surface and follows the serialized graph into the Arena's
per-tick evaluators.

The recursive container and RegionLayout envelope are documented separately in
[`boneyard-system.md`](boneyard-system.md). This chapter begins at
RegionLayout section 1 (`TriggerControl`), sections 3/4/7/8/9 (recipes), and
section 13 (`TimeLine`).

All addresses are image-base virtual addresses for the analyzed retail
`SolomonDark.exe`:

- image base: `0x00400000`
- file size: `4,723,200` bytes
- SHA-256: `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`

## Conclusions

- Boneyard scripts are typed object graphs, not text. `CodeLine` is the common
  instruction record used for trigger predicates, script actions, nested
  control flow, and TimeLine spawn records.
- A `CodeLine` opcode is accompanied by a variable-length typed operand array.
  Operand type is serialized with every value; action IDs do not imply a fixed
  byte width. Null operands are real type-0 entries and must not be discarded.
- Bonedit exposes 15 trigger types, 14 predicates, 94 menu registrations for
  92 unique action IDs, seven placeable TimeLine event kinds, and three spawn
  record kinds. Event kind 7 is runtime-created and is not offered as a normal
  graph node.
- Trigger conditions use ALL/AND or ANY/OR composition. Predicate flag bit 0
  negates a condition. Script execution is cooperative: `ScriptThread` runs at
  most ten zero-delay instructions per tick, then yields on sleeps and native
  asynchronous wait tokens.
- TimeLine graph X is execution time/order; graph Y is the stable tie-break and
  editor lane. Relinking sorts events by X then Y before the Arena tick walks
  them.
- Spawn events create transient `Spawner` objects. Spread duration, steady or
  chaotic scheduling, recipe/group selection, and spawn-location policy are
  data, while actual monster construction remains compiled native behavior.
- There is no stock generic “enable/disable scenery object” action. Scripts can
  change weather, start fire or explosions, invoke off-screen magic, lock the
  camera, set music, and destroy off-camera objects. Flags and counters can
  coordinate compiled logic, but they are not an arbitrary scenery-property
  API.
- Recipe sections are definition stores addressed by UIDs. The post-load pass
  at `0x0064BC40` resolves those UIDs, trigger script links, timeline label and
  event links, NPC links, group members, and type-5 `CodeLine` operands to live
  pointers.

## Native class map

The stock factory type is shown where the class is factory-managed. `Trigger`,
`TriggerControl`, and `CodeLine` are constructed by their owning serializers
rather than by RegionLayout's polymorphic manager.

| Class | Type | Allocation | Vtable | Constructor | Destructor body / delete slot | Sync |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `CodeLine` | owned | `0x20` | `0x007A0EB8` | `0x006821B0` | `0x00683530` / `0x00686060` | `0x00683C10` |
| `Trigger` | owned | `0xC0` | `0x007A0F90` | `0x00684040` | `0x00684150` / `0x00686080` | `0x00684360` |
| `TriggerControl` | embedded | — | `0x007A0FE0` | `0x006860A0` | `0x00686210` / `0x006894D0` | `0x00686400` |
| `ScriptThread` | 3008 / `0x0BC0` | `0x80` | `0x007A0F4C` | `0x00682C10` | vtable `+0x00` `0x00682D40` | `0x00684610` |
| `TimeLine` | 6006 / `0x1776` | `0xE8` | `0x0079F308` | `0x00640E60` | `0x00640F20` / `0x00646F60` | `0x00646F80` |
| `TimeLineEvent` | 6007 / `0x1777` | `0xA4` | `0x00789080` | `0x004A9E80` | `0x004A9F40` / `0x004AA0E0` | `0x00652040` |
| `Spawner` | 6008 / `0x1778` | `0x44` | `0x00785884` | `0x00463400` | vtable `+0x00` `0x00448DD0` | `0x00463460` |
| `MonsterRecipe` | 6001 / `0x1771` | — | `0x0079F208` | `0x006400C0` | vtable `+0x00` `0x00644BE0` | `0x0063E890` |
| `UIDGroup` | 6002 / `0x1772` | — | `0x00799FB4` | `0x005AFF00` | vtable `+0x00` `0x005BA670` | `0x0064A130` |
| `ItemRecipe` | 6003 / `0x1773` | — | `0x007963A4` | `0x00573410` | vtable `+0x00` `0x00574D30` | `0x00570D90` |
| `NPCRecipe` | 6004 / `0x1774` | — | `0x0079F2E4` | `0x00640C20` | vtable `+0x00` `0x00646A60` | `0x0063EBD0` |
| `ItemSet` | 6005 / `0x1775` | `0x5C` in the stock definition loader | `0x00796450` | `0x00573CB0` | vtable `+0x00` `0x005753E0` | no-op `0x0042E260` |

The object-manager types all use virtual slot `+0x14` for `Sync`. A `Spawner`
also exposes initialize at vtable `+0x04` (`0x00463440`) and tick at `+0x08`
(`0x0046D000`). A `ScriptThread` exposes tick at `+0x08` (`0x0068B060`).

## `CodeLine`: common bytecode record

`CodeLine::Sync` at `0x00683C10` is symmetric. A list stores a count in its
payload and then two children per line: a header and a body wrapper.

```text
CodeLineList payload:
    u32 line_count

for each line:
    child header payload:
        u32 opcode
        u32 flags
    child wrapper payload: empty
        child body payload:
            u32 operand_count
            repeat operand_count:
                u8 operand_type
                value selected by operand_type
            u8 has_nested_lines
            if has_nested_lines:
                u32 nested_line_count
                CodeLine header/wrapper children[nested_line_count]
```

The `Trigger` object contains one embedded `CodeLine` at `+0x98`. Its body is
synchronized directly, so that one location has no empty wrapper. All
pointer-held lines use the wrapper above.

| Operand type | Serialized value | Meaning |
| ---: | --- | --- |
| 0 | none | Deliberate empty argument/placeholder |
| 1 | `u32` | Integer, Boolean selector, enum, count, or scalar bits interpreted as an integer |
| 2 | `f32` | Time, ratio, damage, threshold, or another floating scalar |
| 3 | native `String` | Text, flag/counter name, label, or compiled selector name |
| 4 | two `f32` values | Position/vector |
| 5 | `u32` on disk | UID; relinked to a live object pointer by `0x0064BC40` |

The instruction format is intentionally generic. Bonedit can retain null
slots and vary operand count when a selector changes the rest of a node. A
decoder must therefore preserve the serialized type and value for every
operand instead of imposing one packed C structure per opcode.

For predicates, `flags & 1` means NOT. Nested lines provide the editor's
IF/ENDIF and loop body structure. The runtime dispatcher is `0x00689750`;
interpreter-only control nodes such as `LOOP`, `END LOOP`, `ENDIF`, `LABEL`,
and `GOTO` update `ScriptThread` state rather than calling a world-effect
helper.

## `TriggerControl` serialization

RegionLayout section 1 is one empty `TriggerControl` chunk with exactly three
children:

```text
TriggerControl
├── triggers
│   payload: u32 trigger_count
│   children: Trigger wrappers[trigger_count]
├── scripts
│   payload: u32 script_count
│   children: (script metadata, CodeLineList)[script_count]
│             then one flag/counter state child
└── runtime threads
    payload: polymorphic manager count and type IDs
    children: serialized ScriptThread objects
```

Script metadata is `u32 uid` followed by a native `String` name. The final
state child stores a counted list of `{String name, String value}` flags,
followed by a counted list of `{String name, u32 value}` counters. Editor files
normally have no serialized runtime threads, but the third manager is real and
accepts type 3008.

### `Trigger` layout and chunks

Each trigger wrapper has an 11-byte tail payload and two children. The first
child is the main trigger; the second is its `CodeLineList` of conditions. The
main child has two children: a fixed parameter block and the directly embedded
`CodeLine` body.

| Serialized location | Native field | Encoding and meaning |
| --- | ---: | --- |
| main payload | `+0x04` | `u32` trigger UID |
| main payload | `+0x08` | native `String` name |
| main payload | `+0x2C` | `u32` trigger type |
| main payload | `+0x24` | `u32` condition connective: 0 ALL/AND, nonzero ANY/OR |
| main payload | `+0x68` | `u32` remaining trip limit |
| main payload | `+0x28` | Boolean initially enabled |
| main payload | `+0x65` | Boolean trip-limit enabled |
| main payload | `+0x94` | Boolean killed/deleted |
| parameter child | `+0x44` | `u32` timer/interval/type-specific parameter |
| parameter child | `+0x84` | `u32` primary script UID |
| parameter child | `+0x48..+0x54` | four `f32` region/timing coordinates |
| parameter child | `+0x58` | `float2` point |
| parameter child | `+0x60` | `f32` radius |
| parameter child | `+0x64` | `u8` target/location selector |
| parameter child | `+0x8C` | `u32` secondary/step-off script UID |
| embedded child | `+0x98` | direct `CodeLine` body |
| condition child | `+0x6C` | counted `CodeLine` predicates |
| wrapper tail | `+0x95` | Boolean pressure state active |
| wrapper tail | `+0x30` | Boolean global scope |
| wrapper tail | `+0x34` | `f32` required pressure duration |
| wrapper tail | `+0x38` | `u32` live pressure countdown |
| wrapper tail | `+0x3C` | Boolean player must remain stationary |

The post-load resolver turns primary UID `+0x84` into pointer `+0x88` and
secondary UID `+0x8C` into pointer `+0x90`. `0xFFFFFFFF` is the common no-link
sentinel in editor output.

### Trigger types offered by Bonedit

`TriggerType_Build` at `0x004B4EC0` creates the complete selector. The retail
display has the typo `on END GAE`; the normalized semantic name is shown here.

| ID | Editor trigger | Runtime source |
| ---: | --- | --- |
| 1 | START GAME | Arena/TriggerControl startup |
| 2 | START WAVE | wave-start dispatch |
| 3 | END WAVE | wave-end dispatch |
| 4 | END GAME | game-end dispatch |
| 5 | WIN GAME | win transition |
| 6 | LOSE GAME | loss transition |
| 7 | PLAYER STEPS ON | spatial enter/leave evaluation; secondary script can handle step-off |
| 8 | MANUAL | explicit `TRIP TRIGGER`, `TRY TRIGGER`, or TimeLine event |
| 9 | INTERVAL | per-tick timer/interval evaluation |
| 10 | PLAYER PRESSURE | spatial pressure countdown, optionally requiring stationary player |
| 11 | MONSTER DIES HERE | death event filtered by stored region/point |
| 12 | BOSS HP | boss-health threshold crossing |
| 13 | LEVEL UP | player level-up event |
| 14 | FIND SOLOMON | Solomon-found event |
| 15 | SOLOMON RUNS | Solomon run-away event |

### Predicates offered by Bonedit

The predicate builder at `0x004B5EF0` registers all 14 condition IDs. Numeric
comparisons flow through `0x006819C0`; the object/location condition has its
own evaluator at `0x006895E0`.

| ID | Editor predicate | Input domain |
| ---: | --- | --- |
| 1 | WAVE NUMBER IS | current Arena wave |
| 2 | OBJECT IS AT | linked object and spatial target |
| 3 | PLAYER HAS ITEM | player inventory/recipe identity |
| 4 | FLAG IS | `TriggerControl` named String flag |
| 5 | COUNTER IS | `TriggerControl` named integer counter |
| 6 | GAME DATA IS | compiled game-data selector |
| 7 | PLAYER LEVEL IS | player level |
| 8 | PLAYER ELEMENT IS | selected element |
| 9 | PLAYER DISCIPLINE IS | selected discipline |
| 10 | PLAYER SKILL LEVEL IS | selected skill and level |
| 11 | PLAYER GOLD IS | current gold |
| 12 | PLAYER HEALTH IS | health value/ratio selector |
| 13 | PLAYER MANA IS | mana value/ratio selector |
| 14 | RANDOM ROLL | native random comparison |

`0x0068B5B0` evaluates the condition list. Connective 0 short-circuits as
ALL/AND; any nonzero connective short-circuits as ANY/OR. Each predicate's
flag bit 0 inverts its result.

## Trigger evaluation and `ScriptThread`

The generic trigger evaluator at `0x00681BA0` first rejects disabled or killed
triggers, then handles the manual, interval, spatial, and pressure state that
can be evaluated without a named game event. Event-specific entry points feed
the same trip/try path:

| Address | Role |
| ---: | --- |
| `0x00689570` | unconditionally trip an eligible trigger |
| `0x0068B8E0` | try a trigger after evaluating conditions |
| `0x0068B920` | monster-death-at-location path |
| `0x0068BB10` | linked monster death path |
| `0x0068BBC0` | TriggerControl per-tick/event dispatcher |
| `0x006822E0` | kill/delete trigger by reference |
| `0x00682340` | disable trigger |
| `0x006823A0` | enable trigger |

Scheduling at `0x00686E70` allocates a `0x80`-byte `ScriptThread`, resolves the
primary or secondary script, attaches the originating trigger and spatial
context, and inserts it into the TriggerControl runtime manager at `+0x208`.
If the trip limit is enabled, scheduling decrements `+0x68`; exhaustion marks
the trigger killed so it cannot schedule another thread.

Important `ScriptThread` fields are:

| Offset | Meaning |
| ---: | --- |
| `+0x18` | script UID/index |
| `+0x1C` | next instruction index |
| `+0x48` | resolved script pointer |
| `+0x4C` | trigger UID |
| `+0x50` | resolved trigger pointer |
| `+0x54` | delay counter or negative native wait token |
| `+0x60` | event/object context |
| `+0x64/+0x68` | event point/context coordinates |

`ScriptThread::Tick` at `0x0068B060` resolves missing links, services the delay
or asynchronous wait token, and calls the opcode dispatcher at `0x00689750`.
It executes no more than ten zero-delay lines in one tick. Calls and loops use
separate stacks; their contents are serialized in child chunks by
`0x00684610`, so a saved live thread can resume its call/loop position.

## Complete Bonedit action set

`TriggerEditor_BuildLogic` at `0x004B6750` makes 94 menu registrations for 92
unique action IDs. IDs 1005 (`FORCE SPAWNS`) and 1043 (`CLEAR REFERENCES`) are
each exposed in two editor categories. The table below is the complete stock
placement surface; names are normalized only for the retail `SOLMON` typo in
1084.

### Core, waves, drops, and monster construction

| ID | Bonedit label | Runtime purpose |
| ---: | --- | --- |
| 1001 | ECHO | emit script/debug text |
| 1002 | SLEEP | yield the current `ScriptThread` for a duration |
| 1003 | START NEXT WAVE | advance immediately (`0x00465C00`) |
| 1004 | START NEXT WAVE WHEN | arm a condition/lull-based advance (`0x004625F0`) |
| 1005 | FORCE SPAWNS | force or release native spawn scheduling (`0x00462680`) |
| 1006 | SPAWN CUSTOM MONSTER | instantiate a `MonsterRecipe` UID (`0x00469580`) |
| 1007 | SPAWN CUSTOM MONSTER GROUP | instantiate a `UIDGroup` (`0x0046C710`) |
| 1008 | DROP ITEM | drop a selected item recipe (`0x00469FE0`) |
| 1009 | DISABLE TRIGGER | disable linked trigger |
| 1010 | ENABLE TRIGGER | enable linked trigger |
| 1011 | TRIP TRIGGER | trip linked trigger without its normal event source |
| 1012 | TRY TRIGGER | evaluate then trip linked trigger |
| 1013 | DELETE TRIGGER | kill linked trigger |
| 1015 | DROP RANDOM ITEM | native random item drop |
| 1016 | DROP GOLD | fixed gold drop |
| 1017 | DROP RANDOM GOLD | ranged/random gold drop |
| 1018 | LIMIT DROPS | set the Arena drop limit/policy |
| 1019 | FORTIFY MONSTER RECIPE | mutate selected monster recipe combat values |
| 1020 | SPAWN PARTIAL MONSTER GROUP | instantiate part of a UID group (`0x0046C790`) |

### Player UI, flow control, inventory, and NPC creation

| ID | Bonedit label | Runtime purpose |
| ---: | --- | --- |
| 1023 | AUTO LEVELUP ON/OFF | toggle automatic level-up |
| 1024 | INVENTORY BUTTON ON/OFF | enable/disable inventory UI control |
| 1025 | SPELLBOOK BUTTON ON/OFF | enable/disable spellbook UI control |
| 1026 | BELT BUTTONS ON/OFF | enable/disable belt controls |
| 1027 | PLAYER MOVING ON/OFF | enable/disable player movement |
| 1028 | PLAYER CASTING ON/OFF | enable/disable player casting |
| 1029 | INVOKE INVENTORY | open/invoke inventory UI |
| 1030 | INVOKE SPELLBOOK | open/invoke spellbook UI |
| 1031 | INVOKE SKILL PICKER | open/invoke skill picker |
| 1032 | LOOP | push loop state; nested/body-aware interpreter node |
| 1033 | END LOOP | update/pop loop state |
| 1034 | INCREASE PLAYER SKILL | increment a selected skill |
| 1035 | TELEPORT PLAYER | move player to serialized point/target |
| 1036 | PUT ITEM IN INVENTORY | grant selected item recipe |
| 1037 | TAKE ITEM FROM INVENTORY | remove selected item recipe |
| 1038 | CALL SCRIPT | push return state and enter another script UID |
| 1039 | SPAWN NPC | instantiate an `NPCRecipe` UID |
| 1040 | SLEEP UNTIL | yield on a native condition token |

### NPCs, references, state, and world effects

| ID | Bonedit label | Runtime purpose |
| ---: | --- | --- |
| 1041 | REFERENCE NPCS | build a working NPC reference set |
| 1042 | REMOVE NPCS | remove referenced NPCs |
| 1043 | CLEAR REFERENCES | clear the current working reference set |
| 1044 | NPCS LOOK AT | set referenced NPC facing/target |
| 1045 | MOVE NPCS | move referenced NPCs |
| 1046 | SET NPC IDLE BEHAVIOR | change referenced NPC idle mode |
| 1047 | NPCS NEED HELP | set referenced NPC help behavior |
| 1048 | PLACE SOLOMON DIGGING | place/start Solomon digging (`0x00467230`) |
| 1049 | NPCS FLEE | make referenced NPCs flee |
| 1051 | SYSTEM / DARK CODE | invoke the compiled system-code selector (`0x006824B0`) |
| 1052 | MONSTER FLAIR | apply compiled monster flair behavior |
| 1053 | REFERENCE MONSTERS | build a working monster reference set |
| 1054 | SET FLAG | set named String flag |
| 1055 | SET COUNTER | assign named integer counter |
| 1056 | INCREMENT COUNTER | increment named counter |
| 1057 | DECREMENT COUNTER | decrement named counter |
| 1058 | FORCE SKILL PICK | force the next skill selection |
| 1059 | DROP POTION | create potion drop (`0x00466B50`) |
| 1060 | DO EXPLOSION AT | create explosion at a point/target |
| 1061 | START FIRE AT | create fire at a point/target (`0x00466C60`) |
| 1062 | WIN LEVEL | enter win state |
| 1063 | LOSE LEVEL | enter loss state |
| 1064 | CHANGE WEATHER | select compiled Arena weather |
| 1065 | LOCK/UNLOCK CAMERA | set camera lock/region (`0x00464B20`) |
| 1066 | DESTROY OFF-CAMERA OBJECTS | clean objects outside camera (`0x004728B0`) |

### TimeLines and interpreter control

| ID | Bonedit label | Runtime purpose |
| ---: | --- | --- |
| 1067 | START TIMELINE | start/reset selected TimeLine UID |
| 1068 | STOP TIMELINE | stop selected TimeLine UID |
| 1069 | PAUSE/UNPAUSE TIMELINE | change selected TimeLine pause/running state |
| 1070 | JUMP TO LABEL | resolve and jump to event-label UID |
| 1071 | JUMP TO NEXT EVENT | move the TimeLine cursor/index |
| 1072 | DISABLE SKILL PICK | disable skill selection |
| 1073 | ENABLE SKILL PICK | enable skill selection |
| 1074 | TAKE GOLD FROM INVENTORY | subtract player gold |
| 1075 | REJUVENATE | restore player resources |
| 1076 | ENDIF | close interpreter conditional block |
| 1077 | LABEL | script control-flow label |
| 1078 | GOTO | script control-flow jump |

### Progression, Solomon, cleanup, music, and target mutation

| ID | Bonedit label | Runtime purpose |
| ---: | --- | --- |
| 1079 | LEVEL UP PLAYER | perform player level-up |
| 1080 | XP ACCUMULATION ON/OFF | toggle XP accumulation |
| 1081 | GRANT XP | grant fixed XP |
| 1082 | SPAWN DEFAULT MONSTER | instantiate compiled/default monster descriptor |
| 1083 | SOLOMON DRIVE-BY | start Solomon drive-by sequence |
| 1084 | RUN SOLOMON AWAY | start Solomon run-away sequence; retail label says `SOLMON` |
| 1085 | SLEEP UNTIL SOLOMON IS GONE | asynchronous Solomon-state wait |
| 1086 | DROP KEY | create key drop |
| 1087 | ENABLE/DISABLE DROPS | toggle Arena drops |
| 1088 | REMOVE UNSEEN MONSTERS | remove monsters never seen by camera/player |
| 1089 | REMOVE OFFSCREEN MONSTERS | remove currently off-screen monsters |
| 1090 | MODIFY XP ACCUMULATION | apply XP multiplier/additive policy |
| 1091 | PREVENT LULLS | change lull suppression/timing |
| 1092 | OFFSCREEN MAGIC | invoke compiled off-screen magic effect |
| 1093 | CHANGE NPCS TO TARGETS | move referenced NPCs to hostile/target role |
| 1094 | SET MUSIC | choose prelude, combat, heavy-combat, boss, academy, academy-old, or Solomon Dark theme |
| 1095 | CHANGE NPCS TO ALLIES | move referenced NPCs to ally role |
| 1096 | REDUCE REFERENCED MONSTER HP | reduce health on referenced monsters |

The numeric holes are significant. `1014` is runtime-only: helper
`0x004630C0` accepts an integer and writes Arena `+0x8FE8 = (operand == 0)`.
That Boolean is initialized true, serialized in the Arena header, and consumed
by the automatic wave/lull scheduler at `0x00465D70`. Thus operand 0 enables
stock automatic wave progression and a nonzero operand disables it. There is
no Bonedit registration or stock player-facing label for 1014. IDs 1021, 1022,
and 1050 have neither a stock menu registration nor a recovered dispatch case.

## `TimeLine` graph model

RegionLayout section 13 is a normal polymorphic manager of type-6006 objects.
`TimeLine::Sync` at `0x00646F80` serializes the following state in one payload,
then stores event children followed by live Spawner children.

| Offset | Encoding | Meaning |
| ---: | --- | --- |
| `+0x14` | native `String` | timeline name |
| `+0x30` | `u32` | timeline UID |
| `+0x34` | Boolean | enabled/running state |
| `+0x38` | polymorphic manager | TimeLineEvent list; type 6007 |
| `+0x84` | `f32` | current time cursor |
| `+0x88` | `u32` | index of next sorted event |
| `+0x8C` | `u8` | pause mode |
| `+0x90` | `u32` | pause counter/threshold parameter |
| `+0x94` | `u32` | lull/monster threshold used by combined pause mode |
| `+0x98` | `u8` | default spawn location policy |
| `+0x99` | `u8` | default spawn position/light policy |
| `+0x9C` | polymorphic manager | live Spawner list; type 6008 |

The Arena owns the live TimeLine manager at `+0x9040` (count `+0x9048`, item
storage `+0x9054`). Relink `0x0064BC40` sorts each event list by event X/time
`+0x1C`, then graph Y `+0x20`, and resets each loaded Spawner's owner at
`+0x14`.

### `TimeLineEvent` serialization and kinds

Every event has a 19-byte parent payload and exactly six children.

| Parent field | Encoding | Meaning |
| ---: | --- | --- |
| `+0x14` | `u32` | event UID |
| `+0x18` | `u32` | event kind |
| `+0x1C` | `f32` | graph X; runtime event time/order |
| `+0x20` | `f32` | graph Y; editor lane and sort tie-break |
| `+0x24` | Boolean | one-shot |
| `+0x25` | Boolean | already fired |
| `+0xA0` | `u8` | runtime/editor state flag |

The six children, in order, are counted arrays at `+0x2C` (UIDs), `+0x4C`
(bytes), `+0x5C` (floats), `+0x6C` (integers), `+0x7C` (Strings), and a
`CodeLineList` of records at `+0x88`. Empty arrays are still represented by
their zero count. UID array entries and applicable record operands are
resolved after load.

`0x004B9FB0` is Bonedit's event creator and `0x004BA1E0` builds the selected
event's controls.

| Kind | Bonedit node | Serialized arrays and runtime result |
| ---: | --- | --- |
| 0 | SPAWN EVENT | `int[0]` count, `int[1]` spread enabled, `int[2]` steady (1) or chaotic (0), `float[0]` spread duration; records are 3001/3002/3003 spawn definitions |
| 1 | TRIGGER EVENT | UID array contains triggers; `byte[0]` 0 trips and 1 tries each trigger |
| 2 | PAUSE TIME LINE | `byte[0]` pause mode; integer/float controls populate the timeline pause parameters |
| 3 | ADVANCE WAVE | invokes the native wave-advance path |
| 4 | LABEL | marker/no-op used as a jump target |
| 5 | JUMP TO LABEL | target UID(s) are resolved by `0x00647080`; updates next event/cursor |
| 6 | SPAWN LOCATING | `int[0]` becomes default location and `int[1]` default position/light policy |
| 7 | RUNTIME SPAWN EVENT | runtime-accepted spawn event; extends kind 0 with `int[3]` group-total behavior and is not a normal creation-menu node |

The location controls exposed by Bonedit include `NEAR PLAYER(S)` and
`ANYWHERE`. Position/light choices include `DARK`, `LIGHT`, `OFF SCREEN`, and
`OFF BONEYARD POSITION`. Spawn-node controls use `SPAWN`, `OF THESE`, `SPREAD
SPAWN ACROSS`, and `STEADILY`/`CHAOTICALLY`.

### Spawn records and `Spawner`

The event's record list uses the same `CodeLine` grammar, but its opcode is a
spawn-record type rather than a script action:

| ID | Bonedit record | Reference |
| ---: | --- | --- |
| 3001 | DEFAULT MONSTER | compiled monster/type selectors in typed operands |
| 3002 | CUSTOM MONSTER RECIPE | type-5 `MonsterRecipe` UID plus placement operands |
| 3003 | MONSTER UID GROUP | type-5 `UIDGroup` UID plus placement operands |

`0x004BA5A0` builds these three record editors. Activating a spawn event at
`0x0046C9A0` allocates a `0x44`-byte `Spawner`, associates it with the event,
and inserts it into the TimeLine's runtime manager. Initializer `0x00463440`
computes the interval as `spread_duration / max(remaining - 1, 1)`.

| Spawner offset | Meaning |
| ---: | --- |
| `+0x14` | owning TimeLine |
| `+0x18` | resolved TimeLineEvent pointer |
| `+0x1C` | serialized event UID |
| `+0x20` | remaining spawn count |
| `+0x24` | live countdown |
| `+0x28` | computed interval |
| `+0x2C` | spread duration/countdown source |
| `+0x30` | steady scheduling flag |
| `+0x31` | runtime group-total/counting flag |
| `+0x34/+0x38` | group and member indexes |
| `+0x3C/+0x40` | location and position policies |

`Spawner::Tick` at `0x0046D000` executes records 3001, 3002, and 3003,
decrements the remaining count, and removes the Spawner when complete. A
TimeLine at end-of-events stays alive until its Spawner manager is empty.

### Per-tick TimeLine evaluator

The Arena tick calls `0x0046E390` for every active TimeLine. In running mode it
captures `+0x84`, computes the native frame delta from `DAT_00820230` and the
active timing scale, and examines event `+0x88` in sorted order:

1. If the next event time is in the future, add the delta to the cursor and
   stop for this tick.
2. Skip an event whose fired bit is already set.
3. Otherwise call event activation at `0x0046C9A0`; set fired for a one-shot
   event and advance the next-event index.
4. Continue consuming same-time/due events until an activation requests a
   pause or the list ends.
5. At end-of-list, remove the TimeLine only after its live Spawner count reaches
   zero.

The pause-state switch is:

| Mode | Resume condition |
| ---: | --- |
| 0 | running |
| 1 | decrement `+0x90` until zero |
| 2 | global live-monster count reaches zero |
| 3 | live-monster count falls below `+0x90` |
| 4 | reserved/stalled state; no release path in this switch |
| 5 | boss count and active boss actor are both zero |
| 6 | wave exceeds `+0x90` or monsters fall below `+0x94`, with no active boss |

Kinds 0 and 7 create Spawners; kind 1 trips/tries triggers; kind 2 sets this
pause state; kind 3 advances the wave; kind 4 is a label no-op; kind 5 jumps;
kind 6 changes subsequent spawn-location defaults.

The stock survival generator adds two constraints to this generic object
model. `WaveData_Parse` at `0x00632730` reads the retail `wave.txt` directives
before `0x006388B0` emits the TimeLine graph. The exact verdict for
`MAXENEMIES` is a retained/dead retail directive: it survives parsing but is
never copied into a TimeLine,
Spawner, or Arena population gate. `WAVEDELAY` similarly contributes a seeded
random draw without installing a delay; preserving that draw is required to
preserve the later generated schedule.

Region tick `0x0063EFC0` owns the Arena `+0x88` low-population timer. It
increments while fewer than 11 monsters are live and no boss exists, and mode
6 compares its stored threshold against that timer (or its monster threshold
against the strict live count). This field is not the schedule's wave ordinal.

## Bonedit authoring surface

Bonedit's main bundle builder is `0x004E41C0`. The relevant panels and node
builders are:

| Address | Authoring surface |
| ---: | --- |
| `0x004B4B50` | trigger options: scope, pressure/stationary behavior, trip limit, scripts |
| `0x004B4EC0` | 15 trigger-type entries |
| `0x004B5EF0` | 14 condition/predicate entries, including IF/ENDIF use |
| `0x004B6750` | complete action menus |
| `0x004DB9E0` | create a new Trigger/script pair |
| `0x004B9FB0` | create a TimeLineEvent graph node |
| `0x004BA1E0` | selected TimeLineEvent controls |
| `0x004BA5A0` | spawn-record controls |
| `0x004BFEA0` | TimeLine graph controls, including add-monster/group/custom buttons |
| `0x004E0640` | event widget dispatch for trigger, pause, and wave controls |
| `0x004B44B0` | ItemRecipe setup |
| `0x004B53F0` | NPCRecipe setup |

The editor is a view over the native object graph. Saving does not compile a
second bytecode format: it invokes the same `Sync` methods used by the retail
loader. A trigger menu choice becomes its numeric type, conditions/actions
become `CodeLine` header/body pairs, timeline boxes become type-6007 children,
and each visible spawn row becomes record 3001, 3002, or 3003. Graph position
is persisted in event X/Y and becomes runtime order after relinking.

The stock create/generator path at `0x006388B0` uses these same constructors to
emit the default `on START GAME`, wave, Solomon, recipe-fortification, and
TimeLine objects. That is why an apparently blank editor Boneyard still has a
large executable timeline graph.

## Recipe object model

Recipes are definitions, not live actors/items. Script actions and spawn
records carry their UIDs; `0x0064BC40` converts those identifiers to pointers
only after all RegionLayout sections have been constructed.

### `MonsterRecipe` (type 6001)

`MonsterRecipe::Sync` at `0x0063E890` serializes 42 values in this exact order.
The offsets explain the non-monotonic byte order. Several one-byte fields are
discriminated unions: Bonedit gives them different labels for different enemy
types, so a universal name would be false.

| Order | Offset | Encoding | Meaning |
| ---: | ---: | --- | --- |
| 1 | `+0x4C` | `u32` | compiled enemy type |
| 2 | `+0x14` | `String` | recipe name |
| 3 | `+0x50` | `u32` | recipe UID |
| 4 | `+0x58` | `f32` | maximum health |
| 5 | `+0x5C` | `f32` | primary damage |
| 6 | `+0x6C` | `f32` | chase speed |
| 7 | `+0x74` | `f32` | movement speed scale |
| 8 | `+0x78` | `u32` | variant/body mode |
| 9 | `+0x7C` | `u32` | projectile/weapon mode |
| 10 | `+0xBC` | `u32` | aura/effect mode |
| 11 | `+0x80` | `u8` | headgear/type-specific mode |
| 12 | `+0x81` | `u8` | type-specific union byte |
| 13 | `+0x82` | `u8` | type-specific union byte |
| 14 | `+0x83` | `u8` | random-variant flag/mode |
| 15 | `+0x30` | `String` | archetype/source name |
| 16 | `+0xC1` | Boolean | linked recipe/definition enabled |
| 17 | `+0xC4` | `u32` | linked UID; resolved to pointer `+0xC8` |
| 18 | `+0x84` | `u32` | behavior/count selector |
| 19 | `+0x88` | `u32` | behavior minimum |
| 20 | `+0x8C` | `u32` | behavior maximum |
| 21 | `+0xB8` | Boolean | flanking |
| 22 | `+0xB9` | `u8` | pathfinding mode |
| 23 | `+0xCC` | `u8` | orb-drop policy |
| 24 | `+0xCD` | `u8` | power-up-drop policy |
| 25 | `+0xCE` | `u8` | item-drop policy |
| 26 | `+0xD0` | `u8` | specific-item-drop policy |
| 27 | `+0xCF` | `u8` | gold-drop policy |
| 28 | `+0xD1` | `u8` | potion-drop policy |
| 29 | `+0x54` | `u8` | special spawn/type mode |
| 30 | `+0x70` | `f32` | attack speed |
| 31 | `+0xD4` | `f32` | XP bonus/modifier |
| 32 | `+0x60` | `f32` | secondary damage |
| 33 | `+0x94` | Boolean | shield |
| 34 | `+0x95` | Boolean | shield others |
| 35 | `+0x96` | Boolean | type-specific combat flag |
| 36 | `+0x97` | Boolean | burning |
| 37 | `+0x64` | `f32` | tertiary damage |
| 38 | `+0x68` | `f32` | extra/type-specific damage |
| 39 | `+0x90` | `u32` | behavior timer |
| 40 | `+0x98` | rectangle | first color/range rectangle |
| 41 | `+0xA8` | rectangle | second color/range rectangle |
| 42 | `+0xC0` | `u8` | casting/type mode |

The stock editor reuses the union fields for body, weapon, arrow, element,
cloak, and other enemy-family options. Their bytes and order are exact; their
label must be selected using `enemyType`, not applied to every recipe.

### `UIDGroup` (type 6002)

`0x0064A130` writes a native String name, `u32` group UID, a count followed by
member UIDs, then the four `u32` fields at `+0x58`, `+0x5C`, `+0x60`, and
`+0x34`. Relink replaces each member UID with the corresponding live recipe
pointer while retaining the serialized identity for save. TimeLine record 3003
uses the group UID; `Spawner` maintains group/member indexes across ticks.

### `ItemRecipe` (type 6003)

`ItemRecipe::Sync` at `0x00570D90` writes:

1. UID `+0x14`, reference name `+0x18`, display name `+0x34`, and description
   `+0x50`;
2. the polymorphic FX list at `+0x6C` (count/type IDs in the payload and one
   child per FX);
3. `u32 +0x84`, `u8 +0x88`, rectangles `+0x8C` and `+0x9C`, classification
   `u8 +0x89`, and signed item level `i8 +0x8A`.

The setup panel at `0x004B44B0` exposes reference name, display name,
description, classification, and item level. It clamps item level to
`[-100, 100]`. Native item materialization consumes `+0x84` and `+0x88` as
compiled item/image selectors, but Bonedit does not expose those two fields in
this setup panel; the decoder therefore keeps their neutral offset names.

### `NPCRecipe` (type 6004)

`NPCRecipe::Sync` at `0x0063EBD0` writes the following logical fields in this
order:

| Offset | Meaning |
| ---: | --- |
| `+0x4C` | compiled NPC type |
| `+0x14` | reference name |
| `+0x30` | display name |
| `+0x50` | recipe UID |
| `+0x56` | idle behavior byte |
| `+0x54` | can-talk Boolean |
| `+0x7A/+0x7C` | relationship selector 0 and UID; live pointer `+0x80` |
| `+0x84/+0x88` | relationship selector 1 and UID; live pointer `+0x8C` |
| `+0x90/+0x94` | relationship selector 2 and UID; live pointer `+0x98` |
| `+0x58` | SAY text |
| `+0x55` | DONE AFTER TALKING TO selector |
| `+0x79` | REMOVE selector |
| `+0x78` | REMOVE NPC WHEN DONE Boolean |
| `+0x9C..+0x9F` | four type/variant bytes |
| `+0xA0..+0xAC` | four wizard/type settings |
| `+0xB0..+0xB3` | enable Boolean for each wizard/type setting |
| `+0xB4`, `+0xC4` | two rectangles |
| `+0x74` | talk speed |

The panel at `0x004B53F0` exposes reference/display names, NPC type, idle
behavior, talk speed, SAY text, removal and conversation completion, wizard
magic type/weapon/stance, and CAN TALK. Relink accepts relationship slot 0 only
when selector `+0x7A` and UID `+0x7C` are positive, slot 1 under the equivalent
`+0x84/+0x88` test, and slot 2 when `+0x90` is positive and UID `+0x94`
resolves.

### `ItemSet` (type 6005)

The RegionLayout `ItemSet` manager records type 6005 and an object child, but
the subclass `Sync` slot is the no-op `0x0042E260`. Consequently that child has
no payload or descendants in the Boneyard path. The constructor still creates
the normal in-memory name/member/FX containers; those are populated by the
separate stock definition loader, not serialized as a Boneyard subclass body.

## Worked example: `mpk_boneyard_alpha`

The decoder is deliberately read-only and strict:

```bash
python3 tools/decode_boneyard_scripts.py \
  "mods/mpk_boneyard_alpha/files/Alpha Arena.boneyard"
python3 tools/decode_boneyard_scripts.py \
  "mods/mpk_boneyard_alpha/files/Alpha Arena.boneyard" --json
```

It first validates the complete recursive `SyncBuffer` and Arena/RegionLayout
envelopes through `inspect_boneyard`, then requires the recovered child counts,
type IDs, operand types, and payload boundaries. Any unknown operand type,
wrong child count, unparsed byte, trailing file byte, or mismatched manager
type is an error.

`Alpha Arena.boneyard` is 40,565 bytes with SHA-256
`d596b4915140f5faa23fd1286e3d622c6189ecb00b9667f5e7b3444a84b8322b`.
The decoder consumes it exactly and recovers nine triggers, nine scripts, one
TimeLine, and one MonsterRecipe.

| Trigger UID | Name/type | Condition | Primary script |
| ---: | --- | --- | ---: |
| 43229 | `on START GAME` / 1 | none | 43228 |
| 51933 | `on SOLOMON RUNS 1` / 15 | none | 51934 |
| 43231 | `on START WAVE 1` / 2 | `WAVE NUMBER IS(1, 0)` | 43230 |
| 56483 | `on START WAVE 2` / 2 | `WAVE NUMBER IS(2, 0)` | 56484 |
| 57029 | `on LEVEL UP 1` / 13 | none | 57030 |
| 57098 | `on LEVEL UP 2` / 13 | `PLAYER LEVEL IS(0, 0, 3)` | 57099 |
| 57433 | `Miniboss` / MANUAL | none | 57434 |
| 57567 | `Win Game` / MANUAL | none | 57568 |
| 95529 | `LullWatcher` / MANUAL | none | 95530 |

The linked scripts prove several different instruction shapes:

| Script UID | Decoded action sequence |
| ---: | --- |
| 43228 | `PLACE SOLOMON DIGGING` with typed null and vector operands |
| 51934 | `LOCK/UNLOCK CAMERA`, `SLEEP(3)`, `DESTROY OFF-CAMERA OBJECTS` |
| 43230 | nested loops, default-monster spawns, sleeps, `ENDIF`, and `START NEXT WAVE WHEN` |
| 56484 | `START TIMELINE(uid:56480)`, then `START NEXT WAVE WHEN` |
| 57030 | `MODIFY XP ACCUMULATION(1, 25.0)` |
| 57099 | `MODIFY XP ACCUMULATION(1, 30.0)` |
| 57434 | `SPAWN CUSTOM MONSTER(uid:57310, 0)` |
| 57568 | `WIN LEVEL` |
| 95530 | `PREVENT LULLS(0, 0.5)` |

TimeLine UID 56480 is named `Skeletons`, starts disabled, and has 26 events.
Their decoded kind sequence is:

```text
0, 0, 2, 3, 6, 0, 6, 6, 2, 0, 0, 2, 0,
1, 2, 6, 0, 6, 0, 2, 0, 6, 2, 1, 0, 1
```

Trigger event 13 links to `Miniboss` UID 57433, event 23 links to `Win Game`
UID 57567, and event 25 links to `LullWatcher` UID 95529. The first spawn event
decodes `ints=[8, 0, 0]`, `floats=[5.0]`, and three type-3001 default-monster
records. The sole monster recipe is UID 57310, `Rotten Tom`, enemy type 1001,
35 maximum HP, and 5 primary damage; script 57434 references that same UID.

The complete human-readable and structured dumps are retained as
`alpha-boneyard-scripting-dump.txt` and
`alpha-boneyard-scripting-dump.json` in the campaign evidence directory. The
unit regression also decodes the Beta arena's two `NPCRecipe` objects, while
the static RE suite pins the executable anchors and exact 92-ID authoring map.

## Evidence standard and boundaries

The class, constructor, vtable, serializer, editor-builder, dispatch, relink,
and tick anchors above were recovered with direct read-only Ghidra headless
decompilation, disassembly, scalar-use searches, string xrefs, and vtable
cataloging against the identified executable. File conclusions are checked by
strict decoding of the committed flat fixture and the Alpha/Beta mod arenas.

The scripting byte grammar, complete stock node IDs, object fields used by the
serializers, UID relink, and runtime state machines are closed for this retail
binary. Type-specific MonsterRecipe union labels remain conditional on the
compiled enemy family, and a few editor-hidden ItemRecipe selectors are named
by offset in the decoder; that is a semantic naming boundary, not an unknown
payload boundary. The Arena's unrelated reserved header fields remain covered
by [`boneyard-system.md`](boneyard-system.md).
