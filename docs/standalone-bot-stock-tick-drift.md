# Standalone Bot Stock Tick Drift

Date: 2026-04-20

## What live probes showed

Using the Lua exec pipe plus `sd.debug.watch_write` on the live bot's
`actor+0x18/+0x1C` position fields, both player-family rails showed stock native
position writers still active after loader movement should have owned the
transform:

Key live observations:

- `sd.bots.get_state()` could be sampled as `moving=false`, `has_target=false`,
  `state=idle` while the same actor address continued changing position.
- A live idle sample showed:
  - `actor+0x158 != 0`
  - `actor+0x15C != 0`
  - `actor+0x218 == 1.0`
- Write-watch hits on `actor+0x18/+0x1C` came from native game sites, proving
  stock code was still the position writer:
  - hub standalone clone rail: `eip=0x6058CC` / `0x6058D2`
  - run gameplay-slot rail: `eip=0x602A94` / `0x602A99`

Those fields are exactly the stock walk inputs recovered in
`actor_per_tick_speed_offset.md`:

```text
dx = [actor+0x218] * [actor+0x158]
dy = [actor+0x218] * [actor+0x15C]
```

## Root cause

The loader seeds `actor+0x158/+0x15C` during loader-owned movement so
`PlayerActor_MoveStep` can mirror stock player stepping. But when standalone bot
movement stops:

- `StopWizardBotActorMotion()` did not clear those stock walk accumulators
- the tick hook only restored pre-tick position when `tracked_actor_moving`
  was true
- once the controller went idle, stock `PlayerActorTick` was allowed to commit
  its own position writes again

Result:

1. Loader stops issuing movement.
2. Stock walk accumulators are still non-zero from the last commanded step.
3. Stock `PlayerActorTick` keeps consuming them and moves the clone anyway.
4. The bot visibly slides / drifts even though the high-level controller is idle.
5. Follow/path logic then rebuilds around the drifted actor position, creating
   the observed non-convergent behavior.

This is a movement-ownership bug: two systems can write the same transform.

## Fix

For player-family bot rails that use loader-owned movement:

- always restore the pre-stock-tick position after `original(self)` in the
  player-tick hook
- clear `actor+0x158` and `actor+0x15C` in `StopWizardBotActorMotion()`
- make sure the gameplay-slot branch still calls the stop helper on idle, not
  only while `binding->movement_active`

That makes standalone clone position fully loader-owned. Any intentional motion
must come from:

- loader-issued movement steps
- explicit loader collision-push logic

Stock tick position writes are discarded consistently instead of being allowed to
leak through when the controller is idle.
