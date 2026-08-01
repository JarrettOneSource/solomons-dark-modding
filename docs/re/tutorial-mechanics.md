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
runes`, all-white colors, and one serialized child containing magnitude 10.0.
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
| `+0x9C` | camera/zoom timer, set to 250 during intro |
| `+0xA0` | per-stage one-shot dialogue flag |
| `+0xA4` | dialogue delay (50 initially), later stage-11 counter |
| `+0xAC` | stage-14 callout suppression byte; initialized to zero and not set by the recovered Tutorial path |

[E01:005D5CF0,005D5FE0,005D6330]

Construction removes entry index 1 from a progression-owned list, gives and
selects skill ID `0x48` (Acid Rain) through `0x00660320(..., 0x48, 1)`, writes
current secondary selection at progression `+0x870`, refreshes it through
`0x0065F9A0`, clears two quick slots, and normalizes starting equipment/HUD
slot state. Activation hides inventory, skill, belt, spell, and combat HUD
surfaces; clears their access gates; computes the movement anchor from the
player's starting position; and enables early protection at `Game+0x1CD5`.
[E01:005D5CF0,005D5FE0]

Activation also installs stock narration/presentation context. It sets the
speaker string to `Sirmin`, releases any prior Game-owned narration/portrait
record, and copies the stock tuple rooted at `0x00B3BD08`, `0x00B3BD10`, and
`0x00B3BD14` into `Game+0x1C94/+0x1C9C/+0x1CA0`. It then sets
`0x0081F694 |= 2`, writes `0x00820253 = 1`, and refreshes the global UI object
at `0x0081F630` through virtual `+0xAC`. These are ambient global presentation
side effects and are a **dirty** reuse seam. [E01:005D5FE0]

The 25-tick intro countdown triggers a stock fade/effect at count 20, initializes
a 250-tick camera/zoom lane, fades the Tutorial overlay in/out, and manipulates
the player camera/zoom presentation fields at actor `+0x158/+0x15C`. Only after
that intro byte clears does stage 0 run. Its renderer uses stock full-screen
fade/panel drawing, including UI bundle record `[0x008199E4] + 0x2124` through
the common glyph/sprite path. [E01:005D6330,005D08C0] [E09:005D0A59,
005D0B7E] [E12]

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
| 13 | Skill-screen callouts: resume, quick-use, automatic concentration/new-skill explanation, and hover-for-information; arrows to each | Waits for skills screen close/resume byte `screen+0x98`; starts next wave, enables combat/status HUD at `+0x1AC4`, disables early protection `+0x1CD5`, and -> 15. | Starts wave 4. |
| 15 | none | Waits for enemy count > 2, then rearms dialogue and -> 14. | Ensures wave 4 has materialized before the teaching overlay resumes. |
| 14 | While `+0xAC` remains zero, arrows/callouts to primary attack and concentration icons: `click these icons to change your` / `primary attack or concentration` | If armed, enemies < 4, and player HP < max HP, queues `SAY_LOOKINGBEATUP` once. Enemy count zero starts next wave and -> 16. | Clears wave 4; starts wave 5. |
| 16 | none | Polls first actor type `0x7DD`, stores it at `+0x88`; when present -> 17. | Wave 5 is the single Potion Skeleton; its death link drops a health potion. |
| 17 | world-object arrow | Repeats first-`0x7DD` lookup. When no such actor remains -> 18. | Intended transition is potion pickup/removal. |
| 18 | `DRINK POTION`; dynamic potion key; arrows to potion belt slot and HP display | Recursively counts potion type `0x1B59` through `0x00552A80`; when zero, starts next wave, queues `SAY_FACETHEWRATH` and `SAY_IMBORED`, -> 19. | Starts wave 6 after the health potion is consumed. |
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

The stock screen arrows to spell, inventory, quick-use, equipment, backpack,
skills, concentration, potion, and HP controls all use the same
`0x005C9BB0` pointer primitive as the world-object arrow. UI targets are
resolved from Game-owned widget rectangles, while world targets go through the
camera projection block. There is no separate objective-marker manager or
waypoint actor in the Tutorial path. The reusable marker is the pointer
primitive plus caller-owned target resolution.

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
| narration queue/idle | `0x004FCEC0`, `0x00462090` | global narration owner, existing localization/audio records | dirty/global | mod-owned prompt/audio queue with cancellation and local scope |
| stock speaker/portrait installation | `0x005D5FE0`; Game `+0x1C94/+0x1C9C/+0x1CA0` | global stock asset tuple and narration/UI owners | dirty/global | dialogue speaker/portrait resource owned by the mod prompt session |
| intro fade/camera presentation | `0x005D6330`, `0x005D08C0`; actor `+0x158/+0x15C`; UI record `[0x008199E4]+0x2124` | Tutorial UI object, player presentation fields, global render state | dirty | scoped scene-intro transition/spotlight with save-and-restore |
| linked action on monster death | `0x004819D0 -> 0x0068BB10 -> 0x006894F0` | MonsterRecipe linked Trigger, ScriptThread/TriggerControl alive | clean-ish inside scenario | `on_enemy_death` event -> validated scenario action |
| spawn definition-backed ground item | `0x00469FE0 -> 0x004699B0 -> 0x0046A360` | active Arena, ItemRecipe, resolved location | clean-ish | semantic item-reward spawn returning actor identity |
| spawn health potion | `0x00466B50 -> Arena vslot +0x148 / 0x0046AE20` | active Arena, subtype/location | clean-ish | potion-reward spawn returning actor identity |
| pickup transfer | `0x005E6B50 -> 0x0063E870/0x0055FF20` | ground actor with held item `+0x148`, delay `+0x14C`, valid inventory | dirty to call, clean to observe | item pickup event; do not call tick manually |
| top-level inventory lesson test | enumeration via `0x004027F0`, Game count `+0x13CC` | local inventory root | dirty/broad | inventory query by stable item/recipe identity |
| recursive potion count | `0x00552A80` | inventory root and type `0x1B59` | clean-ish query | `inventory.count({type="potion"})` / event-driven objective |
| wave advance | `0x00465C00` | active Arena and configured wave graph | clean-ish | authority-owned `scenario.start_next_wave()` |
| spawn custom monster/group | `0x00469580`, `0x0046C710`, `0x0046C790` | validated recipe/group/location and Arena | clean-ish | semantic spawn request returning identities |
| enable/delete trigger | `0x00463020`, remote helpers `0x006822E0/0x00682340/0x006823A0` | live TriggerControl and UID | clean inside graph | scenario trigger handle with enable/disable/delete |
| script sleep/loop | command IDs 1002, 1032, 1033 | live ScriptThread | clean | coroutine/timeline primitives |
| level-authored camera lock | command 1065 -> `0x00464B20` | active camera/Arena and serialized region | clean-ish in solo | local-participant camera constraint handle |
| destroy off-camera objects | command 1066 -> `0x004728B0` | active scene/camera ownership | dirty/destructive | no broad public seam; explicit filtered cleanup only |
| XP floor for lesson progression | `0x00680AB0(...,10,1)` in stage 11 | local progression and post-wave idle | dirty as implicit loop | explicit tutorial reward transaction, once |
| unlock/select Acid Rain | `0x00660320(...,0x48,1)`, progression `+0x870`, `0x0065F9A0` | local progression and skill catalog | clean-ish if transactional | validated grant/select API with reversible tutorial loadout |
| force skill selection | command 1058, progression virtual `+0x85C` | local progression and valid skill ID | dirty raw | semantic skill-choice request by stable skill ID |
| gate HUD/input | Game `+0x1AC0..+0x1AC4` plus widget state | Game/UI live and exact paired restoration | dirty raw | scoped participant-local access/visibility masks |
| temporary early protection | Game `+0x1CD5`; consumers `0x0052AC80/0x0052B150` | global Tutorial Game | dirty | explicit protection rule owned by session/participant |
| attach overlay to modal screen | `0x00428160` plus UI-owner virtual `+0xA8` | live UI tree and modal screen | dirty raw | loader overlay layer automatically follows active modal surface |
| first-run prelude | `0x005B6C90`, ControlPicker class | frontend globals, controls bundle, profile gate | dirty | mod settings/onboarding flow with mod-owned persistence |
| completion persistence | `0x005CD3A0`, `0x005CF4F0`, saver `0x005BE0B0` | Tutorial-marked Game and stock profile | dirty | versioned mod-owned completion flag at explicit milestone |

No other objective/waypoint entity, prompt queue, tutorial-only actor factory,
or separate loot-arrow timeout exists in the analyzed Tutorial controller,
trigger graph, item-drop actor, or UI draw chain. The apparent family of
objective arrows is one stock screen-space pointer helper fed by different
caller-owned target calculations.

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
| `0x00414F90` | rotated/transformed sprite draw used by pointer |
| `0x00414540` | common transformed sprite/quad draw |
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
| `0x004FCEC0` | narration queue insertion |
| `0x00508C60` | MapPicker render; handoff only |
| `0x0050C730` | MapPicker constructor; handoff only |
| `0x0050E5E0` | open/attach MapPicker; handoff only |
| `0x0050E980` | MapPicker tick; handoff only |
| `0x00514A20` | Game control callback that invokes MapPicker opener |
| `0x00552A80` | recursive inventory count by item type |
| `0x0055FF20` | inventory insertion used by pickup |
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
| `0x005C9710` | Tutorial primary heading draw |
| `0x005C9960` | Tutorial subheading draw |
| `0x005C9BB0` | pointer angle/blink/stock-arrow draw |
| `0x005C9C70` | Tutorial bordered callout draw |
| `0x005CA480` | Tutorial subheading wrapper |
| `0x005CA560` | Tutorial callout wrapper |
| `0x005CD3A0` | Game destruction path; tutorial gate clear/save |
| `0x005CF4F0` | Game Over path; tutorial gate clear/save |
| `0x005D08C0` | Tutorial render and all teaching overlays |
| `0x005D2520` | Game HUD render consuming `+0x1AC3/+0x1AC4` |
| `0x005D5CF0` | construct/install Tutorial controller |
| `0x005D5FE0` | Tutorial activation/reset and initial gates |
| `0x005D6330` | Tutorial 0..19 stage machine |
| `0x005E6B50` | ground item/Sack tick and pickup transfer |
| `0x0063E870` | ground actor unregister/removal in pickup path |
| `0x00646CB0` | first registered actor by native type |
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
