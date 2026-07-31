# Solomon Dark Multiplayer Beta v0.1.0-beta.27

- FIXED — After a Game Over, players are no longer stuck looking dead in the lobby, hub, or next run. Ending a run now fully resets every participant's life, death, vitality, status, combat, and presentation state while preserving their profile and connected session. Within-run corpse rendering and dead-only wave-boundary respawn are unchanged.
- NEW — The launcher now shows staged connection progress from Join, Launch, or Host through mod sync, game staging, lobby connection, handshake, session preparation, world loading, and hub arrival. Real loader errors replace the progress message.
- KNOWN BEHAVIOR — Water damage remains the stock value per contact; rapid multi-target, multi-frame contact aggregation can appear as larger single hits.
- Permanent regression coverage now includes the staggered two-peer Game Over session-semantics verifier while retaining the focused wave-boundary respawn verifier.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
