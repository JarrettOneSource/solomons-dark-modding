# Steam Friend Playtest

This checkpoint supports public and friends-only Steam lobbies and carries the
multiplayer protocol over Steam Networking Messages. All launches use Solomon
Dark AppID `3362180`. The launcher stages the x86 Steam runtime and
`steam_appid.txt` into its disposable stage. It never copies or stores Steam
credentials.

## What has been verified

- A Release host launch initializes Steam under AppID 3362180, creates the selected
  public or friends-only four-player lobby, publishes protocol/build metadata,
  and reaches `LobbyReady`. The launcher waits for that milestone, returns the
  real lobby ID, and accurately reports whether the overlay invite dialog
  opened.
- A Release join launch initializes Steam under AppID 3362180, enters the requested
  lobby, and completes the host compatibility handshake. The desktop launcher
  listens for accepted Steam invitations while it is open and launches this
  join path automatically.
- Protocol v65 statically covers lobby membership checks, host ownership,
  compatibility handshake, authenticated gameplay routing, goodbye/timeout
  cleanup, automatic re-handshake after silent route loss, and no host
  migration.
- The gameplay replication matrix now runs through a real two-account Steam
  session: a Windows host and a Proton client, each signed into a different
  Steam account. It covers native onboarding, shared run entry, full wizard and
  staff visuals, stock input ownership, movement/heading correction,
  animation, transient statuses, vitals, death/revive, inventory, progression,
  combat, enemies, drops, scene transitions, and reconnect.
- Every real level-up upgrade row (`8..79`) has been applied and checked in
  both ownership directions (144 owner/observer checks). All 16 native stat
  rows have also been maxed independently on both players, including derived
  values, secondary spell costs, Creativity picker width, Concentrate state,
  and measured mana recovery.
- All 23 native right-click abilities were exercised in both ownership
  directions. Firewalker, Mindstar, and Regenerate persistent behavior also
  passed both ways. Fireball Explode, exactly four Embers, and Air Chaining
  against five victims converged with matching targets, endpoints, positions,
  and terminal state.
- The Steam level-up barrier pauses both players for the same cohort. A player
  who has chosen sees the exact remaining-player count; resume waits for every
  accepted choice, and the host auto-picks for an unresolved player after 60
  seconds.
- Host-authored enemy motion was sampled 240 times, deliberate client drift
  reconciled without ownership leakage, 80 simultaneous enemies converged,
  stale snapshots held their last valid state, and repeated run exit/re-entry
  preserved authority.
- The latest primary-cast stress completed 60/60 real kills, 30 per player. All
  12 naturally generated drops matched between peers. A separate retirement
  soak completed 64/64 client-owned gold pickups without a duplicate credit or
  crash.
- Gold, health and mana orbs, potions, all six tested native equipment classes,
  powerups, Luthacus storage, and Fomentius/Hagatha ownership paths were checked
  through Steam. Exact item recipe, color, equipment identity, participant
  ownership, and visible native remote lanes converge where the stock actor has
  a corresponding visual lane.
- Active-run reconnect removes the old proxy and replication epoch while the
  host run remains alive. A fresh process for the same Steam identity received
  new revision-1 inventory, equipment, spellbook, statbook, gold, and loadout
  state; stale item/equipment identities did not leak into the replacement.
- The explicit flat Boneyard matches on both staged copies and contains no
  scenery, roads, fences, or static collision circles. The embedded Lua runtime
  contract passes on both peers with 10 namespaces and 89 required functions.

A genuine cross-account Steam peer handshake has been exercised on this
machine with a Windows host and a WSLg/Proton joiner. The joiner accepted a
friends-only lobby, completed the authenticated compatibility handshake, and
entered the shared run. Local UDP remains available for deterministic
development, but the release gameplay matrix above was rerun through Steam.
Two physical Windows PCs remain the final player-environment acceptance gate.

The latest local structured evidence is:

- `runtime/steam_friend_v64_primary_kill_stress_r37.json` — 60 bidirectional
  primary kills and 12 naturally generated drops.
- `runtime/steam_friend_v64_native_inventory_sync_r37.json` — stock inventory,
  equipment, potion, orb, gold, and drop materialization.
- `runtime/steam_friend_v64_active_run_reconnect_r38.json` — same-identity
  replacement, fresh revision epoch, and stale-state rejection.
- `runtime/steam_friend_v64_active_pair_state_r39_auto_disable_godmode.json` —
  transforms, animation, transient status, derived stats, inventory boundary,
  and inert-death/revive behavior.
- `runtime/steam_friend_v64_flat_boneyard_r39_flatcorpse.json` — exact staged
  flat fixture, blank world census, and authoritative enemy convergence.
- `runtime/steam_friend_v64_lua_runtime_contract_r38_reconnect.json` — both-peer
  embedded Lua surface contract.

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
isolated Proton prefix, stages AppID 3362180, and starts the normal join
flow. Pass the host lobby ID as its only argument to test a direct lobby-ID
join. `SDMOD_PROTON_PATH`, `SDMOD_STEAM_API_DLL`, `SDMOD_GAME_DIR`, and
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

## Join a lobby

1. The host opens `SolomonDarkMultiplayerBeta.exe`, clicks **Host Game**, and
   chooses **Friends Only** or **Public**.
2. The host picks a loadout and enters the hub.
3. The other player selects the lobby on the website, joins it through Steam,
   or enters its Lobby ID in the launcher.
4. The other player picks a loadout and enters the hub.
5. Do not begin the run until every player is visible in the shared hub and both
   runtimes report an authenticated peer.

## Direct Lobby ID

The host launcher displays its lobby ID after `LobbyReady`. The CLI reports the
same value at `launch.multiplayerSession.lobbyId`, and the host loader log
records it after `Steam multiplayer lobby ready`. Share it privately, paste it
into the joining launcher, and click **Join Lobby ID**. The join does not report
success until the host compatibility handshake authenticates.

The website lists public lobbies and the friends-only lobbies that the signed-in
Steam user can enter. A lobby appears after its host reaches the hub. Its
**Connect** action opens the installed beta launcher and joins that lobby. If
the website is unavailable, join through Steam or use the Lobby ID.

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
owning process inserts or stacks real native potions and exact recipe-backed
equipment in its stock inventory. Hat, robe, staff, wand, ring, and amulet
equipment identity replicates to observers; visible lanes are materialized on
native remote actors. Random Skill, Damage x4, and Bonus Skill powerups are
host-authorized. Luthacus storage and Fomentius/Hagatha merchant actions remain
owner-local stock UI paths whose resulting state replicates to peers. Observer
processes intentionally retain participant rows rather than a second stock
inventory root. Nested sack browsing, the remaining Hagatha catalog, non-shop
quest/reward insertion, and durable cross-session persistence are still open.
