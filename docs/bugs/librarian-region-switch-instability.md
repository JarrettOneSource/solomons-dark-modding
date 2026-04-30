# Librarian Region Switch Instability

Status: open

Owner: investigation / stock-client RE

Date first recorded here: 2026-04-15

## Summary

Switching from the hub into `librarian` is unstable in the current client path.

Important distinction:

- this is **not** currently believed to be caused by the Lua bot mod
- it was reproduced even with `sample.lua.bots` disabled
- the scene can still load after the exception, so this is not always a clean
  “hard crash every time” bug

Current interpretation:

- this is a **stock-client region-switch instability** on the `hub -> librarian`
  path that the mod loader can observe and log
- it should be treated as a separate bug from the bot entrance-follow work

## Scope

Known affected path:

- `hub -> librarian`

Region metadata:

- `region_index = 2`
- `region_type_id = 4004`

Related stable comparison paths:

- `hub -> memorator`
- `hub -> dowser`
- `hub -> polisher_arch`

## Reproduction

Minimal repro used during investigation:

1. Launch through the mod loader.
2. Keep `sample.lua.bots` disabled.
3. Let the harness or a direct Lua call trigger:
   - `sd.debug.switch_region(2)`
4. Observe the loader log and scene state.

## Observed Behavior

What happens on the bad path:

- the loader logs `gameplay.switch_region: dispatched ... from=hub to=librarian target_region=2`
- a first-chance access violation is logged
- the exception code observed is `0xC0000005`
- the faulting address observed in-session was `0x444FC000`
- despite the exception, the scene can still settle to:
  - `name=librarian`
  - `region=2`
  - `region_type=4004`

So the current symptom is:

- unstable / noisy transition with first-chance exceptions
- not necessarily an immediate fatal process termination on every attempt

## Why This Matters

This blocks clean sign-off for full entrance-driven private-area travel across
all hub interiors.

The current entrance-follow system is good enough for:

- participant scene model
- shared/private scene presence split
- memorator entrance-driven bot travel

But `librarian` cannot currently be called “stable” until the stock switch path
is better understood.

## Non-Causes / Exclusions

This issue is **not** the same as the earlier bot-induced scene churn crashes.

Those earlier crashes were improved by:

- arming the scene churn window before `SwitchRegion`
- relying on stock `world_unregister` plus hook-side binding reset
- removing unsafe manual pre-switch bot teardown

The `librarian` issue still appears even when the bot mod is off, which is why
it is tracked separately here.

## Related Docs

- [participant-entrance-follow.md](../participant-entrance-follow.md)

See especially:

- measured `librarian` anchor data
- caveat notes that `hub -> librarian` still raises first-chance exceptions

## Next Investigation

The next correct task is a focused stock-client RE/debug pass for the
`hub -> librarian` region-switch path.

High-value next steps:

1. Map the exact game-side region-switch path for `region_index = 2`.
2. Determine whether the fault is:
   - missing / late-initialized region data
   - teardown ordering
   - a bad object pointer specific to the `librarian` region
3. Compare `librarian` against the clean `memorator` path.

This should be treated as a separate bug-fix slice, not more entrance-follow
policy work.
