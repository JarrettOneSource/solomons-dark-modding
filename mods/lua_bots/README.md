# Lua Bots

This runtime mod spawns one patrol bot after a run starts:

- `Lua Patrol Bot` (`wizard_id = 0`)

The bot spawns beside the player at run start, then patrols between two fixed
points with a 200-unit gap so movement, facing, and walk animation can be
observed without the noise of the two-bot follow harness.

Enable it with:

- `./dist/launcher/SolomonDarkModLauncher.exe enable-mod sample.lua.bots`

The mod cleans up its named bots on `run.ended`.
