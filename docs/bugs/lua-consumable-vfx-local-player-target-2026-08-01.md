# Lua consumable VFX skipped for the local player

## Investigation

The downloaded Invincibility Potion 0.2.0 emitted its authoritative
`item.consumed` event in a live solo run, but the expected active-effect VFX
was absent. The loader log recorded:

```text
lua_items: consumable VFX skipped. ... participant_id=1 ... error=participant actor is not materialized
```

At the same instant, `sd.player.get_state()` reported a valid local player and
the native potion effect callback ran. The event was therefore valid; only the
VFX target lookup failed.

## Root cause

`SpawnSpellGlowForParticipant` resolves every target through
`TryGetParticipantGameplayState`. That registry owns replicated and synthetic
participant actors, but the stock slot-0 player is resolved through
`TryGetPlayerState`. In solo the event uses the runtime local ID because no
gameplay transport is initialized; in multiplayer it uses the transport ID.
For each peer's own player, neither identity has a materialized
participant-registry actor. The VFX request is then discarded even though the
stock local player actor and world are live.

After correcting that target lookup, native registration succeeded but the
effect was still absent from a capture taken immediately after consumption.
Ghidra call-site analysis of stock `Anim_SpellGlow` creation showed two more
contract violations:

- every stock registration passes the native world-animation layer constant
  `75.0`; the Lua consumable seam instead passed `0.0`, behind the terrain;
- `Anim_SpellGlow` is deliberately a one-frame animation. Its draw method
  calls vtable slot `+0x18`, which resolves to `0x00401FD0` and sets the base
  object's completed byte at `+0x05`. A single queued glow can therefore be
  drawn and retired between the replicated-event acknowledgement and the next
  player-visible frame or capture.

The world accepted both registrations, so the old code reported success in
each case even though it did not provide an observable pickup VFX.

A repeat run exposed one remaining presentation race after the replacement
glow pulse was added. The consume call completed at `19:27:39.699` and the
D3D9 backbuffer was captured at `19:27:39.760`, yet that completed frame
contained no green VFX pixels. Native world-animation update and loader
backbuffer capture are separate points in the frame. Recreating a one-frame
native primitive frequently does not make that primitive resident in the
completed backbuffer that the player or an evidence capture observes.

A 12-frame live sweep pinned down the timing. The first completed capture was
still pre-effect, the second showed the green stock glow 786 milliseconds
after consumption, and the third was already outside the one-second pulse at
1.438 seconds. A one-second window also cannot cover sequential host and
client backbuffer captures in multiplayer. A pump-queued atlas burst did not
change this boundary either: the renderer could drain it before a completed
backbuffer became observable. With the pulse widened to four seconds, a
second sweep still showed the native glow in only two of eight completed
captures. Native `Anim_SpellGlow` remains a useful stock effect, but it cannot
by itself satisfy a consistent observer-visible presentation contract.

## Foundational fix

Resolve the local transport participant through the existing local-player
gameplay seam, and keep the participant gameplay registry for remote and
synthetic actors. This preserves the replicated consumed event as the single
trigger and changes only how each observer maps that participant ID to its
native actor. Register the stock `Anim_SpellGlow` at the same `75.0` animation
layer used by native call sites. Turn the one-frame native primitive into a
four-second activation pulse by scheduling replacement glows from the same
replicated event. Four seconds spans the observed native frame boundary and
allows both peers to see the effect without changing its three-minute gameplay
duration. During that presentation window, derive a small orbiting burst from
the consumable's registered atlas directly in the existing D3D9 EndScene
render pass. Building it at the render seam, rather than queuing it from a
gameplay pump, makes every completed frame deterministic while retaining the
stock glow underneath. Both layers are observer-local presentation derived
from the replicated event; they add no mod network message or client-authored
gameplay state.

The later ZORDER native-only cutover removes that overlay burst. Because the
four-second replacement window above proved insufficient for sequential
completed-frame observations on both peers, the native pulse window is widened
to twelve seconds; the registered gameplay duration remains unchanged.

## Required proof

- The active VFX is visible for the local player in a live solo run.
- In multiplayer, both peers render the VFX for either participant from the
  same replicated consumed event.
- Authority damage remains blocked for the declared duration and resumes
  after expiry.
