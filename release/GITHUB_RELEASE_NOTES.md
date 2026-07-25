# Solomon Dark Multiplayer Beta v0.1.0-beta.17

- Remote Earth casts no longer produce constant or looping boulder sounds. Replicated casts for every element now play their stock audio exactly once per real event.
- The giant black texture labeled "Left" no longer appears while spectating; loader status surfaces now stay diagnostics-only.
- Death animations now finish on every peer, with one consistent five-second death and grace window.
- Spectator cameras keep dying players in view through their full death presentation instead of appearing to teleport the body, and spectator controls no longer appear over newly summoned minions.
- Dead players can no longer cast spells or affect the world; the lockout is enforced by multiplayer authority as well as the local UI.
- A latent x86 hook-decoder bug that could jump into freed memory has been fixed. Run-entry regression testing completed 10/10 runs and 20/20 peer entries with zero crash dumps.
- **Known issue:** Boneyard trees, large rocks, and ground clutter may still differ slightly between host and client. That fix is in progress for the next beta.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
