# Solomon Dark Multiplayer Beta v0.1.0-beta.21

- NEW — One reliable way out of a multiplayer session: Leave Lobby, launcher close, normal game exit, peer departure, and authority loss now share the same teardown path. Hosts send a goodbye and promptly remove public listings; clients can leave and rejoin while the host keeps playing. The loader also suppresses the stock game's close-URL action in memory without modifying the retail executable.
- NEW — Website mod links can install or update a specific mod through `solomondarkrevived://install-mod/{slug}`. The launcher validates the exact link shape, shows consent before downloading, and installs atomically.
- FIXED — Remote players and Lua bots now use the native player locomotion path, restoring collision presence, movement stepping, spatial rebinding, and footsteps.
- NEW — The game now presents a D3D9 loading screen with owner art, real monotonic stage labels, and a short reveal gate while entering matches, Boneyards, single-player runs, and every multiplayer join stage including Connecting to match. The desktop launcher deliberately stays plain during join preview, consent, and mod sync.
- NEW — Lua bots are full lobby members and share the native four-seat capacity with humans. Both peers see BOT roster chips and `isBot` membership data; bot spawns use native circle-placement validation with bounded outward search and pending-position reservation.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
