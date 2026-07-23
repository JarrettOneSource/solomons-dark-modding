# Lua audio

`sd.audio` gives each Lua mod bounded, presentation-local playback through the
copy of `bass.dll` already loaded by Solomon Dark. The game retains ownership
of its device initialization and lifetime. The seam supports short samples,
streamed music or speech, explicit stop, and live volume changes without
exposing BASS handles or allowing paths outside the mod.

Audio is never simulation state. A mod that wants every peer to hear the same
cue broadcasts a semantic event from the authority and lets each peer play its
own local file:

```lua
sd.events.on("boss.enrage", function(event)
  sd.audio.play_sample("audio/enrage.ogg", {volume = 0.8})
end)

-- Authority-side encounter code:
sd.events.broadcast("boss.enrage", {boss = "grave_oracle"})
```

The event is ordered and replicated; the sound bytes and playback handle are
not. Mod parity ensures that peers entered the session with the same asset.

## API

### `sd.audio.play_sample(path[, options]) -> handle`

Loads a complete audio asset as a BASS sample and starts one channel. Repeated
calls can overlap because each call owns its own sample and channel. This is
the right path for stingers, impacts, UI cues, and short voice lines.

### `sd.audio.play_stream(path[, options]) -> handle`

Creates and starts a file-backed BASS stream. Use it for music, ambience, and
long voice tracks. A stream does not load the entire file into sample memory.

Both play calls accept only these options:

```lua
{
  volume = 1.0, -- finite number from 0 through 1
  loop = false, -- boolean
}
```

Both return a positive opaque handle scoped to the calling mod. The handle is
not a native BASS channel and has no meaning in another mod or process.

### `sd.audio.stop(handle) -> boolean`

Stops and frees one owned playback. It returns `false` when that handle is no
longer active. It cannot stop stock game audio or another mod's playback.

### `sd.audio.set_volume(handle, volume) -> boolean`

Writes BASS volume attribute 2 for one owned playback. `volume` must be finite
and between 0 and 1. It returns `false` for an unknown or retired handle; a
native BASS failure is a Lua error.

### `sd.audio.get_state([handle]) -> table|nil`

With a handle, returns its copied semantic state or `nil`. With no argument
(or `nil`), returns an array containing every playback owned by the calling
mod:

```lua
{
  handle = 4,
  kind = "stream",       -- "sample" or "stream"
  path = "audio/theme.ogg",
  volume = 0.6,
  loop = true,
  created_milliseconds = 19342,
  state = "playing",     -- playing, stalled, paused, stopped, or unknown
}
```

There are no channel numbers, sample handles, pointers, function addresses,
or global registry slots in this table.

### `sd.audio.clear() -> count`

Stops and frees all playback owned by the calling mod and returns the number
retired. Handles remain monotonic and are not reused after `clear`.

### `sd.audio.is_available() -> boolean`

Reports whether the loader found the required exports on the already-loaded
game `bass.dll`. The namespace exists even when those exports are unavailable,
but the three audio capabilities are then absent and play calls fail visibly.
The loader never loads a second BASS DLL and never calls `BASS_Init`; device
configuration, global pause, and the stock mix remain owned by the game.

Lua entry scripts run early in process startup. Register handlers there and
begin playback from a later game event or timer, after the game has initialized
its BASS device. A premature play call reports the exact BASS error instead of
silently queuing or taking ownership of device setup.

## Paths and limits

Paths are UTF-8 and relative to the calling mod's root. They must name an
existing regular `.wav`, `.ogg`, `.mp3`, or `.caf` file. Absolute paths,
`.`/`..` components, unsupported extensions, missing files, symlinks or
junctions that resolve outside the mod root, and embedded NULs are rejected.
The canonical final path is containment-checked before BASS sees it.

The runtime bounds audio to:

- 64 simultaneous playbacks per mod;
- 256 simultaneous Lua playbacks across all loaded mods;
- 512 bytes in a relative path; and
- 512 MiB per referenced asset.

Finished one-shots are detected on the main/gameplay Lua pump and freed.
Looping or paused channels remain owned until stopped. Every remaining sample
or stream is stopped and freed when its mod unloads or the Lua engine shuts
down. Audio deliberately survives run and scene transitions unless the owning
mod stops it.

## Capabilities and multiplayer

When the BASS export contract is available, the runtime advertises:

- `audio.local.playback`
- `audio.sample`
- `audio.stream`

All operations are presentation-local on offline, host, and client processes.
They do not require simulation authority and do not send packets. Use
`sd.events.broadcast` for a synchronized cue, `sd.state` for shared encounter
state, and `sd.audio` only for the resulting local presentation.

The disabled `sample.lua.audio_lab` mod demonstrates event-driven samples,
looping streams, volume changes, and cleanup. It intentionally does not ship a
sound file; place licensed test media under its `audio/` directory before
enabling it. `tools/verify_lua_audio.py` checks the strict surface and can drive
both BASS paths against an asset in the first loaded Lua mod without launching
the game itself.

## Verification

With a loader already running, verify namespace, capability, schema, path, and
argument rejection without producing sound:

```powershell
py -3 tools/verify_lua_audio.py
```

To exercise real sample and stream handles, place a licensed audio file inside
the first loaded Lua mod and pass its mod-relative path:

```powershell
py -3 tools/verify_lua_audio.py --asset audio/acceptance.wav
```

The verifier loops at low volume, checks both semantic state tables and a live
volume change, then stops and frees each handle. It attaches only to an existing
named pipe; it never launches or focuses Solomon Dark.
