# Bot Play For Me cannot start in solo runs

## Investigation

The live Lua Bots 1.2.0 package received a physical F9 press in an isolated
solo run and changed its requested state to enabled, but takeover never became
active. Its diagnostics remained `desired=true`, `active=false`, and
`brain.mode=waiting` while `sd.player.get_state()` reported a live slot-zero
actor with 45 health.

At the same time, `sd.runtime.get_multiplayer_state()` exposed the local
`LocalHuman`/`Native` participant with `runtime_valid=false`, `in_run=false`,
and zero life. The synthetic Lua bot participant in that same solo run was
valid and in-run.

## Root cause

`RefreshLocalParticipantFromGameState` already maps the native slot-zero player
into the shared semantic participant runtime. `TickLocalTransport` calls that
refresh only after its `g_local_transport.initialized` guard. A solo run has no
gameplay transport to initialize, so the function returns before refreshing
the local participant. Lua Bots correctly refuses takeover when its semantic
participant says it is dead or materializing, even though the native player is
live.

## Foundational fix

Refresh the local semantic participant before the transport guard on every app
tick. Keep `transport_connected` tied to actual transport initialization, so a
solo player gains truthful gameplay state without being mislabeled as a
network connection. Packet receive/send and all authority behavior remain
behind the existing transport guard.

## Required proof

- In solo, the local semantic participant is valid, in-run, and carries the
  native player's current life.
- Physical F9 activates Bot Play For Me and a second F9 cleanly hands control
  back.
- Local and Steam multiplayer transport behavior remains unchanged.
