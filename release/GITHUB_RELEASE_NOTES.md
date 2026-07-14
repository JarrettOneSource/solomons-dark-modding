# Solomon Dark Multiplayer Beta v0.1.0-beta.1

The first public multiplayer beta for the original Solomon Dark 0.72.5.

Download and extract `SolomonDarkMultiplayerBeta-v0.1.0-beta.1.zip`, then run
`SolomonDarkMultiplayerBeta.exe`. Choose the folder containing your original
`SolomonDark.exe`. The game is not included, and the current Steam remake is
not supported.

## Host and join

1. Both players open Steam on separate accounts that are already friends.
2. The joining player opens the launcher and clicks **Join Friend** first.
3. The host clicks **Host & Invite Friends** and sends the Steam invite.
4. The joining player accepts the invite while Solomon Dark is open.
5. Wait until both characters appear in the hub before starting a run.

The host can also share the lobby ID shown by the launcher if the Steam invite
does not arrive.

## What's included

- Friends-only Steam multiplayer for up to four players.
- Synchronized movement, animation, health, death, enemies, drops, and pickups.
- Synchronized stats, skillbooks, loadouts, level-ups, and spell upgrades.
- Shared level-up pauses with a waiting message and a 60-second auto-pick.
- Synchronized Embers, Fireball explosions, Air Chaining, and other upgraded
  spell behavior.
- Complete remote wizard bodies, staffs, and orbs.
- A blank flat boneyard for multiplayer testing.
- Lua 5.4 and the current `sd.*` modding API.

## Known issues

- The host is trusted, and there is no host migration.
- Steam uses the Spacewar development AppID. The joining player should click
  **Join Friend** before accepting the invite so Steam does not open Spacewar.
- Equipment, powerups, and shop or trader ownership are not fully synchronized
  yet. Health and mana potions are synchronized.
- Two separate Windows PCs are recommended for playtesting.

Logs for bug reports are stored under
`%LOCALAPPDATA%\SolomonDarkMultiplayerBeta\runtime`.
