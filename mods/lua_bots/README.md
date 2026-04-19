# Lua Bots

This runtime mod now experiments with a profile-driven participant bot that can
exist in:

- the shared hub
- supported private hub interiors
- runs

The current entrance-driven hub/private policy is:

- the bot does not instantly mirror private-area scene changes
- instead, the Lua policy tries to move the bot to a safe staging point near the
  matching hub entrance before following into a private area
- coordinated run transitions still use the direct participant `run` promotion
- `run.started` now latches a pending run promotion and completes it on the next
  stable `testrun` tick, instead of trying to force the scene update from the
  event callback itself

This runtime mod still spawns one follow bot after a run starts:

- `Lua Patrol Bot` (`profile.element_id = 0`, `profile.discipline_id = 2`)

The bot spawns beside the player at run start, then maintains a follow band
around the player instead of running a patrol graph.

Current spawn contract:

```lua
local bot_id = sd.bots.create({
  name = "Lua Patrol Bot",
  profile = {
    element_id = 0,
    discipline_id = 2,
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

Current same-scene follow behavior:

- spawn point = `player position + (50, 0)`
- stop distance = `50` units from the player
- resume distance = `96` units from the player
- if the bot is already following, it keeps closing until it reaches the
  `50`-unit stop band
- once stopped, it stays put until the player gets farther than `250` units away
- if the player walks into the bot, it does not try to back away
- beyond `96` units, the bot issues a `move_to` toward the nearest point on
  the `50`-unit stand-off ring around the player
- same-scene follow now snaps that ring target to the nearest traversable
  nav-grid sample before issuing the move, instead of trusting coarse cell
  centers or a raw point inside a blocked follow cell

Current spawn/materialization behavior:

- requested bot spawn transforms are sanitized in the DLL against the live
  gameplay path/collision grid before the actor is published
- if the requested point is blocked or off-grid, the loader snaps the bot to the
  nearest traversable cell center instead of materializing it into a wall

Enable it with:

- `./dist/launcher/SolomonDarkModLauncher.exe enable-mod sample.lua.bots`

Current measured entrance targets are documented in:

- [participant-entrance-follow-plan.md](/mnt/c/Users/User/Documents/GitHub/SB%20Modding/Solomon%20Dark/Mod%20Loader/docs/participant-entrance-follow-plan.md)

The mod cleans up its named bots on `run.ended`.
