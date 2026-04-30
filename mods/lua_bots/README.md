# Lua Bots

This runtime mod now experiments with a profile-driven participant bot that can
exist in:

- the shared hub
- supported private hub interiors
- runs

## Layout

- `scripts/main.lua` is a small bootstrap that installs `sd.runtime.require_mod`
  when needed and starts the app module.
- `scripts/lib/app.lua` owns the bot policy, event subscriptions, follow logic,
  combat targeting, and scene transition handling.

The current entrance-driven hub/private policy is:

- the bot does not instantly mirror private-area scene changes
- instead, the Lua policy tries to move the bot to a safe staging point near the
  matching hub entrance before following into a private area
- coordinated run transitions still use the direct participant `run` promotion
- `run.started` now latches a pending run promotion and completes it on the next
  stable `testrun` tick, instead of trying to force the scene update from the
  event callback itself

By default this runtime mod manages the current companion test pair:

- `Lua Bot Fire` (`profile.element_id = 0`, `profile.discipline_id = 1`)
- `Lua Bot Earth` (`profile.element_id = 2`, `profile.discipline_id = 1`)

[`config/active_bots.txt`](config/active_bots.txt) controls the active sample
set. Use `all` there when you intentionally want the full element coverage
harness:

- `Lua Bot Water` (`profile.element_id = 1`, `profile.discipline_id = 1`)
- `Lua Bot Earth` (`profile.element_id = 2`, `profile.discipline_id = 1`)
- `Lua Bot Air` (`profile.element_id = 3`, `profile.discipline_id = 1`)
- `Lua Bot Ether` (`profile.element_id = 4`, `profile.discipline_id = 1`)
- `Lua Bot Fire` (`profile.element_id = 0`, `profile.discipline_id = 1`)

Automation can override the file for one launch by setting
`SDMOD_LUA_BOTS_ACTIVE`. [`scripts/Replay-UiSandbox.ps1`](../../scripts/Replay-UiSandbox.ps1)
does this through `-BotSet`; use `-BotSet default` for the Fire/Earth pair,
`-BotSet all` for the five-element harness, or a comma-separated subset such
as `water,air`.

Each bot maintains a follow band around the player instead of running a patrol
graph.

Current spawn contract:

```lua
local bot_id = sd.bots.create({
  name = "Lua Bot Fire",
  profile = {
    element_id = 0,
    discipline_id = 1,
  },
  scene = {
    kind = "run",
  },
  ready = true,
  position = { x = spawn.x, y = spawn.y },
})
```

Scene intent contract:

- `scene = { kind = "shared_hub" }`
  - participant belongs to the shared hub space
- `scene = { kind = "private_region", region_index = ..., region_type_id = ... }`
  - participant belongs to a specific private hub interior
- `scene = { kind = "run" }`
  - participant belongs to the current run space

If omitted, bot creation now derives a default scene intent from the active
scene:

- hub root -> `shared_hub`
- hub interior -> `private_region`
- `testrun` -> `run`

Current spawn behavior:

- shared hub spawn point = measured hub anchor `(956, 508)` plus each bot's
  configured per-bot spacing offset
- anchored private/hub transitions spawn from the transition anchor plus each
  bot's configured per-bot spacing offset
- run and non-hub fallback spawn point = `player position` plus each bot's
  configured per-bot spacing offset

Current same-scene follow behavior:

- stop distance = `100` units from the player
- resume distance = `250` units from the player
- if the bot is already following, it keeps closing until it reaches its chosen
  follow point inside the roomy follow band
- once stopped, it stays put until the player gets farther than `250` units away
- if the player walks into the bot, it does not try to back away
- beyond `250` units, the bot chooses a random traversable point between
  `100` and `250` units from the player and issues a `move_to`
- same-scene follow now snaps that chosen target to the nearest traversable
  nav-grid sample before issuing the move, instead of trusting coarse cell
  centers or a raw point inside a blocked follow cell

Current primary attack range behavior:

- fire, earth, air, and ether use the squad primary gate of `360` units
- water uses the recovered native frost-cone range instead of the squad gate
- level-1 water has `actor[0x290] = 0`, so the native cone range is
  `205 + 4 * actor[0x290]`, with the bot using a `5`-unit safety margin
- level-1 water passes a `30` degree cone input to the native query, which uses
  it as roughly `+/-15` degrees around the actor heading
- the same native field drives upgraded wider frost behavior when it is present

Current spawn/materialization behavior:

- requested bot spawn transforms are sanitized in the DLL against the live
  gameplay path/collision grid before the actor is published
- if the requested point is blocked or off-grid, the loader snaps the bot to the
  nearest traversable cell center instead of materializing it into a wall

Enable it with:

- `./dist/launcher/SolomonDarkModLauncher.exe enable-mod sample.lua.bots`

Current measured entrance targets are documented in:

- [participant-entrance-follow.md](../../docs/participant-entrance-follow.md)

The mod cleans up its named bots on `run.ended`.
