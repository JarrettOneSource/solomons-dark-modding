# Lua input and local-player control

`sd.input` routes gameplay actions through the game process. The movement,
mouse, and binding queues are consumed by the stock player tick and control
brain; they do not move the OS cursor or synthesize Windows input while a run
is active.

## Local-player takeover

Mods that require `input.local_player.takeover` may claim the local player's
gameplay controls:

```lua
sd.input.set_local_player_takeover(true)
sd.input.set_local_player_takeover_target(
  enemy_actor_address,
  enemy_x,
  enemy_y)
sd.input.hold_movement_frames(direction_x, direction_y, 1)
sd.input.hold_mouse_left_frames(2)
sd.input.press_binding("belt_slot_1")
```

Only one mod can own the takeover at a time. Ownership is local to the running
game process, so the same mod can independently drive the host's local player
and a client's local player. Movement is sampled by the existing slot-zero
player tick, primary casts enter the native control-brain path, and secondary
casts use the player's live belt binding and stock dispatcher. Multiplayer
authority and replication are unchanged.

`hold_movement_frames` publishes one current direction and a duration from the
current player tick. A newer call replaces both values; repeated one-frame
calls maintain a one-frame intent instead of accumulating a stale backlog.
If a frame cannot be applied, it is restored only when no newer duration has
replaced it.
This differs deliberately from mouse clicks and binding presses, which are
discrete queued events.

When a stock run has not materialized the local actor's control brain yet, the
takeover claim initializes it through the game's own player-actor initializer
before accepting bot commands. Existing live control brains are left intact.

Call `sd.input.set_local_player_takeover(false)` before returning control to
the player. Release clears pending movement, mouse holds, binding edges, cast
intent, targets, primary/previous skill latches, and control-brain target and
movement fields. Takeover's native primary priming snapshots the actor's prior
selection and restores that exact selection during release. The loader performs
the same release automatically if the owning mod unloads or hot reloads.

`sd.input.get_local_player_takeover_state()` returns the owner, queued-control
counts, current native cast and movement fields, primary-selection snapshot and
last-restore fields, `native_state_clear_succeeded`, and `clean`. `clean` is
true only after every queue/native field is cleared and the selection snapshot
has been restored. Acceptance tests can assert it immediately after release
instead of relying on visual inspection.
