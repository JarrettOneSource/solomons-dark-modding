# Test media

Place licensed `.wav`, `.ogg`, `.mp3`, or `.caf` files here before enabling
the Lua Audio Lab. The sample event handlers default to:

- `audio/stinger.ogg`
- `audio/music.ogg`

Audible author media is intentionally not included in the repository.

`acceptance.wav.base64` is a deterministic 10 ms silent PCM fixture used only
by `tools/verify_lua_audio_multiplayer.py`. The verifier decodes
`acceptance.wav` for its staging window and removes it after both exact game
process IDs stop. It is not author media and contains no audible samples.
