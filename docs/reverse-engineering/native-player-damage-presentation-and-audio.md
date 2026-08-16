# Native player damage presentation and audio

Status: statically verified against retail `SolomonDark.exe` SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
This report owns the nonterminal PlayerWizard damage-reaction boundary: the
common Actor hit redraw, the PlayerActor health receiver, the Wizard ouch
request, the poison-suppression lane, and the transition into the separately
documented player-death lifecycle. Magic Shield construction and input remain
owned by the skills system; its damage-time presentation is included here only
to prevent ordinary health damage from impersonating it.

## Result

The stock Wizard has no hurt body strip. Accepted ordinary primary or secondary
damage leaves the current idle, walk, or queued-action selector intact and arms
the common Actor red redraw. The redraw starts at alpha one, loses `0.05` per
fixed tick, and therefore lasts 20 ticks unless another eligible hit refreshes
it. It is source-over red, not additive white, and it duplicates the current
living body pose rather than selecting or restarting an animation.

The voice reaction is a separate, globally throttled request. Positive direct
damage that leaves the PlayerWizard nonterminal may choose one of the three
`Wizard_Ouch` cues once the shared deadline has expired. The cue volume rises
as post-hit health falls. Terminal damage, healing, and presentation-suppressed
damage do not make this request.

Native poison proves why the receiver must keep health authority separate from
presentation authority. `Poisoned::Tick 0x00627160` fills only the tertiary
damage lane, sets context flags `0x88`, and dispatches through the same player
receiver. It can reduce health and cross the native `-10` lethal threshold, but
it does not arm the red redraw and does not request an ouch voice.

## Evidence and ownership thread

| Role | Address / field | Recovered behavior |
| --- | --- | --- |
| Generic contact dispatch | `0x0063E7D0` | Verifies connected ownership and dispatches target `vtable +0x4C`. |
| Player incoming-damage override | `0x00548150` | Resolves resistance and damage lanes, then enters `0x0052F540`. It does not select a Wizard body animation. |
| Player damage/health owner | `0x0052F540` | Applies modifiers, invokes the common reaction, mutates per-player health, arms terminal state at HP at most `-10`, and conditionally requests the ouch cue. |
| Common Actor reaction | `0x00627F80` | When primary plus secondary damage is positive, writes Actor `+0x78=1` and `+0x80=1`, copies context intensity/RGBA, and clears `+0x80` when context flag bit `0x08` is set. |
| Common Actor fixed tick | `0x00624AC0` | Subtracts `0.05` from the live hit latches and clamps at zero. |
| Common Actor renderer | `0x00624B40` | Redraws the current body/action pose red with ordinary alpha `min(remaining * intensity, 1)`. |
| Wizard presenter | `0x0054BA80` | Continues to sample locomotion/action art; shield `+0x1D0` is an independent additive shell pulse. |
| Poison modifier tick | `0x00627160` | Resets the context, sets source, flags `0x88`, writes tertiary damage `0x0081C6F0`, and dispatches through `0x0063E7D0`. |
| Ouch request | call at `0x0053074A` inside `0x0052F540` | Chooses registry entry `228 + Integer(3)` and schedules the next request after inclusive `Integer(20,60)` ticks. |

The unshielded player path reaches `ActorDamageReaction` at call
`0x0052FDF1`. The renderer therefore receives an orthogonal common-Actor latch;
there is no edge from damage into the Wizard action queue. Player death retains
higher priority: once the health owner arms terminal state, the next common
tick enters the death virtual and the death presenter replaces the living body.

## Complete receiver membership

| Member / branch | Health consequence | Red body redraw | Wizard ouch | Lifecycle consequence |
| --- | --- | --- | --- | --- |
| Positive melee/contact primary damage | subtract accepted damage | 20-tick latch, refreshed by later hits | eligible after shared deadline when nonterminal | remains in current idle/walk/action state |
| Positive projectile primary/secondary damage | subtract accepted damage | same common latch | same eligibility | projectile/contact ownership remains upstream |
| Positive direct lightning/effect damage using primary/secondary | subtract accepted damage | same common latch unless context bit `0x08` suppresses it | eligible unless suppressed or terminal | effect actor keeps its own visual lifetime |
| Repeated eligible direct hit during an active latch | subtract accepted damage | refresh to one; no animation restart | request only if the independent deadline expired | current body/action program continues |
| Direct hit leaving HP in `(-10, +infinity)` | subtract accepted damage | common latch | eligible, including displayed health already at zero | player remains native-alive until `-10` |
| Direct hit leaving HP at most `-10` | subtract accepted damage | reaction is upstream but death presentation wins | no request | terminal state, then native death lifecycle |
| Poison periodic tick | subtract tertiary damage | suppressed: flags `0x88`, no primary/secondary latch | no request | can still reach terminal health |
| Zero damage | no mutation | no latch | no request | no transition |
| Healing / positive HP delta | increase and clamp through health owner | no latch | no request | no transition |
| Presentation-suppressed direct context (`flags & 0x08`) | normal accepted health mutation | intensity latch is zero, so no visible redraw | no request | gameplay consequence remains |
| Magic Shield with capacity remaining | shield absorbs without health overflow | no red body redraw; separate `+0x1D0` shell pulse | no Wizard ouch | shield hit/break path returns before health damage |
| Idle, walking, or queued cast under an ordinary hit | unchanged selector | redraws that exact current pose | same audio gate | damage does not cancel motion or action |
| Respawn / fresh run | health and player actor are reconstructed | stale latch absent | deadline/event state is new-run state | starts at idle rather than reversing death |

The Website survival graph currently exposes one PlayerWizard class across all
five element selections and both discipline values. Equipment and element
change the composed living sprites but not the common damage receiver. Every
composed body variant is therefore one presentation family, not a separate
damage branch. Remote participants use the same host-authoritative receiver;
the hit latch and audio event must be replicated rather than inferred from a
client-local health comparison.

## Exact ouch contract

Registry entries 228 through 230 are a uniform pool:

| Entry | Native path | SHA-256 |
| ---: | --- | --- |
| 228 | `sounds\\Wizard_Ouch\\SAY_OUCH1.wav` | `3e851ee873c9798923624d2b117c6fc91d656f66d7961a00935cfb182393b638` |
| 229 | `sounds\\Wizard_Ouch\\SAY_OUCH2.wav` | `509ce875de5322ebc4ee883cf2f1db9ba172b1cf22a6a6da6e31a0e2c91d12b7` |
| 230 | `sounds\\Wizard_Ouch\\SAY_OUCH3.wav` | `26cd8bea5d55a47b6476f130481bad26887f7af1cf12ec43b2989e495323e5ea` |

For an eligible hit at fixed tick `t`, the active gameplay RNG is consumed in
this order:

```text
cueIndex = Integer(3)
nextDeadline = t + Integer(20, 60)  // inclusive
```

The call uses fixed playback rate. Its non-spatial gain multiplier is:

```text
healthBand = clamp((HP_after - 25) / 20, 0, 1)
gain = 0.25 + 0.75 * (1 - healthBand)
```

Thus HP at least 45 requests gain `0.25`, HP at most 25 requests gain `1`, and
the interval is linear. The sound wrapper applies point attenuation from the
victim position and the per-sound ten-channel cap. The deadline is shared by
the active gameplay owner, not one independent cooldown per cue or renderer.
The call-site comparison is strict: a request is eligible when the current
fixed tick is greater than the stored deadline.

## Rendering and replication contract

- The host receiver owns whether damage was accepted, whether it was
  presentation-suppressed, the last ordinary-hit tick, terminal state, the
  shared ouch deadline, cue RNG, and the semantic audio event.
- A browser client samples the replicated hit latch against the authoritative
  presentation tick. It must not infer a hit from interpolated health because
  poison, healing, joining clients, and terminal transitions would be
  ambiguous.
- The red pass duplicates only the living Wizard body/equipment layers. The
  ground shadow, independent element orb/VFX, Magic Shield shell, and death
  sprites are not recolored as ordinary body art.
- The red pass uses the same texture, transform, visibility, and body order as
  the underlying pose, then applies tint `#ff0000`, normal blend, and the
  derived latch alpha.
- Audio is a retained run-scoped semantic event with the victim position and
  post-hit health gain. Snapshot interpolation must not replay or synthesize
  it, and run replacement must reset its cursor and deadline.

## Confidence and remaining boundary

High confidence: receiver and poison call graphs, common latch fields and
decay, red redraw semantics, lack of a hurt body selector, `-10` terminal
threshold, cue pool, draw order, inclusive delay, strict deadline comparison,
health-volume formula, and suppression of poison/terminal/healing requests are
instruction-backed and agree with the existing contiguous Wizard capture.

Magic Shield's additive pulse is independently live-captured and documented in
`native-animation-state.md`. Implementing its activation, mana, capacity,
break, and right-click input is intentionally not part of ordinary player
damage presentation; that work must enter through the native skills system.
No browser limitation requires an approximation for the ordinary red redraw or
three exact WAV cues.
