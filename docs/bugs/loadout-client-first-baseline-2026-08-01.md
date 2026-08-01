# Loadout client-first baseline

Date: 2026-08-01

Status: reproduced on current main before the loadout lifecycle redesign

## Question

What happens when a multiplayer client finishes the stock loadout picker
before the host?

## Controlled reproduction

The two-peer Windows loopback run used exact source SHA
`1bf18620c50350d455e24cbfd3eb00fed23d8f70`, isolated instances with prefix
`ldt-base2`, UDP ports `51711` and `51712`, and audio disabled. Both peers
started on the stock Create screen. The verifier submitted Water/Body for the
client while leaving the host on its untouched element picker, captured both
backbuffers and runtime states, then submitted Fire/Mind for the host and
required both peers to converge in the shared hub.

The runtime root was the verifier-owned `C:\ldt-base2`; no owner install was
used. The only enabled mod was the existing UI-sandbox verifier mod, held in
its `pair_manual` preset so it could expose the read-only Lua/state and stock
semantic-action seams without driving either picker. Cleanup matched and
stopped only PIDs `22020` and `26188` at their exact staged executable paths.

Evidence is under
`/mnt/d/codex-evidence/loadout-20260731/baseline/client-first-main`:

- `result.json` contains the action receipts, paired runtime snapshots,
  convergence assertions, launch ledger, and exact-PID cleanup receipts.
- `screenshots/host-still-picking.png` shows the host on the stock element
  picker while the client has already finished.
- `screenshots/client-after-pick.png` shows the client covered by the existing
  loading image, the generic text `Opening the route...`, and a 56% progress
  bar.
- `logs/host-solomondarkmodloader.log` and
  `logs/client-solomondarkmodloader.log` preserve the state-machine timing and
  later convergence.

## Actual behavior

The ordering does not immediately crash or permanently deadlock, but it is not
a healthy host-gated lifecycle. It enters an undefined, authority-inverted
intermediate state and later recovers:

1. The client completed Create at `02:33:13.868` and moved from
   `selecting_loadout` to `connecting`.
2. While the host still showed the stock Create surface and reported
   `session_state=not-in-game`, the client had already created its own hub
   state: `scene=hub`, `session_state=in-hub`, local runtime intent
   `SharedHub`, and one participant. The authority player was absent.
3. The host already received that client runtime intent while it was still
   picking: its participant count was two and the remote client runtime was
   valid with `scene_kind=SharedHub`.
4. The client hid this premature hub behind the ordinary connecting cover.
   Its loading snapshot was active at progress `0.56`, stage
   `establishing_route`, with `Opening the route...`; the rendered screenshot
   has the normal progress bar. There was no host-pick-specific state or text.
5. The host completed Create at `02:33:20.579`, reached the hub at
   `02:33:21.482`, and became authoritative. The client then received the host
   checkpoint, materialized the host actor at `02:33:25.690`, completed its
   loading cover at `02:33:25.860`, and both peers converged.

Classification: **undefined but recovering**. The eventual hub is usable, so
this specific run is not a hard failure. The pre-host interval is nevertheless
structurally wrong: a transport client creates and publishes a hub lifecycle
before the authority player exists, then communicates the wait through a
generic progress bar. The redesign must prevent client world creation until
the host has picked, represent that wait explicitly without a progress bar,
and preserve the observed ability to converge once the host is ready.

## Ranked causes to test in the redesign

1. Create completion is locally owned on every peer, so the client enters its
   own hub before any host-ready predicate can gate world creation.
2. The current `Connecting` phase waits for a materialized host only after the
   stock Create transition has already created the client's hub.
3. Participant runtime publication is independent of loadout authority, which
   lets the still-picking host observe the client's premature `SharedHub`
   intent.
4. Loading presentation has only generic transport/checkpoint stages and no
   barrier variant for a selected client waiting on an unselected host.

The post-change verifier must distinguish these predictions with runtime
state, action ordering, screenshots, and later convergence rather than treating
"both eventually reached hub" as sufficient.
