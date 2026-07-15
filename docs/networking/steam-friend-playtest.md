# Steam Friend Playtest

This checkpoint supports friends-only Steam lobbies and carries the multiplayer
protocol over Steam Networking Messages. Multiplayer launches use the Steamworks
Spacewar development AppID (`480`); single-player launches retain the retail
AppID. The launcher stages the x86 Steam runtime and `steam_appid.txt` into its
disposable stage. It never copies or stores Steam credentials.

## What has been verified

- A Release host launch initializes Steam under AppID 480, creates a
  friends-only four-player lobby, publishes protocol/build metadata, and reaches
  `LobbyReady`. The launcher waits for that milestone, returns the real lobby ID,
  and accurately reports whether the overlay invite dialog opened.
- A Release join launch initializes Steam under AppID 480 and reaches
  `WaitingForInvite` without a lobby ID. Redirected CLI launches also return at
  that milestone while the game remains running, which is the path used by the
  desktop UI.
- Protocol v54 statically covers lobby membership checks, host ownership,
  compatibility handshake, authenticated gameplay routing, goodbye/timeout
  cleanup, automatic re-handshake after silent route loss, and no host
  migration.
- The gameplay replication matrix has been exercised with the explicit local
  UDP backend, including player visibility, both player ownership directions,
  all native stat and upgrade entries, level-up choices, late join, Embers,
  Fireball Explode, Air Chaining, deaths, drops, and pickup authority.
- The same-machine two-account Steam run exercised real friend invites twice,
  native character onboarding, shared run entry, full remote wizard bodies,
  movement/animation/status/vitals, the participant inventory ledger, and
  disconnect/rejoin. Disconnect removes the old native proxy and participant
  replication epoch; a fresh revision-1 rejoin replaced an earlier revision-7
  skillbook/statbook instead of inheriting its Chaining rank.
- Every real level-up upgrade row (`8..79`) has been applied and checked in
  both ownership directions (144 owner/observer checks). All 16 native stat
  rows have also been maxed independently on both players, including derived
  values, secondary spell costs, Creativity picker width, Concentrate state,
  and measured mana recovery.
- The focused Steam behavior pass verified Fireball Explode damage and native
  impact playback on both peers, four Embers on both peers with terminal and
  fallback-materialization convergence, and Air Chaining against five victims
  with identical ordered target IDs and source/target endpoints for every
  captured frame.
- The local two-process barrier pass verifies that every player pauses for the
  same level-up cohort, resolved players see the exact remaining-player count,
  all accepted choices apply before resume, and an unresolved player receives a
  host-authored auto-pick after the measured 60-second deadline.
- Accepted client-owned potion pickups now increase the owning client's real
  stock native inventory stack and converge back to the host's participant view
  exactly once.

A genuine cross-account Steam peer handshake has been exercised on this
machine with a Windows host and a WSLg/Proton joiner. The joiner waited without
a lobby ID, accepted the host's friend invite, joined the friends-only lobby,
completed the authenticated compatibility handshake, and entered the shared
run. Two physical PCs remain the recommended final player-environment check,
but they are not required for same-machine development validation.

The latest local structured evidence is:

- `runtime/steam_friend_active_pair_run_stats33.json` — fresh invited pair and
  shared run bootstrap.
- `runtime/steam_friend_active_pair_state_reconnect_final32.json` — active-run
  reconnect, visible native body lanes, status/vitals, derived stats, costs,
  inventory ledger, and revision reset.
- `runtime/steam_friend_spell_behavior_all_post_reconnect_final32.json` —
  Explode, Embers, and strict Air Chaining after reconnect.
- `runtime/steam_friend_active_pair_all_stats_final33.json` — exhaustive fresh
  stat matrix on both Steam owners.
- `runtime/steam_friend_active_pair_all_upgrade_rows_final27.json` plus
  `runtime/steam_friend_active_pair_regenerate_upgrade_final28.json` — all 144
  real upgrade-row ownership checks, including the two level-cap residuals.

These files contain no credentials. Steam and lobby identities are operational
diagnostics and should still be treated as private when sharing raw logs.

For same-machine development, WSLg can provide the required second Steam
process and account boundary. Install a 32-bit-capable Wine environment and a
Proton compatibility tool, sign the Linux Steam client into the second account,
then start its join-wait process from WSL:

```bash
./scripts/Launch-WslSteamMultiplayerClient.sh
```

The script publishes a self-contained win-x86 launcher into `runtime/`, uses an
isolated Spacewar Proton prefix, stages AppID 480, and starts the normal join
flow. Pass the host lobby ID as its only argument to test the direct lobby-ID
fallback. `SDMOD_PROTON_PATH`, `SDMOD_STEAM_API_DLL`, `SDMOD_GAME_DIR`, and
`SDMOD_WSL_STEAM_INSTANCE` override machine-specific defaults. No account name,
password, refresh token, or Steam Guard code is read or copied by the script.

If the WSLg Steam client aborts while cleaning up PulseAudio, restart that
client with audio disabled; multiplayer transport and the Steam UI do not
require it:

```bash
PULSE_SERVER=unix:/dev/null SDL_AUDIODRIVER=dummy ~/.steam/debian-installation/steam.sh
```

## Prerequisites

1. Both players use the same Release checkpoint. Protocol and staged-build
   fingerprints must match exactly.
2. Both players run the Steam desktop client, sign into different accounts, and
   add each other as Steam friends.
3. Both players have the original Solomon Dark 0.72.5 game files and extract
   the same beta ZIP to a normal folder.
4. Release users run `SolomonDarkMultiplayerBeta.exe` directly; no build tools
   or separate .NET runtime are required. Developers building from source use:

   ```powershell
   .\scripts\Build-All.ps1 -Configuration Release
   ```

## Recommended invite flow

The joiner should start the join-wait process before accepting the invite. This
matters while using the shared Spacewar AppID: accepting an invite while no
Solomon Dark process is active can cause Steam to start Valve's Spacewar sample
instead of this development launcher.

1. On the joining PC, open `SolomonDarkMultiplayerBeta.exe` and click
   **Join Friend** with the lobby ID box empty.
2. Wait until Solomon Dark is open. Its runtime should report
   `WaitingForInvite`.
3. On the hosting PC, open the same launcher UI and click
   **Host & Invite Friends**.
4. Wait for the UI to report that the lobby is ready. It fills the
   **Lobby ID (optional)** box with the created lobby ID. If the Steam overlay
   invite panel opens, select the already-waiting friend. If the overlay is
   unavailable, use **Invite to Game** from the Steam Friends window or share
   that lobby ID privately. The host remains in a valid inviteable lobby either
   way.
5. The joiner accepts the invite while their join-wait game is still open.
6. Do not begin the run until both players are visible in the shared hub and
   both runtimes report an authenticated peer.

## Lobby-ID fallback

The launcher UI fills its **Lobby ID (optional)** box once the host reaches
`LobbyReady`. The CLI reports the same value at
`launch.multiplayerSession.lobbyId`, and the host loader log records it after
`Steam multiplayer lobby ready`. Share it privately, enter it on the joining
PC, and click **Join Friend**. A lobby-ID join does not return success until the
host compatibility handshake authenticates.

The equivalent command-line launches are:

```powershell
.\launcher\SolomonDarkModLauncher.exe launch --multiplayer host
.\launcher\SolomonDarkModLauncher.exe launch --multiplayer join --lobby-id <lobby-id>
```

Use `--instance <name>` when preserving separate staged/profile state for
repeatable diagnosis. The launcher profile is isolated from the retail Solomon
Dark APPDATA tree; `--temporary-profile` additionally resets that isolated
profile for a one-off run.

## First two-player checklist

- Both full wizard bodies, staff, and staff orb are visible.
- Movement, heading, HP/MP, death, and revive are visible in both directions.
- Each player casts every base element once. The observer sees the native cast
  animation/effect and the owner pays the matching mana cost.
- Trigger a shared level-up cohort. Every participant pauses and receives a
  picker; after choosing, that player sees `Waiting on N players`. Nobody
  resumes until all choices are accepted. In a timeout check, leave one picker
  untouched for 60 seconds and confirm the host auto-picks before resuming all
  peers.
- Verify Fire Embers and Explode for each owner, including projectile/explosion
  position and terminal status.
- Verify Air Chaining for each owner against at least five targets. Every peer
  should see the same ordered target IDs and arc endpoints.
- Pick up host-authored gold, health/mana orbs, an item, and a potion. Confirm
  one credit only and no client-authored duplicate drop.
- Disconnect the client, rejoin the same still-open host lobby, and verify the
  late-join book/stat/loadout catch-up before casting again. A reconnecting
  client may use **Last Game**; while connected, the loader redirects that safe
  stock menu path into multiplayer character onboarding and then follows the
  host's active run.

## Expected diagnostics

Each stage writes:

- `.sdmod\startup-status.json`
- `.sdmod\multiplayer-session-status.json`
- `.sdmod\stage-report.json`
- `.sdmod\logs\solomondarkmodloader.log`

The structured multiplayer status is bound to the same per-launch token as the
startup status and reports phase, AppID, lobby ID, capacity, authenticated peer
count, overlay/invite state, SDR route/ping, and any terminal error. Healthy
host milestones are `CreatingLobby`, `lobby ready`, then `LobbyReady` (runtime
status `Ready`).
Healthy join milestones are `WaitingForInvite`, `JoiningLobby`,
`Handshaking`, then `Connected`. A protocol version, build fingerprint, AppID,
lobby-owner, capability, or membership mismatch must fail closed instead of
admitting gameplay packets.

Authenticated peers exchange gameplay state continuously. Ten seconds without
an authenticated packet unregisters the stale route; a client still present in
the valid lobby returns to `Handshaking` with a fresh session nonce.

## Current boundary

Inventory/book/loadout rows are replicated as participant-owned state. The
verified potion slice also inserts or stacks a real native potion object in the
owning client's stock inventory. Arbitrary item/equipment insertion, powerup
ownership, and shop/trader transfers are still unfinished; do not treat a
peer-visible row as proof that those stock UI or merchant paths own a native
object yet.

Spacewar AppID 480 is a shared development namespace, not a production product
identity. This public beta deliberately uses it only for development
playtesting; replace it with the project's assigned Steam AppID before a
production release.
