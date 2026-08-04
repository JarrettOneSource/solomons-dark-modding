# Solomon Dark Multiplayer Beta v0.1.0-beta.32

- When you join a lobby whose mods you don't have, the host now sends them to you directly after you accept the download prompt - no manual install needed. Declining simply cancels the join with nothing downloaded.
- The custom boneyard picker now appears in single player too, not just when hosting. Escape closes it cleanly and falls back to the stock maps instead of also opening the pause menu, boneyard names sit properly centered in the selection bar, and the picker no longer reacts to keys typed into other windows while the game is in the background.
- Items added by mods now actually drop from enemies. Drop chances were being skipped for every naturally spawned enemy, so even guaranteed boss drops never appeared; each enemy death now rolls modded drops exactly once, on stock maps and custom boneyards alike, for every player in the match.
- Bot teammates no longer freeze up mid-fight. A bot that hit exactly 10% mana would stop attacking and spin in place forever; mana recovery now engages at the boundary and the bot keeps fighting, including straight through level-up picks.
- Enemy targeting is now a single decision instead of two fighting authorities. Skeletons pick sensible nearest targets, and distant leftover enemies come to you, so waves advance without hunting the last straggler down.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
