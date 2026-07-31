# Solomon Dark Multiplayer Beta v0.1.0-beta.28

- NEW — The framework now lets a mod claim the local player's gameplay controls through the same stock control-brain seam used by bots. Claims are owner-scoped and exclusive; release or mod unload clears movement, mouse, bindings, cast intent, and targets before returning full control, and mods can show a local on-screen takeover indicator without adding network state.
- Hardened the full real-flow end-to-end harness and corrected Game Over and fresh-run scoping so stock loading transitions, new run nonces, and isolated verifier instances are handled consistently.
- KNOWN BEHAVIOR — Water damage remains the stock value per contact; rapid multi-target, multi-frame contact aggregation can appear as larger single hits.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
