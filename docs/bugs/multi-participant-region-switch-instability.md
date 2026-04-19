# Multi-Participant Region Switch Instability

## Summary

Switching regions with more than one materialized participant can still crash the
current client during world unregister on the old scene.

This was observed while validating bot spawn sanitization with:

- the managed `Lua Patrol Bot`
- one additional `SharedHub` bot created at a deliberately bad spawn coordinate
  to prove nearest-traversable spawn snapping

The additional bot itself spawned correctly after snapping from `(0, 0)` to a
valid hub cell, but a later region switch caused the client to die while both
participant actors were being unregistered from the hub world.

## Scope

- scene family: `hub -> private_region`
- participant count: `>= 2` materialized participant bots in the same scene
- current confirmed path: shared hub with two materialized bot participants,
  then region switch

## Current Evidence

- both participant actors reached the shared hub and were materialized
- the second bot did not embed into bad geometry after the spawn-safety fix
- during the later region switch, loader logs captured:
  - `world_unregister enter` for both bot actors
  - then a first-chance `0xC0000005`
  - then process death / Lua pipe loss

This is distinct from the single managed-bot path, which remains stable on the
current memorator and run-follow validations.

## Why It Matters

The current single-bot companion framework can be treated as working for the
validated paths, but the broader participant scene model is not yet safe to
treat as “multiple remote players can all churn scenes together” until this is
understood and fixed.

That makes this an important future multiplayer blocker, not a cosmetic edge.

## Not Yet Proven

- Whether the crash is specific to:
  - multiple gameplay-slot bot actors
  - mixed participant kinds
  - the private-region switch path itself
  - or old-scene unregister ordering
- Whether the crash reproduces identically on all private interiors or only a
  subset

## Next RE Slice

1. Reproduce with a minimal two-participant setup and no extra Lua follow
   behavior.
2. Capture exact unregister order and slot ownership for both actors.
3. Trace the stock old-scene teardown path around the failing unregister.
4. Decide whether the fix belongs in:
   - participant dematerialization ordering
   - slot/world unregister sequencing
   - or a stock-client bug-fix shim in the loader
