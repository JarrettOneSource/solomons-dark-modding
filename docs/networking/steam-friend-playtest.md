# Steam Friend Playtest

This checkpoint supports friends-only Steam lobbies and carries the multiplayer
protocol over Steam Networking Messages. Multiplayer launches use the Steamworks
Spacewar development AppID (`480`); single-player launches retain the retail
AppID. The launcher stages the x86 Steam runtime and `steam_appid.txt` into its
disposable stage. It never copies or stores Steam credentials.

## What has been verified

- A Release host launch initializes Steam under AppID 480, creates a
  friends-only four-player lobby, publishes protocol/build metadata, and reaches
  `Ready`.
- A Release join launch initializes Steam under AppID 480 and reaches
  `WaitingForInvite` without a lobby ID.
- Protocol v50 statically covers lobby membership checks, host ownership,
  compatibility handshake, authenticated gameplay routing, goodbye/timeout
  cleanup, automatic re-handshake after silent route loss, and no host
  migration.
- The gameplay replication matrix has been exercised with the explicit local
  UDP backend, including player visibility, both player ownership directions,
  all native stat and upgrade entries, level-up choices, late join, Embers,
  Fireball Explode, Air Chaining, deaths, drops, and pickup authority.

A genuine Steam peer handshake still requires two different Steam accounts in
two simultaneously running Steam clients. Use two PCs for the first playtest.
An account switcher changes the account used by one client; it is not process
isolation and cannot prove two live peers on one Windows session.

## Prerequisites

1. Both players use the same Release checkpoint. Protocol and staged-build
   fingerprints must match exactly.
2. Both players run the Steam desktop client, sign into different accounts, and
   add each other as Steam friends.
3. Both players have the Solomon Dark game files and this launcher workspace.
4. Build once on each checkout:

   ```powershell
   .\scripts\Build-All.ps1 -Configuration Release
   ```

## Recommended invite flow

The joiner should start the join-wait process before accepting the invite. This
matters while using the shared Spacewar AppID: accepting an invite while no
Solomon Dark process is active can cause Steam to start Valve's Spacewar sample
instead of this development launcher.

1. On the joining PC, open
   `SolomonDarkModLauncher.UI\bin\Release\net8.0-windows\SolomonDarkModLauncher.UI.exe`
   and click **Join Friend** with the lobby ID box empty.
2. Wait until Solomon Dark is open. Its runtime should report
   `WaitingForInvite`.
3. On the hosting PC, open the same launcher UI and click
   **Host & Invite Friends**.
4. If the Steam overlay invite panel opens, select the already-waiting friend.
   If the overlay is unavailable, use **Invite to Game** from the Steam Friends
   window. The host remains in a valid inviteable lobby either way.
5. The joiner accepts the invite while their join-wait game is still open.
6. Do not begin the run until both players are visible in the shared hub and
   both runtimes report an authenticated peer.

## Lobby-ID fallback

The host lobby ID appears in the host loader log after
`Steam multiplayer lobby ready`. Share it privately, enter it into the launcher's
**Lobby ID (optional)** box on the joining PC, and click **Join Friend**.

The equivalent command-line launches are:

```powershell
.\SolomonDarkModLauncher\bin\Release\net8.0-windows\win-x86\SolomonDarkModLauncher.exe launch --multiplayer host
.\SolomonDarkModLauncher\bin\Release\net8.0-windows\win-x86\SolomonDarkModLauncher.exe launch --multiplayer join --lobby-id <lobby-id>
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
- Level once on each participant. The level-up pause is shared, only the offered
  participant can choose, and both peers see the resulting book/stat/loadout
  revision.
- Verify Fire Embers and Explode for each owner, including projectile/explosion
  position and terminal status.
- Verify Air Chaining for each owner against at least five targets. Every peer
  should see the same ordered target IDs and arc endpoints.
- Pick up host-authored gold, health/mana orbs, an item, and a potion. Confirm
  one credit only and no client-authored duplicate drop.
- Disconnect the client, rejoin the same still-open host lobby, and verify the
  late-join book/stat/loadout catch-up before casting again.

## Expected diagnostics

Each stage writes:

- `.sdmod\startup-status.json`
- `.sdmod\stage-report.json`
- `.sdmod\logs\solomondarkmodloader.log`

Healthy host milestones are `CreatingLobby`, `lobby ready`, then `Ready`.
Healthy join milestones are `WaitingForInvite`, `JoiningLobby`,
`Handshaking`, then `Connected`. A protocol version, build fingerprint, AppID,
lobby-owner, capability, or membership mismatch must fail closed instead of
admitting gameplay packets.

Authenticated peers exchange gameplay state continuously. Ten seconds without
an authenticated packet unregisters the stale route; a client still present in
the valid lobby returns to `Handshaking` with a fresh session nonce.

## Current boundary

Inventory/book/loadout rows and item/potion pickup credits are replicated as
participant-owned state, but arbitrary participant-owned native inventory
objects are not complete. Powerup insertion and shop/trader ownership are also
unfinished. Do not treat a peer-visible ledger row as proof that every stock
inventory UI or merchant path owns a real local native object yet.

Spacewar AppID 480 is a shared development namespace, not a shipping product
identity. Replace it with the project's assigned Steam AppID before distribution.
