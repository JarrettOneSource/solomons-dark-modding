# Stock tutorial mechanics

Investigation date: 2026-08-01
Target: stock 32-bit `SolomonDark.exe` 0.72.5 and
`data/levels/tutorial.boneyard`
Method: static reverse engineering only; no game instance was launched

## Result

**Loot-drop arrow verdict: reusable, but reuse the pointer primitive rather
than the Tutorial controller.** The stock arrow is a client-rendered sprite
that can point from any screen-space origin to any screen-space target. The
cleanest native seam is `Tutorial_DrawPointer` at `0x005C9BB0`, backed by UI
sprite record 28 at `[0x008199E4] + 0x15A8`. It takes two screen points and a
blink flag, computes the angle, and draws the stock gold arrow. A loader can
track a validated world object, project it through the local camera, and invoke
this helper during the local HUD render without enabling the stock tutorial.
The helper is **clean-ish**: it is small and general, but assumes that the
stock UI bundle and render state are live. The complete Tutorial object is a
**dirty seam** because its target selection, stage state, inventory tests,
camera, HUD gates, and dialogue all use solo/global state. [E01:005D08C0]
[E08:005C9BB0] [E09:005C9C3B] [E10]

The arrow is not an actor and has no independent lifetime. At Tutorial stages
8 and 17, the render method looks up the first registered ground `Sack` /
item-drop actor of type `0x7DD`, reads its live world position every frame, and
draws the pointer. It stops when the stage advances. Pickup removes the ground
actor; there is no arrow timeout, and the actor field at `+0x14C` is a pickup
delay rather than a lifetime. The stock lookup is global and identity-blind,
so another `0x7DD` can steal or prolong the pointer. A mod-facing seam should
therefore be per-client and identity-bound, not a wrapper around that lookup.
[E01:005D0F14,005D1EC4] [E03:00646CB0]
[E14:005E6B50]

The tutorial is a hybrid of two systems:

1. first-play/profile code selects a control scheme and loads the Tutorial
   Boneyard;
2. the Boneyard's `START GAME` script executes command 1051 with the string
   `TUTORIAL`, which constructs a compiled `Tutorial` controller;
3. Boneyard triggers and scripts own monsters, drops, waves, fires, Solomon's
   placement, and camera lock;
4. the compiled controller owns the 0-through-19 teaching state machine,
   overlays, dialogue timing, UI/input gates, and calls that advance waves.

This split is important for reuse. The Boneyard command language is a useful
data-driven scenario seam. The Tutorial controller is purpose-built and should
not be instantiated outside this exact scene. [E01:005D5CF0,005D6330]
[E13] [E15] [E16:00689750] [E17:006824B0]

## 2026-08-26 opening-guidance and first-cast boundary clarification

A requested browser usability pass reopens the Tutorial's opening and first
combat lesson. The reusable native facts are already closed by the complete
controller and pointer census above; this clarification records precisely
which requested behavior is retail and which is an explicit web extension.

- Stock stage 0 renders `USE YOUR KEYBOARD / TO MOVE THE WIZARD` and `Find
  and confront Solomon Dark`. It owns no pointer call. Completion remains the
  strict squared-distance test `> 40000` from Tutorial `+0x80/+0x84`; the
  controller has no "first physical movement input" acknowledgement field.
- The stage-0/1 Dig target is nevertheless exact and available: START GAME
  script 10000 places the one Solomon Dig actor, and the shared UI-28 pointer
  primitive `0x005C9BB0` accepts caller-owned screen points. A browser arrow
  aimed at the authoritative Dig position is therefore an exact-asset web
  extension, not a newly discovered stock stage-0 member. Its lifecycle can
  end when the encounter leaves `digging` for `turning`, the first accepted
  Solomon-contact edge.
- Stock stage 2 renders `POINT AND CLICK YOUR MOUSE / TO THROW MAGIC
  MISSILES`. WAVE 1 starts two complete five-Skeleton groups. The controller
  advances to stage 3 when either the primary-cast counter is positive **or**
  global enemy count exceeds five. There is no Tutorial pause/freeze call in
  stage 2 and no mobile-copy branch in `Tutorial::Render 0x005D08C0`.
- Consequently, materializing all ten authored opening Skeletons makes the
  stock enemy-count fallback true on the next controller tick. The heading is
  legitimately a one-tick state under that contract; it is not a renderer
  timeout or CSS race. Holding stage 2 until the first accepted primary cast,
  pausing hostile simulation and player translation while aim/cast/UI clocks
  continue, and using left/right-joystick copy are explicit requested browser
  policy. The player hold is not retail behavior and must clear retained
  velocity as well as current movement input; otherwise the browser's native-
  style velocity recurrence continues translating the wizard.

The complete pointer family, all later stages 3..19, authored wave rows,
narration, HUD gates, save/resume, and teardown remain unchanged. Do not
generalize the requested selective hold into the ordinary Boneyard pause
system: a normal gameplay pause also seals the very primary-cast action that
must release this lesson.

### 2026-08-27 movement-copy completion correction

The browser-only first-movement acknowledgement must consume the same
authoritative movement epoch as the stock PlayerActor kernel, not a raw
nonzero input sample. `PlayerActor::Tick 0x00548B00` enters movement only when
the accumulated lane passes the strict squared `0.01` test at
`0x0054AD54..0x0054AD7B`. The Website may hide its configured desktop/mobile
copy after a user-authenticated input produces that admitted epoch. It may not
hide for input that is sealed by another owner, for a below-threshold lane, or
for the Tutorial's forced intro velocity without user input. The existing
persisted boolean remains a browser projection; its corrected meaning is
"the player completed an admitted movement epoch," not "the host observed a
nonzero input component."

Stock itself retains the stage-0 teaching copy until its independent
distance-from-anchor transition advances the controller. The browser's earlier
hide edge remains an explicit requested accessibility policy and must not
change stage, narration, Dig-pointer, or forced-intro ownership.

## Address and evidence conventions

Addresses are original virtual addresses for the shipped executable with image
base `0x00400000`; they are not ASLR-adjusted process addresses. Names in this
document are recovered semantic names, not claims that retail symbols exist.
`Game+offset` refers to the object rooted by stock global `0x0081C264`, and
`Arena+offset` to the active world/arena rooted by `0x0081C260` or the Game's
arena member as noted.

Evidence citations use the packet index at the end of this document. A suffix
such as `[E01:005D6330]` identifies the function or instruction range inside
that artifact. The prior first-play gate work is cited as `[Q1]`; this pass
accepted and extended it rather than redoing it.

Seam ratings mean:

- **clean**: narrow, data-oriented behavior with limited ambient state;
- **clean-ish**: reusable when called at the correct native phase with explicit
  prerequisites;
- **dirty**: coupled to Tutorial/global UI/gameplay state and better
  reimplemented behind a semantic loader API.

## Priority: loot-drop arrow, end to end

### 1. What causes the two tutorial drops

There are two deterministic drop chains. They are authored in the Tutorial
Boneyard, not hard-coded as a generic Tutorial-controller reward.

| Lesson | Enemy recipe | Death link | Trigger/script | Spawned payload |
| --- | --- | --- | --- | --- |
| Inventory | `Item Skeleton`, UID 10051, HP 2 | link byte `2`, UID 10049 | `Drop Item Trigger` UID 10049 -> script 10050 | embedded recipe UID 3010, stock spelling `Sorceror's Amulet`, live type 7003 / `0x1B5B` |
| Potion | `Potion SKELETON`, UID 10065, HP 4 | link byte `1`, UID 10072 | `Drop Health Potion` UID 10072 -> script 10073 | health potion subtype 0, live type 7001 / `0x1B59` |

The item recipe is serialized in the level as type `AMULET`, name
`Sorceror's Amulet`, description `A dull trinket, carved with a few beneficial
runes`, all-white colors, and one serialized FX child. Its exact ten-byte
payload is `02 00 00 00 00 02 00 00 20 41`. `FX::Sync` at `0x00570A90`
serializes byte kind `+0x14`, 32-bit target `+0x18`, byte operator `+0x1C`,
then float magnitude `+0x20`, so the row decodes as kind 2
`FX_SPELLCLASSDAMAGE`, target 0 Ether, percentage operator 2, magnitude 10.0.
`FX_Apply` at `0x00576AA0` therefore multiplies the Ether-class damage lane by
`1 + 10/100 = 1.1`; `FX_Format` at `0x00575C20` presents the row as
`Ether Damage +10.0%`. The earlier opaque-child wording was incomplete and
must not be used to justify a no-effect web item.
The item command uses location mode 7. The potion command also uses location
mode 7. At runtime `ScriptLocation_Resolve` (`0x00466600`) resolves mode 7 to
the current script thread's trigger position at `[0x0081F618] + 0x64`; for these
death-linked scripts, that is the dying monster's position. [E02]
[E13:10049,10072,10050,10073] [E27:00466600] [E28]

`Monster_OnDeath` at `0x004819D0` decrements the global enemy count, performs
normal death bookkeeping, and passes the recipe's link byte at `+0xC1`, linked
Trigger pointer at `+0xC8`, and death context to `0x0068BB10`. Link byte 1
launches the linked trigger directly. Link byte 2 additionally runs the
trigger's normal eligibility/limit checks through `0x00681BA0` and
`0x0068B5B0`. Eligible links launch their script through `0x006894F0`.
[E25:004819D0] [E26:0068BB10] [E27:006894F0]

The item script command is ID 1008 / `0x3F0`. Dispatcher `0x00689750` calls
`0x00469FE0`, which clones the embedded `ItemRecipe` through `0x004699B0`,
resolves the location, and creates the ground actor. The potion command is ID
1059 / `0x423`; it calls `0x00466B50`, which resolves the location and invokes
the Arena's potion-drop virtual at vtable slot `+0x148` (`0x0046AE20` in the
Tutorial Arena). Both ultimately create type `0x7DD` with the live item stored
at actor `+0x148`. [E14:0046A360,0046AE20] [E15]
[E16:00689750]

The general stock reward path is independent of the tutorial:
`EnemyReward_Select` at `0x0047C070` can call Arena virtuals `+0x140` for an
item (`0x0046A360`), `+0x144` for gold (`0x0046AA90`), or `+0x148` for a
potion (`0x0046AE20`). What is tutorial-specific is the level's linked-death
graph and the Tutorial controller's choice to render an arrow at stages 8 and
17. While a Tutorial controller exists, the potion-drop path forces subtype 0
(health), another reason not to instantiate it as a generic marker service.
[E14:0047C070,0046AE20]

### 2. Spawn gate versus render gate

The mechanism has two distinct gates:

- **Spawn:** no profile/tutorial boolean is consulted by the item-drop actor
  factory. The deterministic tutorial drops happen because the two monster
  recipes are linked to level-authored triggers.
- **Arrow render:** the compiled `Tutorial::Render` switch must be at stage 8
  or 17, and `World_FindFirstByType(..., 0x7DD)` must return a live actor.

Therefore the loot actor and linked-death scripting are reusable outside the
tutorial. The stock automatic arrow is tutorial-stage-only. [E01:005D08C0]
[E14] [E26]

### 3. Target acquisition and tracking

Both world-arrow cases repeat the same inline sequence:

| Stage | Lookup call site | Projection/draw span | Intended target |
| ---: | ---: | ---: | --- |
| 8 | `0x005D0F14` | `0x005D0F3D..0x005D10BB` | amulet ground actor |
| 17 | `0x005D1EC4` | `0x005D1EED..0x005D206F` | health-potion ground actor |

`World_FindFirstByType` at `0x00646CB0` scans the registered actor array at
world owner `+0x324`, bounded by count `+0x318`, and returns the first actor
whose type field at `+0x08` equals `0x7DD`. The result is also written to
Tutorial `+0x88`, but the renderer performs the lookup again and reads actor
position `+0x18/+0x1C` every render. The cache is therefore not a persistent
identity or ownership binding. [E01:005D0F14,005D1EC4]
[E03:00646CB0]

Consequences:

- the pointer follows movement because the target position is live-read;
- it selects the first registered ground Sack, not specifically the scripted
  amulet or potion;
- it is one global selection in the solo Tutorial scene, not per player;
- it has no network participant identity or visibility filter;
- a mod that needs stable behavior must retain its own actor handle/UID and
  validate it before each projection.

### 4. World-to-screen and placement

The stage renderer reads camera/world state through `0x0081C260`, including
scale at camera/region `+0x84`, and uses the stock rectangle and projection
helpers at `0x00403730`, `0x0042D1B0`, `0x00403790`, `0x00410FF0`, and
`0x00416B50`. The recovered constants are 20, 60, and -40. The duplicated
block projects the actor, forms an actor-offset reference at
`(projected_x - 20, projected_y - 60)`, obtains the centers of the active
world/camera and Tutorial-owned UI rectangles through `0x00403730`, adjusts a
rectangle by -40 through
`0x0042D1B0`, and clips the two-endpoint line to the viewport through
`0x00410FF0`; `0x00403790` and `0x00416B50` copy the resulting four-float
line/rectangle records. The clipped endpoints are passed to `0x005C9BB0`.
[E01:005D0F3D..005D10BB,005D1EED..005D206F] [E03:00403730,0042D1B0,
00403790,00410FF0,00416B50] [E12]

This projection block is duplicated rather than exposed as a Tutorial helper.
For a loader seam, use the loader's validated local camera/world-to-screen
path and viewport clamp. Only the final pointer draw needs to call the stock
Tutorial helper.

### 5. Pointer geometry, sprite, and draw path

`Tutorial_DrawPointer` at `0x005C9BB0` has the effective signature:

```text
DrawPointer(float start_x, float start_y,
            float target_x, float target_y,
            bool blink)
```

The function uses five stack arguments and callee cleanup (`RET 0x14`). It
computes `atan2(target_y-start_y, target_x-start_x)`, converts radians to
degrees with `180/pi`, normalizes negative angles by adding 360, and calls the
rotated sprite draw at `0x00414F90`. When `blink` is true, it draws only while
`global_tick 0x0081F658 % 50 > 19`: 30 visible ticks followed by 20 hidden
ticks. When `blink` is false it draws every call. [E08:005C9BB0] [E09]

The instruction sequence at `0x005C9C3B..0x005C9C5D` loads the UI bundle from
`0x008199E4`, adds `0x15A8`, and calls `0x00414F90`. This is UI bundle record
28: crop `(202,656,58,61)` in `images/UI.png`, a gold upward arrow. The sprite
bundle record is not an arrow actor or a line primitive. `0x00414F90` builds a
rotation/translation transform through `0x00403120`, then calls
`Sprite_DrawTransformed` at `0x00414540`; that binds the texture through
`0x00420030` and submits the textured quad through the common sprite renderer.
[E08:00403120,00414540,00414F90] [E09:005C9C3B]
[E10]

Asset identities used to validate the record are:

| Asset | SHA-256 |
| --- | --- |
| `images/UI.bundle` | `1db00ea8826e787ca9a320c90a33e726991cae00906baddfdc8bde31da697498` |
| `images/UI.png` | `37d5e8fc543af12a9d8019e738dbe1e29b648211144a3782c3a32e71f76cd2eb` |
| extracted record 28 crop | `c513161e3c67c417b47c9ba1f8b466e8822dd05a4ff44593a19eaa923d5ccc98` |

### 6. Despawn and failure behavior

There is no arrow object to destroy and no arrow timeout.

- Stage 8 advances to 9 when the top-level inventory scan finds any item whose
  live type is not potion `0x1B59`. This normally follows amulet pickup.
- Stage 17 advances to 18 when the first-type-`0x7DD` lookup returns null.
- The ground actor tick at `0x005E6B50` decrements actor `+0x14C`; only after
  that pickup delay expires does proximity pickup proceed. Pickup unregisters
  the actor through `0x0063E870`, inserts the held item into inventory through
  `0x0055FF20`, and clears actor `+0x148` before destruction.

No lifetime countdown or timeout-driven removal was recovered in this path.
An unrelated `0x7DD` can keep stage 17 alive after the potion is collected, and
can redirect stage 8. Stage 8's completion test is also broader than the
intended item: any non-potion in the scanned inventory satisfies it.
[E01:005D6330] [E14:005E6B50]

### 7. Recommended loader exposure

Suggested semantic API shape (design recommendation only; this task makes no
product-code change):

```lua
handle = sd.ui.point_at_world_object(target, {
  source = "hud",       -- or explicit screen point / UI anchor
  blink = true,
  clamp_to_viewport = true,
  scope = "local",
  clear_when = "removed" -- optional timeout or caller-controlled policy
})
handle:clear()
```

Implementation requirements:

1. own one marker record per local client/participant;
2. bind the marker to a validated actor identity, not type `0x7DD`;
3. read the target's presentation position on the render thread;
4. project through that client's active camera and clamp to its viewport;
5. after stock HUD state is established and while `0x008199E4` is resident,
   call `0x005C9BB0` or draw UI record 28 through the loader sprite API;
6. clear explicitly on target removal, scene generation change, timeout, or
   caller request;
7. never toggle `Game+0x1CD4/+0x1CD5`, never allocate the Tutorial controller,
   and never reuse its first-`0x7DD` scan.

Rating: target tracking/projection as a new semantic loader surface is
**clean**; direct `0x005C9BB0` use is **clean-ish**; instantiating or driving
`Tutorial` is **dirty**. Stock behavior is global/solo. The recommended surface
is per-client and can independently point each participant at a different
object.

## First-play invocation and control picker

The prior gate investigation established the persisted entry condition. The
global dark-profile object is rooted at `0x0081A330`; byte `+0x104`, absolute
VA `0x0081A434`, is serialized in the encoded binary `darkdata.cfg`. Missing or
unreadable profile data defaults it to 1 in `0x005A8390` at `0x005A849E`.
After profile load, boot function `0x005BF6A0` tests it at `0x005C38D3`:
nonzero enters `0x005B6C90`; zero enters normal frontend `0x005A7D90`.
[Q1]

`FirstPlay_BeginPrelude` at `0x005B6C90` clears the current UI, applies the
transition string `prelude`, and allocates the `ControlPicker`. Its class
anchors are:

| Role | Address |
| --- | ---: |
| vtable | `0x00799C9C` |
| constructor | `0x005A84C0` |
| layout | `0x005A8620` |
| choice callback | `0x005A8790` |
| tick/transition | `0x005B9990` |
| render | `0x005B9A30` |

The render heading is `SELECT A CONTROL SCHEME`. The three choices are visual
controls-bundle panels rather than text labels. Their callback behavior pins
their meaning:

| Choice object | Result | Exact assignments |
| --- | --- | --- |
| picker `+0x84` | arrow-key keyboard scheme | movement keys 200/208/203/205 and related action globals; picker mode 1 |
| picker `+0x138` | WASD keyboard scheme | movement keys 17/31/30/32 and related action globals; picker mode 2 |
| picker `+0x1EC` | mouse scheme | `0x00B3BCB0 = 1`; picker mode 4 |

The complete two visible keyboard presets share Escape menu, `I` inventory,
`T` skills, and right-mouse belt 1. WASD mode maps belts 2..8 to `1`..`7`;
Arrow mode maps them to Delete, End, Backspace, Page Up, Page Down, Insert,
and Home. These assignments are part of the picker transaction, not retained
preferences outside the selected preset. The full scan-code table is pinned in
`docs/reverse-engineering/native-input-model.md`.

All three choices trigger the same fade/selection transition. When the fade
reaches 1.0, tick `0x005B9990` calls `TutorialGame_Bootstrap` at `0x005B6B00`
and destroys the picker. [E01:005A8790,005B9990,005B9A30]

`0x005B6B00` clears the frontend, allocates a Game through `0x005CC800`, stores
it at application `+0xDA8`, loads
`data\\levels\\Tutorial.boneyard` (string VA `0x0079A154`), sets the tutorial
scene activation bytes, and starts the Game. It does **not** directly construct
the Tutorial controller. The level's `START GAME` script contains command 1051
with `TUTORIAL`; dispatcher `0x00689750` routes it to `0x006824B0`, whose
case-insensitive `tutorial` branch calls `0x005D5CF0`. This data-to-compiled
bridge is the exact controller creation point. [Q1] [E13:10000]
[E15:1051] [E16:00689750] [E17:006824B0]

Reuse verdict: the picker is a **dirty** first-run frontend object with direct
global binding writes. A mod should use its own settings UI and store a
semantic control-mode choice. The useful reusable mechanism is the pattern of
a one-shot prelude followed by a level bootstrap, not direct picker reuse.

## Tutorial controller

### Object and lifecycle

`Tutorial_CreateAndInstall` at `0x005D5CF0` allocates `0xB0` bytes, installs
vtable `0x0079AFC4`, stores the object at `Game+0x1CD0`, sets tutorial-scene
byte `Game+0x1CD4 = 1`, attaches it to the UI object tree, and prepares the
player loadout. Confirmed virtuals are:

| Slot/role | Address |
| --- | ---: |
| deleting destructor / remove | `0x005C96F0` |
| activate/reset | `0x005D5FE0` |
| render | `0x005D08C0` |
| tick/stage machine | `0x005D6330` |

Important Tutorial fields are:

| Offset | Meaning |
| ---: | --- |
| `+0x78` | owner/UI context captured at construction |
| `+0x7C` | teaching stage, 0..19 |
| `+0x80/+0x84` | stage-0 movement anchor |
| `+0x88` | last first-`0x7DD` result; refreshed, not stable identity |
| `+0x8C` | intro fade/alpha lane |
| `+0x90` | tutorial overlay opacity lane |
| `+0x94` | pre-stage intro active byte |
| `+0x98` | intro countdown, initialized to 25 |
| `+0x9C` | forced-movement decay timer, set to 250 during intro |
| `+0xA0` | per-stage one-shot dialogue flag |
| `+0xA4` | dialogue delay (50 initially), later stage-11 counter |
| `+0xAC` | selected-HUD lesson acknowledgement byte; initialized to zero, set to one by the primary or concentration-A HUD click before its compact selector opens, and read only by stage-14 presentation |

[E01:005D5CF0,005D5FE0,005D6330]

Construction removes entry index 1 from a progression-owned list, gives and
selects skill ID `0x48` (Acid Rain) through `0x00660320(..., 0x48, 1)`, writes
current secondary selection at progression `+0x870`, refreshes it through
`0x0065F9A0`, clears two quick slots, and normalizes starting equipment/HUD
slot state. Activation hides inventory, skill, belt, spell, and combat HUD
surfaces; clears their access gates; computes the movement anchor from the
player's starting position; and enables early protection at `Game+0x1CD5`.
It then recursively finds the first Health Potion and Mana Potion in the
inventory root through `0x005529A0` and `0x00552B70`, removes both live item
objects through the ordinary inventory removal path `0x00568170`, and refreshes
the belt through `0x005D50E0`. The normal Game initializer has already created
one of each starter potion, so the stock Tutorial begins its lessons with
neither starter potion. The health potion dropped by wave 5 is consequently
the only health-potion quantity present at stage 18 in the natural route.
[E01:005D5CF0,005D5FE0,005D6297-005D62EB]

Activation also installs stock narration/presentation context. It sets the
speaker string to `Sirmin`, releases any prior Game-owned narration/portrait
record, and copies the stock tuple rooted at `0x00B3BD08`, `0x00B3BD10`, and
`0x00B3BD14` into `Game+0x1C94/+0x1C9C/+0x1CA0`. It then sets
`0x0081F694 |= 2`, writes `0x00820253 = 1`, and refreshes the global UI object
at `0x0081F630` through virtual `+0xAC`. These are ambient global presentation
side effects and are a **dirty** reuse seam. [E01:005D5FE0]

The 25-tick intro countdown triggers a stock fade/effect at count 20, initializes
a 250-tick forced-movement lane, and fades the Tutorial overlay in/out. Once
blend exceeds `0.8`, the controller writes the player actor movement accumulator
`+0x158/+0x15C` to `(0,-actor+0x70)`. After intro teardown, the 250-tick lane
writes `(0,-actor+0x70*(remaining/250))` while decrementing. `PlayerActorTick
0x00548B00` then clamps that accumulator through the normal wizard speed
envelope, calls `PlayerActor_MoveStep 0x00525800`, and damps it. This is the
stock automatic northward walk into the opening scene, not camera or zoom
presentation. Only after the intro byte clears does stage 0 run. Its renderer
uses stock full-screen fade/panel drawing, including UI bundle record
`[0x008199E4] + 0x2124` through the common glyph/sprite path.
[E01:005D6330,005D08C0] [E09:005D0A59,005D0B7E] [E12]

### Complete stage progression

The table below follows the actual transition order. Stages 14 and 15 execute
out of numeric order: closing the skill screen moves 13 -> 15, stage 15 waits
for the new wave to materialize, then moves 15 -> 14. Stages without a render
case are intentionally blank presentation phases, not missing analysis.
[E01:005D6330,005D08C0]

| Stage | Rendered instruction / marker | Completion test and side effects | Boneyard coupling |
| ---: | --- | --- | --- |
| 0 | `USE YOUR KEYBOARD` / `TO MOVE THE WIZARD`; `Find and confront Solomon Dark` | Compares player position with anchor `+0x80/+0x84` through `0x00403B90`; squared distance over 40,000 -> 1. After the initial 50-tick delay, queues `SAY_SOLOMONDARKSHOWYOURSELF` once. | START GAME has placed Solomon and configured the initial wave; the player-step trigger can lock the camera. |
| 1 | none | Waits for Arena combat-active byte `Arena+0x8F14`, then -> 2 and rearms the dialogue one-shot. | Arena emits `START WAVE 1`. |
| 2 | `POINT AND CLICK YOUR MOUSE` / `TO THROW MAGIC MISSILES`; `Defeat all evil emanations` | When global enemy count `0x0081984C > 0`, queues `SAY_IAMSIRMIN` and `SAY_NEVERHEARDOFYOU`. When `Game+0x1C34 > 0` or enemy count > 5, -> 3. | Wave 1 spawns two repetitions of the five-starter-skeleton group. |
| 3 | none | Enemy count reaches zero: queues `SAY_EASILYVANQUISHED`, -> 4. | Wave 1 clear. |
| 4 | none | Waits for narration controller `0x00462090` to report idle, then -> 5. Shows inventory/skill/belt widgets and enables the spell and quick-use presentation/input gates `+0x1AC3/+0x1AC2`. | none |
| 5 | `A SECONDARY SPELL IS READY`; dynamic key label and `Click here or press '%s' to cast 'ACID RAIN'`; pointer to the spell control | Polls skill `0x48` state at `+0x64`; once positive, queues `SAY_ICAMEPREPARED`, `SAY_ACIDRAINHUH`, `SAY_SURRENDER`, calls `0x00465C00`, -> 6. | Starts wave 2. |
| 6 | none | Enemy count zero -> 7. | Wave 2's item skeletons have been defeated and its death-linked amulet script has run. |
| 7 | none | On zero, queues `SAY_CARELESSFOOL`, -> 8. Immediately scans inventory; if any top-level item type is not potion `0x1B59`, enables inventory UI/access at `+0x1AC0` and skips to 9. | The amulet may already have been picked up before the controller observes the clear. |
| 8 | world-object arrow | Each tick scans inventory for any non-potion. On success enables inventory and -> 9. Render looks up the first `0x7DD` and points at it. | Intended target is `Sorceror's Amulet`. |
| 9 | `ACCESS YOUR INVENTORY`; dynamic open key; pointer to inventory control | Waits for inventory screen pointer `Game+0x15A0`; reparents/attaches the Tutorial overlay through `0x00428160` and the UI owner's virtual `+0xA8`, then -> 10. | none |
| 10 | Inventory-screen callouts: resume key, quick-use slots, equipped-item area, backpack drag/double-click help, and arrows to each | Waits for inventory screen close/resume byte `screen+0x14C`; queues `SAY_UNREDEEMABLE`, `SAY_SOUNDLIKEMYMOTHER`, `SAY_ACCEPTYOURFATE`; starts next wave; zeroes counter; -> 11. | Starts wave 3. |
| 11 | Conditional `WALK INTO ENEMIES TO CLUB THEM`; `This requires an equipped staff` | Increments counter. After 100 ticks, if enemies are gone and progression level `+0x30 < 2`, grants 10 XP per tick through `0x00680AB0(...,10,1)` until level-up. Once player action/cooldown `+0x168 == 0`, level > 1, and progression `+0x83C == 0`, enables skills at `+0x1AC1`, queues `SAY_MAKEMESTRONGER` and `SAY_LEVELLINGUP`, -> 12. | Wave 3 supplies the normal XP; controller guarantees progress if it was insufficient. |
| 12 | `ACCESS YOUR SKILLS`; dynamic open key; pointer to skills control | Waits for skills screen pointer `Game+0x1664`; reparents/attaches overlay; -> 13. | none |
| 13 | Skill-screen callouts: resume, quick-use, automatic concentration/new-skill explanation, and hover-for-information; arrows to each. The preceding category-3 choice is auto-filled into A by `ActorProgressionRefresh 0x0065F9A0`. | Waits for skills screen close/resume byte `screen+0x98`; starts next wave, enables combat/status HUD at `+0x1AC4`, disables early protection `+0x1CD5`, and -> 15. | Starts wave 4. |
| 15 | none | Waits for enemy count > 2, then rearms dialogue and -> 14. | Ensures wave 4 has materialized before the teaching overlay resumes. |
| 14 | While selected-HUD acknowledgement `+0xAC` remains zero, one live-rectangle pointer plus two unframed lines teach the primary and concentration-A controls: `click these icons to change your` / `primary attack or concentration`. Either eligible control click suppresses that presentation for the remainder of this Tutorial object. | If armed, enemies < 4, and player HP < max HP, queues `SAY_LOOKINGBEATUP` once. Enemy count zero starts next wave and -> 16; the HUD click does **not** advance the stage. | Clears wave 4; starts wave 5. |
| 16 | none | Polls first actor type `0x7DD`, stores it at `+0x88`; when present -> 17. | Wave 5 is the single Potion Skeleton; its death link drops a health potion. |
| 17 | world-object arrow | Repeats first-`0x7DD` lookup. When no such actor remains -> 18. | Intended transition is potion pickup/removal. |
| 18 | `DRINK POTION`; dynamic potion key; arrows to potion belt slot and HP display | Recursively sums health-potion subtype 0 quantities through `0x00552A80`; when zero, starts next wave, queues `SAY_FACETHEWRATH` and `SAY_IMBORED`, -> 19. | Activation removed the ordinary starter potions, so the natural wave-5 drop is the only health potion and one drink starts wave 6. |
| 19 | `SURVIVE` | Once enemy count > 5, calls the Tutorial object's remove/destructor virtual at `+0x18`. This ends the teaching overlay, not the Game or persisted first-play flag. | Wave 6 enables three survival interval triggers; their ongoing scripts populate the arena. |

The route is therefore:

```text
intro -> 0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10
      -> 11 -> 12 -> 13 -> 15 -> 14 -> 16 -> 17 -> 18 -> 19 -> overlay removed
```

### Prompt, callout, and narration systems

The tutorial has **two separate presentation mechanisms**.

#### Hard-coded teaching overlays

`Tutorial::Render` at `0x005D08C0` switches directly on stage and constructs
English strings at each call site. It is not a generic prompt queue. Dynamic
key labels are obtained from the configured control globals through
`0x004299B0` and `0x00402BF0`. The render cases use these helpers:

| Helper | Address | Behavior | Reuse quality |
| --- | ---: | --- | --- |
| primary teaching heading | `0x005C9710` | draws current string with font at `0x008199A0 + 0x1351CC` | clean-ish inside HUD render |
| secondary/subheading | `0x005C9960` | draws current string with font at `0x008199A0 + 0xE7D98` | clean-ish inside HUD render |
| bordered screen callout | `0x005C9C70` | measures through `0x004F5460`, draws background through `0x00417760`, then text | clean-ish, global render state |
| callout wrapper | `0x005CA560` | wrapper around bordered callout placement | dirty without its expected coordinate context |
| subheading wrapper | `0x005CA480` | wrapper around subheading placement | dirty without its expected coordinate context |
| directional pointer | `0x005C9BB0` | rotated stock arrow between two points | clean-ish; recommended low-level seam |

[E03:005C9710,005C9960,005C9C70,005CA560,005CA480]
[E08:005C9BB0]

For completeness, these are every unique teaching literal constructed by
`Tutorial::Render`; `\n` marks an embedded line break and `%s` is the dynamic
configured-key label. The resume literal is used on both modal screens.

```text
USE YOUR KEYBOARD\nTO MOVE THE WIZARD
Find and confront Solomon Dark
POINT AND CLICK YOUR MOUSE\nTO THROW MAGIC MISSILES
Defeat all evil emanations
A SECONDARY SPELL IS READY
Click here or press '%s' to cast 'ACID RAIN'
ACCESS YOUR INVENTORY
Click here or press '%s' to open the inventory screen
Click here or press '%s'\nagain to resume playing
Put items here\nfor quick use
Put equippable items\nhere to wear them.
Found items go in your backpack.  Click and\ndrag to move items, double-click to use them.
WALK INTO ENEMIES TO CLUB THEM
This requires an equipped staff
ACCESS YOUR SKILLS
Click here or press '%s' to open the skill screen
Drag skills here\nfor quick use
You are CONCENTRATING on\nyour new skill automatically
This confers a bonus, but is\nlimited to one skill at a time.
Hover your mouse over a\nskill icon for more information.
click these icons to change your
primary attack or concentration
DRINK POTION
Click here or press '%s' to drink\nthis potion and restore your health.
SURVIVE
```

[E01:005D08C0] [E09]

#### Stage-14 selected-HUD acknowledgement and exact layout correction

The earlier pass incorrectly described Tutorial `+0xAC` as having no recovered
writer. That pass stopped at the Tutorial constructor/tick/render xrefs and did
not follow the two Game-owned HUD controls back through their shared action
handler. A fresh read-only replica pass against the same retail image closes
the omitted input edge:

- `Game::HandleControlAction 0x005D8120` compares the activated control with
  primary control `Game+0x3AC`. When a Tutorial exists at `Game+0x1CD0`, the
  instruction at `0x005D8281` stores byte `1` to `Tutorial+0xAC` **before**
  the Plane Orb guard, compact-selector allocation, or selection result.
- The same handler compares concentration-A control `Game+0x46C`; instruction
  `0x005D8358` performs the identical store before constructing `Select
  Concentration`.
- Concentration-B control `Game+0x52C` is a real sibling compact selector, but
  its branch has no Tutorial write. The stock Tutorial does not grant Split
  Mind, and the stage-14 lesson names the primary/A pair only.
- The stage-13 “CONCENTRATING ... automatically” statement is enforced by
  `ActorProgressionRefresh 0x0065F9A0`, not by the Tutorial controller. After
  the forced level-up grants exactly one of rows 65, 67, or 60, refresh sees an
  empty A/index 16, enumerates learned category-3 rows excluding B, and picks a
  uniform candidate with the active gameplay RNG. In this Tutorial there is
  exactly one candidate, so A becomes the newly learned row without a draw-
  dependent visible outcome. The valid stage-14 selected HUD is therefore the
  primary-plus-A layout, not a primary-only fallback.
- Opening and then cancelling either covered selector still acknowledges the
  lesson. Choosing a different skill is not the predicate. The byte remains
  set for the lifetime of the Tutorial object and is reset only by activation
  `0x005D5FE0` at `0x005D6016`; no stage transition clears it.
- `Tutorial::Render 0x005D08C0` reads the byte at `0x005D1D29`. A nonzero
  value suppresses the complete stage-14 pointer and both text lines. It does
  not alter stage `+0x7C`; wave-4 enemy count zero remains the only 14 -> 16
  transition.

The same render case resolves live rectangles rather than fixed screen
coordinates. `Game+0x3C0` is the rectangle inside primary control `+0x3AC`,
and `Game+0x480` is the rectangle inside concentration-A control `+0x46C`.
Let their centers be `P=(Px,Py)` and `A=(Ax,Ay)`. The exact authored layout is:

```text
pointer origin = ((Px + Ax) * 0.5, (Py + Ay) * 0.5)
pointer target = (Px + 30, Py + 50)
line 1 center/baseline = (Px - 220, Py + 50)
line 2 center/baseline = (Px - 220, Py + 70)
```

The constants are instruction-read doubles `0.5` at `0x007DE808`, `30` at
`0x00784D50`, `50` at `0x007847C8`, `220` at `0x0079B860`, and `70` at
`0x00787C40`. With the ordinary Tutorial primary-plus-A cluster recovered in
`native-skill-screen-and-quickbar.md`, `P=(780,25.5)` and `A=(820,25.5)`, so
the pointer origin is `(800,25.5)`, its target is `(810,75.5)`, and the two
text centers/baselines are `(560,75.5)` and `(560,95.5)`. HUD-hide movement changes both
live rectangles together; a fixed `(800,25)` or viewport-centered text block
is not the stock contract.

Evidence: retail `SolomonDark.exe` 0.72.5, preferred image base `0x00400000`,
SHA-256 `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`;
fresh replica `decompile_targets.py` for `0x005D8120`, `0x005D08C0`, and
`0x005D50E0`; `find_writes_to_offset.py 0xAC`; and
`dump_floats_at.py` for the five constants above. Confidence is high: the
writers, reader, reset, geometry producers, constants, selector siblings, and
stage transition are all instruction-derived.

The residual sweep through `ActorProgressionRefresh` also closes its selected-
primary sibling: after A and optional B, `0x0065FD43..0x0065FE75` preserves
temporary Plane Orb ID 80, otherwise replaces an invalid primary with one
uniformly selected learned category-1 row. The Tutorial's Magic Missile row 8
is already valid, so this sibling does not change its stage-14 pixels, but it
shares the same refresh/RNG owner and is recorded in
`native-progression-and-skills.md` rather than silently omitted.

The stock screen arrows to spell, inventory, quick-use, equipment, backpack,
skills, concentration, potion, and HP controls all use the same
`0x005C9BB0` pointer primitive as the world-object arrow. UI targets are
resolved from Game-owned widget rectangles, while world targets go through the
camera projection block. There is no separate objective-marker manager or
waypoint actor in the Tutorial path. The reusable marker is the pointer
primitive plus caller-owned target resolution.

The stage-10 equipment target resolves widget coordinates through
`0x00570F80`. Its conditional backpack target requires the live inventory
screen at `Game+0x15A0` and a non-null `screen+0x294` member, treats
`screen+0x188` as an indexed UI-entry list, and retrieves entry zero through
`0x005D07A0 -> 0x00558E40 -> 0x004F9320`. The base helper bounds-checks the
index against list count `+0x08`, loads the ref-counted entry from array
`+0x14`, and retains it. If the entry and its nested node are live,
`0x004282D0` accumulates each parent node's `+0x14/+0x18` offset along the
`+0x70` parent chain before the callout and pointer are drawn.

These are generic UI collection/coordinate mechanisms, not a waypoint
service. Raw direct reuse is **dirty**: the backpack target means "first
rendered backpack entry in this stock modal," not a stable inventory-item
identity. A loader should resolve a semantic inventory handle to a local UI
anchor owned by the active overlay. [E01:005D1540..005D16E6] [E30] [E31]
[E32] [E35:004282D0,00570F80]

Recommended exposure is a semantic loader overlay layer—heading, body/callout,
UI-anchor pointer, and world-object pointer—rather than direct access to the
hard-coded Tutorial stage renderer. It should own strings, layout, lifetime,
viewport, and local participant scope. Directly calling the small draw helpers
is **clean-ish**; invoking `0x005D08C0` is **dirty**.

#### Narration queue

Dialogue keys are queued separately through `Narration_Queue` at `0x004FCEC0`
on global narration owner `0x008199F8`. Each call supplies a localization key,
speaker/side boolean, and scalar 0.5. The stock queue reads
`data/dialogue/narration.txt`, manages the current and pending records, and
tracks playback/display duration. `0x00462090` reports whether the narration
controller is idle; stage 4 waits on it before revealing the next lesson.
[E01:005D6330] [E03:00462090] [E14:004FCEC0]

All keys enqueued by the controller, in order of possible execution, are:

```text
SAY_SOLOMONDARKSHOWYOURSELF
SAY_IAMSIRMIN
SAY_NEVERHEARDOFYOU
SAY_EASILYVANQUISHED
SAY_ICAMEPREPARED
SAY_ACIDRAINHUH
SAY_SURRENDER
SAY_CARELESSFOOL
SAY_UNREDEEMABLE
SAY_SOUNDLIKEMYMOTHER
SAY_ACCEPTYOURFATE
SAY_MAKEMESTRONGER
SAY_LEVELLINGUP
SAY_LOOKINGBEATUP
SAY_FACETHEWRATH
SAY_IMBORED
```

This queue is reusable only for already-authored narration resources and is
global, so direct use is **dirty** for arbitrary mod tutorials. A loader should
expose a local semantic prompt/dialogue queue with explicit text/audio assets,
priority, cancellation, and scene-generation ownership. Stock narration keys
could be an optional compatibility backend.

#### Residual helper boundary

An exhaustive symbol/decompile sweep of the adjacent `0x005C9600..0x005CA800`
range found no hidden Tutorial prompt queue, objective manager, marker actor,
or second arrow implementation. The other recovered functions are ordinary
Game/UI neighbors: `0x005C9F40` formats enemy names/presentation,
`0x005CA380` destroys a health-bar array, `0x005CA3A0` constructs a belt
button, `0x005CA460` is a deleting destructor, `0x005CA730` clears a string
array, and `0x005CA7C0` manages floating/gold messages. The only additional
lesson-relevant neighbor is the generic skills-modal opener at `0x005CA640`,
described with input gating below. [E33] [E34]

## Tutorial Boneyard scenario

### Static level inventory

The stock level is named `Tutorial`, has bounds `2043 x 2053`, player spawn
`(1025, 2070.0703125)`, seven `MonsterRecipe` objects, six `UIDGroup` objects,
one embedded `ItemRecipe`, and no `TimeLine`. It contains 13 triggers and 12
named scripts (one script is shared by two triggers). [E02] [E13]

The remaining serialized layout contains 92 world objects (26 trees, one
monument, 64 gravestones, and one building), 53 roads, 28 fences, 90
dead-hawg sprite placements, and four terrain records. Item-set and NPC-recipe
managers are empty. These are scenery/layout content rather than additional
tutorial control mechanisms. [E29]

Monster recipes:

| UID | Name | Kind | HP | Special tutorial property |
| ---: | --- | --- | ---: | --- |
| 10004 | `Starter SKELETON` | skeleton | 2 | baseline lesson enemy |
| 10051 | `Item Skeleton` | skeleton | 2 | death link byte 2 -> trigger 10049 |
| 10059 | `SKELETAL ARCHER` | archer | 3 | wave-4 ranged enemy |
| 10065 | `Potion SKELETON` | skeleton | 4 | death link byte 1 -> trigger 10072 |
| 10076 | `SKELETON` | skeleton | 3 | survival recipe; item/orb/gold chances disabled, potion field 4 |
| 10077 | `SKELETAL ARCHER` | archer | 4 | survival recipe; potion field 1, powerup field 4 |
| 10085 | `DEADLY SKELETAL ARCHER` | archer | 4 | late survival recipe; no potion drop |

UID groups:

| UID | Name | Ordered members |
| ---: | --- | --- |
| 10010 | `FIVE SKELETAL WARRIORS` | 5 x 10004 |
| 10052 | `FIVE ITEM SKELETONS` | 5 x 10051 |
| 10060 | `Archer + Melee Group` | 2 x 10059, 3 x 10004 |
| 10061 | `Three Archers` | 3 x 10059 |
| 10078 | `Survive Group` | 10076, 10077, 10076 |
| 10086 | `deadly survive group` | 10085, 10076 |

[E02]

### Trigger graph

| Trigger UID | Stock name/type | Script UID | How it is reached |
| ---: | --- | ---: | --- |
| 10001 | `on START GAME`, type 1 | 10000 | level activation |
| 10003 | `on START WAVE 1`, type 2 | 10002 | Arena wave event |
| 10047 | `on START WAVE 2`, type 2 | 10048 | controller calls start-next-wave at stage 5 |
| 10049 | `Drop Item Trigger`, Manual type 8 | 10050 | Item Skeleton death link; script deletes this trigger after use |
| 10054 | `on START WAVE 3`, type 2 | 10055 | controller stage 10 |
| 10057 | `on START WAVE 4`, type 2 | 10058 | controller stage 13 |
| 10063 | `on START WAVE 5`, type 2 | 10064 | controller stage 14 |
| 10072 | `Drop Health Potion`, Manual type 8 | 10073 | Potion Skeleton death link |
| 10074 | `Survival Trigger`, interval type 9 | 10075 | enabled by wave-6 script |
| 10079 | `on START WAVE 6`, type 2 | 10080 | controller stage 18 |
| 10081 | `Survive Trigger 2`, interval type 9 | 10075 | enabled by wave-6 script; shares script 10075 |
| 10083 | `Survival Trigger 3`, interval type 9 | 10084 | enabled by wave-6 script |
| 642218 | `Lock Camera Trigger`, player-steps-on type 7 | 642219 | player enters serialized trigger region |

Interval payloads are preserved exactly in `[E13]`: 10074 and 10081 carry
float 1.0, and 10083 carries float 1.5, with their serialized condition/limit
records. This pass does not rename those condition operands beyond what the
runtime evaluator proves. That avoids turning opaque trigger-condition IDs
into invented time units. [E13] [E24:00681BA0]

### Scripts in execution order

| Script | Exact authored actions | Controller relationship |
| --- | --- | --- |
| START GAME, 10000 | command 1004 configures the initial next-wave condition; command 1051 `TUTORIAL` constructs the controller; places Solomon digging at the serialized location; starts two fires at serialized locations/areas | establishes scene before stage 0; Arena later emits wave 1 |
| WAVE 1, 10002 | loop 2 times: spawn group 10010; then configure the next-wave condition | stages 1-3 |
| WAVE 2, 10048 | loop 3 times: force spawn mode 2, spawn group 10052, sleep 2 seconds; sleep 7 seconds; force mode 1; spawn group 10052 | stages 5-8; item skeleton death launches amulet script |
| Drop Item, 10050 | drop embedded ItemRecipe at location mode 7; delete trigger 10049 | supplies stage-8 target and makes the scripted item trigger one-shot |
| WAVE 3, 10055 | spawn 3 from group 10010; force spawn mode 2; force skill-pick IDs 65, 67, 60; loop 4 times: spawn group 10010, sleep 4 seconds | stages 10-11 |
| WAVE 4, 10058 | spawn group 10010; spawn group 10060; sleep 5 seconds; spawn group 10061 | stages 13, 15, 14 |
| WAVE 5, 10064 | force spawn mode 1; spawn custom monster UID 10065 | stages 16-18; death launches potion script |
| Drop Health Potion, 10073 | drop potion subtype 0 at location mode 7 | supplies stage-17 target |
| Survival, 10075 | force spawn mode 1; spawn 1 from group 10078 | used by triggers 10074 and 10081 |
| WAVE 6, 10080 | force skill-pick IDs 8, 72, 57; enable triggers 10074, 10081, 10083 | stage 19 and continuing survival |
| Survival 3, 10084 | spawn 1 from group 10086 | later/deadlier survival additions |
| Lock Camera, 642219 | lock camera to serialized region; sleep 3 seconds; destroy off-camera objects | early approach/pre-wave staging |

[E13]

`FORCE SKILL PICK` is retained by numeric skill ID because the command's
runtime behavior is the evidence: command 1058 / `0x422` resolves the player
progression object and calls its selection virtual at `+0x85C`. The Boneyard
does not serialize human-readable spell names for these operands. It should
not be confused with the controller's explicit grant/unlock of Acid Rain ID
`0x48`. [E15:1058] [E16:00689750]

### Reusable Boneyard commands

These are every command used by the Tutorial level and their recovered native
execution seams:

| ID | Authored command | Builder/parser | Runtime behavior | Seam |
| ---: | --- | ---: | --- | --- |
| 1002 / `0x3EA` | sleep for seconds | `0x004BF790` | dispatcher returns a script delay | clean data-driven primitive |
| 1004 / `0x3EC` | start next wave when ... | `0x004D2080` | `0x004625F0`, configures Arena `+0x8FF8/+0x8FFC` | clean-ish, Arena-owned |
| 1005 / `0x3ED` | force spawn mode | `0x004D2170` | `0x00462680`, writes Arena `+0x8F00` | dirty raw; semantic enum recommended |
| 1006 / `0x3EE` | spawn custom monster | `0x004D28B0` | `0x00469580` | clean-ish with validated recipe/location |
| 1007 / `0x3EF` | spawn custom monster group | `0x004D4790` | `0x0046C710` | clean-ish with validated UID group |
| 1008 / `0x3F0` | drop item | `0x004D2E60` | `0x00469FE0` | clean-ish, clone recipe then spawn ground actor |
| 1010 / `0x3F2` | enable trigger | `0x004D49D0` | trigger-group helper `0x00463020` | clean inside a level-owned trigger graph |
| 1013 / `0x3F5` | delete trigger | `0x004D4B20` | trigger-group helper `0x00463020` | clean inside a level-owned trigger graph |
| 1020 / `0x3FC` | spawn N from monster group | `0x004D4850` | `0x0046C790` | clean-ish |
| 1032 / `0x408` | loop N times | `0x004BF480` | script interpreter loop frame | clean script primitive |
| 1033 / `0x409` | end loop | `0x004BF440` | script interpreter loop frame | clean script primitive |
| 1048 / `0x418` | place Solomon digging | `0x004D84B0` | `0x00467230` | dirty, Solomon-specific |
| 1051 / `0x41B` | string special command | string-code builder | `0x006824B0`; `TUTORIAL` branch calls `0x005D5CF0` | dirty dispatch escape hatch |
| 1058 / `0x422` | force skill pick | `0x004D0C20` | player progression virtual `+0x85C` | dirty without semantic skill validation |
| 1059 / `0x423` | drop potion at | `0x004D34F0` | `0x00466B50` -> Arena virtual `+0x148` | clean-ish |
| 1061 / `0x425` | start a fire at | `0x004D3720` | `0x00466C60` | clean-ish world-prop primitive |
| 1065 / `0x429` | lock/unlock camera | `0x004D3950` | `0x00464B20` | clean-ish if participant/camera scoped |
| 1066 / `0x42A` | destroy off-camera objects | direct builder | `0x004728B0` | dirty/destructive scene operation |

[E15] [E16] [E17] [E18]

The command interpreter is a stronger basis for custom mod tutorials than the
compiled Tutorial controller, but raw invocation is still tied to Arena,
Trigger, and ScriptThread lifetime. A loader should expose validated scenario
operations with scene-generation ownership and participant authority rather
than arbitrary command IDs.

## Completion has three different meanings

The stock flow has three milestones that must not be conflated:

1. **Teaching overlay complete:** stage 19 sees more than five enemies and
   removes the `Tutorial` UI/controller object. Survival continues.
2. **Tutorial run ends:** ordinary Game Over/scene teardown proceeds through
   the tutorial Game's stock lifecycle.
3. **First-play profile complete:** because `Game+0x1CD4` is set, teardown
   clears profile byte `0x0081A434` and saves `darkdata.cfg`.

`GameOver_Tick` at `0x005CF4F0` performs the clear at `0x005CF8AB`, saves
through `0x005BE0B0` at `0x005CF8B1`, cleans up through `0x005C9670`, and
returns to frontend dispatch. `Game_Destroy` at `0x005CD3A0` has the equivalent
clear/save at `0x005CD3FF/0x005CD405`. Thus stage 19 alone does not persist
completion. Conversely, any teardown path that destroys a Game marked
`+0x1CD4` can clear the first-play gate; the clear is scene-identity-based, not
proof that all lessons or survival were completed. [Q1]
[E01:005CD3A0,005CF4F0]

This is a **dirty** persistence seam. Mod tutorials should keep their own
versioned completion state and commit it only at an explicit semantic
milestone. They should not write the stock encoded profile byte.

## Input, HUD, and protection gates

The controller initially clears five adjacent Game bytes and restores them at
lesson boundaries. The consumer analysis establishes their behavior:

| Game field | Stock role in this tutorial | Set to 1 | Important consumers | Suggested exposure |
| ---: | --- | --- | --- | --- |
| `+0x1AC0` | inventory screen access/widget enable | stage 7/8 after any non-potion inventory item | Game input/update path, inventory widget | `tutorial.set_access("inventory", bool)` with save/restore |
| `+0x1AC1` | skills screen access/widget enable | stage 11 after level-up | keyboard/UI handler `0x005CB360` | `tutorial.set_access("skills", bool)` |
| `+0x1AC2` | quick-use/belt action input and presentation | stage 4 | `0x005CB360`, control handler `0x005D8120`, belt/UI render | scoped action-category mask |
| `+0x1AC3` | spell/secondary HUD visibility | stage 4 | Game HUD render `0x005D2520` | scoped HUD surface visibility |
| `+0x1AC4` | combat/status HUD visibility | stage 13 close | Game HUD render `0x005D2520` | scoped HUD surface visibility |
| `+0x1CD4` | Tutorial Game identity/persistence marker | controller construction | Game Over/destructor and several scene branches | do not expose as a generic mod flag |
| `+0x1CD5` | early tutorial hit/combat suppression | activation; cleared after skill screen | early return in `0x0052AC80` and `0x0052B150`; control render paths | explicit local protection policy, never a raw byte |

[E20] [E21:005D2520,005CB360,005D8120,0052AC80,0052B150]

The activation method also hides widget nodes by changing their UI state bits,
then refreshes their layouts through virtual `+0xAC`. Later stages both set the
boolean gate and reveal/refresh the associated widget. This is why simply
writing one byte is not a complete or robust unlock operation. The controller
uses `Game+0x15A0` for the live inventory screen and `Game+0x1664` for the
skills screen, and waits for their close/resume bytes at `+0x14C` and `+0x98`.
[E01:005D5FE0,005D6330] [E20] [E21]

The normal keyboard handler at `0x005CB360` tests inventory byte `+0x1AC0`
before calling `0x005C6F10`, and skills byte `+0x1AC1` before calling
`0x005CA640`. `0x005C6F10` closes an open skills modal, toggles an existing
inventory modal through `0x00550760`, or allocates the stock inventory screen
with `0x00560380(Game+0x13B8, Game+0x1410, 0)` and stores it at
`Game+0x15A0`. `0x005CA640` performs the inverse mutual-exclusion/toggle
operation: it closes inventory through `0x00550760`, closes existing skills
through `0x006568E0`, or retains progression `Game+0x1654`, constructs through
`0x006576C0`, and stores the new screen at `Game+0x1664`. Both install a new
modal through `0x004277E0` and `0x004280E0`. The stock screen openers are
therefore **dirty/global** seams, even though the gates themselves look like
bytes. [E21:005CB360] [E34:005CA640]
[E35:005C6F10,00550760,004277E0,004280E0]

Recommended design: a scoped tutorial session should snapshot only the access
and visibility categories it changes, apply participant-local masks, and
restore the snapshot on completion, cancellation, or scene transition. Direct
Game-field writes are **dirty** and global. A semantic gate service with
generation-bound restoration is **clean**.

## Every reusable mechanism and proposed loader seam

This catalog consolidates the reusable pieces, including mechanisms already
described above. `Required state` is the minimum native context shown by the
stock call path.

| Mechanism | Exact stock seam(s) | Required state / invocation | Quality | Recommended loader exposure |
| --- | --- | --- | --- | --- |
| point at screen target | `0x005C9BB0`, UI record 28 at `[0x008199E4]+0x15A8` | render thread; UI bundle resident; start/target pixels; valid render state | clean-ish | `sd.ui.point_between`, caller-owned lifetime |
| point at world object | stage spans `0x005D0F3D..0x005D10BB`, `0x005D1EED..0x005D206F`; lookup `0x00646CB0` | validated actor and local camera/viewport | stock wrapper dirty; semantic version clean | `sd.ui.point_at_world_object`, local participant scope |
| locate registered actor by type | `0x00646CB0` | active world list `+0x318/+0x324` | clean-ish for diagnostics, dirty for identity | typed iterator returning validated handles, not first-only lookup |
| stage/objective state machine | `0x005D6330`; Tutorial `+0x7C/+0xA0/+0xA4` | compiled Tutorial object, global Arena/Game/player predicates | dirty/purpose-built | mod-owned event-driven objectives with explicit enter/complete/cancel actions |
| heading/subheading | `0x005C9710`, `0x005C9960` | stock font bundle and HUD render phase | clean-ish | tutorial overlay heading/body primitives |
| bordered callout | `0x005C9C70` | current string, font, coordinates, render state | clean-ish | layout-owned callout with text and anchor |
| dynamic key label | `0x004299B0`, `0x00402BF0` | configured action/key globals | clean-ish | resolve semantic input action to localized glyph/name |
| resolve modal UI element anchor | equipment `0x00570F80`; backpack `0x005D07A0 -> 0x00558E40 -> 0x004F9320`, then `0x004282D0` | live owning modal; for backpack, `Game+0x15A0`, non-null member `+0x294`, list `+0x188`, entry zero | dirty/index-coupled | resolve a stable semantic handle to a participant-local modal anchor |
| narration queue/idle | `0x004FCEC0`, `0x00462090` | global narration owner, existing localization/audio records | dirty/global | mod-owned prompt/audio queue with cancellation and local scope |
| stock speaker/portrait installation | `0x005D5FE0`; Game `+0x1C94/+0x1C9C/+0x1CA0` | global stock asset tuple and narration/UI owners | dirty/global | dialogue speaker/portrait resource owned by the mod prompt session |
| intro fade and forced north movement | `0x005D6330`, `0x005D08C0`; PlayerActor movement accumulator `+0x158/+0x15C`; `PlayerActorTick 0x00548B00`; UI record `[0x008199E4]+0x2124` | Tutorial UI/controller object, authoritative player actor, global render state | dirty | scoped scene-intro transition plus authority-owned forced movement |
| linked action on monster death | `0x004819D0 -> 0x0068BB10 -> 0x006894F0` | MonsterRecipe linked Trigger, ScriptThread/TriggerControl alive | clean-ish inside scenario | `on_enemy_death` event -> validated scenario action |
| spawn definition-backed ground item | `0x00469FE0 -> 0x004699B0 -> 0x0046A360` | active Arena, ItemRecipe, resolved location | clean-ish | semantic item-reward spawn returning actor identity |
| spawn health potion | `0x00466B50 -> Arena vslot +0x148 / 0x0046AE20` | active Arena, subtype/location | clean-ish | potion-reward spawn returning actor identity |
| pickup transfer | `0x005E6B50 -> 0x0063E870/0x0055FF20` | ground actor with held item `+0x148`, delay `+0x14C`, valid inventory | dirty to call, clean to observe | item pickup event; do not call tick manually |
| top-level inventory lesson test | enumeration via `0x004027F0`, Game count `+0x13CC` | local inventory root | dirty/broad | inventory query by stable item/recipe identity |
| recursive health-potion count | `0x00552A80` | inventory root, type `0x1B59`, subtype 0, and stack quantity `+0x88` | clean-ish query | `inventory.count({type="potion", subtype="health"})` / event-driven objective |
| discard Tutorial starter potions | `0x005D6297..0x005D62EB` -> `0x005529A0/0x00552B70` -> `0x00568170` | Tutorial activation, inventory root, first recursive native Health and Mana Potion objects | dirty/Tutorial-owned | one activation transaction that removes both starter objects before teaching begins |
| normalize belt/HUD inventory slots | `0x005D50E0` after the Tutorial clears two quick slots | Game-owned belt records, inventory, progression, UI layout and stock item types | dirty/global | one transactional loadout refresh owned by the tutorial session |
| wave advance | `0x00465C00` | active Arena and configured wave graph | clean-ish | authority-owned `scenario.start_next_wave()` |
| spawn custom monster/group | `0x00469580`, `0x0046C710`, `0x0046C790` | validated recipe/group/location and Arena | clean-ish | semantic spawn request returning identities |
| enable/delete trigger | `0x00463020`, remote helpers `0x006822E0/0x00682340/0x006823A0` | live TriggerControl and UID | clean inside graph | scenario trigger handle with enable/disable/delete |
| script sleep/loop | command IDs 1002, 1032, 1033 | live ScriptThread | clean | coroutine/timeline primitives |
| level-authored camera lock | command 1065 -> `0x00464B20` | active camera/Arena and serialized region | clean-ish in solo | local-participant camera constraint handle |
| destroy off-camera objects | command 1066 -> `0x004728B0` | active scene/camera ownership | dirty/destructive | no broad public seam; explicit filtered cleanup only |
| level-authored fire prop | command 1061 -> `0x00466C60` | active Arena and serialized location/area | clean-ish | scenario-owned world-effect spawn with an explicit lifetime |
| place Solomon digging | command 1048 -> `0x00467230` | stock Solomon actor/scene contract and serialized location | dirty/story-specific | no broad public seam; expose a generic validated actor action if needed |
| XP floor for lesson progression | `0x00680AB0(...,10,1)` in stage 11 | local progression and post-wave idle | dirty as implicit loop | explicit tutorial reward transaction, once |
| unlock/select Acid Rain | `0x00660320(...,0x48,1)`, progression `+0x870`, `0x0065F9A0` | local progression and skill catalog | clean-ish if transactional | validated grant/select API with reversible tutorial loadout |
| force skill selection | command 1058, progression virtual `+0x85C` | local progression and valid skill ID | dirty raw | semantic skill-choice request by stable skill ID |
| gate HUD/input | Game `+0x1AC0..+0x1AC4` plus widget state | Game/UI live and exact paired restoration | dirty raw | scoped participant-local access/visibility masks |
| open inventory/skills modal | `0x005C6F10`, `0x005CA640`; constructors `0x00560380/0x006576C0`; close `0x00550760/0x006568E0`; attach `0x004277E0/0x004280E0` | Game, progression/inventory roots, mutually exclusive modal state | dirty/global | participant-scoped semantic stock-screen request, not raw function access |
| temporary early protection | Game `+0x1CD5`; consumers `0x0052AC80/0x0052B150` | global Tutorial Game | dirty | explicit protection rule owned by session/participant |
| attach overlay to modal screen | `0x00428160` plus UI-owner virtual `+0xA8` | live UI tree and modal screen | dirty raw | loader overlay layer automatically follows active modal surface |
| first-run prelude | `0x005B6C90`, ControlPicker class | frontend globals, controls bundle, profile gate | dirty | mod settings/onboarding flow with mod-owned persistence |
| completion persistence | `0x005CD3A0`, `0x005CF4F0`, saver `0x005BE0B0` | Tutorial-marked Game and stock profile | dirty | versioned mod-owned completion flag at explicit milestone |

No other objective/waypoint entity, prompt queue, tutorial-only actor factory,
or separate loot-arrow timeout exists in the analyzed Tutorial controller,
trigger graph, item-drop actor, or UI draw chain. The apparent family of
objective arrows is one stock screen-space pointer helper fed by different
caller-owned target calculations. The adjacent Tutorial helper-family range
`0x005C9600..0x005CA800` was separately inventoried so nearby draw and wrapper
functions were not mistaken for a second marker subsystem. [E33]

## MapPicker handoff for `mpk`

The Tutorial controller does **not** call the stock `MapPicker` at any stage.
The picker becomes available during the Tutorial Game through the normal Game
map-control callback. The exact handoff chain is:

```text
Game control handler 0x00514A20
  clicked control = Game + 0x0E00
  require Arena + 0x8E48 <= 0
    -> MapPicker_Open 0x0050E5E0
       if Arena + 0x8E94 is null
         -> MapPicker constructor 0x0050C730
       attach/pause picker; picker + 0x80 = owner
```

The `MapPicker` vtable is `0x0079208C`, object size is `0xA0`, tick is
`0x0050E980`, and render is `0x00508C60`. The only constructor caller recovered
is `0x0050E5E0`; the only caller of that opener is `0x00514A20`. A story/beta
dialog branch can run before construction when its separate globals are set,
but it reaches the same opener. [E05] [E06] [E07]

This is the complete Tutorial-side finding and the handoff boundary for sibling
`mpk`: begin at `0x00514A20 -> 0x0050E5E0 -> 0x0050C730`, with Game map
control `+0xE00`, Arena gate `+0x8E48`, and Arena picker pointer `+0x8E94`.
No picker hijack or deeper MapPicker implementation analysis is included here.

## Native address index

| Address | Recovered role |
| ---: | --- |
| `0x0040AF70` | stock effect setup invoked at Tutorial intro countdown 20 |
| `0x00414F90` | rotated/transformed sprite draw used by pointer |
| `0x00414540` | common transformed sprite/quad draw |
| `0x004277E0` | bind an allocated stock modal to its owner pointer |
| `0x004280E0` | attach a UI child and set its parent |
| `0x00428160` | detach a UI child from its current parent |
| `0x004282D0` | resolve a modal UI-list entry's on-screen anchor |
| `0x00462090` | narration controller idle predicate |
| `0x004625F0` | configure next-wave condition |
| `0x00462680` | set forced spawn mode |
| `0x00463020` | trigger enable/delete group helper |
| `0x00464B20` | scripted camera lock/unlock |
| `0x00465C00` | start next wave |
| `0x00466600` | resolve script location; mode 7 uses trigger position |
| `0x00466B50` | scripted potion drop |
| `0x00466C60` | scripted fire spawn |
| `0x00467230` | place Solomon digging |
| `0x00469580` | spawn custom monster |
| `0x004699B0` | clone ItemRecipe into live item |
| `0x00469FE0` | scripted item drop |
| `0x0046A360` | Arena item-drop actor creation |
| `0x0046AA90` | Arena gold-drop path |
| `0x0046AE20` | Arena potion-drop path |
| `0x0046C710` | spawn custom group |
| `0x0046C790` | spawn N from group |
| `0x004728B0` | destroy off-camera objects |
| `0x0047C070` | generic enemy reward selector |
| `0x004819D0` | monster death, reward and linked-trigger entry |
| `0x004F9320` | bounded ref-counted pointer-list entry getter |
| `0x004FCEC0` | narration queue insertion |
| `0x00508C60` | MapPicker render; handoff only |
| `0x0050C730` | MapPicker constructor; handoff only |
| `0x0050E5E0` | open/attach MapPicker; handoff only |
| `0x0050E980` | MapPicker tick; handoff only |
| `0x00514A20` | Game control callback that invokes MapPicker opener |
| `0x00550760` | close the stock inventory modal |
| `0x005529A0` | recursive first Health Potion lookup |
| `0x00552A80` | recursive Health Potion quantity sum |
| `0x00552B70` | recursive first Mana Potion lookup |
| `0x00558E40` | inventory-anchor list getter delegate |
| `0x0055FF20` | inventory insertion used by pickup |
| `0x00560380` | construct the stock inventory modal |
| `0x00568170` | inventory-tree removal used to discard Tutorial starter potions |
| `0x00570F80` | resolve stock equipment-widget coordinates |
| `0x005A7D90` | normal frontend route when first-play flag is zero |
| `0x005A8390` | missing-profile defaults; sets tutorial gate to one |
| `0x005A84C0` | ControlPicker constructor |
| `0x005A8620` | ControlPicker layout |
| `0x005A8790` | ControlPicker selection callback |
| `0x005B6B00` | Tutorial Game/Boneyard bootstrap |
| `0x005B6C90` | first-play ControlPicker/prelude entry |
| `0x005B9990` | ControlPicker tick and tutorial transition |
| `0x005B9A30` | ControlPicker render |
| `0x005BC1B0` | dark-profile serializer |
| `0x005BDB50` | dark-profile loader |
| `0x005BE0B0` | dark-profile saver |
| `0x005BF6A0` | post-profile-load first-play branch |
| `0x005C6F10` | normal inventory-modal opener/toggle |
| `0x005C96F0` | Tutorial deleting destructor/removal virtual |
| `0x005C9710` | Tutorial primary heading draw |
| `0x005C9960` | Tutorial subheading draw |
| `0x005C9BB0` | pointer angle/blink/stock-arrow draw |
| `0x005C9C70` | Tutorial bordered callout draw |
| `0x005CA480` | Tutorial subheading wrapper |
| `0x005CA560` | Tutorial callout wrapper |
| `0x005CA640` | normal skills-modal opener/toggle |
| `0x005CD3A0` | Game destruction path; tutorial gate clear/save |
| `0x005CF4F0` | Game Over path; tutorial gate clear/save |
| `0x005D07A0` | Tutorial modal UI-entry getter wrapper |
| `0x005D08C0` | Tutorial render and all teaching overlays |
| `0x005D2520` | Game HUD render consuming `+0x1AC3/+0x1AC4` |
| `0x005D50E0` | belt/HUD inventory validation and layout normalization |
| `0x005D5CF0` | construct/install Tutorial controller |
| `0x005D5FE0` | Tutorial activation/reset and initial gates |
| `0x005D6330` | Tutorial 0..19 stage machine |
| `0x005E6B50` | ground item/Sack tick and pickup transfer |
| `0x0063E870` | ground actor unregister/removal in pickup path |
| `0x00646CB0` | first registered actor by native type |
| `0x006568E0` | close the stock skills modal |
| `0x006576C0` | construct the stock skills modal |
| `0x00660320` | grant/unlock skill; used for Acid Rain `0x48` |
| `0x00680AB0` | grant XP; stage-11 floor uses 10 |
| `0x00681BA0` | trigger eligibility/condition evaluator |
| `0x006824B0` | string special-command handler; `TUTORIAL` branch |
| `0x00683C10` | CodeLine serializer |
| `0x00686400` | TriggerControl serializer |
| `0x006894F0` | launch Trigger script |
| `0x00689750` | script command runtime dispatcher |
| `0x0068B5B0` | trigger limit/eligibility support |
| `0x0068BB10` | monster-death linked-trigger dispatcher |

## Evidence and reproducibility

### Inputs

| Input | Size | SHA-256 |
| --- | ---: | --- |
| stock `SolomonDark.exe` | 4,723,200 bytes | `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3` |
| stock `data/levels/tutorial.boneyard` | 33,220 bytes | `97802f2ca45d9bc6f90a497e7c12a55926298161e191fa70eee5e666b90106ed` |

The executable was analyzed read-only through the repository's Ghidra replica
pool wrapper against the existing analyzed `SolomonDark` project. The Boneyard
was parsed read-only through the repository's SyncBuffer tooling. Static code,
serialized level data, and sprite pixels were mutually sufficient, so the
conditional runtime-instance allowance was not used.

### Evidence index

The audit packet is `/mnt/d/codex-evidence/tutre-20260801/`. Its final
`sha256-manifest.txt` binds every artifact.

| Citation | Artifact | What it establishes |
| --- | --- | --- |
| Q1 | `/mnt/d/codex-evidence/tutorialq-20260801/evidence.md` | prior first-play flag load/test/clear chain; SHA-256 `4f462c3c9738c9698d004770c8346d794b1f032f1ccbc8a545e0dfa53ba416d9` |
| E01 | `raw/01_core_tutorial_control_decompile.txt` | controller construction, activation, stages, render, picker, completion paths |
| E02 | `raw/02_tutorial_boneyard_semantics.json` | semantic level, monster, group, item counts and fields |
| E03 | `raw/03_tutorial_helpers_decompile.txt` | narration idle, actor lookup, inventory count, text/callout helpers |
| E04 | `raw/04_arrow_frontend_gates_decompile.txt` | rotated sprite draw and frontend/gate consumers |
| E05 | `raw/05_map_picker_xrefs_decompile.txt` | MapPicker class anchors and constructor xrefs |
| E06 | `raw/06_map_picker_invocation_xrefs.txt` | exact opener/caller graph |
| E07 | `raw/07_map_picker_invocation_decompile.txt` | Game map-control invocation and Arena fields |
| E08 | `raw/08_arrow_render_chain_decompile.txt` | pointer math, blink, transform, texture/quad render chain |
| E09 | `raw/09_tutorial_key_instructions.txt` | exact arrow instructions and tutorial render call sites |
| E10 | `raw/10_ui_record_28_arrow.png` | pixel-extracted stock arrow sprite |
| E11 | `raw/11_tutorial_constants.txt` | first raw constant pass retained for provenance |
| E12 | `raw/12_tutorial_constants_typed.txt` | typed float/double constants used by movement/arrow/intro |
| E13 | `raw/13_tutorial_trigger_tree.txt` | complete TriggerControl/CodeLine tree and authored operands |
| E14 | `raw/14_loot_and_scripting_decompile.txt` | reward factories, ground actor pickup, narration, serializers |
| E15 | `raw/15_tutorial_script_command_decompile.txt` | command builders and command-specific runtime helpers |
| E16 | `raw/16_script_runtime_dispatch.txt` | command dispatcher cases |
| E17 | `raw/17_script_runtime_helpers.txt` | string special command including `TUTORIAL` |
| E18 | `raw/18_script_builder_data_refs.txt` | authored command-name and builder cross-references |
| E19 | `raw/19_command_1051_string.txt` | numeric/string-command probe retained for provenance |
| E20 | `raw/20_tutorial_gate_offset_accesses.txt` | exhaustive Game gate-field access scan |
| E21 | `raw/21_tutorial_gate_consumers.txt` | decompiled gate consumers and UI/combat behavior |
| E22 | `raw/22_offset_c8_reads.txt` | linked-trigger pointer-field access support |
| E23 | `raw/23_trigger_runtime_symbols.txt` | trigger-runtime symbol range inventory |
| E24 | `raw/24_trigger_runtime_decompile.txt` | trigger eligibility and remote enable/disable/delete behavior |
| E25 | `raw/25_enemy_death_reward_xrefs.txt` | monster death/reward xrefs |
| E26 | `raw/26_enemy_death_trigger_chain.txt` | linked death-trigger dispatch behavior |
| E27 | `raw/27_trigger_location_and_launch.txt` | script location mode 7 and trigger script launch |
| E28 | `raw/28_tutorial_item_recipe_tree.txt` | exact embedded amulet recipe subtree |
| E29 | `raw/29_tutorial_boneyard_layout_summary.txt` | complete serialized level-section and static-layout counts |
| E30 | `raw/30_tutorial_ui_anchor_helper_decompile.txt` | Tutorial wrapper for modal UI-entry lookup |
| E31 | `raw/31_tutorial_inventory_anchor_delegate_decompile.txt` | inventory-anchor lookup delegate |
| E32 | `raw/32_tutorial_inventory_anchor_base_decompile.txt` | bounded ref-counted UI-entry list lookup |
| E33 | `raw/33_tutorial_helper_symbol_range.txt` | adjacent Tutorial helper-family symbol inventory |
| E34 | `raw/34_tutorial_residual_helpers_decompile.txt` | residual address-range audit; ordinary Game/UI neighbors, not hidden Tutorial subsystems |
| E35 | `raw/35_tutorial_modal_and_anchor_helpers_decompile.txt` | inventory/skills modal openers and modal-anchor coordinate helpers |

### Reproduction pattern

Representative static pass:

```powershell
./scripts/Invoke-GhidraHeadless.ps1 `
  -ProjectRoot 'C:\Users\User\Documents\GitHub\SB Modding\Solomon Dark\Decompiled Game\ghidra_project' `
  -ReplicaRoot 'C:\Users\User\Documents\GitHub\SB Modding\Solomon Dark\Decompiled Game\ghidra_project_replicas' `
  -ReplicaCount 6 `
  -ScriptPath 'C:\sd-tutre-20260801\tools\ghidra-scripts\decompile_targets.py' `
  -ScriptArguments '0x005D5CF0;0x005D5FE0;0x005D6330;0x005D08C0;0x005C9BB0'
```

The complete commands and tool/input hashes are recorded in the evidence
packet. The canonical Ghidra project and stock game tree were not modified.

## 2026-08-23 web-port closure addendum

This addendum reopens the 2026-08-01 report only where a complete browser port
needs facts that the earlier loader-seam question did not consume. The stage
machine, authored level graph, and pointer conclusions above remain valid.

### Fresh-profile entry has no tutorial-choice dialog

A fresh direct-retail run was made from a task-owned copy of the verified
4,723,200-byte executable. Its copied `sandbox` directory was removed before
launch; the source game tree and real saves were untouched. No loader DLL or
mod was present. At `1600 x 900`, retail showed, in order:

1. the stock beta notice;
2. `SELECT A CONTROL SCHEME`, with `Controls.0` and `Controls.2` visible;
3. the baked `...MIDNIGHT / SIX MONTHS AGO...` prelude card; and
4. Tutorial stage 0 in the rain-darkened Boneyard, with no ordinary HUD and
   `USE YOUR KEYBOARD / TO MOVE THE WIZARD` above
   `FIND AND CONFRONT SOLOMON DARK`.

The durable captures are:

| Capture | SHA-256 |
| --- | --- |
| [`control-picker.png`](../assets/tutorial-stock-20260823/control-picker.png) | `d494e30118af4ce3001b52895925e460d3533c42cd0f1227e78a0dd23771bdd2` |
| [`midnight-prelude.png`](../assets/tutorial-stock-20260823/midnight-prelude.png) | `11816ad1334d2024603c7b9725180b514b192f980fee31c55e42794bacba8c2d` |
| [`stage-0.png`](../assets/tutorial-stock-20260823/stage-0.png) | `8b43df2d8bcaa5bd9d92894e31cf9dc749d67e4f5fa99ec1bac39c26b286829c` |

A fresh canonical read-only Ghidra replica search found the existing
`tutorial` level/command strings and the control-picker heading, but zero
functions or strings for `WOULD YOU`, `PLAY THE TUTORIAL`, or
`SKIP TUTORIAL`. `YES` is a general UI literal used by unrelated screens.
Retail therefore enters the tutorial automatically from the persisted
fresh-profile byte; it does not ask a tutorial-specific yes/no question. A web
yes/no offer is an explicit product gate in front of the native sequence, not
a recovered retail screen.

The control-picker membership is also sharper than the earlier callback-only
description. Exact UI-tree fixture `menu-goldens.json` and the clean capture
show `Controls.0` at `(477.5,290)-(722.5,610)` and `Controls.2` at
`(850.5,324)-(1149.5,576)`. `Controls.1` is constructed but parked off-screen
in this build. The callback branches remain arrow keyboard (mode 1), WASD
keyboard (mode 2), and dormant mouse mode 4. The browser port must preserve the
two visible choices and must not make the native-hidden third panel visible.

The intro card is not a recoverable text string. `Tutorial::Render`
`0x005D08C0` draws UI bundle record 43 through the two calls using
`[0x008199E4] + 0x2124`; the extracted exact record is frame
`(266,62,340,66)`, logical size `443 x 171`, trim `(50,50)`. The first-play
owner selects music key `prelude` at `0x005B6C90`; `music.txt` maps it to
module subsong 0.

### Exact intro-card, teaching-text, and callout rendering

A final screenshot comparison against the fresh retail captures exposed that
the earlier web-port consequence compressed the intro and used approximate
font/color styling. The render and tick instructions close those fields
without inference:

- `Tutorial::Activate` initializes blend `+0x8C = 0`, fade `+0x90 = 1`,
  intro-active `+0x94 = 1`, and delay `+0x98 = 25`. When the delay is 20,
  `Tutorial::Tick` arms forced-movement lane `+0x9C = 250`. Once the delay
  reaches zero, blend adds the double constant `0.0025` per 100-Hz tick with a
  float32 store and clamps to one. At one, fade subtracts double `0.02` per
  tick, clamps to zero, clears intro-active, and invokes the intro teardown
  callback. The exact float32 sequence clears after 475 ticks. No controller
  stage predicate runs while intro-active remains set; the 250-tick lane only
  begins decrementing afterward.
- During intro-active ticks with blend strictly above `0.8`, the controller
  overwrites PlayerActor movement accumulator `(+0x158,+0x15C)` with
  `(0,-actor+0x70)`. After teardown it decrements `+0x9C` first and, while the
  result is positive, writes `(0,-actor+0x70*(remaining/250))`. The shared
  player tick clamps and consumes this as ordinary motion. The opening
  northward walk is therefore authoritative Tutorial movement and must not be
  replaced by a camera offset or left to user input.
- UI record 43 is drawn centered at `(800,450)` in the retail DirectX branch
  with RGB floats `(0.85,0.73,0.44)`, the shared packed browser tint
  `0xD9BA70`. UI record 68 is the complete skull backdrop: frame/logical size
  `(753,335,93,99)` / `93 x 99`, scale `4`, alpha `blend^2`, center X `800`,
  and center Y `350 - 100*blend`. The world/lesson layer is multiplied by
  `1-fade`; record 43 and the skull remain above the black intro surface until
  teardown.
- `ControlSchemePicker::Render 0x005B9A30` draws its heading with Fonts group
  4 (`+0x1351CC`, the `40/10/28` heading wrapper), common gold `0xD9BA70`,
  center X `800`, and baseline Y `50`. It does not use the smaller menu face.
- On selection, `0x005A8790 -> 0x005B9990` commits the binding globals once,
  fades the visible picker alpha by `0.02` per tick to black in 50 ticks,
  decays the selected-panel flash by `0.1` per tick, and advances its handoff
  scalar by float32 `0.01` per tick until the Tutorial bootstrap at 100 ticks.
- Tutorial primary headings (`0x005C9710`) use the same Fonts group 4 and
  common gold. Secondary text (`0x005C9960`) uses Fonts group 3
  (`+0x0E7D98`, the `24/6/28` menu wrapper) and the same gold. Both helpers
  first draw a crisp black copy at `(x+2.25,y+2.25)`, then the gold copy at the
  authored baseline; no blurred CSS shadow or white subtitle exists.
- Stage 0/2 primary and secondary baselines are `100/170`. Stages 5/9/12/18
  use `screenHeight-170` / `screenHeight-140` (`730/760` at `1600 x 900`).
  The conditional stage-11 pair uses `80/110`; stage 19 uses primary baseline
  `200`.
- Bordered modal callouts (`0x005C9C70`) measure Fonts group-3 text, expand the
  frame by `20 x 28`, draw the filled mirrored nine-slice from UI record 4,
  and paint the text in common gold. Stage 14 does not use that callout: its
  two lines go through the unframed secondary-text helper.

These are members of the stock Tutorial presentation owner, not optional UI
polish. A web implementation is incomplete if it shows a white baked card,
omits record 68, advances the lesson during the 475-tick intro, uses the menu
font for the picker/primary heading, paints secondary/callout text white, or
wraps the stage-14 copy in an invented panel.

### Exact forced-spawn and survival-trigger semantics

The START GAME script's two command-1061 rows are also fully typed. Each calls
the stock `Fire 0x7E3` factory with scalar arguments `(1.0, 100.0, 1000.0)`
and its authored point: `(1766.1005859375, 147.63815307617188)` or
`(1852.1005859375, 199.63815307617188)`. Dispatcher helper `0x00466C60`
copies the first scalar into the Fire payload, normalizes the second into the
area/scale lane, stores the third in the actor lifetime lane, enables the
actor, and registers it. These are two distinct 1,000-tick `Fire` actors using
the shared DeadHawg 46..77 presentation, not baked level sprites or an
indefinite ambient decoration.

Fresh canonical read-only decompilation closes two previously opaque pieces of
the Tutorial Boneyard graph:

- `0x00462680` stores the script operand at Arena `+0x8F00`.
- `0x00469580` obtains the raw point from `0x00465E40`, temporarily applies
  that Arena policy, then always runs `0x00466200` and collision/path
  adjustment `0x00463D30`.
- In `0x00466200`, policy `1` is the light-point branch and policy `2` is the
  off-screen branch. Thus Tutorial wave 2 and the delayed wave-3 groups really
  use off-screen placement, while the final wave-2 group, wave 5, and survival
  groups use light placement. These are placement policies, not author-written
  coordinates.

Interval trigger `0x00681BA0` multiplies the serialized seconds at `+0x60` by
the 100-Hz game clock and truncates it; `0x0068BBC0` compares against the Game
tick at `Game+0x28`, records the current tick at trigger `+0x44`, and advances
one round-robin interval-trigger cursor per fixed tick. Predicate dispatcher
`0x00689750` and comparator `0x006819C0` resolve every authored Tutorial
operand as follows:

| Trigger | Period | ALL predicate | Script result |
| ---: | ---: | --- | --- |
| 10074 | 100 ticks | live enemy count `< 100` | force light placement; spawn one random member of group 10078 |
| 10081 | 100 ticks | enemy count `> 10`, enemy count `< 150`, and player level `< 4` | the same script 10075 and group 10078 |
| 10083 | 150 ticks | player level `> 3` | spawn one random member of group 10086 |

All three start disabled and wave-6 script 10080 enables them. The first two
share a script but retain independent clocks and eligibility. This explains
why the survival phase can accelerate below level 4 without either inventing
a wall-clock spawner or treating the serialized `1.0/1.5` values as unknown.

### Tutorial-specific Solomon dialogue branch

The opening Solomon actor is another member of the stock tutorial, not just
the ordinary generated-Boneyard six-cue encounter:

- When Solomon finishes facing a player and `Game+0x1CD0` contains the
  Tutorial controller, `0x0047D0F0` queues, in order,
  `SAY_OHBOYANOTHERWIZARD`, `SAY_IHAVEBEENDISPATCHED`,
  `SAY_ILLDOTHEDISPATCHING`, `SAY_YOURPERVERSIONS`, and
  `SAY_TODEATHEXACTLY`. Speaker side alternates Solomon/player.
- At retreat start, `0x0047D570` queues `SAY_SOLOMON_LAUGH1`,
  `SAY_COWARDCOMEBACK`, and `SAY_GETHIMBOYS`; the last remains the combat
  release cue.
- These eight cues share the same global narration queue as the sixteen
  Tutorial-controller keys listed above. They may not overlap or bypass the
  stage-4 narration-idle wait.

The complete stock tutorial narration membership is therefore 24 cue keys,
not 16. Every corresponding WAV is present in the retail `voices` directory;
the browser implementation must carry the exact source bytes and derive queue
duration from the PCM extent.

A second clean fresh-profile observation sampled Tutorial stage 0 at 0.3,
1.0, 2.0, and 4.0 seconds after the control-picker handoff. The
`SAY_SOLOMONDARKSHOWYOURSELF` queue is audible across those samples, but retail
draws no subtitle, speaker label, dialogue box, or portrait over the teaching
heading/world. The narration owner is therefore audio/queue state in this
scene; a visible web caption panel would be an invented presentation member.

### Viewport, live HUD anchors, and the transient stage-2 heading

A 2026-08-24 follow-up reopened the Tutorial presentation family after the web
port placed the 1600 x 900 coordinates directly into its overlay. The native
renderer does not own a fixed 1600-wide child surface. `Tutorial::Render`
`0x005D08C0` reads the active UI owner's width/height from the Tutorial base
fields at `+0x1C/+0x20`: primary and secondary copy use center X
`width * 0.5`; stages 5/9/12/18 use baselines `height - 170` and
`height - 140`. Prelude record 43 and record 68 likewise use that live UI
coordinate context. The observed `(800, 450)` and `(800, 350-100*blend)`
positions are therefore the 1600 x 900 instance, not invariant coordinates for
an expanding browser viewport. [E01:005D08C0] [E09:005D0A59..005D0E80]

The in-world pointer cases resolve the target again on every render through
the Game-owned widget rectangle and `0x00403730`; `0x005C9BB0` then draws the
arrow at a recovered offset from that live target. The complete movable-HUD
membership is:

| Stage | Semantic target | Native source | Arrow origin relative to resolved target |
| ---: | --- | --- | --- |
| 5 | secondary quick slot / spell control | Game widget `+0x600`; `0x005D0E97..0x005D0EFA` | `(-70,-50)` |
| 9 | inventory control | Game widget `+0x240`; `0x005D1197..0x005D11FD` | `(-40,-40)` |
| 12 | skills control | Game widget `+0x300`; `0x005D1875..0x005D18F8` | `(+40,-40)` |
| 14 | primary/concentration icon lane | midpoint of Game widgets `+0x480` and `+0x3C0`; `0x005D1D36..0x005D1DE9` | from the `+0x3C0` anchor plus `(+30,+50)` to the midpoint |
| 18 | health-potion control | Game widget `+0x8C4`; `0x005D214B..0x005D21C3` | `(-50,-30)` |
| 18 | health display | Game widget `+0x3C0`; `0x005D21C8..0x005D2279` | `(-100,+70)` |

The scalar dump from the canonical read-only replica pins the shared constants:
`0x00787C40 = 70`, `0x007847C8 = 50`, `0x00784650 = 40`,
`0x00784D50 = 30`, and `0x007DE908 = 100`. Modal stages 10 and 13 use the
same live-rectangle rule, including their modal-owned quick-slot, equipment,
first-backpack-entry, concentration, and hover targets. Unlike the in-world
HUD, those targets and their Tutorial overlay are reparented into the same
fixed native modal surface; moving/scaling that surface moves both together.
[E01:005D1285..005D1CDE] [E30] [E31] [E32] [E35]

The apparently broken lifetime of stage 2 is native. Script-thread tick
`0x0068B060` executes up to ten non-blocking commands per tick. Wave-1 script
10002 loops twice over group 10010 without a sleep; group helper `0x0046C710`
therefore calls enemy factory `0x00469580` for all ten Starter Skeleton rows in
the same script tick. BadGuy construction at `0x00473390` increments global
enemy count `0x0081984C` immediately. The Tutorial first enters stage 2 at the
Solomon combat-release edge; on its next tick the exact branch at
`0x005D6624..0x005D6633` sees `enemyCount > 5` and enters blank stage 3. Thus
the Magic Missile heading is intentionally a one-fixed-tick transitional
member unless a primary-cast branch wins first. A web delay would not be a
parity correction.

### Web-port consequence

The exact port boundary is now: confirmed-absent selected browser save ->
web-only yes/no offer -> native visible control picker -> native prelude card
and music -> exact Tutorial level/controller/Solomon graph -> ordinary Game
Over and durable-profile teardown. A present, corrupt, or temporarily
unreadable selected save is not “absent” and must suppress the offer. The
authenticated adapter checks its cloud row; the anonymous adapter checks its
device-local row. Tutorial gameplay is solo-authoritative, but its
presentation, stage, trigger clocks, loot identities, narration queue, and
completion boundary must remain resumable browser-save state.

## Tutorial entrance-fence spawn and camera-lock correction — 2026-08-24

The Website report that Tutorial enemies can materialize south of the entrance
fence reopened the placement and camera branch above. The earlier report
correctly named the common placement helpers, but it stopped before the
UID-group cache field and treated the 300-tick script sleep as though it were
the camera-lock lifetime. That left two false web assumptions: one raw point
per group batch and a transient camera target.

All addresses below are preferred-image addresses for retail 0.72.5 at image
base `0x00400000`, 4,723,200 bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
The canonical read-only Ghidra replica was queried through
`Invoke-GhidraHeadless.ps1`; the exact stock `tutorial.boneyard` remains
33,220 bytes with SHA-256
`97802f2ca45d9bc6f90a497e7c12a55926298161e191fa70eee5e666b90106ed`.

### Native ownership and call census

- `SpawnEnemy 0x00469580` has exactly five direct callers:
  `0x0046BCD0`, `0x0046C790`, `0x0046BB50`, script dispatcher
  `0x00689750`, and `0x0046C710`.
- Full-group helper `0x0046C710` has only the script-dispatcher caller.
  Spawn-N helper `0x0046C790` is called by the dispatcher and
  `Spawner::Tick 0x0046D000`.
- Placement adjustment `0x00463D30` has three xrefs: the shared Arena policy
  owner `0x00466200` and two player-action branches inside `0x0054CC50`.
  The latter are not Tutorial-enemy producers.
- Camera command `0x00464B20` and cleanup command `0x004728B0` each have one
  xref, the authored-script dispatcher `0x00689750`. There is no hidden
  Tutorial unlock caller or second cleanup owner.

`0x00465E40` builds an eligible-player list, consumes the native selection draw
even with one Tutorial participant, then obtains a random unit vector through
`0x00410C50` and adds exactly `100` world units to the selected player root.
`SpawnEnemy` invokes that raw-location path for each requested enemy. It then
temporarily installs Arena policy `+0x8F00`, calls `0x00466200`, and registers
the returned actor.

`0x00463BE0` is the exact policy predicate. Raw instructions at
`0x00463C2E..0x00463C39` show policy 0 accepts a Region light scalar less than
**or equal to** zero; the earlier wording "below zero" was too strict. Policy
1 is strictly greater than zero. Policies 2/3/4 remain off-screen, direct, and
outside-rectangle respectively. `0x00463D30` first accepts a raw point only
when both placement collision and the policy pass, otherwise it searches the
recovered ellipse-compressed rings, with exact Y scale
`0.800000011920929`, fresh starting angle per ring, and the policy-0 fallback
at radius `350`.

Stock has no fence-side or connected-component query in this chain. The
entrance barrier affects ordinary movement collision, but spawn admission is
collision plus policy around the sampled player root. A no-south-side guarantee
is therefore not a hidden stock fence mechanism.

### Complete UID-group placement table

`0x0046C710` copies UIDGroup byte `+0x58` to `DAT_0081985D`, clears the cached
root globals `0x00819864/0x00819868`, then calls `SpawnEnemy` once per ordered
member. Every call still consumes its own raw player/direction draws. When
`+0x58` is zero, every member resolves that fresh raw point independently.
When it is nonzero, the first member's final policy/collision-adjusted root is
cached and later members reuse that final root without another placement
search. The exact serialized Tutorial rows are:

| UID | Name | Ordered members | `+0x58` dword / byte | Final-root behavior |
| ---: | --- | --- | --- | --- |
| 10010 | `FIVE SKELETAL WARRIORS` | 10004 x5 | `0x00000000` / `0x00` | fresh raw and final root per member |
| 10052 | `FIVE ITEM SKELETONS` | 10051 x5 | `0x00000000` / `0x00` | fresh raw and final root per member |
| 10060 | `Archer + Melee Group` | 10059,10059,10004,10004,10004 | `0x00000000` / `0x00` | fresh raw and final root per member |
| 10061 | `Three Archers` | 10059 x3 | `0xCDCDCDCD` / `0xCD` | first final root shared by all three |
| 10078 | `Survive Group` | 10076,10077,10076 | `0x00000000` / `0x00` | selected member owns a fresh root |
| 10086 | `deadly survive group` | 10085,10076 | `0x00000000` / `0x00` | selected member owns a fresh root |

The remaining serialized tail values are also drained: fields `+0x5C/+0x60`
are `0xCDCDCDCD` in all six rows, and `+0x34` is zero in all six. No seventh
group or alternate placement flag exists. The `0xCD` value is file truth from
the retail row; the web projection consumes only its proven nonzero cache
semantics and does not infer author intent from the fill pattern.

### Persistent camera target and delayed cleanup

Trigger 642218 launches script 642219 when the player enters its serialized
rectangle. Command 1065 mode 0 calls `0x00464B20`, which immediately:

1. intersects the authored rectangle
   `(-35.53448486328125,-37.4495849609375,2675.215576171875,887.3675537109375)`
   with the Tutorial Arena;
2. stores target bounds `(0,0,2043,849.91796875)` at
   Arena `+0x8E98..+0x8EA4`;
3. snapshots the live camera endpoints into `+0x8EA8..+0x8EB4`; and
4. stores float32 blend `0.01` at `+0x8EB8`.

Arena tick `0x0046E570` recursively moves all four current endpoints toward
that target, multiplies the blend by exact double `1.01`, and caps it at one.
Nothing in script 642219 unlocks it. Command 1065 mode 1 is the only unlock
branch and has no Tutorial producer.

The following 300-tick sleep belongs solely to command 1066. At expiry,
`0x004728B0` removes out-of-target scenery residents, Roads, compact/decor
records, bridge/spatial records, and related cached geometry, then rebuilds the
affected spatial owners. It does not iterate the Fence manager at `+0x885C`,
the BadGuy actor manager, or the player. The entrance Fence and live enemies
therefore remain; cleanup is not the missing enemy relocation mechanism.

Spawn policy adjustment reads the persistent target at
`+0x8E98..+0x8EA4`. The local camera interpolates toward it until scene
teardown. Save/resume is a Website extension, so it must persist enough lock
age to reconstruct that presentation rather than reinterpret the 300-tick
cleanup countdown as lock duration.

The raw point still has its native collision/policy fast path before target
containment. If a ring search is required, every non-dark candidate must fit
inside the persistent target inset by the actor radius; dark policy alone
bypasses that rectangle. Off-screen evaluation follows the current recursively
interpolated camera, not the cleanup counter.

### 2026-08-26 live-enemy transition correction

The later report that an enemy can remain below the locked camera does not
reveal another map-bounds transition. The instruction ownership above means:

1. entering trigger 642218 immediately starts the persistent camera target;
2. command 1066 later removes only the named static/spatial families;
3. no branch changes player or enemy movement bounds;
4. no branch relocates, retires, damages, or retargets a live Badguy; and
5. the Fence manager and both Gate leaves remain live.

The adjacent Gate contact census now closes the missing hostile branch. Region
callback `0x00646D00` drives a Gate only for actor flag bit `0x1`.
`PlayerWizard` owns flags `0x801`; common Badguy owns flags `0x2` plus movement
exclusion mask `0x80`, which still collides with Gate mask `0x100`. Enemies can
therefore be physically trapped behind a closing leaf but cannot reopen it.
Stock normally avoids the edge through encounter flow; it does not guarantee
recovery after a player deliberately leaves an enemy in the entrance strip.

For the Website, the least invasive soft-lock policy is to keep the full
Tutorial camera active whenever any registered enemy circle or ground Sack
carrier lies outside the future target `(0,0,2043,849.91796875)`. Dying actors
remain members until retirement because the linked Item/Potion Skeleton reward
can create a required Sack at the death root. If an old/live state becomes
unsafe after a lock, suspend that lock immediately; once every enemy and Sack
carrier is inside (or has retired) and the player remains in the authored
trigger, the ordinary lock may start again. While locked, every new Tutorial
birth must also fit wholly inside the target, including native dark-policy fast
paths. This policy preserves enemy movement, Gate/Fence collision, damage,
loot, RNG, and death; it neither teleports nor deletes an actor and is
explicitly a web safety extension.

### Observation and web consequence

A fresh clean process was launched directly from a task-owned retail copy as
PID 14644 at `2026-08-24 17:14:40-04:00`, with an empty copied sandbox, no
loader, and only five loaded modules. The process path was
`C:\Users\User\AppData\Local\Temp\solomon-stock-tutorial-fence-78bdsF\SolomonDark.exe`.
At 1600 x 900, the player crossed the entrance, confronted Solomon, and the
opening ten skeletons materialized on the combat side. The settled capture is
`11-solomon.png`, SHA-256
`86114c009a436722b88afdc2bc2e6aa67c73eb8ed84842036c67e7ab9a024dd8`.
This observation confirms the normal visible result but does not replace the
static conclusion that stock owns no absolute fence-side predicate.

The Website must correct the stock facts first: fresh raw sampling per member,
the exact one-row final-root cache, persistent lock target, recursive camera
age, and delayed-cleanup lifetime. The user-required absolute exclusion of the
spawn strip is then an explicit Website safety rule, not a falsely attributed
native branch: while the exact Tutorial scene is active, every enemy placement
candidate must stay on the combat side of the complete serialized entrance
Fence chain, including across its dynamic Gate gap. Ordinary generated and
custom Boneyards do not inherit that fixed-scene domain.

### Validation receipt

- Fresh read-only replica xrefs close all five `SpawnEnemy` callers, both group
  helpers, all three placement-adjust xrefs, and the single camera/cleanup
  dispatcher owners. Raw instructions confirm policy-0 equality and the
  collision-radius/target-ring call shape. No canonical Ghidra project data
  was modified.
- The exact rebased report on Mod Loader base `6cb56037` passed the complete
  registered Mac static RE suite `500/500`. Log SHA-256 is
  `eed446e35a25d069c98e03a187bc2c8262fb616642b2974cec52b89d70b58512`.
- The stock process was stopped by exact PID after capture. The isolated source
  tree and clean-stock capture directory remain retained because publication
  was not requested; no loader code, runtime patch, push, or deployment was
  performed.

## 2026-08-27 Sirmin wardrobe override

A browser comparison found that the Tutorial wizard inherited the placeholder
Ether Hat/Robe color, making Sirmin purple like Magic Missile. The complete
Tutorial constructor already contained a separate authored wardrobe writer;
the prior controller census stopped after its skill and belt mutations.

`Tutorial_CreateAndInstall 0x005D5CF0` resolves the equipped Hat through
`Game+0x1428` at `0x005D5DA1..0x005D5DA9` and the equipped Robe through
`Game+0x142C` at `0x005D5E0E..0x005D5E16`. Both use common item accessor
`0x00570D80`. For each object the controller constructs exact base RGBA
`(1,0.5,0,1)`, passes luminance factor `0.6000000238418579` from
`0x007854D0` to `0x0040FC60`, and writes the resulting float4 only to the
primary wearable color at item `+0x88..+0x94`.

The transform uses the shared luminance weights
`0.30860000848770142`, `0.6093999743461609`, and
`0.0820000022649765`:

```text
luminance = f32(r*0.3086000085 + g*0.6093999743 + b*0.0820000023)
out.channel = f32(0.6*luminance + 0.4*channel)
```

There is no RNG draw in this override. The starter Hat/Robe selectors remain
zero and their secondary colors remain exact white. Staff material and the
selected Magic Missile element effect are not recolored, so the stock visual
is a tan/orange Sirmin wardrobe with the independent purple Ether effect—the
same split visible in clean capture
`docs/assets/tutorial-stock-20260823/stage-0.png` (SHA-256
`8b43df2d8bcaa5bd9d92894e31cf9dc749d67e4f5fa99ec1bac39c26b286829c`).

This writer runs once when the compiled Tutorial controller is installed and
belongs to the disposable Tutorial player generation. It applies to both Hat
and Robe, every heading/pose/fixed attachment bank that consumes their two
item colors, death presentation until the Tutorial Game ends, mute/audio
branches, and resumed Tutorial snapshots carrying the same live equipment.
It does not recolor Staff, Amulet, rings, NPCs, later College/Create clothing,
or a normal player generation. All members are extractable and no platform
exception remains.

### 2026-08-27 Website validation receipt

Production Mac Chrome reported exact Tutorial Hat/Robe primary tint `0xC4915E`
with white secondary, while the independent Ether effect remained active as
effect 8. The captured wizard is tan under the purple effect, and all page,
console, and failed-response arrays were empty. First College confirmation then
replaced the disposable wardrobe with the selected Air starter appearance.
