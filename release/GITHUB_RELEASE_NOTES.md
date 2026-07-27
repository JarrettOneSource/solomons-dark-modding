# Solomon Dark Multiplayer Beta v0.1.0-beta.19

- NEW — Mod Settings: mods declare settings in manifest.json; the launcher Mods tab gains a per-mod Settings dialog (toggles, sliders, text, dropdowns, key binds, action buttons). Changes apply live to a running game; host-scope settings replicate to clients read-only. Bot Brain ships fully configurable as the first example.
- NEW — Bot Players: the sd.bots Lua API spawns host-controlled synthetic players that occupy a real slot, appear in the member list and ally HUD on every peer, are targeted by enemies, and die/respawn through the standard flows. The opt-in bot.brain mod plays autonomously past wave 5.
- FIXED — Summoned golems/minions now replicate to all players: visibility, animation, HP, death, recast, expiry, and owner-death/disconnect cleanup.
- FIXED — Held-cast sounds (e.g. Frost Jet) now stop immediately on other players' screens when the caster releases.
- FIXED — Client-cast Earth Boulder is now visible to the host; all primary projectiles materialize for observers even when the native replay is missed.
- FIXED — Client-cast Earth Boulder damage was inflated roughly 300x by a replication bug; it now matches stock host-cast values bit-for-bit. Earth feels much weaker now — that is the game's intended balance.
- CHANGED — Enemy HP no longer scales up with player count; multiplayer enemies match solo.
- INTERNAL — Native audio loop registry for diagnosing stuck sounds from Lua; replay-authority hardening (packet-driven observer replays can never mutate replicated enemy HP).
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
