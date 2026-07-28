# Solomon Dark Multiplayer Beta v0.1.0-beta.22

- FIXED — Enemies spawned after the host character dies now complete the stock hostile-selector success path and keep chasing and attacking surviving players. Authority remains on the host process, while client enemy simulation stays suppressed.
- NEW — Loader support for Lua Bots 1.0.1 adds a one-time AI-style-to-Behavior roster migration, a native Mind/Body/Arcane Discipline loadout for each bot's own skill book, complete element-colored robe/hat/staff/selector initialization and replicated nameplates, and authority-owned stuck recovery after 30 seconds without target or waypoint progress. Recovery uses native circle-placement validation, a cooldown, and explicit logging.
- FIXED — A client who talks to the real Solomon Dig NPC to start waves no longer loses movement after the dialog. The local NPC remains alive until the stock interaction finishes its paired controller restores; wave authority remains on the host.
- FIXED — Replicated damage to the local player now replays the genuine native red overlay, actor reaction, and throttled stock Ouch dispatch exactly once. It is presentation-only and never fires for heals, snapshot reapplies, or damage to another participant.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
