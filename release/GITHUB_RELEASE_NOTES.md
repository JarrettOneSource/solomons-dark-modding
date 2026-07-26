# Solomon Dark Multiplayer Beta v0.1.0-beta.18

- Lightning and Air damage work again in multiplayer, and remote spell damage is no longer lost when a network snapshot arrives after the cast.
- Water and Earth casts now keep their intended aim through native spell dispatch and deal damage correctly for both peers.
- WAN deaths are now reliable: remote corpses always appear with normal lighting instead of a black silhouette, the dropped staff is replicated, and dead-owner HP stays at exactly zero.
- Enemies now re-acquire the nearest surviving player after their current target dies.
- Multiplayer lobbies now survive Game Over. Every peer waits behind the Loading Boneyard barrier and can start another run without rejoining.
- Host spectator controls and the spectator HUD now display correctly. The launcher no longer triggers a Windows Desktop access-denied dialog.
- Release coverage was audited and hardened across 859 automated checks.
- **Known issues:** A Fireball cast by the client occasionally deals no damage; this is under investigation. Earth damage varies strongly with charge hold time, so a tap and a held cast can deal very different damage.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
