# Local UDP join bypassed host-mod consent

## Symptom

With a fresh local-multiplayer client and a host advertising downloadable mods,
clicking **Join Game** downloaded the host's mods and launched the game without
showing the **The host has mods** consent prompt.

The live directory trace showed the join preview resolving both packages and
the package downloads beginning immediately afterward. The client started with
no installed mods, so the no-download path did not apply.

## Root cause

`MainWindowViewModel.ExecuteLobbyPrimaryAction` special-cased
`SDMOD_MULTIPLAYER_TRANSPORT=local_udp` and invoked `LaunchSteamJoin` directly.
That skipped `JoinLobbyWithModCheckAsync`, which is the only path that performs
the join preview and opens the host-mod download prompt. The direct launch then
ran normal host-mod synchronization inside the launcher command, so downloads
were verified but never consent-gated.

This was a launcher flow error, not a directory or cache issue. Local transport
still rides the same website mod-discovery contract as Steam and must not bypass
the player's download decision.

## Resolution

All initial Join Game actions now run the same join-preview path. After the
player accepts and the website packages are prepared, local UDP launches
directly; Steam continues into explicit lobby membership. A launcher contract
locks both routing decisions.
