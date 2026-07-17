# Steam lobby privacy and website directory contract

The native loader owns the Steam lobby and peer transport. The website is an
optional directory and password-ticket issuer; it is not in the gameplay data
path.

## Offline invariant

After the launcher starts a host, Steam lobby creation and the invite dialog run
without waiting for the website. Directory publication runs in a detached
best-effort launcher process with a five-second HTTP timeout. Failure to resolve,
connect to, or receive a successful response from the website does not close the
game or Steam lobby.

Steam friends may always join through a host invite. For password-protected
lobbies, immediate Steam friends bypass the website ticket check so the invite
path still works during a website outage.

## Directory viewer authentication

The desktop UI never reads or submits a registry SteamID. It periodically asks
the x86 CLI for a directory session. The CLI initializes Steamworks as Spacewar
(AppID `480`), requests `GetAuthTicketForWebApi` using identity
`solomon-dark-directory-v1`, exchanges the resulting ticket with
`POST /api/auth/steam/session`, then cancels the Steam ticket and shuts the
temporary Steamworks session down.

Only the backend-issued 15-minute bearer token returns to the UI. It is kept in
memory and attached to lobby-list requests. Without that verified token the UI
still receives Public and Private rows, but Friends Only rows stay hidden.

The backend must configure its Steam Web API key as `Steam:WebApiKey` (or the
`Steam__WebApiKey` environment variable). The key is server-only.

## Privacy mapping

| Launcher value | Website token | Steam lobby type | Native admission |
| --- | --- | --- | --- |
| `public` | `public` | Public | Normal compatibility handshake |
| `password` or `private` | `passwordProtected` | Invisible | Matching website ticket, or immediate Steam friend |
| `friends` | `friendsOnly` | Friends Only | Steam friend/invite membership plus compatibility handshake |

Protocol `60` adds a 160-byte join-ticket field to `SessionHelloPacket`. A ticket
is checked by the host only for a password-protected lobby. It is HMAC-SHA256
signed, expires quickly, and is bound to the joining SteamID and lobby ID.

## Host launcher inputs

```text
--multiplayer host
--lobby-privacy public|password|friends
--lobby-password-salt <32 lowercase hex>       # password only
--lobby-password-hash <64 lowercase hex>       # password only
--directory-url <https base URL>
--max-players <2-4>
--boneyard-id <stable id>
--boneyard-name <display name>
--boneyard-sha256 <64 lowercase hex>
--lobby-phase hub|loading|session|results
--lobby-wave <integer>
--lobby-difficulty <text>
--lobby-elapsed-seconds <integer>
--lobby-status-text <text>
```

The default privacy is Friends Only. The default directory is
`https://solomon.genericproject.xyz`. HTTP is accepted only for a loopback
development URL.

Password material is already-derived metadata. The exact contract is
PBKDF2-HMAC-SHA256 over UTF-8 password bytes, 210,000 iterations, a 16-byte
random salt, and a 32-byte result. The launcher never needs the plaintext.

The boneyard and run-status options establish the expected website payload now.
They are launcher-supplied until a live game-state source updates them.

## Join launcher inputs

Direct public/friend join:

```text
SolomonDarkModLauncher.exe launch --multiplayer join --lobby-id <id>
```

Password-authorized join:

```text
SolomonDarkModLauncher.exe launch --multiplayer join --lobby-id <id> --join-ticket <ticket>
```

Offline wait-for-invite mode:

```text
SolomonDarkModLauncher.exe launch --multiplayer join
```

The launcher also accepts `sdr://join/<id>`, an optional `ticket` query value,
and `sdr://wait-for-invite` through its `open-uri` internal path.

## URI registration backend

These commands are intended for a future settings button or installer. They do
not require administrator rights:

```text
SolomonDarkModLauncher.exe protocol register --json
SolomonDarkModLauncher.exe protocol status --json
SolomonDarkModLauncher.exe protocol unregister --json
```

Registration writes `HKCU\Software\Classes\sdr` and points Windows at the
published launcher executable's `open-uri "%1"` command.

## Native status file

The host directory worker watches `.sdmod/multiplayer-session-status.json`. In
addition to the existing transport state, protocol `60` publishes:

```json
{
  "localSteamId": 76561198000000001,
  "personaName": "Luthacus",
  "privacy": "friendsOnly",
  "protocolVersion": 60,
  "manifestSha256": "64 lowercase hex characters",
  "friendSteamIds": [76561198000000002]
}
```

The file remains local. The detached publisher combines it with the launcher
host inputs and sends a heartbeat to `POST /api/lobbies/announce` every 20
seconds. It sends `DELETE /api/lobbies/{lobbyId}` when the game exits cleanly.
