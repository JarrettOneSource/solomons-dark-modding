SOLOMON DARK MULTIPLAYER BETA
Version 0.1.0-beta.1 | Multiplayer protocol 52

This is an early friends-only co-op beta for the original 32-bit Solomon's Dark
0.72.5. It does not include the game. Every player needs the same beta ZIP, the
same original game version, Steam running, and a separate Steam account.

QUICK START

1. Extract the entire ZIP to a normal folder. Do not run it from inside the ZIP.
2. Start Steam and sign in. Friends must already be friends on Steam.
3. Double-click SolomonDarkMultiplayerBeta.exe.
4. Choose the folder containing the original SolomonDark.exe when prompted.
   The supported executable is Solomon's Dark 0.72.5 with SHA-256:
   03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3
5. The joining player clicks Join Friend FIRST and leaves the lobby ID empty.
6. After the joiner's game is open and waiting, the host clicks
   Host & Invite Friends.
7. The host invites the waiting friend through Steam. If the overlay does not
   open, use Steam Friends > Invite to Game or privately share the lobby ID
   shown by the launcher.
8. Wait until both full wizard bodies are visible in the hub before starting a
   run.

LOBBY-ID FALLBACK

The host's launcher displays a lobby ID after the lobby is ready. The joining
player may paste that ID into the optional Lobby ID box and click Join Friend.

IMPORTANT BETA NOTES

- Multiplayer uses Valve's Spacewar development AppID 480 for testing. Accept
  an invite only while the joining Solomon Dark process is already open;
  otherwise Steam may start the Spacewar sample instead.
- Sessions are trusted-host, friends-only, and currently limited to four
  players. There is no host migration.
- All players must use the exact same beta build. Compatibility mismatches fail
  closed instead of attempting to connect.
- Player bodies, movement, vitals, deaths, spells, skill/stat books, level-up
  upgrades, upgraded spell behavior, enemies, drops, and the verified potion
  inventory path are synchronized. Arbitrary native equipment insertion,
  powerups, and shop/trader ownership are still incomplete.
- Level-up cohorts pause together. After choosing, the UI shows Waiting on N
  players. The host resumes everyone after all choices arrive, or auto-picks
  for an idle player after 60 seconds.
- This is a beta. Back up any save/profile data you care about. The launcher
  uses an isolated mod profile and disposable staged game copy, but bugs remain
  possible.

TROUBLESHOOTING

- "Unsupported executable": choose the original 0.72.5 folder, not the current
  Steam remake.
- Steam lobby/API error: restart Steam normally (not as a different Windows
  privilege level), verify both accounts are online, then retry.
- Invite opens Spacewar: close it, reopen this launcher, have the joiner click
  Join Friend first, and then send/accept the invite again.
- Invisible or stale peer: wait in the hub for authentication. If it does not
  recover, both players close the game and start a fresh lobby.
- Logs and disposable stages are under:
  %LOCALAPPDATA%\SolomonDarkMultiplayerBeta\runtime

The launcher never packages or copies Steam credentials. See
THIRD-PARTY-NOTICES.txt for bundled dependency notices.
