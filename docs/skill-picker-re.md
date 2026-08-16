# Skill Picker Native Path

This note captures the recovered native level-up and skill-picker seams used by
Lua-controlled participants.

This is the level-up option picker. It is not the `Select a Spell` acquisition
dialog and it does not assign runtime primary or belt inputs. See
`spell-picker-re.md` for that separate native surface boundary.

## Evidence Receipt

This report targets the retail Beta 0.72.5 executable at
`SolomonDarkAbandonware/SolomonDark.exe`, PE32 preferred base `0x00400000`,
size `4,723,200`, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
The function addresses below are preferred-image virtual addresses recovered
from the read-only Ghidra project for that exact executable. The settled stock
screen witness remains
`tests/fixtures/webgame/menu-reference-captures/skill-picker.png`.

The shipped authored-script membership was also swept with
`tools/decode_boneyard_scripts.py`. Of the six shipped `.boneyard` scene
files, only Story 0 owns `LEVEL UP` triggers: UID 57029 applies action 1090
`MODIFY XP ACCUMULATION` with operand `25.0`, and UID 57098 applies the same
action with operand `30.0` when the player is level 3. Those one-shot global
triggers modify Story XP accumulation; they do not create the level-up sound,
sparkles, light, curtain, or picker.

## Level-Up Gate

`0x0067C250` is the native level-up routine. It updates:

- `progression + 0x30`: current level
- `progression + 0x34`: current XP
- `progression + 0x38`: previous XP threshold
- `progression + 0x3C`: next XP threshold
- `progression + 0x40`: local/non-local progression mode (`0` is local
  player-style, nonzero skips local picker UI)
- `progression + 0x44`: pending local skill-pick count
- `progression + 0x70/0x74`: HP/current max
- `progression + 0x7C/0x80`: MP/current max

The routine only increments the pending picker count for local player-style
progressions (`progression + 0x40 == 0`). Non-local/bot progressions can level,
but they do not get native UI pick state.

The base progression constructor initializes `progression + 0x40` to local
player-style mode. Bot-owned progressions are marked non-local through `progression + 0x40`
when the loader materializes them, and the bot level-sync path verifies that
mode before entering native `level_up`. That keeps the bot on the native
level/threshold path without allocating the local player level-up screen object
at `progression + 0x83C`.

The loader still snapshots the global pending-picker counter before every
level-up hook. If a non-local progression changes that global value, the hook
restores the exact previous value so bot or remote levels cannot create extra
local skill-picker screens or extend an already pending player picker loop.

Bots call the same native `level_up` routine when syncing to the shared player
level. The loader stages the bot's current XP from the live source progression
or debug-sync request, then lets `0x0067C250` advance the bot progression's
level and threshold fields. This path does not write progression level, HP, max HP, MP, or max MP directly. HP/MP limit changes remain owned by the native
skill-choice apply and refresh path below.

## Threshold Presentation and Picker Reveal

The local threshold transition and the picker are adjacent but separately
owned native systems:

1. `0x0067C250` consumes every crossed threshold, refills HP/MP, and queues
   the local choices. After the threshold loop it calls trigger fanout
   `0x0068BA90(13)`, creates the picker through `0x0065F480(0)`, and tail-calls
   `0x005C88B0` exactly once.
2. `0x005C88B0` always calls `0x00528A20` for the local PlayerActor. A second
   `0x0052A220` branch runs only when progression flags `+0x878 & 0x400` are
   set; it is an actor-associated bonus-light branch, not the ordinary
   threshold effect.
3. `0x00528A20` writes float `180.0` to PlayerActor `+0x168`, then dispatches
   sound-registry member `+0x908`, entry 52 `sounds\levelup`, once at scalar
   `1.0` (`0x00528A3E`). The old attribution of calls `0x00647F6B` and
   `0x00647FBE` to level-up was wrong: their only caller is skill 77 Turn
   Undead (`0x00647EF0`), where they request the same asset at pitches 2 and 3
   before applying the undead flee/weaken effect.
4. Player tick `0x00533520` enters the effect branch while `+0x168` is
   positive, subtracts exactly `1.0`, and, when the player is in the visible
   viewport, creates one `Anim_Sparkle` (`0x00453980`) from exact
   BadGuys record 73. Starting from 180, the branch therefore emits 180
   sparkles over 180 ticks / 1.8 s; the emitter values used by those births run from 179
   through 0.
5. Each sparkle is constructed with timer 180, decay 3, and a fixed
   `RandomFloat(360, false)` angle. Player tick then adds
   `RandomFloat(2, false)` to the decay, so individual particles survive
   36--60 ticks, not one fixed 60-tick lifetime. For a player whose world Y is
   `playerY` and whose viewport top is `world + 0x8BD0`, the exact birth
   offsets are
   `x = RandomFloat(30, true)` and
   `y = -20 - RandomFloat(playerY - viewportTop, false)`. Particle tick
   `0x00453A30` subtracts that fixed decay from the timer and moves Y by
   `-0.1` per tick; the angle does not advance. Render `0x00458230` uses
   `sin(particleTimer degrees)` as uniform scale. Birth alpha is fixed at
   `(1 - abs(x) / 30) * sin(emitterTimer degrees) * 0.75`; there is no
   independent random-alpha multiplier.
   The calls consume the active gameplay RNG in this exact five-word order:
   unsigned Y magnitude, signed-X magnitude, signed-X sign, unsigned angle,
   then unsigned decay. Each magnitude uses the stock float primitive's
   closed endpoint domain and intermediate float32 stores: integer sample
   `k` from bound 100001, `f32(f32(f32(k) / 100000) * magnitude)`. The X sign
   is chosen by the second word's bit 6. Thus `x = -30`, `x = +30`, angle
   `360`, and decay `5` are all reachable; treating signed X as one draw or
   using a half-open browser random changes both the distribution and later
   stream membership.
6. Player light submission `0x005299A0` observes the same `+0x168` timer. Its
   stored region-light record is still the ordinary heading-offset player
   source with intensity 1 and flag 1, but its radius is
   `(actor[+0x268] + 1) * 2.6 + sin(timer degrees)`. The separate immediate
   draw-helper argument `2.6 - RandomFloat(0.2, false)` is not stored as the
   region-light radius. The Website's ordinary player source models the
   baseline `actor[+0x268] == 0` lane, so the threshold variation replaces
   radius 2.6 with `2.6 + sin(timer degrees)` rather than adding a second
   player light. The sparkle and light belong to the PlayerActor, not to
   `LevelupScreen`.

This means one large XP grant which crosses several levels plays one ordinary
level-up sound and arms one 1.8-second actor effect, even though it queues
several choices. Rebuilding the next queued offer must not replay the threshold
sound/effect. Forced picker action `0x0067C320` increments pending choices and
opens a screen with build delay 10 and forced flag `+0x624 = 1`; it does not
call `0x005C88B0` and therefore does not synthesize a level transition.

`LevelupScreen` construction at `0x00658620` initializes reveal alpha
`screen + 0x100` to `0` and direction `screen + 0x104` to `+1`. Tick/build
`0x0066F920` clamps
`alpha + direction * 0.025` to `[0,1]`; the opening reveal is therefore 40
ticks / 0.4 s at 100 Hz. Apply input at `0x00671470` is gated until alpha is
exactly 1. Render `0x0067DF80` owns the screen-space presentation:

- full-viewport black alpha is `0.5 * revealAlpha`;
- the ambient ring/arc family uses `0.1 * revealAlpha`;
- the panel/content lane uses `revealAlpha^3` before reaching its settled
  geometry.

The complete screen-owned sound sequence is distinct from the PlayerActor
threshold request:

- When the screen's one-tick constructor delay reaches zero, `0x0066FAA4`
  requests registry member `+0xB18`, entry 64 `sounds\openpanel`, at gain 1
  and pitch 1.
- Merely changing the active `UiRect` does not dispatch audio. This includes
  pointer hover and any non-native keyboard/gamepad focus graph supplied by a
  port.
- Activating a skill card requests member `+0x44`, entry 1
  `sounds\pickskill`, at `0x00671635`, gain 1 and pitch 1.
- Starting any close from settled alpha requests `sounds\openpanel` again at
  `0x00670D35`, this time with gain 1 and pitch `0.75`. Card selection sets
  close direction to `-0.75`; the save action uses `-1`.
- When a closing screen reaches zero alpha and another pending choice remains,
  `0x00670C9D..0x00670CC4` restores reveal alpha/direction to `1`, writes ten
  ticks to build delay `+0x78`, and sets hidden-content byte `+0x604`. The
  branch then requests member `+0x11A0`, entry 102 `sounds\unlockskill`, at
  `0x00670CD3`. Render `0x0067DF80` tests `+0x604` at `0x0067EAC1` and skips
  the offer/control content while it is set. On the delay's `1 -> 0`
  transition, the builder replaces the options, clears `+0x604` at
  `0x0066FCE4`, and exposes the next offer settled. This is a 10-tick blank
  rebuild handoff, not a second 40-tick reveal and not an immediate card swap.

Entry 53 `sounds\levelupskill` is loaded but no retail dispatch was found.
None of these screen sounds substitutes for the PlayerActor-owned entry-52
threshold request.

## Sorceror's Charm Actions

The previous conclusion that stock had no reroll or deferred choice was
incorrect. It came from tracing only the card loop in `0x00671470`. A complete
active-`UiRect` sweep exposes two sibling actions, both rendered only while
`progression + 0x839` is nonzero.

`progression + 0x7CC + selector` is the durable Hagatha ownership byte span,
so selector 17 `SORCEROR'S CHARM` is exactly `progression + 0x7DD`.
Normal screen creation `0x0065F480(0)` clears `+0x839`, then grants one action
when `+0x7DD != 0`. A queued-offer rebuild grants it again. Either side action
or a card selection clears `+0x839`, so one displayed offer cannot use both
actions and cannot reroll twice.

The right sibling `UiRect` is `screen + 0x540`. Activation at `0x006714D9`:

1. replaces the actor-private offer seed `progression + 0x834` with
   `RandomInt(1_000_000)` from the active gameplay stream;
2. clears the current-offer action byte `+0x839`;
3. requests registry member `+0x1014`, entry 93 `sounds\summon`, at
   `0x00671532`, gain 1 and pitch `0.8`; and
4. sets the screen rebuild delay to two ticks without decrementing pending
   choices. It does not set hidden-content byte `+0x604`, so the old offer
   remains drawn during those two ticks before the replacement is built.

The left sibling `UiRect` is `screen + 0x48C`. Activation at `0x00671546`:

1. requests member `+0x18`, entry 0 `sounds\click`, at `0x00671568`;
2. starts a close at direction `-1`;
3. clears `+0x839` and the screen-active byte `+0x838`;
4. decrements current pending choices at `progression + 0x44`; and
5. increments deferred choices at `progression + 0x48`.

The next call to `0x0065F480` adds all deferred choices back into `+0x44` and
clears `+0x48` before creating the screen. This is the stock **SAVE SKILL**
meaning behind the charm description "preserves the reroll for later": it
defers this unresolved skill choice until a later level-up screen, where the
owned charm grants a fresh one-use reroll action.

Tick/build `0x0066F920` also establishes the settled side-control hit boxes.
For `n` cards, `panelWidth = n * 200 + 60`; both rectangles are 255 by 100 at
`y = 450 - 177.5 + 50 = 322.5`. SAVE SKILL begins at
`x = 800 - panelWidth / 2 - 140`; ROLL AGAIN begins at
`x = 800 + panelWidth / 2 + 40`. Render `0x0067DF80` draws authored UI
record 57 at the SAVE SKILL rectangle and record 56 at ROLL AGAIN. These are native
atlas members and interaction regions, not replacement HTML labels.

The screen renderer draws a translucent curtain over the already rendered
world and does not contain a selective enemy/effect visibility branch. The
stock actor-world pause holds non-player actor clocks while PlayerActor ticks
continue, which lets the local sparkle/light advance beneath the picker. A web
renderer that additionally suppresses paused non-local actors, enemy
projectiles, primary spells, and transient effects during the modal is a
browser presentation policy, not a recovered native field write. It must keep
that policy separate from the proven curtain timing and preserve scenery, the
local player, its level-up effect, and the fixed HUD.

## Option Roll

`0x0066F920` is the level-up screen tick/build path. Once the reveal timer
finishes, it clears the screen option arrays and calls the progression virtual
method at vtable slot `+0x74`:

```c
progression->vtable[0x74 / 4](progression, desired_count, &screen->options);
```

The screen constructor at `0x00658620` initializes `desired_count` to `3` and
stores the native `Array<int>` option list at screen offset `+0x8C`.

`0x0065F480` creates the level-up screen when `progression + 0x44` has pending
picks. After construction it checks progression entry `0x3F`:

```c
if (*(short *)(progression->table + (0x3F * 0x70) + 0x22) > 0) {
    screen->desired_count = 4;
}
```

So the native choice count is normally `3`, but rises to `4` when skill/entry
`0x3F` is visible. The bot path mirrors this by reading
`[gameplay.skill_choices].bonus_choice_count_skill_id` from
`config/binary-layout.ini`, checking the bot's own progression table, and then
calling the same progression vtable roll method.

`Array<int>` layout:

- `+0x00`: vtable (`0x007848EC`)
- `+0x04`: `int*` values
- `+0x08`: count
- `+0x0C`: flags/metadata word

`0x0040B2D0` clears/frees the array value pointer and resets the count.

The build path consumes each rolled option immediately: at `0x0066FDF2` it
loads the option id from `screen + 0x90 + index * 4`, then calls `0x00657C00`
to resolve the name/icon payload. The return address after that call is
`0x0066FE0E`. Replacing only the screen array on a later multiplayer tick is
therefore too late: selection reports authoritative ids, but the visible
children still describe the discarded local random roll.

For a host-authored local offer, the loader arms the exact local progression
and offer before creating the screen. A hook on progression vtable slot `+0x74`
lets the native roll allocate its normal `Array<int>`, then replaces those ids
with the authoritative offer before control returns to `0x0066F920`. Names,
icons, and selection consequently share one option list. The hook is removed
when the local transport shuts down.

### Concentrated Creativity and Insight

The screen constructor initializes `screen + 0xFC` to `-1`; this field is
the skill ID that will receive the rare Insight Bonus. Immediately after the
normal option roll, `0x0066F920` reads concentration collection
`0x00819E70` at index `16`. Only selected skill `63` (Creativity) enters
the branch. The timed all-concentration field at progression `+0x828` is not
consulted by this picker path.

The chance is exactly:

```c
if (concentration[16] == 63 && RandomInt(5) == 1) {
    // build Insight candidate list
}
```

This is one successful value among `0..4`, matching the advertised 20%.
Each displayed option is admitted only when:

- progression vtable `+0x30(option_id)` is false, or the option already has a
  nonzero effective rank at skill-row `+0x22`; and
- that effective rank is less than the compiled maximum recovered from the
  row property table, minus two.

The game chooses one candidate randomly and stores its option ID at
`screen + 0xFC`. No candidate leaves the field at `-1`. The binary contains
an apparent typo while filtering: it compares the loop *index* to `0x34`,
not the option ID. Since this screen displays only three or four options, that
comparison cannot exclude Spell Welding.

## Choice Apply

`0x00671470` is the level-up screen apply handler. After the two Sorceror's
Charm sibling branches above, its card loop handles a selected option id:

1. Reads the option id from the native option array.
2. Optionally maps the id through progression vtable slot `+0x34` for the UI
   side-click alternate.
3. Decrements local pending picker count at `progression + 0x44`.
4. Clears temporary picker fields at `progression + 0x860/+0x864`.
5. Calls `0x00660320 PlayerAppearance_ApplyChoice(progression, choice, 1)`.
6. Applies the same choice a second time only if it matches the concentrated
   Creativity Insight ID at `screen + 0xFC`.
7. Handles special option `0x34` by marking entry `0x34` active, invoking
   progression vtable slot `+0x9C`, then after refresh invoking slot `+0x94`.
8. Calls `0x0065F9A0 ActorProgressionRefresh(progression)`.

Bots do not use the screen object or the local pending-picker count. They roll
through the same progression vtable `+0x74`, present that rolled option list to
Lua, then apply the selected option with `PlayerAppearance_ApplyChoice` and
`ActorProgressionRefresh` on the bot's own progression object.

Multiplayer native clients use the same non-local guard for host-authored
shared level-ups. A connected non-host suppresses its own local picker/event,
accepts a host `LevelUpOffer`, and applies only the host-confirmed
`LevelUpChoiceResult`. The host rolls the options through each participant's
materialized progression/book state and rejects returned choices that were not
part of the issued offer.

## Synchronized World Pause

`0x004022A0` is the common `ActorWorld::Tick` dispatcher. Its actor-list ABI is:

- `world + 0x08`: actor count
- `world + 0x14`: actor pointer array
- `world + 0x48`: actor currently being dispatched
- `actor + 0x04`: pending-initialize byte
- `actor + 0x05`: pending-remove byte
- actor vtable `+0x04`: initialize method
- actor vtable `+0x08`: tick method

The virtual tick call returns at `0x00402348`. A live trace of a skeleton
resolved its vtable tick to stock address `0x00484B90`, while a PlayerActor
resolves to `0x00548B00`.

While a multiplayer level-up cohort is unresolved, the loader detours
`ActorWorld::Tick` and dispatches only actors whose virtual tick is the
PlayerActor tick. This keeps the existing PlayerActor hook pumping transport,
Lua, picker UI, and forced-choice cleanup, but holds enemies, projectiles,
pickups, and effects. Once every participant confirms its choice, the stock
actor-world dispatcher resumes on the next frame.

## Regression Harness

Run the live bot skill-choice regression with:

```sh
python3 tools/test_bot_skill_choice_regression.py --iterations 20
```

The harness launches a fresh loader game, enters a test run, disables autonomous
bot ticks, forces shared level-up events, rolls bot options through the native
progression picker, chooses one option per bot per level, then validates:

- every presented option resolves to a skill name and source `wizardskills/*.cfg`
- selected option metadata matches the option actually applied
- the bonus choice-count path can expose four options
- option pools evolve across repeated levels
- selected skills mutate native progression entry/stat state, unless the native
  entry was already maxed and is expected to no-op
- `HEALTH UP` / `MANA UP` selections produce the corresponding HP/MP stat diffs
- bot loadout before/after snapshots are present for every application

The full result is written to `runtime/test_bot_skill_choice_regression.json`.
Use `--from-report runtime/probe_bot_skill_choice_stress.json` to validate a
previous stress report without launching the game again.

Run the multiplayer visual-identity regression with:

```sh
python3 tools/verify_multiplayer_skill_picker_visual_identity.py
```

It traces `0x00657C00` calls returning to `0x0066FE0E`, compares the option ids
used by the native visual builder with the host offer and pinned picker array,
then accepts the first option and verifies that the same id is applied and the
native picker closes on both peers.

Run the complete multiplayer level-up barrier regression with:

```sh
PYTHONPATH=tools python3 tools/verify_multiplayer_level_up_barrier_sync.py
```

It proves an unfrozen stock skeleton moves before the barrier, remains fixed
while the host waits on an unresolved client, and moves again after resume. It
also waits for the real 60-second timeout and requires the forced client choice
to apply exactly once, close both native pickers, and release the shared pause.
