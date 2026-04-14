# Lua Bots

This runtime mod spawns one patrol bot after a run starts:

- `Lua Patrol Bot` (`profile.element_id = 0`, `profile.discipline_id = 2`)

The bot spawns beside the player at run start, then patrols between two fixed
points with a 150-unit gap so movement, facing, walk animation, and the
2-second idle pause at each patrol point can be observed without the noise of
the two-bot follow harness.

Current spawn contract:

```lua
local bot_id = sd.bots.create({
  name = "Lua Patrol Bot",
  profile = {
    element_id = 0,
    discipline_id = 2,
  },
  ready = true,
  position = { x = spawn.x, y = spawn.y },
})
```

Current patrol geometry:

- spawn point `A` = `player position + (50, 0)`
- patrol point `B` = `A + (150, 0)`
- dwell time at each point = `2000 ms`

Enable it with:

- `./dist/launcher/SolomonDarkModLauncher.exe enable-mod sample.lua.bots`

The mod cleans up its named bots on `run.ended`.
