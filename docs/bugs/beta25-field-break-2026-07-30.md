# beta.25 owner field break

Date: 2026-07-30

Status: root causes established from the owner topology; corrective validation
is recorded below

## Scope and evidence boundary

The owner ran `v0.1.0-beta.25` on the production topology: Home PC hosted,
client B joined through the desktop launcher, lobby, and Steam broker, the
client selected Water, the host selected Air, and client B completed the
Solomon Dig interaction.

The investigation used only the supplied read-only snapshots:

- the 702,296-byte host loader log;
- crash submission `b925856f-...zip`, which contains client B's loader log,
  crash log, and one 191,218,636-byte minidump; and
- crash submission `fbf23d97-...zip`, which contains the host loader log but no
  crash log or minidump.

The original inputs and their SHA-256 hashes are inventoried under
`/mnt/d/codex-evidence/fieldbreak25-20260730`. No owner installation,
production website, or production database was accessed.

## Findings before changes

### 1. The client-loading delay is Steam gameplay starvation

The host entered `loading_boneyard` at 08:51:04.501 and started the run-loading
barrier at 08:51:04.888. At 08:51:06.908 its Steam gameplay queue reported
sustained pressure with two reliable packets retained and 64 disposable
packets dropped. Client B did not receive the authoritative run entry until
08:51:22.950 and entered its loading scene at 08:51:22.955.

That is an 18.449-second host-transition-to-client-transition delay. Once the
client received the run entry, native loading and barrier convergence
completed normally: client B released at 08:51:28.403 and the host released at
08:51:29.532.

The application queue introduced this delay. Its proactive Steam route gate
stopped every gameplay packet when estimated route queue time reached 250 ms,
kept the peer limited until the estimate dropped below 50 ms, and stopped
examining later packets for that peer after the first blocked packet. A fresh
reliable `State` packet therefore waited behind bulk world traffic even though
it carried the run-entry and wave-control state needed to make forward
progress.

The same starvation became one-way liveness failure later in the session.
Client B's last received host gameplay packet was at approximately
08:52:48.897. At 08:53:18.897 it timed the host out at exactly 30,000 ms even
though its Steam keepalive had succeeded 265 ms earlier and the Steam route
was still connected.

Root cause: the beta.25 semantics-aware queue preserved freshness within a
packet family, but its route-pressure gate still treated all gameplay as one
priority class and one per-peer FIFO. Current run control could be starved by
bulk state.

### 2. Both living humans were explicitly respawned

The completed-wave command introduced for synthetic participant parity did not
mistake a human for a Lua participant. It had a separate unconditional local
human path on every peer:

1. `RefreshHostWaveRespawnCommand` published an epoch for every completed
   wave;
2. `TryApplyWaveRespawnCommand` first processed host-owned synthetic
   participants and then always called `TryRespawnLocalPlayerAt`; and
3. `TryRespawnLocalPlayerAt` always cleared input, restored HP and mana, wrote
   the Arena spawn coordinates, cleared death fields, and rebound the actor's
   grid cell. It never checked whether the actor was dead.

The owner logs record the consequence directly. Client B logged
`Respawned local multiplayer player` at 08:52:07.233 and applied wave-respawn
epoch 1 at `(1276.097534, 2238.820068)`. The host published epoch 1 and logged
the same local respawn at 08:52:08.332. Both actors were alive before that
boundary.

Root cause: the beta.25 wave-respawn contract deliberately reset every party
member, an old rule documented by the synthetic parity work. That rule is
invalid. A wave command may acknowledge a completion epoch for every peer, but
the respawn primitive may mutate only a participant whose live native HP is
zero or below.

Binding rule:

> On wave completion, only dead participants may be returned to spawn and
> respawned. Living participant positions, resources, input, cast state,
> animation state, terminal state, and grid registration must remain
> untouched.

The rule applies equally to local humans and host-owned synthetic
participants. The dead synthetic same-actor respawn acceptance remains
required.

### 3. Water was stock per contact; the apparent spike was aggregation across
targets and frames

The `a21e77f` direct-damage gate hypothesis was tested and rejected:

- a remote human participant is registered with
  `ParticipantControllerKind::Native`;
- the Water damage-context gate is authorized only on the host for
  `ParticipantControllerKind::LuaBrain`;
- packet-driven remote native damage against replicated run enemies is
  suppressed before the native damage call; and
- the local client owner follows the untouched slot-zero native path.

Client B's exact native observations identify Water as skill 32 and accumulate
in 0.025 HP contacts. The host's accepted claims preserve a continuous
authoritative before/after chain and are all integer multiples of 0.025. For
example, the first target transitions from 2.500000 to 2.450000 and then from
2.450000 to 2.099998. No unclaimed native decrement appears between accepted
claims.

Water is a continuous cone. During the owner's cast it contacted several
enemies in parallel and the network claim path combined multiple 0.025
contacts into values such as 0.050, 0.075, 0.200, and 0.350 before applying
them on the host. Those packet totals looked like high per-hit damage but did
not add a second damage path.

Root cause of the symptom: packet-level aggregation obscured the stock
per-contact value while the multi-target continuous cast produced many valid
contacts. The permanent owner-flow regression must therefore observe the
pre-aggregation native contacts as well as the authoritative HP delta and fail
unless every Water contact is the stock 0.025 value on both peers.

## Crash classification

### Client B: confirmed same-tick PlayerWizard teardown/use

Crash `b925856f` is a `0xC0000005` null read. The dump records:

- faulting runtime address `0x00E19A8C`, static retail address `0x00529A8C`;
- `ECX=0`, `ESI=0x171DEC20`; and
- a stack returning through the stock application tick called by
  `DetourAppMainTick`.

The matching retail image and RTTI identify `0x171DEC20` as a
`PlayerWizard`. Headless decompilation shows `0x00529A8C` dereferencing a
member reached from the wizard during the stock object tick.

The client log supplies the causal ordering. At 08:53:18.897 the application
declared the host timed out. At 08:53:18.903 it dematerialized remote actor
`0x171DEC20`. At 08:53:18.904 the stock tick dereferenced that same actor and
faulted.

`PumpGameplayMainThreadWork` drained participant-destroy requests before the
original retail application tick. Root cause: transport teardown invalidated a
remote `PlayerWizard` that the current stock tick still intended to traverse.
Participant destruction must run only after the stock application tick.

### Host: confirmed process-detach worker-destructor fast fail

Crash `fbf23d97` reports exit `0xC0000409`, has no crash log, and has no
minidump. The host continued to tick normally through 08:53:37.839; the
launcher recorded termination at 08:53:39.686.

The absence of an exception artifact is consistent with the failure occurring
during DLL/CRT process detach after normal game termination. beta.25 still
owns namespace-static joinable `std::thread` objects for the asynchronous
logger and network telemetry writer, plus the local-UDP ingress worker on that
backend. `DllMain` intentionally skips the ordinary blocking shutdown path
when Windows is terminating the process. Destruction of any still-joinable
`std::thread` calls `std::terminate`, producing the observed
`0xC0000409` after the crash handler's useful lifetime.

Root cause: background workers with destructor-enforced join semantics were
reintroduced after the loader had already adopted explicit Windows thread
handles for process-detach safety. All three workers must use explicit handles;
ordinary unload still signals, joins, and closes them, while process
termination cannot invoke a terminating C++ thread destructor.

## Corrective design

The field-break correction has five narrow foundations:

1. Wave-respawn targets carry observed current HP and the low-level native
   primitive re-reads HP immediately before any mutation. Living local and Lua
   participants acknowledge the epoch without clearing input, changing
   resources, moving, or rebinding.
2. Participant-destroy requests are drained only by
   `PumpGameplayPostStockTickWork`.
3. Steam gameplay traffic has a dedicated reliable control channel. Current
   control may make one bounded send attempt during route pressure while bulk
   work remains paced and replaceable; one blocked bulk packet no longer hides
   later control work.
4. Logger, telemetry, and local-UDP worker ownership uses explicit Windows
   thread handles rather than namespace-static `std::thread` destructors.
5. The fresh-profile real-flow preflight exposed a separate deterministic
   quick-start failure before either peer reached the hub. The control-scheme
   picker action was dispatched 26 times against one retiring stock UI owner
   in under a second, followed immediately by a null-call fault at static
   retail `0x005D7FD3`. The join flow now records the picker owner when its
   one semantic action is queued and cannot dispatch against that owner
   again. A failed queued dispatch clears the record; observing a different
   surface retires it. This preserves retry for a genuinely new picker
   instance without invoking a completed stock surface twice.

The owner-flow harness permanently selects client B as the Solomon
interactor, client Water, host Air, and continues from wave 1 into wave 2. It
records both local PlayerWizard positions immediately before and after the
completion boundary, exact Water contacts and authoritative HP changes, and
wave-2 convergence. It uses only mission ports 50911/50912 and launches with
`SDMOD_DISABLE_AUDIO=1`.

## Focused permanent regression

The permanent defect-class verifier is
`tools/verify_multiplayer_wave_boundary_respawn.py`. It does not replay the
tutorial. It copies the repository-owned
`tests/fixtures/savegames/fieldbreak25_existing_wizard/solomondark` fixture
into separate writable host and client save roots, launches the normal
quick-start join flow with launcher Lua automation disabled, and asks the host
to start a generated Boneyard through the semantic `sd.hub.start_match`
surface.

The fixture was created by an isolated `fb25` test instance, not copied from
an owner installation. Its stable SHA-256 inputs are:

- `darkdata.cfg`:
  `0a9dd9c222b61df4930495aea50a65ebe2e057811092080451fee94a6594ea06`;
- `Region0._cache`:
  `b161e5ee2db912f55b6086b562f1dff797e81176a69c887fc1eb2324bd0bf15e`.

The Start Match seam is distinct from the older test-run shortcut. Exact
retail decompilation and a live isolated probe established that pending level
kind `1` selects a newly generated Boneyard before the existing stock
`Gameplay_SwitchRegion` call. The retained Ghidra output is under
`/mnt/d/codex-evidence/fieldbreak25-20260730/ghidra-fb25-exact`.
After both peers release the run-loading barrier, the verifier queues the
idempotent stock `ArenaStartWaves` entrypoint once. This removes dependence on
which peer happens to publish the first wave edge while retaining the real
`wave.txt` schedule and native spawner; no test wave override is installed.

Focused run `fb25-wb34` proved the corrected boundary before landing:

- the host was alive at `(1550, 550)` on both sides of wave-1 completion;
- owner and observer displacement across the boundary were both exactly
  `0.0`, and both actor identities were preserved;
- the dead client retained its owner and observer actor identities and
  converged exactly on the host-authored respawn position
  `(985.219299, 150)`;
- wave 1 completed `0.430` seconds after the controlled final stock enemy
  death; and
- both peers converged into wave 2, spawning phase, with one live enemy and
  three remaining to spawn.

The verifier uses a fixed stock run seed and holds one stock wave-1 enemy
alive until the corpse observation is complete. Test-only survival support
keeps the intended living participant alive; it does not replace the
wave-completion publisher, wave schedule, respawn command, or same-actor
respawn primitive. The complete preliminary result is
`/mnt/d/codex-evidence/fieldbreak25-20260730/fb25-targeted34-result.json`.

## Retained synthetic respawn acceptance

The `a21e77f` acceptance remains a native-combat proof: it uses no HP write,
forced enemy-death call, or test wave override. An ordinary surviving fighter
must complete the retail schedule; the dead synthetic participant must then
return alive on the same actor and progression on host and client B, with
full resources, native registration, coherent nameplate state, shared
targetability, and a later authoritative enemy-HP edge.

The old acceptance also required the respawned bot to be near each peer's
local player. That assertion encoded the beta.25 defect: it passed only when
the same completed-wave seam teleported both living humans to the respawn
area. The corrected acceptance instead requires the bot's post-respawn
placement to converge between host and client B while allowing living local
players to remain where gameplay left them.

Run `fb25-fieldbreak25-pre3` passed that corrected contract on ports
50911/50912. Ember preserved both peer-local actor/progression identities,
reached full HP/mana, converged to zero peer placement delta in traversable
Arena space, was targeted through shared network actor IDs, and then produced
14 authoritative Air damage edges totaling `0.350001` HP. The launcher-reported
PIDs `3424` and `26404` were stopped by exact executable path. The result and
visual capture are under
`/mnt/d/codex-evidence/botcombat-20260729/runs/fb25-fieldbreak25-pre3`.

## Full-flow harness limitation

The earlier fresh-profile real-flow calibration attempted to drive the stock
menus, host Start Match UI, client B's Solomon Dig, and subsequent combat.
The retained `fb25-loopback-calibration5..13` evidence, plus the later
isolated `fb25-targeted1..33` diagnostics, repeatedly stopped before a usable
wave-boundary sample, most often at the host
`wait_scene=testrun` calibration boundary. Those runs did identify and fix a
repeat dispatch against one retiring control-picker owner, and they improved
loading/hub state observation, but they are not wave-boundary acceptance.

Per the owner correction, that path was not iterated after the focused
regression passed. The landing runs the full loopback variant once, records
any remaining UI-driving gap as a harness limitation, and does not treat such
a gap as contradictory evidence against the direct two-instance wave
boundary proof. NFO is unnecessary unless a WAN-specific claim is required;
none is required for this local defect.

## Validation

The released beta.25 before-fix loopback attempt and the first corrective
attempt are preserved under `fb25-loopback-prefx-beta25` and
`fb25-loopback-postfix`. Both stop before the shared hub at the repeatable
control-picker fault described above; both clean only their exact staged
processes and ports. They are preflight failure evidence, not wave-boundary
acceptance.

Landing evidence is written without changing the tested commit:

- exact-SHA source/Python/static-RE/launcher/Release totals:
  `/mnt/d/codex-evidence/fieldbreak25-20260730/landing-validation.json`;
- exact-SHA focused boundary result:
  `/mnt/d/codex-evidence/fieldbreak25-20260730/fb25-targeted-final-result.json`;
- exact-SHA synthetic respawn result:
  `/mnt/d/codex-evidence/botcombat-20260729/runs/fb25-fieldbreak25-final-sha/result.json`;
- the one permitted final full-flow loopback:
  `/mnt/d/codex-evidence/fieldbreak25-20260730/fb25-fullflow-final/result.json`.

The CDB crash transcript is
`/mnt/d/codex-evidence/fieldbreak25-20260730/fb25-client-cdb-analysis.txt`.
The landing manifest records the exact commit, test floors, Release
warning/error counts, push state, and CI conclusion. No release is created by
this landing.
