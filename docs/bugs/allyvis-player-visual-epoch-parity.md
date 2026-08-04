# Player visual epoch parity investigation

## Scope

This investigation covers the beta.32 reports grouped under `allyvis`:

1. live ally health rows disappear after a room/scene transition;
2. run teardown can leave duplicated wizard presentation and detached staff visuals;
3. the owning client's local HP presentation can disagree with the host's
   authoritative replicated HP.

The untouched baseline is origin `main` at
`b076478ac1698ff21e95facde5a46a6a4513cd65`. All live work used disposable
`avz-*` instances, local UDP ports `52171` through `52178`, and a two-process
host/client pair with the Lua bot `Ember`. Audio was disabled. The staged game
processes were stopped only by the exact PIDs and executable paths returned by
the launcher.

## Untouched-baseline evidence

The evidence root is `/mnt/d/codex-evidence/allyvis-20260804/`.

- `baseline-bot-lifecycle/` proves that the host, client, and `Ember` all
  materialize in the shared hub and the initial run.
- `baseline-pair-bot/` applies a native seven-point hit to the client's host
  clone while the launcher's test god-mode setter is active. The host captures
  authoritative life `43/50`; the client applies correction sequence 1 and the
  host renders 86 percent, but the next acknowledged owner frame republishes
  `50/50`. Both peers then report 50.
- `baseline-exit-pair-bot/` repeats the same native hit without god mode. The
  client's native local probe and the host's remote native probe converge near
  `43.04/50`, establishing that normal stock damage is not itself overwriting
  the correction. This is the control for the authority-fence diagnosis.
- `baseline-hub-pair-bot/` drives both humans to death while `Ember` remains
  alive. The retained spectator scene visibly contains duplicated wizard bodies,
  crossed staff geometry, and an orb separated from its wizard. This is a
  transition-state reproduction, not yet the final clean-hub acceptance path.
- `baseline-hub3-pair-bot/` moves both humans from the shared hub into the
  Librarian private room. On the host, the client and `Ember` remain connected,
  runtime-valid, alive at `50/50`, and present in the durable two-member remote
  roster while both native actor addresses are zero. On the client, the host is
  materialized but `Ember` remains alive with actor address zero. The paired
  `manual-room-host.png` and `manual-room-client.png` captures show the ALLY rows
  disappearing with those actor bindings. The launcher then stopped PIDs 14484
  and 28316 only after both executable paths matched their `avz-hub3-*` stages;
  every reserved UDP port bound successfully afterward.

The live logs establish the HP ordering precisely:

1. host-native damage changes the client's clone from 50 to 43;
2. the host queues authoritative correction sequence 1 at 43;
3. the client logs successful application at 43;
4. the host world indicator renders 86 percent;
5. an ACK-bearing owner frame restores 50, and the host renders 100 percent.

## Root causes

### 1. Participant presentation has no scene-epoch identity

World actor snapshots already carry `scene_epoch`, and
`RefreshWorldSceneTracking` advances it when the semantic scene, gameplay
scene, world, or region identity changes. Participant `StatePacket`,
`ParticipantFramePacket`, `ParticipantRuntimeInfo`, and
`ParticipantTransformSample` carry only `run_nonce` plus broad scene intent.
Two different native worlds that are both `Run`, or two incarnations of the
shared hub, are therefore the same participant timeline.

`AppendParticipantTransformSample` clears history only when `run_nonce` or
scene intent changes. It can interpolate or replay presentation sampled from a
destroyed world onto the replacement actor in the next world.

### 2. Durable participant state and actor-local presentation state are mixed

`ParticipantEntityBinding` stores durable replicated presentation next to
actor-local materialization, death, equipment-reconcile, animation, cast, and
native-vitals checkpoints. `ResetParticipantEntityMaterializationState` clears
the actor and transform target, but leaves the replicated presentation cache,
equipment retry state, death attachment state, and other actor-local applied
state intact.

Run termination makes this worse deliberately. `ResetParticipantRuntimeForRunTermination`
copies the outgoing run position, appearance, visual-link identities, and staff
attachment identity into a new transform sample, relabels that sample as the
default shared-hub intent, and installs it as the only history row. A new hub
actor can therefore be created from a sample whose position and equipment
belong to the dead run actor. The detached staff/orb and duplicate-body symptoms
are consequences of that invalid cross-world handoff, not independent renderer
bugs.

### 3. A vitals delivery ACK is treated as authoritative convergence

The host clamps owner frames while a
`pending_participant_vitals_corrections_by_participant` entry exists. In
`NormalizeParticipantFramePacket`, any ACK at or beyond the correction sequence
erases that entry before verifying that the ACK-bearing frame's HP agrees with
the correction. The frame is then accepted unmodified.

That means a client can successfully write authoritative HP and ACK delivery,
then have another native writer restore stale HP before its next refresh. The
ACK-bearing stale value immediately becomes the host's replicated truth. The
test god-mode setter provides a deterministic reproduction of this race; the
same contract is unsafe for any stock or modded native writer. Delivery and
convergence are different states.

### 4. Ally-row identity is derived from ephemeral actor bindings

`BuildGameplayAllyHudRows` starts from `g_participant_entities` and drops every
participant whose current binding has no actor address or gameplay slot. Scene
preparation intentionally abandons every outgoing actor and clears those
addresses. The durable multiplayer roster still says that the remote humans
and bots are connected and alive, but the ally-row presentation temporarily
has no source of identity. Row survival therefore depends on the replacement
actor materializing and its stock control brain registering another row in the
same native frame.

The existing analyzed retail program also fixes the native seam precisely:
`FUN_005CF480` at `0x005CF480` is a `__thiscall` append taking the gameplay
object, the stock label glyph address, and a float HP ratio, in that order. It
grows the gameplay health-bar array at count offset `0x1C20`, writes the glyph
pointer at row offset `+0`, writes the ratio at `+4`, then increments the
count. `FUN_0052C910` calls it after computing current/max HP and passes the
UI-bundle ALLY glyph at global `0x008199E4` plus `0x38`.
This lets one durable participant-presentation roster continue feeding the
stock renderer without inventing a replacement widget.

The first post-change live launch also proved why the exact argument order is
part of this finding. A provisional ratio-first declaration wrote float
`1.0` (`0x3F800000`) into row offset `+0`; the client then faulted at
`0x005D34C9` when the stock renderer treated that field as a glyph pointer and
read `+0x94`. The headless instruction dump of `FUN_005CF480` shows
`[ESP+0x10]` copied to row `+0` and `[ESP+0x14]` loaded as a float into row
`+4` after the function's three register saves. The stock call site pushes the
computed ratio first and the glyph pointer last, establishing the typed call
as `(gameplay, glyph, ratio)`. The failed launch dump and read-only Ghidra
outputs are retained in the campaign evidence.

## Required foundational correction

The fix must introduce one participant-presentation epoch contract rather than
special cases for the top HUD, nameplates, or staff attachment:

- every locally published participant presentation is tagged with a monotonic
  scene epoch derived from the native scene identity;
- transform history cannot interpolate across that epoch;
- a binding records the epoch of the actor it materialized and fully resets all
  actor-local applied presentation state when the actor or epoch changes;
- run termination does not relabel run coordinates or run attachment state as
  hub presentation;
- the connected/alive participant presentation roster remains durable while an
  actor is replaced, and the replacement materialization re-establishes all
  stock presentation consumers as one transaction;
- authoritative vitals remain fenced until an owner frame both acknowledges the
  correction and reports matching HP. An ACK is not itself convergence.

Regression contracts must cover epoch history separation, complete actor-local
presentation reset, no run-to-hub presentation carry, durable alive roster
identity, and ACK-with-stale-HP rejection. Live acceptance must then prove the
same host/client/bot relationships across a room transition, a stock Game Over
return to hub, and induced client damage with matching local and remote numeric
probes plus backbuffer captures.
