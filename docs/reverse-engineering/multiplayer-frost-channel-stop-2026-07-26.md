# Multiplayer Frost channel stop — 2026-07-26

## Scope

This note records the pre-fix root cause for issue #55 from beta.18 WAN
testing:

> A remotely replayed Frost Jet keeps `sounds\iceloop__loop` active after the
> caster releases primary input.

Frost Jet is the Water primary (`selection_state=0x20`, transport
`skill_id=32`, progression spell `1012`). Its dispatcher is
`0x00543860`, and its cone query is `0x00641B10`.

## Stock audio lifecycle

Headless Ghidra tracing against the retail executable established the stock
loop owner and stop edge:

| Event | Native call site | Return | Audio object |
| --- | --- | --- | --- |
| Frost loop start | `0x00549BB2` | `0x00549BB7` | registry `+0x182C`, `sounds\iceloop__loop` |
| primary transition comparison | `0x005496E5` | — | actor current primary at `+0x270`, previous primary at `+0x274` |
| Frost loop stop | `0x00549725` | `0x0054972A` | registry `+0x182C`, `sounds\iceloop__loop` |

The transition block first calls the Frost stop routine when selecting Water;
that initial stop is harmless at a zero refcount. The dispatcher then starts
the loop. On a normal local release, the next stock `PlayerActor` tick sees
the primary transition `0x20 -> 0`, calls the same stop routine a second time,
and returns the loop refcount to zero.

This is a native transition edge. The correct multiplayer replay must present
released input to a stock remote-actor tick; calling the audio routine
directly would bypass stock ownership and refcount behavior.

## Live beta.18 baseline

The loopback probe used the isolated `sfx` pair on UDP ports `48611/48612`,
with audio enabled. It traced `SoundLoop::Start` at `0x00408320` and
`SoundLoop::Stop` at `0x00408350` on both processes, filtered to the Frost
return sites and registry object.

For a client cast observed by the host:

| Observation | Caster/client | Observer/host |
| --- | ---: | ---: |
| Frost start monotonic ms | `344385843` | `344385906` |
| harmless selection stop count | `1` | `1` |
| release stop monotonic ms | `344387546` | absent |
| final Frost loop refcount | `0` | `1` |

Wall-clock log edges make the transport result unambiguous:

- `20:12:28.182`: the caster's stock release-stop edge ran.
- `20:12:28.217`: the host received
  `Multiplayer remote cast input release` for the same cast sequence.
- `20:12:28.232`: the host retired the replay as
  `cast complete (remote_input_released)`.
- Through the end of the seven-second observation window, the observer had no
  second Frost stop call and its Frost loop refcount remained `1`.

The release reached the observer 35 ms after the caster's native stop, within
the 50 ms cast snapshot interval. This rules out a late snapshot and the
three-second input-stall timeout. The replay retired from the explicit release
packet; the native stop edge was missing.

Evidence:

- `/mnt/d/codex-evidence/spell-fx-20260726/baseline/frost-stop-client-to-host.json`
- `/mnt/d/codex-evidence/spell-fx-20260726/baseline/logs/client-solomondarkmodloader.log`
- `/mnt/d/codex-evidence/spell-fx-20260726/baseline/logs/host-solomondarkmodloader.log`

## Root cause

Remote cast input is written and consumed on opposite sides of the stock
actor tick:

1. `PlayerActorTickHook` asks
   `OngoingCastShouldDriveSyntheticCastInput()` before calling the stock actor
   tick, then writes that result to the gameplay cast-intent and mouse-left
   fields.
2. The beta.18 implementation returns `true` unconditionally for unbounded
   held primaries such as Frost and Air once startup has completed. It does
   not inspect `remote_input_release_requested` or
   `remote_input_timed_out`.
3. `ProcessPendingBotCasts()` runs after the stock actor tick. It reads the
   received release state, waits two processing ticks, and retires the replay.
4. `FinishBotCastNativeLifecycle()` writes both the current and previous
   primary skill IDs to zero.

Consequently, the stock tick immediately before retirement still sees held
input. Retirement then changes the actor directly from `(current=0x20,
previous=0x20)` to `(current=0, previous=0)`. The following stock tick sees no
transition, so `0x00549725` never runs and the remote Frost loop remains
referenced.

### Input-only correction falsified

The first correction made the pre-stock input rule return `false` for an
active remote unbounded held primary after release. A Release build then ran
five additional client-to-host trials with `SDMOD_DISABLE_AUDIO=1`; the
traces remained active while the stock BASS device was suppressed.

All five trials still missed the observer's second stop call and ended with
the observer Frost refcount at `1`. For example, trial 1 recorded the caster
release stop at monotonic `344751453`, the host received the release at
`20:18:32.100`, and replay cleanup ran at `20:18:32.115`, but no host Frost
stop appeared.

That result exposed the second half of the same native edge. Before the stock
tick, remote replay also reapplies its authored selection state and retains
the control-brain target. The stock path at `0x0054964A` can therefore select
Frost again even when synthetic mouse input is low, before the
current/previous comparison executes. The existing bounded Earth release path
already prevents this reselection by clearing the authored control-brain
target and setting its state ID to the ordinary unknown/idle sentinel for the
release tick. Unbounded held remote primaries lacked the equivalent release
edge.

Input-only attempt evidence:

- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/frost-input-only-attempt-5x.json`
- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/frost-input-only-logs/client-solomondarkmodloader.log`
- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/frost-input-only-logs/host-solomondarkmodloader.log`

### Input plus idle control brain correction falsified

A second correction combined released synthetic input with an idle authored
control brain before the stock tick. Five more audio-disabled client-to-host
trials still produced only the harmless initial stop on the observer. The
observer refcount remained `1` in all five trials, while the caster recorded
its real release stop each time:

| Trial | caster release stop ms | observer stop count | observer refcount |
| ---: | ---: | ---: | ---: |
| 1 | `345067421` | `1` | `1` |
| 2 | `345075328` | `1` | `1` |
| 3 | `345083265` | `1` | `1` |
| 4 | `345091125` | `1` | `1` |
| 5 | `345098984` | `1` | `1` |

The host received each explicit release and retired each replay two
post-release processing passes later. In trial 1, for example, release arrived
at `20:23:48.091` and cleanup ran at `20:23:48.094`. The failure therefore
remained a missing stock transition edge, not transport latency.

Focused disassembly of the stock transition path identified the remaining
precondition:

1. `0x00549027` tests actor `+0x160`, the animation-drive state. A nonzero
   value sets the transition guard for the tick.
2. `0x00549046` tests actor `+0x1EC`, the no-interrupt flag. A nonzero value
   sets the same guard.
3. `0x005495F2` tests that guard. When set, control jumps directly to the
   current/previous comparison without clearing or selecting a current
   primary.
4. Only with a clear guard does `0x00549602` write current primary `+0x270`
   to zero before the optional selection at `0x0054964A`.
5. `0x005496E5` then compares current and previous, reaching the Frost stop at
   `0x00549725` for the required `0x20 -> 0` transition.

On the first stock tick with remote input low, `+0x160` and `+0x1EC` still
describe the preceding held frame. The early transition block therefore
skips the current-primary clear. The spell handler later in that tick consumes
released input and clears those fields, but replay settlement can retire the
cast before another stock tick. Retirement writes both current and previous
primary IDs to zero, erasing the edge.

Evidence:

- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/frost-two-tick-attempt-5x.json`
- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/frost-two-tick-logs/client-solomondarkmodloader.log`
- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/frost-two-tick-logs/host-solomondarkmodloader.log`
- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/dump_frost_transition.py`
- `/mnt/d/codex-evidence/spell-fx-20260726/investigation/find_frost_latch_writes.py`

## Fix contract

Once a remote-controlled unbounded held primary has become active and its
release or timeout state is observed,
`OngoingCastShouldDriveSyntheticCastInput()` must return `false`. The next
stock remote-actor tick must also run with the authored control brain idled,
animation-drive state `+0x160` clear, and no-interrupt flag `+0x1EC` clear.
Those are the native local-release preconditions: stock can clear the current
primary, consume the `0x20 -> 0` edge, and stop the loop before the existing
post-tick settle logic retires the cast.

This should be a held-primary lifecycle rule, not a Frost audio special case.
Bounded held primaries keep their existing explicit release-edge path, and
per-cast projectiles remain unaffected.

Post-fix acceptance is five client-to-host loopback trials in which both
processes record exactly one real Frost start and release stop, both final
loop refcounts are zero, and observer stop latency is no more than one 50 ms
snapshot interval relative to the caster stop.

## Initial release-edge validation

The held-primary lifecycle correction passed five audio-disabled
client-to-host trials. Each process recorded one Frost start and two stock
stop calls (the harmless selection stop plus the real release stop), and every
final loop refcount was zero.

| Trial | caster release stop ms | observer release stop ms | latency ms |
| ---: | ---: | ---: | ---: |
| 1 | `345794593` | `345794640` | `47` |
| 2 | `345797343` | `345797390` | `47` |
| 3 | `345800078` | `345800093` | `15` |
| 4 | `345802750` | `345802796` | `46` |
| 5 | `345805375` | `345805421` | `46` |

All five latencies are within the 50 ms snapshot interval. The launch record
has `audioDisabled=true`; both logs confirm stock BASS initialization was
suppressed, so validation relied exclusively on the instrumented native stop
edge.

Evidence:

- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix/frost-stop-client-to-host-5x.json`
- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix/logs/client-solomondarkmodloader.log`
- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix/logs/host-solomondarkmodloader.log`

## Registry revalidation and remaining latency edge

The permanent native-audio registry then re-ran the same lifecycle without
temporary function traces. It proved the refcount correction, but a longer
four-trial sample caught one latency failure:

| Trial | caster stop ms | observer stop ms | latency ms |
| ---: | ---: | ---: | ---: |
| 1 | `350436937` | `350436968` | `31` |
| 2 | `350439406` | `350439453` | `47` |
| 3 | `350441796` | `350441843` | `47` |
| 4 | `350444250` | `350444328` | `78` |

Trial 4 provides exact causal timing. The caster's stock loop stop ran at
`21:53:24.858`, but the AppMain-owned transport did not send the explicit
release packet until `21:53:24.886`, 28 ms later. The host applied that packet
at `21:53:24.917`, then the remote stock actor produced the stop at
`21:53:24.934`. No app-thread tick-gap diagnostic occurred in that interval;
the observed 78 ms is therefore product scheduling, not attributed external
load.

Two ordinary scheduling boundaries remained:

1. the local `PlayerActor` stock tick could stop the caster loop after the
   current AppMain transport pass, leaving release transmission for the next
   AppMain pass; and
2. `ApplyRemoteCastPacket()` updated `BotCastInputState` immediately, but the
   remote stock-tick path normally copied that state into `ongoing_cast` only
   in its post-stock `ProcessPendingBotCast()` pass.

The durable correction is still a held-primary lifecycle rule. After each
local stock player tick, the gameplay transport owner must flush an active
cast release immediately when input is no longer held. Before each remote
stock actor tick, the replay must sample the matching `BotCastInputState`
release/timeout state directly. This removes both extra AppMain/actor passes;
the existing stock transition still owns `SoundLoop_Stop`.

Evidence:

- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-registry/frost-loop-lifecycle-5x.json`
- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-registry/logs/client-solomondarkmodloader.log`
- `/mnt/d/codex-evidence/spell-fx-20260726/post-fix-registry/logs/host-solomondarkmodloader.log`
