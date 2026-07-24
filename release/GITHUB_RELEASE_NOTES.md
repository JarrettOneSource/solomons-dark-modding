# Solomon Dark Multiplayer Beta v0.1.0-beta.13

- Hosts can choose a lobby capacity from 2 to Steam's 250-member limit; the default remains four.
- Multiplayer presentation now keeps player names and health bars visible, holds the joining cover until the host character exists, and preserves the stock death, spectator, and respawn flow.
- Players can enter hub rooms independently while the host continues simulating the courtyard, and joining clients no longer duplicate the courtyard Student population.
- Protocol 82 reduces motion traffic, improves interpolation, and adds reliable identity, progression, wave, and authority checkpoints.
- The D3D9 overlay now preserves device state, batches draws, survives device resets, and supports long-path Lua loading and hot reload.
- Quick-start no longer leaves fresh saves hidden behind an opaque cover while the tutorial is already running.
- Normal game shutdown no longer terminates through lingering worker threads. Crash reports now collect the native log, minidump, startup status, and packaged loader version from the paths the loader actually uses.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
