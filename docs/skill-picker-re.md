# Skill Picker Native Path

This note captures the recovered native level-up and skill-picker seams used by
Lua-controlled participants.

## Level-Up Gate

`0x0067C250` is the progression level-up routine. It updates:

- `progression + 0x30`: current level
- `progression + 0x34`: current XP
- `progression + 0x38`: previous XP threshold
- `progression + 0x3C`: next XP threshold
- `progression + 0x44`: pending local skill-pick count
- `progression + 0x70/0x74`: HP/current max
- `progression + 0x7C/0x80`: MP/current max

The routine only increments the pending picker count for local player-style
progressions (`progression + 0x40 == 0`). Non-local/bot progressions can level,
but they do not get native UI pick state.

The loader still snapshots the global pending-picker counter before every
level-up hook. If a non-local progression changes that global value, the hook
restores the exact previous value so bot or remote levels cannot create extra
local skill-picker screens or extend an already pending player picker loop.

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
`0x3F` is visible. The bot path mirrors this by reading the bot's own
progression table before calling the same progression vtable roll method.

`Array<int>` layout:

- `+0x00`: vtable (`0x007848EC`)
- `+0x04`: `int*` values
- `+0x08`: count
- `+0x0C`: flags/metadata word

`0x0040B2D0` clears/frees the array value pointer and resets the count.

## Choice Apply

`0x00671470` is the level-up screen apply handler. For a selected option id it:

1. Reads the option id from the native option array.
2. Optionally maps the id through progression vtable slot `+0x34` for the UI
   side-click alternate.
3. Decrements local pending picker count at `progression + 0x44`.
4. Clears temporary picker fields at `progression + 0x860/+0x864`.
5. Calls `0x00660320 PlayerAppearance_ApplyChoice(progression, choice, 1)`.
6. Applies the same choice a second time only if it matches the screen's rare
   Insight Bonus marker at `screen + 0xFC`.
7. Handles special option `0x34` by marking entry `0x34` active, invoking
   progression vtable slot `+0x9C`, then after refresh invoking slot `+0x94`.
8. Calls `0x0065F9A0 ActorProgressionRefresh(progression)`.

Bots do not use the screen object or the local pending-picker count. They roll
through the same progression vtable `+0x74`, present that rolled option list to
Lua, then apply the selected option with `PlayerAppearance_ApplyChoice` and
`ActorProgressionRefresh` on the bot's own progression object.

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
