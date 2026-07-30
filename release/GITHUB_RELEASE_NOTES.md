# Solomon Dark Multiplayer Beta v0.1.0-beta.26

- FIXED — After a wave completes, living players are no longer teleported back to spawn. The wave-respawn seam now returns and respawns only dead participants; living participants' positions and state remain untouched.
- FIXED — Steam clients no longer wait behind bulk gameplay traffic to enter the loading screen when the host starts a match. Join-phase run control now has bounded reliable priority under route pressure.
- FIXED — Participant destruction now runs after the stock application tick, and logger, telemetry, and local-UDP workers use process-detach-safe handles, resolving the participant-teardown and process-exit crash paths reported on July 30.
- FIXED — Fresh multiplayer quick-start no longer repeatedly dispatches the stock control-picker action against one retiring UI owner.
- KNOWN BEHAVIOR — Water damage remains the stock value per contact; rapid multi-target, multi-frame contact aggregation can appear as larger single hits.
- Permanent regression coverage now includes the focused two-peer wave-boundary respawn verifier and the hardened real-flow E2E.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
