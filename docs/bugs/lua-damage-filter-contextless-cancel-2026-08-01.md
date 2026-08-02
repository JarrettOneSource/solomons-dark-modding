# Lua damage cancellation leaks when the native context is unavailable

## Investigation

The downloaded Invincibility Potion 0.2.0 blocked the framework's queued
native magic-hit probe on both local-multiplayer participants immediately
after consumption. During the same live run, however, the stock simulation
continued for the declared three-minute duration and the players eventually
took ordinary gameplay damage. One participant died and emitted
`run.ended`, which correctly cleared the mod's active effect before the
175-second damage check.

The host loader log recorded calls to the player damage hook for which the
Lua damage-filter context could not be captured. The current hook logs that
condition and then calls the stock damage function without invoking any Lua
filter. The queued probe always supplies the full native context, so it could
not expose this path.

Evidence is under
`/mnt/d/codex-evidence/modpipe-20260801/phase-c/development-fix-validation/local-full-20260802-0245/`.

## Root cause

`HookPlayerActorMagicDamage` treats the damage-lane context as a prerequisite
for the entire filter call. The lane addresses are needed to rewrite damage,
but they are not needed to cancel a hit: the hook already has the target actor
and can resolve its authoritative participant ID. As a result, a filter that
returns `false`, such as the potion's invincibility filter, is skipped on
valid stock calls that do not expose the lane context.

## Foundational fix

Always construct a filter payload from the hooked target actor. Capture the
source, flags, and damage lanes when the native context is available. Even
when those optional fields are unavailable, invoke damage filters so a
handler can cancel the hit. Only permit lane rewrites when the complete lane
context was captured; otherwise retain the stock call and emit the existing
bounded diagnostic if a handler attempted a rewrite.

This changes the framework authority seam only. The potion continues to ride
the replicated `item.consumed` event and does not add client state or a custom
sync channel.

## Required proof

- Context-complete and context-incomplete damage calls both honor cancellation.
- Damage-lane rewrites remain limited to calls with a captured native context.
- In solo and multiplayer, ordinary authority damage remains blocked through
  the declared duration and resumes after expiry.
