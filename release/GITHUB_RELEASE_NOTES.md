# Solomon Dark Multiplayer Beta v0.1.0-beta.1

This is the first public friends-only co-op beta. It is meant for development
playtesting, not a production release.

Download `SolomonDarkMultiplayerBeta-v0.1.0-beta.1.zip`, verify it against
`SHA256SUMS.txt`, extract the whole ZIP, and run
`SolomonDarkMultiplayerBeta.exe`. Each player must choose their own original
Solomon Dark 0.72.5 folder. The game itself is not included, and the current
Steam remake is not compatible.

## Host and join

1. Both players start Steam and sign into separate accounts that are already
   Steam friends.
2. The joining player opens the launcher and clicks **Join Friend** first,
   leaving Lobby ID empty.
3. After the joiner's game is open, the host clicks
   **Host & Invite Friends** and sends the Steam invite.
4. The joiner accepts while their Solomon Dark process is still open. A lobby
   ID shown by the host can be shared privately as a fallback.
5. Wait until both complete wizard bodies are visible in the hub before the
   host begins the run.

## Included in this beta

- Friends-only Steam lobbies and gameplay transport through Steam Networking
  Messages under the Spacewar development AppID 480.
- Host-authoritative run, enemy, damage, death, drop, pickup, vitals, status,
  and position state with interpolation and correction for remote players.
- Full participant stat, skillbook, statbook, spellbook, loadout, and level-up
  upgrade replication in both ownership directions.
- A synchronized level-up barrier: everyone pauses together, resolved players
  see `Waiting on N players`, and the host resumes after all choices or a
  60-second auto-pick.
- Networked upgraded spell behavior, including Fireball Embers/Explode and Air
  Chaining target/endpoint state.
- Visible remote wizard bodies, staff/orb presentation, movement, animation,
  death/revive, and reconnect/late-join catch-up.
- A blank flat boneyard fixture for deterministic multiplayer testing.
- Rush repaired and verified through real keyboard input for host- and
  client-owned players. Max-rank movement matched the live native acceleration,
  cap, and damping model in both directions.
- Embedded Lua 5.4 support and the current `sd.*` runtime API.

## Known beta limits

- Trusted-host sessions, four-player capacity, and no host migration.
- Spacewar 480 is a shared development identity. Accept invites only after the
  joiner has clicked **Join Friend**, or Steam may launch its Spacewar sample.
- Arbitrary participant-owned native equipment insertion, powerups, and
  shop/trader transfers remain incomplete. The health/mana potion insertion
  slice is the currently verified native inventory path.
- Two physical Windows PCs are the recommended player-environment test even
  though the two-account Windows/WSL Steam flow has completed an authenticated
  gameplay session on the development machine.
- This beta supports only the original 0.72.5 `SolomonDark.exe` with SHA-256
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

Please include both players' launcher transcript and the relevant logs under
`%LOCALAPPDATA%\SolomonDarkMultiplayerBeta\runtime` when reporting a problem.
