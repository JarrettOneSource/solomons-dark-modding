# Lua authoring workflow

The loader ships a generated LuaLS/EmmyLua inventory, opt-in entry-script hot
reload, and an in-game exec console. These tools share the native binding and
safe-thread execution paths; they do not define a second scripting API.

## Editor API

`api/lua/sd.lua` is generated from the `RegisterLua*Bindings` functions that
construct the live `sd` table. The repository `.luarc.json` adds that directory
to LuaLS automatically, so scripts under `mods/` get namespace and function
completion. Generated signatures deliberately accept and return `any`; the
feature documents remain the source of truth for argument, result, authority,
and lifecycle contracts.

Regenerate after adding, removing, or renaming a binding:

```bash
python tools/generate_lua_api_stubs.py
```

Check without writing:

```bash
python tools/generate_lua_api_stubs.py --check
```

The `Lua authoring contracts` GitHub workflow runs the check and generator unit
tests on every main push and pull request. A binding-registry change therefore
cannot merge with a stale checked-in editor inventory.

## Entry-script hot reload

Hot reload is explicit and disabled by default. Enable it for a Lua or hybrid
development mod:

```json
{
  "runtime": {
    "apiVersion": "0.2.0",
    "entryScript": "scripts/main.lua",
    "hotReload": true
  }
}
```

The launcher still mirrors the complete mod into the isolated stage. Initial
startup executes that staged entry script. Its private runtime bootstrap also
records the original source entry path, and the loader checks that exact file
four times per second. A byte hash catches edits even when filesystem timestamp
resolution is coarse; a changed value must remain stable for at least 300 ms
before it is considered complete.

Reload closes the owning `lua_State` through the normal lifecycle path. Event
handlers, filters, timers, bus/net subscriptions, draw frames, sprite atlases,
time/camera requests, authored UI, audio, AI, and registered content are
released before the new state registers them again. `sd.state` and persisted
`sd.storage` data are outside that state and remain available.

The loader syntax-checks a candidate in a temporary Lua state before touching
the running state. A missing, oversized, or syntactically invalid source file
is rejected and the prior state remains live. If top-level execution fails only
after teardown, the mod stays unloaded; edit the source again to retry. Each
source version is attempted once, preventing an error loop every poll.

Only the entry script is watched and executed. Art, bundles, overlays, and
other resources remain the staged launch snapshot; re-stage to update them.
Hot reload is capped at a 1 MiB source entry. It is automatically deferred while
a Steam or local-UDP gameplay transport is configured, including a host lobby
that does not have a connected peer yet. Relaunch without a multiplayer
transport to reload source. Local Lua bots do not trigger that gate. This keeps
the running code covered by the exact staged manifest hash that every peer
compares during its session handshake.

`sd.runtime.get_mod().hot_reload` reports whether the current mod opted in.

## In-game exec console

Press <kbd>Ctrl</kbd>+<kbd>`</kbd> to open or close the console after the loader starts. It targets
the first loaded Lua mod, exactly like `scripts/Invoke-LuaExec.ps1` and
`tools/lua-exec.py`, and displays the target id in its header. Submitted chunks
enter the existing queue and execute only from the gameplay-safe or front-end
main-thread pump under the Lua engine mutex. The window procedure never touches
a `lua_State` directly.

Controls:

- `Enter` submits the current chunk.
- `Up` / `Down` navigate the 64-entry command history.
- `Backspace` removes one UTF-8 character.
- `Ctrl+V` pastes text; pasted newlines allow multi-line chunks.
- `Ctrl+L` clears displayed output.
- `Escape` closes the console.

Input is capped at 4 KiB. The console retains at most 128 output lines and uses
the bounded loader draw list for its panel. `print(...)`, return values, and Lua
errors use the same capture result as the named pipe. Closing the console does
not cancel a chunk that the safe-thread pump has already begun; shutdown drains
queued requests through the normal engine lifecycle.

The console is a developer surface, not a multiplayer command channel. Lua API
authority checks still apply to every submitted call.

## Live acceptance

Enable only the disabled `sample.lua.authoring_lab` mod and launch through the
normal staged launcher. The lab owns an invisible native UI surface so a reload
must release and recreate a real mod-owned resource. From this repository run:

```bash
python tools/verify_lua_authoring.py
```

On an offline launch, the verifier applies one valid source edit, confirms a new
Lua state and UI handle, injects a syntax error and confirms that the prior state
survives, then restores the original source and confirms a final reload. On a
Steam or local-UDP transport launch, auto mode instead confirms that the edit is
deferred for the entire observation window, even when no remote participant is
connected. It reads the same `transport_enabled` runtime predicate as the native
reload gate, rather than waiting for the transport to report ready. Every path
restores the entry script's exact original bytes.

For exact local-UDP pair coverage, use:

```bash
python tools/verify_lua_authoring_multiplayer.py --launch-pair
```

The pair verifier stages only `sample.lua.authoring_lab`, waits for the
authenticated host/client session, and applies one source edit. Both peers are
observed through the same interval. Each peer must retain its baseline version
and exact native UI surface handle with `transport_enabled` and
`transport_ready` true. The verifier then restores the original bytes and
repeats the two-peer stability interval. It refuses to overwrite a concurrent
source change, never tiles windows or performs global process cleanup, and stops
only the two process IDs returned by its launch.

The offline matrix was live-confirmed on 0.72.5 on 2026-07-23: the authored
surface handle changed from `1` to `4` on the valid edit, the syntax-invalid
candidate preserved handle `4`, the restored baseline recreated handle `7`, and
the source bytes matched exactly afterward. The verifier works from WSL or
Windows Python; Windows uses a bounded redirected-pipe reader because
`select()` cannot wait on a Win32 anonymous pipe.

This remains a normal rendered-game acceptance run. Do not start it unattended
while someone is actively using the Windows desktop: Solomon Dark can activate
its game window even when its process receives a hidden startup window style.

The in-game console remains a visual/input acceptance gate: open it with
<kbd>Ctrl</kbd>+<kbd>`</kbd>, submit `return authoring_lab_version`, and confirm
that both the command and `authoring-baseline-0001` result render in the panel.
This check intentionally requires a user-controlled game window; the verifier
does not synthesize global keyboard input or steal focus.
