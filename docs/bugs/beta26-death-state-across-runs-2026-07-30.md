# beta.26 death state across runs

Date: 2026-07-30

Status: fixed and validated; root cause was recorded before corrective code
changes

## Scope and evidence boundary

The owner reported a two-machine `v0.1.0-beta.26` session in which all
players died, the native Game Over command completed, both players returned
through the stock end menu to the still-connected lobby, and the host
continued to see the client as dead in the hub and in the next run.

The investigation started from `16d412c1ebde79bbb5b21b07dde2eec5b42cf16b`,
the then-current `origin/main` tip. It used the supplied owner log read-only
and separate staged instances. No owner installation was launched or changed.
The loopback instances used the `drst` prefix, audio disabled, and the
owner-approved UDP ports 51211 and 51212 after Windows excluded-range and
ownership checks.

Primary evidence:

- `/mnt/d/codex-evidence/beta26-owner-field-20260730/homepc-session2.log`;
- `/mnt/d/codex-evidence/deathreset-20260730/red/approved-ports-preflight.txt`;
- `/mnt/d/codex-evidence/deathreset-20260730/red/baseline-staggered-death-reset.json`;
- `/mnt/d/codex-evidence/deathreset-20260730/red/baseline-staggered-death-reset.stdout.log`; and
- staged screenshots under
  `runtime/game-over-acceptance/drst-repro3/death-reset`.

## Reproduction before changes

The permanent Game Over verifier was extended first, without changing the
runtime. It uses the repository-owned existing-wizard save fixture, launches
two normal quick-start instances, kills the client through a host-authoritative
hit, kills the host, waits for native Game Over on both peers, and advances the
host through the end menu before advancing the client. This deliberate
stagger reproduces the owner topology's relevant ordering instead of allowing
a prompt alive packet from the returning client to hide the defect.

The baseline run `drst-repro3` failed at the first post-run hub checkpoint:

- the host was in the hub and its local participant was alive at `50/50`;
- the client was still on the prior run's post-Game-Over path with
  `run_end_pending_lobby_return=true`;
- the host's materialized remote client retained `2.4510047/50` HP and native
  animation-drive state `1`; and
- the host screenshot did not show an upright client in the hub.

The later client return published fresh alive state, so this low-latency
loopback run self-healed before the second run. That does not contradict the
owner result. The owner log shows the same lifecycle gap lasting minutes:
native Game Over was dispatched at approximately 19:39:30 while the connected
client did not complete its post-run return until approximately 19:42:43 and
the next run began at approximately 19:43:30. The field report establishes
that the stale dead state survived that WAN ordering into run two; the
controlled loopback run isolates the same missing run-boundary reset before a
later peer packet can mask it.

## Root cause

`ParticipantEntityBinding::native_remote_death_epoch_active` is intentionally
durable. Once an authoritative dead presentation is committed,
`ApplyNativeRemoteParticipantDeathPresentationState` continues driving the
corpse even after the short death-presentation flag expires. That is the
required WAN guarantee: a clone which materializes late during the same run
must still become a corpse.

The durable epoch currently has only an alive-packet retirement path. Generic
entity dematerialization and rematerialization deliberately preserve it, as
required within a run. No run-lifecycle termination path clears it.

The transport half has the same missing boundary.
`NotifyLocalRunEnded` resets spectator, wave, loading, and hit-feedback state,
then changes only the local participant's `in_run`, transform, and scene
intent. It leaves every participant's life, mana, death presentation,
statuses, combat animation, and remote transform history intact. It does not
normalize remote participants at all. Consequently, a host which reaches the
hub first rematerializes the client's preserved remote binding from the last
dead runtime frame. The durable binding epoch then correctly, but in the
wrong lifecycle, drives that hub actor as a corpse.

This is not a wave-boundary respawn regression. The supplied session records
that the fieldbreak25 living-participant and dead-only respawn rules held
throughout. It is not a disconnect or lobby recreation: the Game Over
sequence retained an authenticated peer. It is not corrupt appearance data:
the loopback failure retained the expected profile, render selectors, and
visual link types. It is a missing run-generation termination transaction.

## Lifecycle boundary

The boundary is `CompleteRunLifecycleEnd`, not entity materialization and not
an individual hub, renderer, or next-run consumer. It is the common,
once-per-run seam used by native Game Over and other genuine run termination
paths before lobby return.

The required contract is:

> A committed death epoch is durable for the complete run generation,
> including delayed packets and late materialization, and is retired exactly
> when that run generation terminates. At the same transaction, every
> retained participant is normalized to out-of-run, full vitality, cleared
> combat/death/status state, and no stale interpolation history. One sanitized
> terminal pose is retained so a peer which reaches the hub first can
> materialize an upright participant before that participant sends a hub
> transform. Progression, equipment, character profile, appearance,
> connectivity, and lobby membership are preserved.

The correction must therefore add one explicit participant run-termination
reset called by `CompleteRunLifecycleEnd`. The transport reset owns replicated
participant combat/vitality state and establishes a fence against later
old-run frames while lobby return is pending. Because a test run can reuse its
deterministic generation seed, nonce equality alone is not a next-run
identity. The fence retires on the local new-run lifecycle callback, or on a
client's authenticated host entry packet carrying an active loading-barrier
contract; ordinary delayed gameplay frames cannot retire it. The native
gameplay reset owns binding-local death epochs and combat drive state. The
generic materialization reset remains unchanged so the WAN corpse guarantee
still holds within a run.

## Correction

`CompleteRunLifecycleEnd` now performs the participant reset transaction
before the rest of the run bookkeeping is cleared:

1. `NotifyLocalRunEnded` normalizes every retained transport participant to
   out-of-run, full HP and MP, no death presentation, no combat animation,
   no poison or damage multiplier, no shield residue, and no active cast or
   participant-vital correction. It clears interpolation history and retains
   one sanitized hub-intent pose.
2. `ResetParticipantEntitiesForRunTermination` clears every materialized
   wizard binding's committed death epoch, corpse attachment/drop state,
   cast and locomotion state, replicated combat drive, status reconciliation,
   and native terminal dispatch state. A writable actor is restored to its
   alive registration and full replicated vitality.
3. The terminated-run nonce fences delayed unhealthy frames from restoring
   death state while the peer is returning to the lobby. The fence is retired
   by the local new-run callback or, for a following client, only by an
   authenticated host Run packet with the active loading-barrier contract.

The reset is not called from hub materialization, renderer code, or the
wave-boundary respawn path. `ResetParticipantEntityMaterializationState`
continues to leave the committed death epoch alone, preserving late WAN
corpse delivery for the lifetime of a run.

## Corrective validation

The two-peer corrective run `drst-fix4` followed the same staggered ordering
as the red reproduction. It passed all of the following:

- the host returned to the hub while the client was deliberately held on the
  post-Game-Over path, and the host already materialized the client upright
  at full HP;
- after both peers returned, each peer observed both local and remote
  participants alive at full HP with cleared death, status, shield, and combat
  state;
- run two passed the same vitality checks on both peers, including native
  actor HP, materialization, profile, render selectors, and visual links; and
- each peer logged one run-termination reset. The host retired the one
  committed remote death epoch; the client had no host corpse epoch to retire
  in this ordering.

Evidence is under:

- `/mnt/d/codex-evidence/deathreset-20260730/green/game-over-next-run-fix4.json`;
- `/mnt/d/codex-evidence/deathreset-20260730/green/live-fix4/`; and
- `/mnt/d/codex-evidence/deathreset-20260730/green/release-build-fence-retirement.log`.

Focused regression evidence also records the fieldbreak25 contract (living
participant untouched and dead-only wave respawn), a host-owned synthetic bot
corpse followed by native wave respawn on both peers and a post-respawn damage
edge, and host-death/client-input continuity. The final landing battery and
exact-SHA live rerun are recorded in the evidence manifest.

## Secondary lobby-directory finding

The owner client's absence of a publish line is expected because only the
host publishes. An isolated host was then launched with the exact beta.26
artifacts from tag `v0.1.0-beta.26`
(`a962c86482f2d45646c4cd12cc7f005712f75e72`):

- launcher SHA-256
  `bcdbf85868b238e26caa153335579f32bf1fc5fc1dc4986ef5b491ea397f9f92`;
- loader SHA-256
  `569d5167ebcec6dd0a560c95899d8285f664560b937dae9356a9c68ba6c4da78`;
- local UDP host port 51211 with audio disabled; and
- a loopback directory endpoint, so production was never modified.

On entering the hub, the unmodified beta.26 host logged:

`Published Steam lobby after the host entered the hub; directory TTL=120s.`

The mock captured the initial `POST /api/lobbies/announce`, subsequent
heartbeats, and `DELETE /api/lobbies/51211` during exact-PID/exact-path
cleanup. This rejects hypothesis A: beta.26's host hub-entered trigger works.
Given the production service's independently established health and zero
traffic in the owner's window, the remaining verdict is hypothesis B, a
host-machine reachability/environment failure. No lobby-directory product
change was made.

The complete capture, with the ephemeral directory secret redacted, is under
`/mnt/d/codex-evidence/deathreset-20260730/secondary/lobby-announce-beta26/`.
