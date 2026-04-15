# Lua Bots

This runtime mod spawns one follow bot after a run starts:

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

Current follow behavior:

- spawn point = `player position + (50, 0)`
- stop distance = `50` units from the player
- resume distance = `250` units from the player
- if the bot is already following, it keeps closing until it reaches the
  `50`-unit stop band
- once stopped, it stays put until the player gets farther than `250` units away
- if the player walks into the bot, it does not try to back away
- beyond `250` units, the bot issues a `move_to` toward the nearest point on
  the `50`-unit stand-off ring around the player

Enable it with:

- `./dist/launcher/SolomonDarkModLauncher.exe enable-mod sample.lua.bots`

The mod cleans up its named bots on `run.ended`.
