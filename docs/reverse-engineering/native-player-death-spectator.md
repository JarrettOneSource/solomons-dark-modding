# Native player death and spectator boundary

The retail death dispatcher at `0x004633D0` performs its two stock death audio
actions before calling `Game_OnGameOver` at `0x005CB570`. The existing
run-ended detour targets that latter call boundary. A connected multiplayer
death can therefore preserve the stock death audio and corpse presentation by
returning from the detour without invoking the Game Over constructor.

`Game_OnGameOver` allocates the native Game Over surface and calls the
constructor at `0x005CAD40`. That surface then owns the fade and scene
transition in its tick at `0x005CF4F0`; its renderer is at `0x005C9030`.
Suppressing only `0x005CB570` keeps the live run scene and wave simulation
intact. The offline path continues through the original call and the existing run
lifecycle teardown unchanged.

Multiplayer holds the dead client on its native corpse for 3000 milliseconds.
After that presentation window, the transport changes only presentation-local
camera and HUD state; simulation authority remains with the existing host and
participant-owner lanes.

The host captures the run-entry spawn position and publishes a monotonically
new wave-respawn epoch when the authoritative wave summary reaches
`completed`. The command is repeated in both the disposable participant frame
and the reliable state checkpoint. Every process validates the configured
authority and matching run nonce, then restores only its own native player
vitals, corpse drive state, position, cast/input state, and world-cell binding.
Normal participant vitals remain owner-authored.

`tools/verify_multiplayer_death_spectator_respawn.py` launches a uniquely named
three-owner local test on independent UDP ports without killing unrelated game
copies. It verifies the three-second death hold with no Game Over surface,
camera convergence on a named alive target, left- and right-click cycling, and
full owner-local respawn after a native one-enemy wave completes.
