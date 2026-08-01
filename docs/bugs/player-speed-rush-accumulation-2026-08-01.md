# Player speed and Rush accumulation (2026-08-01)

## Owner report

During the BOTENDURE endurance match, the host became visibly faster over the
run and eventually appeared to zoom. The accepted R25 classification retained
this as the open hard finding `Rush-associated movement-speed accumulation`.
This pass treats the observation as a real defect and asks which speed term is
growing, who writes it, and what the executable says Rush should do before
changing code.

## Evidence consumed

The immutable source evidence is under
`/mnt/d/codex-evidence/botendure-20260731/`. The derived, reproducible position
analysis is written by `tools/analyze_movement_speed_timeline.py` to
`/mnt/d/codex-evidence/speedpass-20260801/prior-evidence/`.

- R20 contains no Rush pick. Its moving host samples are bounded: quarter
  medians are 76.49, 92.06, 99.39, and 94.59 units/second; maximum 118.23.
- R25 contains no Rush pick. Its moving host quarter medians are 61.39, 50.95,
  64.90, and 62.78 units/second; maximum 160.63. This accepted long run does not
  itself show monotonic speed growth.
- The original speed finding came from the R21 game-barrier run. The host chose
  Rush (skill 67) at native ranks 1 and 2. The host reached 226.62
  units/second, while the client, which did not choose Rush, reached 133.93.
  R21's host moving-sample p90 was 197.02 versus the client's 114.29.
- The older R21 `speed-growth-analysis.json` compared all samples, including
  stationary hub, pause, and level-up intervals, and therefore reported a
  misleading first-quarter median of zero. The corrected moving-only curves
  still confirm a large Rush-associated host/client difference, but they do
  not support per-tick exponential compounding.
- The diagnostic state embedded in the same logs exposes the actual growing
  value. R21's host reached 11,107 pending scripted movement frames and the
  client reached 10,715. At 60 player ticks per second, each is roughly three
  minutes of stale held movement. R25 reproduced the same class without a
  single Rush pick: host 7,368 and client 3,254. R20's shorter run reached 102
  and 38. The derived JSON and `movement-input-backlog.csv` retain every
  sampled value and source line.

Position deltas are an observational proxy, not the native speed value. Turns,
collisions, teleports, pauses, and sample cadence can lower or contaminate them.
The controlled baseline and fixed live runs therefore record the native terms
alongside fixed-input position steps.

## Native design contract

Rush is native skill catalog row 67. The executable-owned catalog says:

- it is a learned passive with ranks 0 through 8;
- `mValue` is the total rank value, not a delta: 0, 10, 20, 25, 30, 35, 40,
  45, and 50 percent;
- `mConcentration` is 25 percent;
- it has no duration or expiry field; and
- the UI text is `Speed: +%d:mValue%%%` and
  `Concentrate: +%d:mConcentration%%% Speed`.

Consequently, ranked Rush is an absolute factor selected from the current
rank, `1 + mValue / 100`. Concentration is a separate absolute factor,
`1 + mConcentration / 100`, applied only while Rush occupies a concentration
slot. Neither factor stacks with an earlier refresh or tick. At rank 2 the
intended concentrated factor is `1.20 * 1.25 = 1.50`; at rank 8 it is
`1.50 * 1.25 = 1.875`.

## Native representation and writers

The stock player movement tick calculates its velocity cap from four terms:

`actor + 0x120` * `actor + 0x74` * `progression + 0x90` * native global
`0x00784740`.

It then applies movement through the actor's `+0x218` move-step scale. The
important terms and writers are:

| Term | Meaning | Writers |
| --- | --- | --- |
| progression `+0x90` | refreshed movement-speed multiplier | Native progression reset `0x0065F5B0` assigns the stock 0.95 baseline. Native concentration pass `0x00661FD0`, case 67, multiplies it once by `1 + mConcentration/100`. The multiplayer remote-progression reconciler writes the replicated absolute value when a remote actor differs. |
| actor `+0x120` | native movement multiplier | Native actor/modifier lifecycle, including native transient status modifiers. The loader does not use this field for ranked Rush. |
| actor `+0x74` | native move-speed scale | Native actor lifecycle/status code. The loader reads it for bot movement and does not use it for ranked Rush. |
| actor `+0x218` | final move-step scale | Native actor construction/reset writes 1.0. The loader's local-player Rush scope temporarily writes it around the stock player tick and restores it afterward. Standalone bot materialization also seeds/restores it. |

The native progression refresh is idempotent: `0x0065F5B0` first resets
`+0x90` to 0.95, then `0x00661FD0` applies the selected concentration once.
Repeated level-up, respawn, and wave refreshes therefore do not compound this
field.

The exact-main controlled run at `20c95de` selected Rush for both owners at
ranks 0, 2, 4, 6, and 8. The stable client-owned fixed-input position-step
factors were exactly 1.0, 1.5, 1.625, 1.75, and 1.875. From rank 2 onward the
host-owned factors and displacement matched the client-owned values exactly,
and both observers converged on the owner's final position. Progression
`+0x90` changed once from 0.95 to 1.1875 when Rush became concentrated and
then stayed fixed through later ranks. Actor `+0x218` read 1.0 after every
trial. This directly rejects Rush refresh stacking, replication reapplication,
and per-tick compounding. The one host rank-zero input trial began during a
run-entry transient and is not used as a ratio denominator; the client
rank-zero trial is complete, and all later paired trials agree.

## Defect classification and cause

This is **not Rush modifier stacking**, **not replication reapplication**,
**not per-tick speed compounding**, and **not a missing cap/expiry**. Rush is
passive and has no duration. Its two speed terms have distinct jobs in the
stock movement envelope: native concentration raises the standing velocity
cap through progression `+0x90`, while the loader supplies the executable's
ranked `mValue` at the final stock human move-step seam. The measured combined
factor is the catalog's intended `ranked Rush * concentration`, with an
absolute maximum of 1.875.

The accumulating value is the scripted movement hold backlog. The public API
stores only one latest `(x, y)` direction, but
`QueueGameplayMovementHoldFrames` adds every new request to
`pending_movement_frames`. Bot Play issues a fresh one-frame request from each
`runtime.tick`. `HookPlayerActorTick` pumps that Lua event before checking the
multiplayer shared-simulation pause, while
`ScopedLocalPlayerScriptedMovementInput` consumes a frame only after that
pause check. During each level-up barrier, wave synchronization hold, or other
shared pause, the producer therefore continues at player-tick cadence and the
consumer does not run. The R21 log shows this causal ordering directly: local
actor ticks are suppressed while the queue climbs from 80 to thousands.

When simulation resumes, the only stored direction is the newest one, yet the
thousands of frames accumulated under older commands keep that direction held
for minutes. The fighter therefore remains continuously accelerated and can
continue moving after the bot's current decision no longer requests it. Rush
picks make the resulting motion more conspicuous by applying their legitimate
bounded factor, but R25's no-Rush backlog proves that Rush does not create the
growth. Position samples conflated instantaneous movement scale with an
ever-growing movement-input duty cycle.

Movement direction is level state, not an event queue. A new request must
replace the remaining hold with `frames` from now; it cannot add duration to a
single overwritten direction. Replacement makes the producer idempotent,
lets a changed direction supersede stale work, and bounds Bot Play's repeated
one-frame intent even while consumption is paused. Mouse clicks and binding
edges remain additive event queues and are outside this defect.

The consumer's failure path had the same additive assumption: after reserving
a frame, a failed native input read or write added that frame back. The fixed
contract restores the prior count only with a compare-and-exchange when the
remaining duration is unchanged. A newer published intent therefore wins and
cannot be extended by recovery of an older one.

## Correction and proof

- Replace, rather than add to, the pending scripted movement duration whenever
  a new direction is published. Release, respawn, and scene teardown continue
  to clear the same single intent. Failed application restores a reserved
  frame only if no newer duration has replaced it.
- Preserve the existing single ownership of speed terms: stock native refresh
  owns concentration and status multipliers, the loader reads the current
  absolute ranked Rush value once at the local stock move-step seam, and the
  remote-progression reconciler writes absolute replicated state. Do not
  synthesize remote movement locally.
- Contract-test replacement semantics, changed-direction ownership, failed
  consumption restoration, release/respawn clearing, rank values,
  concentration ownership, Rush restoration, and the 1.875 bound.
- Extend the retained Rush live verifier to repeat picks and refreshes across
  a shared-simulation pause, respawn, and wave boundary. Record both peers'
  native fields, pending movement duration, fixed-input position steps, and
  observer convergence. A repeating one-frame producer must remain at one
  pending frame while paused and return to zero when stopped.

The generic movement-intent publisher now stores the requested duration, and
the failed-consumption path conditionally restores rather than adds. Rush code
and balance data are unchanged.

The two-owner local Rush matrix interleaves both fighters' rank updates at 2,
4, 6, and 8. At every one of its 16 level-up pause probes, 240 repeated
one-frame publications left exactly one pending frame and cleared to zero on
resume. Both peers measured the same rank-zero-relative movement factors:
1.5, 1.625, 1.75, and 1.875. Owner and observer native contexts agreed at
every rank, and the progression movement term stayed at the single
Concentration refresh value rather than growing.

The natural wave-boundary verifier repeats the same 240-publication check
before the boundary and after the client respawn. Both peers returned to zero,
and all four native movement terms for each fighter were unchanged across the
respawn and equal in owner/observer views. Together, these gates cover skill
picks, level-up pauses, a wave transition, and a respawn without synthesizing
remote movement locally.

Matched rank 0, rank 4, and rank 8 backbuffers from both peers show ordinary
arena framing and stable player presentation without a zooming or smeared
movement state. The numeric series is authoritative for speed because a still
frame cannot measure velocity; the captures supply the owner's complementary
visual check.

Pre-fix and post-fix controlled evidence, including matched start/mid/late
screenshots from both peers, is stored separately under
`/mnt/d/codex-evidence/speedpass-20260801/`.
