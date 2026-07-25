# Multiplayer session lifecycle

The authenticated Steam lobby and gameplay runs have different lifetimes. A
native Solomon's Dark Game Over ends one run nonce; it does not leave or
destroy the loader lobby. The host remains host, authenticated members remain
members, and the existing transport keeps pumping while each process follows
the stock Game Over and mode-specific post-run transition.

Story mode continues through Mortuary, Hall of Fame, and the main menu. The
Boneyard branch installs its stock front-end surface while the completed run
lands in the private Memoratorium region. Once that native cleanup is complete,
the multiplayer post-run flow sends the stock Menu binding to expose the
native Hall of Fame controller. It validates that controller against its exact
vtable, invokes its stock continue virtual on the application thread with the
native handler's required ignored four-byte stack argument, and lets
`HallOfFame::Tick` reinstall the native main menu. The input handler is a
fade-state gate, so the join flow retries it at a bounded cadence until the
surface advances instead of treating an early no-op call as completion. The
existing main-menu/profile onboarding flow then returns that same process to
the shared hub. During initial Create onboarding the flow remembers the
player's actual element and discipline choices. If stock completed-run
cleanup presents Create again, it replays those same semantic stock actions
on the new controller; a native no-Lua fresh-start configuration supplies the
equivalent choices explicitly. This works whether the new controller starts
with retained values or `unset` sentinels, because the button handlers own
progression. It does not hard-code a fallback loadout, call
`Gameplay_SwitchRegion` from the post-run scene,
construct a region or UI object, write a native field, relaunch the process, or
rejoin the lobby. When all peers are back in the shared hub, the host can start
another run. The new run receives a fresh nonce inside the same lobby and
process group.

The native teardown call graph and its separation from loader session state are
recorded in
[`native-game-over-session-semantics.md`](../reverse-engineering/native-game-over-session-semantics.md).

## Published activity state

`multiplayer-session-status.json` publishes `sessionState` beside the existing
`members[]` and backward-compatible `gamePhase` fields:

| `sessionState` | Meaning |
|---|---|
| `not-in-game` | No materialized shared-hub or active-run actor. This covers startup, stock post-run screens, and other private/non-session scenes. |
| `in-hub` | The local player and world are materialized in the shared hub. |
| `in-boneyard` | The local player is in a live Boneyard run nonce. |

The launcher lobby card consumes `sessionState` directly. Directory and website
publication keep using `gamePhase`: `loading` before readiness release,
`session` after release, `results` during stock post-run progression, and
`hub` in the shared hub.

## Run-loading readiness barrier

Starting a run moves every participant, including the host, into the
`Loading Boneyard` presentation. The host freezes the expected participant-ID
set from the connected lobby/transport roster. Each process builds its locally
visible set from:

1. its valid local Boneyard actor for the active run nonce; and
2. every expected remote native participant whose actor is materialized on
   that process for the same run nonce.

The sorted ID set is hashed deterministically. A client acknowledges only when
its visible count and set hash exactly match the host's expected count and set
hash. The host applies the same rule to its local view and accepts client acks
only from expected authenticated participants on the active nonce. This proves
that every participant actor is materialized on every participant process,
rather than treating transport readiness or an aggregate count as visibility.
The exact actor set must remain continuously materialized for 250 milliseconds
before the process emits its ack. This prevents the first transient actor
pointer observed during stock respawn from releasing the presentation before
the scene has settled.

The host publishes one authenticated release after every frozen member has
acked. Release travels in the low-latency participant frame and the reliable
state checkpoint. A client accepts release only from its configured authority.

## Failure bound

Every barrier has a 25-second monotonic deadline. If an expected peer stalls,
crashes, or disappears during loading, the host releases the loaded peers with
reason `timeout`, logs the ready/expected counts and waiting participant IDs,
and keeps the run alive. A client also owns an independent 25-second fallback
deadline so loss of the host release cannot leave its loading presentation
visible forever.

The barrier state is available through
`sd.runtime.get_multiplayer_state().run_loading_barrier`, including active,
released, timed-out, nonce, deadline, count, hash, ready-ID, expected-ID, and
waiting-ID evidence.

## Regression gate

`tests/re/static_multiplayer_session_lifecycle_contracts.py` locks the status
labels, stock post-run reentry, absence of lobby teardown calls, packet
membership proof, authority checks, reliable convergence lane, and both
deadlines.

`tools/verify_game_over_session_semantics.py` is the live contract. Its isolated
three-peer run captures `Loading Boneyard` on all participants, verifies exact
mutual visibility, terminalizes the run through each peer's native
Boneyard-mode GameOver object and stock fade-only front-end branch, returns all
three processes through the stock Hall-of-Fame/main-menu onboarding path, and
starts a second fresh nonce without relaunch or rejoin. A separate isolated
pair kills only its recorded client PID after the run-start request and proves
the surviving host releases at the deadline instead of hanging.
