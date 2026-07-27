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

## Fix contract

Once a remote-controlled unbounded held primary has become active and its
release or timeout state is observed,
`OngoingCastShouldDriveSyntheticCastInput()` must return `false`. The next
stock remote-actor tick must also run with the authored control brain idled so
it cannot reselect the primary. Stock can then consume the `0x20 -> 0` edge
and stop the loop before the existing post-tick settle logic retires the cast.

This should be a held-primary lifecycle rule, not a Frost audio special case.
Bounded held primaries keep their existing explicit release-edge path, and
per-cast projectiles remain unaffected.

Post-fix acceptance is five client-to-host loopback trials in which both
processes record exactly one real Frost start and release stop, both final
loop refcounts are zero, and observer stop latency is no more than one 50 ms
snapshot interval relative to the caster stop.
