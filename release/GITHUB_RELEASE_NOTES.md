# Solomon Dark Multiplayer Beta v0.1.0-beta.20

- FIXED — WAN sessions no longer drop from transport overload: peer-to-peer sends are now paced, coalesced, and backpressured with route recovery, eliminating the beta.19 "connection failed" disconnect under real internet play.
- FIXED — Crash on session close: a game engine Direct3D device-lifetime race (present in the stock game) could crash on teardown or at the menu; the loader now owns the device for the life of the process.
- NEW — Bot roster: Bot Brain now fields up to three bots. Name each one, pick its element (fire, water, earth, air, ether) and discipline (Skirmisher kites and casts; Guardian bodyguards a human player; Striker fights close and flees late). Host controls the roster, changes apply live, and it syncs to every player in the session.
- NEW — Structured mod settings: mods can declare list settings (rosters, tables, schedules); the launcher renders them as add/remove/reorder cards with the same live-apply and host-sync behavior as all settings.
- INTERNAL — Shared list-validation vectors across loader and launcher; transport queue policy + D3D lifetime regression suites.
- The release contains no bundled mods or generated runtime residue.

Download the ZIP. Extract the ZIP. Start `SolomonDarkMultiplayerBeta.exe`.
