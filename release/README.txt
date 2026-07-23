SOLOMON DARK MULTIPLAYER BETA
Version {{VERSION}}

ABOUT THIS BETA

This beta adds Steam multiplayer to the original 32-bit Solomon's Dark 0.72.5.
The beta ZIP does not include the game. GitHub releases provide the original
game as a separate optional download named
Solomons-Dark-0.72.5-Original-Game.zip.

Each player needs:

- The complete beta folder
- The original game
- An active Steam account

HOW TO PLAY

1. Extract the entire ZIP to a normal folder.
2. Start Steam.
3. Make sure that your Steam account is active.
4. Start SolomonDarkMultiplayerBeta.exe.
   Installed website mods update automatically. If a launcher update is
   available, the launcher asks before downloading it and restarting.
5. Select the folder that contains the original SolomonDark.exe.
   Bundled mods start disabled; enable only the mods you want in the launcher.
6. Use Choose Save to select one of the launcher's eight local save slots.
7. The host clicks Host Game and selects Friends Only or Public.
   Host Game does not open an invite picker automatically.
8. The host goes to the hub.
9. Select the host's lobby through Steam, the website, or use a Lobby ID.
10. Wait until every wizard is visible in the hub, then start a run.

SAVES

- Launcher saves are separate from the original game's saves.
- The game always uses the selected local slot on disk.
- Link Steam on your SDR website account to enable cloud backups. The launcher
  detects the active linked Steam account automatically.
- Cloud backups run after local save changes and when the game closes. They do
  not replace the local save directory.
- On Steam Deck/Proton, leave the launcher open until the game closes so it can
  copy the staged save back before backing it up.
- Cloud backups are disabled until the Steam account is linked.

STEAM DECK

1. Switch to Desktop Mode and extract the entire beta ZIP into a new folder.
   Do not run the launcher from inside the ZIP or extract a new beta over an
   older beta folder.
2. In Steam, select Add a Game > Add a Non-Steam Game, browse with the file
   type set to All Files, and select the top-level
   SolomonDarkMultiplayerBeta.exe.
   Do not select launcher/SolomonDarkModLauncher.exe; that is an internal
   helper and is not the desktop launcher.
3. Open the shortcut's Properties. Set Target to the top-level EXE, set
   Start In to the extracted beta folder, leave Launch Options empty, and use
   Compatibility to force a Proton 10 or Proton 11 version.
4. Return to Gaming Mode and start the shortcut.

LIMITS

- Multiplayer supports a maximum of four players.
- Host migration is not available.
- All players must use the same beta build.
- Level-ups pause all players until all players select an upgrade.
- After 60 seconds, the host selects an upgrade for each player who did not select one.
- Most combat, upgrades, enemies, drops, equipment, and inventory data synchronize.
- Some inventory, quest reward, and saved data do not synchronize.

Make a copy of important profile data before you play.

PROBLEM SOLVING

- Unsupported game: Select the original Solomon's Dark 0.72.5 folder.
- Steam does not start: Start Steam. Make sure that your Steam account is active.
- Steam Deck Play returns immediately to Play: Confirm that the full beta was
  extracted, the shortcut targets the top-level EXE, and Proton is forced in
  the shortcut's Compatibility settings.
- Missing player: Wait in the hub. If the connection does not recover, close both games.
- After you close both games, start a new lobby.
- The log files are in:
  %LOCALAPPDATA%\SolomonDarkMultiplayerBeta\runtime
- Launcher save slots are in:
  %LOCALAPPDATA%\SolomonDarkMultiplayerBeta\saves
- If the game crashes, the launcher asks before submitting crash diagnostics.
  Submit Logs sends logs, runtime configuration, the enabled-mod list, and any
  minidump to private website storage under your Steam identity. Don't Send
  sends nothing. Saves and Steam credentials are not included.

The launcher does not store or package Steam credentials.
