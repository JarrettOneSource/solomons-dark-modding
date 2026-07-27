# QoL backend ownership and close-path design

This note records the backend choices for the owner's issue #68 list. The
implementation deliberately has one session-end coordinator even though the
underlying resources have two owners.

## Session teardown ownership

The loader owns the live Steam lobby, Steam Networking Messages sessions, and
the local-UDP gameplay transport. The launcher CLI's
`LobbyDirectoryPublisher` sidecar owns website announce, heartbeat, and delist.
That split already existed because the sidecar has the directory credential
and the loader has the live Steam handles.

`multiplayer_session_teardown.cpp` is now the canonical session-end
coordinator. Explicit launcher leave, launcher-window close, normal game exit,
a clean remote host close, and loss of the session authority all enter this
coordinator. It selects `LobbyClosed` for a host and `Leaving` for a client,
then asks both configured transport providers to close through their shared
teardown APIs.

For a host, the coordinator also atomically writes
`.sdmod/session-teardown-{launchToken}.request.json`. The publisher stops
heartbeats as soon as it sees that request, sends `DELETE /api/lobbies/{id}`,
and atomically writes the matching completion record. The loader waits up to
three seconds for that completion before closing the game. The publisher's
ordinary process-exit delist remains a second attempt for normal exits, while
the website TTL remains a crash-only backstop.

Steam sends an authenticated reliable session-goodbye, marks a hosted lobby
non-joinable, and holds the message session open for a 150 ms delivery grace
before leaving the lobby, closing peer networking sessions, and clearing rich
presence. Local UDP sends the same semantic goodbye three times over that
150 ms window before closing its socket. A client goodbye removes only that
participant on the host. A host goodbye tells every client that the host
closed the lobby and starts their graceful local close instead of waiting for
the peer timeout.

Local UDP now publishes the same launch-token-bound
`multiplayer-session-status.json` contract as Steam. That keeps the real WPF
roster, Leave Lobby state, and clean-close message attached to the staged
process instead of inventing a launcher-only test state. Each staged instance
also receives its own `SolomonDarkModLoader_LuaExec_{instance}` pipe name.
For the explicit local-UDP development transport, Join Game goes directly
through the launch command because there is no Steam lobby membership step to
perform. Steam launches retain the existing pre-membership flow.

The hidden `sd.__session_leave()` function is installed only while the
launcher exec request is evaluated. It returns `{ok, error}` through the
existing Lua-result encoding. The pipe writes and flushes the standard JSON
response before changing the coordinator from `AwaitingResponse` to `Armed`;
the next app tick starts teardown. A small restricted Lua control state makes
this verb available on clean installations with zero enabled mods.

## Local game behavior after leave

Version one closes the staged game gracefully and leaves the launcher open.
Returning to a menu in-process was rejected for this cut because session state
currently spans Steam callbacks, local transport state, replicated runtime
state, scene-owned participant objects, run barriers, and the stock navigation
stack. Resetting only part of that graph would make a second session in the
same process less reliable than a clean relaunch.

The coordinator posts `WM_CLOSE` only after transport notification and, for a
host, the bounded directory-delist wait. The launcher window's close handler
uses the same Lua verb and gives its exact staged child PID four seconds to
finish. It then requests a normal window close for another 500 ms and, only as
a bounded last resort, terminates that exact PID. It never searches for or
kills other Solomon Dark processes.

Final local authority timeout, Steam lobby-owner loss, and exhausted Steam
lobby recovery also signal the coordinator. Recoverable Steam route and
service interruptions still use their existing reconnect state machine; only
the terminal outcome tears down the session.

## Raptisoft close URL patch

The supported retail executable has SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Headless Ghidra found the full
`http://www.raptisoft.com/solomondarkbeta/` string at `0x00799FD0`. Its
reference at `0x005B65BC` is in `FUN_005B6500`, the `MyApp` destructor. The
destructor's call at `0x005B65DE` targets the URL-launch wrapper
`FUN_00423BB0`; that path reaches the imported `ShellExecuteA` call at
`0x00423B5D`.

The patch is configured as:

```ini
[native.runtime_patches]
raptisoft_close_url_launch_call=0x005B65DE
```

At initialization the loader resolves that address against the staged image,
requires original bytes `E8 CD D5 E6 FF`, and writes
`90 90 90 90 90`. It never changes `SolomonDark.exe` on disk. The patch is
intentionally not restored during loader shutdown: the stock application
destructor is the code being guarded, so restoring the call during process
teardown would reintroduce the browser race. Windows discards the patched image
when the process exits.

The configured value is the preferred-image virtual address. The normal-close
smoke loaded the executable at `0x007B0000`, resolved RVA `0x001B65DE` to
runtime address `0x009665DE`, and read back five `90` bytes while the on-disk
file still contained the original call. Both a normal window close and a
leave-driven close created no new browser process.

## Install-mod activation

The website's existing public mod-detail and version-download APIs already
provide the slug, launcher mod ID, semantic versions, content hash, package
hash, size, and package URL needed by the launcher. No Website backend change
was required.

The launcher accepts one strict
`solomondarkrevived://install-mod/{slug}?directory={origin}` path segment.
Remote directories require HTTPS; loopback development directories may use
HTTP. Userinfo, fragments, duplicate or unknown query fields, invalid slugs,
and additional path segments are rejected. The primary launcher resolves the
mod first, then reuses its existing consent modal to name the mod, version,
and source host. Confirmation runs the existing bounded download, package-hash
verification, safe ZIP extraction, manifest/content verification, cache, and
atomic promotion pipeline. A fresh install appears in the Mods tab; an older
edition is replaced through the same transaction; current or newer local
editions are left unchanged.

The UI command bridge preserves the CLI grammar by placing the slug directly
after `install-mod-preview` or `install-mod`, before JSON output flags. A
launcher contract covers that exact ordering in addition to URI parsing,
single-instance activation routing, package verification, current-version
classification, and atomic update replacement. The website frontend contract
was already sufficient, so no Website repository change or deployment was
needed.
