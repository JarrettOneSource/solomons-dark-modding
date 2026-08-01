# Loadout and match-start lifecycle

## Decision

Every multiplayer run has its own loadout generation. A participant must
commit a stock Create selection for that generation before entering its world.
The previous generation's element and discipline are preselected, so keeping
the loadout is one stock discipline click. Selecting another element reopens
the stock discipline step and commits only after the second stock choice.
The one-click keep path replays the retained element through the stock click
handler before delivering that discipline click, preserving the native
selection side effects that raw highlight fields do not produce.

The host is the sole world-creation authority:

```text
host Picking --commit--> host WorldReady --> hub or run exists
client Picking --commit before host--> Picked + no-bar host barrier
client Picked + host WorldReady-------> WorldReady + enter existing world
host WorldReady + client Picking------> host plays; client trickles in later
Game Over------------------------------> generation + 1, everyone Picking
```

The participant and transport identity domains remain separate. Loadout state
is attached to the actor-domain participant record and replicated with its
generation. Authority lookup accepts the configured host participant or Steam
identity, but never compares an actor-domain value to an unrelated transport
slot.

## Baseline

The pre-change client-first experiment is recorded in
[loadout-client-first-baseline-2026-08-01.md](../bugs/loadout-client-first-baseline-2026-08-01.md).
At `1bf1862`, the client entered a hub before the host had picked and showed the
generic `Opening the route...` screen with a 56 percent bar. It later recovered
after the host picked, but the ordering was undefined rather than an explicit
barrier.

## Presentation

A client that commits before the host uses the existing loading artwork with
the exact label `Waiting for host to pick loadout`. This barrier variant draws
no progress bar, waits at least 150 ms before presentation, and uses the same
D3D9 lifetime guard as the other loading stages. No new picker or confirmation
UI is introduced.

## Directory lifecycle

The host directory publisher starts with the launched multiplayer session,
not with hub entry. Its phase vocabulary is:

| Runtime | Directory phase | Display text |
| --- | --- | --- |
| current loadout generation is not world-ready | `picking-loadout` | `Picking Loadout` |
| shared hub | `hub` | `In Hub` |
| run transition | `loading` | `Loading` |
| active run | `session` | `In Match` |
| post-run before the next world | `picking-loadout` | `Picking Loadout` |

The publisher sends an immediate update when this fingerprint changes, keeps
its ordinary heartbeat, and delists through canonical session teardown. The
launcher card, website API validation, persistence contract, and public lobby
browser use the same new phase. Website rendering is isolated on branch
`ldt/picking-loadout-status-20260731`; it is not a deployment artifact.

## Live acceptance

The controlled loopback variants use ports 51711 and 51712, audio disabled,
an explicit flat Boneyard and one-wave fixture, exact staged paths, and exact
PID cleanup. Evidence is rooted at
`/mnt/d/codex-evidence/loadout-20260731/acceptance/`:

- `client-first/` captures the no-bar host barrier and converged wave;
- `host-first-trickle/` captures the host playing while the client remains in
  stock Create, followed by clean trickle-in;
- `game-over-repick/` asserts generation-two preselection, changed elements,
  and replicated second-run element fingerprints; and
- `announce-lifecycle/` records launch-time picking, hub, match, post-Game-Over
  picking, and DELETE against a Windows-loopback mock. Production is untouched.
