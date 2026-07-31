# Botendure owner wave

Date: 2026-07-31

Status: r18 live forensics complete; wave-boundary respawn correction under gate

## Scope

This investigation uses the owner's real two-machine topology: HomePC hosts,
workstation20 joins by the lobby ID through the desktop launcher and Steam
broker, and both local players use Bot Play For Me. It does not use a direct
transport seam, a test-only takeover path, an owner installation, or the NFO
host.

Evidence is rooted at
`/mnt/d/codex-evidence/botendure-20260731`. The `steam-r6` attempt crossed the
real launcher boundaries on both machines, created and joined one Steam lobby,
started both product processes, authenticated two members, and observed a
connected Steam route. It then failed before both peers converged in the hub.

## Product finding: deferred Lua entry failures leaked states

The workstation20 Bot Brain entry script could not read one of its modules.
The loader retried the complete deferred entry startup approximately every
tick. The captured client log contains 145 failures, followed by a Lua
`not enough memory` compilation failure and process loss. The read-only
observer loaded before the failure, but its Lua pipe could no longer return a
valid game state.

`CreateLuaStateForMod` allocates a new Lua state before it registers bindings
and executes the entry script. A failed deferred start returned that partial
state to `PollLuaSettingsReplicationChanges`. That caller logged the error and
continued without closing the state or retiring the deferred flag. The next
poll allocated another state. The ordinary initial-load caller already closes
a failed state; only the host-settings deferred path omitted the cleanup.

The correction makes a deferred entry failure fail closed for that process.
It logs the failure once, calls `CloseLuaStateForMod`, and therefore releases
the partial state and retires the deferred flag. A broken mod remains disabled
instead of consuming memory in a tick-rate retry loop.

## Harness finding: workstation20 path guard covered the wrong maximum

The failed Bot Brain module was staged at a 261-character Windows path. The
real-flow harness checked only its loading-screen asset path on workstation20,
although its local peer guard enumerated every staged Bot Brain file. The
remote check consequently accepted a layout beyond the native path budget.

The corrective harness now enumerates every Bot Brain source file at its
hashed runtime destination on workstation20 and checks the actual longest
candidate. It also uses a compact, still stage-confined `r\l` launcher layout,
bringing the observed longest runtime path below the 248-character safety
limit. The exact uploaded launcher directory is renamed only inside the
newly-owned stage, and all existing confinement and exact-path cleanup rules
remain in force.

## Harness finding: lobby ID entry can asynchronously rebuild Join Game

The first corrected-path rerun reached both launcher UIs, but client B's
controller tried to invoke `Join Game` immediately after setting the lobby ID.
The launcher was still applying the new value and temporarily had no visible,
enabled Join Game button. The preceding run succeeded only because its UI
update completed inside that timing window.

The controller now waits for a newly visible, enabled Join Game boundary after
setting the lobby ID, then invokes that exact button. This preserves the
neutral Host Game readiness check before the lobby ID exists and removes the
remaining render-timing race without using coordinates or a product seam.

## Harness finding: Windows PowerShell rejected a null replacement backup

The next rerun completed the real lobby join, converged both peers in the hub,
entered wave 1, and loaded Bot Brain successfully on workstation20. Enabling
client B's takeover then failed before the setting reached the mod. Windows
PowerShell bound `File.Replace(source, destination, $null)` to a .NET Framework
path call that rejected the null backup as an illegal path.

The remote settings transaction now supplies a stage-confined backup path,
checks that both transaction paths are new, performs the atomic replacement,
and deletes the backup after success. The first-write path remains an atomic
same-volume move. No game or launcher seam was added.

## Harness finding: client takeover was armed after combat began

The following run reached the real match with both peers healthy at the
Solomon completion boundary. The harness then waited for enemy
materialization before requesting either takeover. In less than 1.3 seconds,
client B fell from 50 HP to 41 HP. The settings request reached Bot Brain while
combat continued, but client B died before the controller could acquire a
living local player. Bot Brain correctly retained `desired=true` and remained
inactive for the dead player.

This was an endurance sequencing defect, not a reason to weaken Bot Brain's
dead-player guard. The real-flow endurance path now prearms client B through
the normal mod setting while both peers are still in the shared hub. The
client remains inactive and clean in the hub, then takes over as soon as its
run actor is valid. The host remains under physical control through the
required Solomon interaction, is armed immediately afterward while still
alive, and only then does the harness wait for paired enemy materialization.

## Product finding: one held primary input became tick-rate network casts

The first full dual-takeover run reached wave 2, then the client stopped
receiving host gameplay. The host remained ready and continued receiving the
client while the client timed the host out, lost its replicated enemies, and
diverged at full health. The host continued under Bot Play until its local run
ended in death. With the peers split, the client remained in wave 2 and no
natural Game Over boundary could converge.

The host log explains the transport collapse. Bot Brain accepted 530 casts,
but the native pure-primary hook queued 15,771 casts. During the final second
alone, native queue IDs 15,741 through 15,771 were created and cast sequences
5,195 through 5,223 were sent. Every new event replaced the preceding active
cast, so the sender emitted reliable release and press edges at tick rate. The
host's captured Steam telemetry reached 197,459 pending reliable bytes and a
95th-percentile queue time of 807,510 microseconds; the runtime reported
sustained backpressure with 618 reliable messages queued.

`HookPurePrimarySpellStart` is a stock sustained-primary boundary and can run
on every game tick while the same mouse press remains held. Its multiplayer
capture path deduplicated only identical millisecond timestamps. The native
dispatcher path already atomically claimed the observed mouse-left edge, but
the pure-primary path bypassed that ownership rule. A single three-frame Bot
Play press therefore generated roughly 30 cast sequences instead of one.

The correction makes both native primary capture routes validate and claim
the same physical or injected mouse-left edge. Whichever native route proves
the cast first owns the one network sequence; further stock ticks and the
other route are ignored until the next real input edge. This preserves
repeated Bot Play presses and held-input updates without limiting the queue or
dropping reliable packets after the defect has already occurred.

The same run also had a four-minute one-way Steam route interruption before
combat and before either takeover was active. It recovered without a process
restart. That event cannot be attributed to the primary-cast amplification;
it remains a distinct external-transport observation for the corrected rerun.

## Harness finding: planned waypoints bypassed stall recovery

The first edge-deduplicated rerun joined the real lobby and moved the host
partway through Solomon Dig, then held the same position for more than four
minutes. Both Steam routes remained ready and continued exchanging packets;
the failure was local navigation rather than a network stall. The captured
timeline fixes the host at `(689.496, 397.125)` while Solomon remained at
`(1299.262, 890.261)`.

The navigation loop measured progress and issued perpendicular detours only
after its planned waypoint list was exhausted. While an active grid waypoint
existed, the branch sent the same blocked movement input and immediately
continued, bypassing all stall accounting. An obstructed waypoint could
therefore loop until the outer timeout. The correction applies the same
progress threshold and alternating real-input detour to every active waypoint.
It does not teleport the player, rewrite navigation state, or use a test seam.

## Harness finding: local Lua sampling spawned overlapping PowerShell clients

During the same stalled approach, the foreground Solomon controller and the
periodic pair sampler queried the host Lua pipe concurrently. The local
`LuaPipe` created a new PowerShell process for every query and had no lock,
while the native server exposes one named-pipe instance and services one client
at a time. One bridge eventually failed inside .NET with an index error. The
cleanup process inventory then failed with `System.OutOfMemoryException`, and
the workstation20 controller returned malformed output instead of its JSON
receipt. Both game processes were still alive; workstation20 nevertheless
closed and removed its owned stage. The exact staged host PID was verified by
executable path, closed through its main window without force, and the local
stage and ports were verified clean in the manual cleanup receipt.

The correction gives each local Lua pipe one serialized, persistent PowerShell
daemon for the run and closes it before game cleanup. This matches the existing
daemon protocol, removes per-sample process churn, and prevents two clients
from racing the loader's single pipe instance. The retained exact-path process
cleanup remains fail closed; the harness does not broaden process ownership or
force-close an unverified PID.

## Transport observation: bounded shared-hub startup backpressure

That rerun emitted one host warning during shared-hub actor materialization:
nine reliable messages were queued and 71 disposable updates were dropped over
two seconds. All 6,743 captured host Steam sends were accepted, the route stayed
connected, and the warning did not recur during the following four minutes.
The maximum pending reliable payload was 27,472 bytes and the queue later
drained. This was a self-limiting startup synchronization burst, not the
reliable tick-rate amplification seen in the preceding run, so no product
change was made for it.

## Product finding: synchronous close preparation reentered WPF Closing

The next attempt completed the host launcher's Ready, instance, Host Game,
privacy, and Start Lobby UI boundaries, but no staged game process appeared.
When exact-path cleanup requested a normal close of the still-live launcher,
Windows recorded an unhandled `System.InvalidOperationException` from
`MainWindow_Closing`: WPF rejected `Close()` because the window was already
closing.

The handler cancels the first `Closing` event, awaits launcher cleanup, then
calls `Close()` after setting its prepared flag. With no active game, the
cleanup task completes synchronously. The continuation therefore called
`Close()` recursively before the first event returned. The correction posts
the final close to the window dispatcher, allowing the canceled event to
unwind first. This keeps the existing graceful lobby/game shutdown behavior
and removes the reentrant close path.

## Harness finding: a failed launcher start discarded its diagnostics

The initiating reason that no game started was not preserved in that attempt.
The wait reported only the expected staged executable path; cleanup then
deleted the isolated launcher profile and its log. No `SolomonDark.exe` crash
appeared in the Windows Application event window, so assigning a product or
Steam cause from that evidence would be speculation.

The real-flow harness now includes the visible launcher automation state in a
launch-timeout error and copies the scoped `launcher.log` with the runtime
artifacts, including when mandatory game telemetry is absent. The next exact-
SHA rerun must use those receipts to resolve the launch failure if it recurs.

The next attempt reproduced the launch refusal while it was live. UI
Automation showed the definitive message that Steam was not ready, and the
local process inventory contained zero `steam.exe` processes. This also
resolves the preceding attempt: its UI path and absence of a game crash were
the same, but its status text had not yet been retained. This is an external
prerequisite loss, not a launcher, package, or game defect. The existing local
Steam client may be started under the same interactive account for the next
authorized lobby run; no login, setting, library, or account change is needed.

## Transport observation: recurrent one-way Steam handshakes

The first complete owner-topology match reached both active local takeovers,
host enemy authority, and client materialization. The client route nevertheless
entered `Handshaking` four times. The intervals lasted 62, 32, 274, and 179
seconds. During each interval the client's receive counter stopped while the
host continued producing outbound traffic; all four intervals later recovered
without a process restart and neither peer reported a Steam send rejection.

The second interval began during combat. Client B remained locally at 50 HP
while disconnected, then received the queued authority state on recovery,
briefly showed 23 HP, and reached zero in the same sampling interval. The host
recorded 52 native damage edges totaling 78 damage against client B. This
explains the early death and is distinct from Bot Brain activation or target
selection.

The same multi-minute one-way interruption occurred before combat in the
edge-amplification run, so it predates and survives the primary-cast fix. The
routes recovered, all sends were accepted, and no product-side transport error
identified a failing call. This remains an external Steam/SDR finding; adding
a resend, timeout override, or alternate transport under match pressure would
be a blind product patch.

## Harness finding: endurance monitoring began after materialization

The pair sampler recorded the route loss and death above, but the endurance
anomaly monitor did not start until after it had synchronously waited for
client enemy materialization. The wait therefore hid the most important
transport interval from live finding emission and began fighter accounting
only after the client was already dead.

The endurance loop now starts immediately after both normal-setting takeovers
are active. Enemy materialization remains a required gate, but it is evaluated
inside the monitored loop. Transport, bot state, HP transitions, and damage
are therefore observed while that gate is pending instead of after it.

## Harness finding: peer-local wave counters inflated endurance progress

The first match emitted a wave-divergence finding and attributed client B's
death to wave 4 even though the replicated authority wave was 2 on both peers.
The helper took the maximum of `sd.waves`, the native combat counter, and the
world counter. Client B's peer-local combat loop advanced to 4 during the
route interruption while the host remained on native combat index 1. Those
diagnostic counters are not authority-owned progress.

Endurance progress, milestone capture, and fighter statistics now use only the
replicated `sd.waves` summary. The peer-local counters remain in every timeline
sample for diagnosis but cannot manufacture a higher wave or a false
divergence.

## Harness finding: outbound traffic masked one-way packet stalls

The packet monitor stored all four send/receive counters in one tuple and
treated any tuple change as progress. A host send increment therefore reset the
stall clock even while client B's receive count was frozen for minutes.

The monitor now tracks the last progress time of each counter independently
and reports a packet stall when either peer's receive counter remains unchanged
for 30 seconds in the run. Continued outbound traffic can no longer conceal a
one-way receive failure.

## Bot finding: accepted skirmisher casts did not produce combat progress

After client B died, the host skirmisher survived and travelled throughout the
arena but stopped making meaningful offensive progress. The captured prefix
contains 893 accepted primary casts and only seven authoritative enemy-damage
edges totaling seven damage. Network actor `281543696187401` alone received
651 accepted cast attempts and no HP edge. After the second enemy death, the
host spent the final 458 seconds with the same nine living enemies and 21.5
aggregate HP while its own HP regenerated to 50.

This is a Bot Brain policy pathology, not a cast-ingress rejection. Scripted
target selection considers native range and geometric distance, while its
progress state counts accepted casts. It has no applied-damage feedback and no
projectile-clear-path signal, so repeated misses against the same moving or
occluded target look successful to the policy. The long perimeter circuit
also defeats the existing short-window oscillation detector because net
displacement remains large.

No combat-policy threshold was changed from this one match. Retargeting after
an arbitrary cast count or treating the player-sized navigation grid as
projectile line of sight would be a band-aid without live applied-damage
validation. The endurance monitor instead gains a class-closing finding when
an active bot accepts at least eight casts over 60 seconds without any living
enemy count or HP progress. The next run explicitly selects the shipped
Striker behavior through the same local setting to continue the owner match
without claiming that this resolves Skirmisher.

## Product finding: local primary diagnostics logged every stock tick

The host loader artifact reached 149 MB before the run ended. It contains
53,202 `pure_primary_start enter` rows and 53,201 matching exits for only 893
accepted Bot Brain casts. `HookPurePrimarySpellStart` budgeted diagnostics for
synthetic actors, but its local-player branch set `log_this` on every stock
invocation without consuming the same budget. Each row also formatted a large
native startup snapshot on the gameplay thread.

The local-player branch now uses the existing 32-entry pure-primary diagnostic
budget. Targeted live probes retain bounded startup evidence, while a held
primary can no longer grow the loader log at frame rate. This is a diagnostic
volume fix only; it does not change input, cast, damage, or network ownership.

## Product finding: delayed client snapshots outlived the stock spawner

The next real Steam run reached the shared lobby, both native run scenes, both
Bot Play takeovers, and replicated authority wave 2. Recurrent receive stalls
delayed the client's usable enemy snapshots until its suppressed stock wave
spawner had stopped ticking. The client then held ten live authoritative enemy
identities but never created a local binding: `bound=[] native=[]`.

The retained client log contains 462 queued replicated materialization requests
and 128 gameplay-pump failures with `stock wave spawner became unavailable`.
It contains no exact-spawn dispatch or completion. The last of 148
host-authoritative spawner suppressions preceded the failed catch-up burst by
more than two minutes. Paired screenshots show a live combat presentation, but
the semantic native enemy roster remained empty, so the client Bot Brain had no
usable local target and died without a respawn.

Replicated catch-up already uses the exact stock-class construction routine.
That routine resolves the active arena and exact stock constructor directly;
the remembered spawner contributes only the dispatch opportunity. The repair
allows the gameplay pump to invoke that existing routine after the spawner has
expired only when the queued request is a non-frozen, active-wave request with
a nonzero authority network actor ID and this peer is the transport client.
Public Lua spawning remains host/offline-authority-only, manual direct spawning
still requires explicit test mode and simulation authority, and host wave
ownership is unchanged.

## Harness finding: transient ws20 SSH loss terminated a live match

The repaired flow reached wave 8 and proved the delayed materialization path
with 42 direct client catch-up dispatches, 42 exact stock-path completions,
and no unavailable-spawner failures. The client held all 40 replicated enemy
bindings. At 26 minutes, however, the evidence controller terminated on
`remote Lua bridge failed: remote Windows Lua bridge timed out`.

This was not a game Lua failure. The existing bridge stopped returning, a new
bridge could not establish SSH, and the artifact and cleanup commands all
reported the same SSH connection timeout. Both exact staged processes remained
alive. SSH later recovered without a game or workstation change, allowing the
client artifacts to be copied and the owned processes and stage to be removed.
The workstation still had ample free memory and disk, its tailnet service was
running, and the System event log contained no warning or error in the failure
window.

The endurance loop now tolerates only the two exact remote-bridge connectivity
errors for a cumulative 180-second outage. It records the outage start, retries,
recovery, duration, and failure count. A persistent outage still aborts at the
budget, and local/game Lua errors remain immediately fatal. Setup,
materialization, and non-endurance probes retain their existing fail-closed
behavior.

## Environmental resolution: workstation website block removed

The owner confirmed that workstation20 had been blocking
`solomondarker.com` throughout the failed runs and removed the block. The
recorded before probe returned HTTP 200 with a DNSFilter `Website Filtered`
HTML page. The after probe returns HTTP 200 application JSON from both
`/api/lobbies` and the launcher's `/api/mods/updates` POST, with the empty mod
request producing an empty update list.

This validates the original environmental classification and may also explain
the r17 SSH/Lua-bridge outage if the workstation policy affected other network
paths. The client-only loopback directory override has been removed completely.
Both peers now use the production directory URL and must complete the normal
website update, lobby announce, and join-manifest path. Lua Bots 1.2.0 remains
in the exact prestage because it is deliberately unpublished.

The r17 authoritative ledger was also reconciled before retrying. All 575
positive rows map to the two replicated fighter identities: the host dealt 30
damage across 30 enemy edges, while the client dealt none. R17 therefore fails
the per-fighter applied-damage requirement independently of its later probe
timeout. The endurance tracker had compared these rows with transport IDs;
damage rows carry replicated participant IDs. Endurance attribution now derives
each fighter's replicated identity from the other peer's sole remote participant
view, while retaining transport IDs separately for transport evidence.

## Owner observation: bare staff did not mean the primary was absent

While r18 was still live, the workstation presentation appeared to have only a
bare wooden staff. Paired D3D9 backbuffers preserved that presentation before
the workstation fighter's recorded death. A semantic capture then read both
fighters from both peers while the workstation fighter was dead and
spectating.

The workstation fighter still had owned primary entry 16, combo entry 16,
native current-spell ID 1011, resolved build 16, and all 83 spellbook rows. Its
own process and the host's remote participant clone agreed on those values and
on the primary, secondary, and attachment equipment identities. The host also
had a native-backed equipped primary. The workstation fighter was at 0/50 HP;
both peers still reported respawn epoch zero while the authority wave had
advanced to seven.

The lost-primary hypothesis is therefore falsified. The bare-staff frame is a
real presentation observation, but it is not evidence that the per-actor
spellbook or equipped-primary state was empty. The alternative that this seat
never received a loadout is also falsified. No respawn had occurred, so there
was no post-respawn spell restoration that could hide a loss.

The paired screenshots and full role-mapped spellbook/loadout capture are under
`runs/steam-r18/captures/live-loadout-forensics` and
`runs/steam-r18/live-loadout-forensics` in the evidence root.

## Damage correlation: client progress stopped before death

R17's reconciled authority ledger contains 30 host enemy-damage edges totaling
30 damage and no workstation enemy-damage edge at all. Its only workstation
death occurred at 187.402 seconds; the host continued applying enemy damage for
another 1,295.346 seconds. Death cannot explain why that seat dealt zero.

R18 contains 29 host enemy-damage edges totaling 29 damage and six workstation
authority-log claims totaling five damage. The recovered workstation rows do
not carry monotonic timestamps, so they are bounded by adjacent timestamped
ledger rows rather than assigned point estimates. The last possible row was no
later than 1,372.779 seconds. The fighter died at 2,103.640 seconds, at least
730.861 seconds later. The host continued applying damage for another 167.139
seconds after that death.

This rejects death as the cause of the workstation fighter's offensive stall.
The primary was present, but its applied-damage efficacy had already stopped
for more than twelve minutes. That remains a distinct Bot Brain combat-policy
finding and must still satisfy the brief's per-fighter applied-damage gate on
the next endurance run.

The redacted correlation, conversion method, conservative timing bounds, and
hypothesis verdicts are recorded in
`runs/steam-r18/r17-r18-damage-death-respawn-correlation.json`.

## Product finding: completion-only respawn publication can starve

The systematic respawn failure is in the host publication boundary. R17 and
r18 each captured the Arena spawn point, but neither host log contains a
published or applied wave-respawn command. Both timelines advanced through
later authority wave numbers while the dead workstation fighter remained
spectating at respawn epoch zero. Neither timeline sampled a wave summary in
the `completed` phase.

`RefreshHostWaveRespawnCommand` published only when
`SnapshotLastCompletedWave()` advanced. That durable latch advances when a
tracked wave has no remaining spawns and no living tracked enemies. The stock
production schedule can start wave N while enemies attributed to older waves
remain alive. Under that overlap, later wave numbers are real boundaries, but
no tracked wave is fully cleared, so the completion latch and respawn command
can starve indefinitely.

The prior fieldbreak25 verifier concealed this production shape. It held one
wave-1 enemy alive, killed the workstation fighter, then explicitly killed the
last enemy before waiting for respawn. It proved the fully-cleared path but
never asserted that a natural wave-2 start respawns a dead owner while the held
wave-1 enemy remains alive. It also asserted HP, position, grid registration,
and actor identity without reading the native current spell.

The correction defines the eligible boundary as the newer of the durable
completed wave and `current wave - 1`. Publication remains host-only,
monotonic, authenticated, and idempotent; it changes only when a command is
eligible, and the existing same-actor primitive still leaves living owners
untouched. The focused verifier now keeps its wave-1 survivor alive across the
natural wave-2 boundary. It captures both fighters' owned loadout, full
spellbook fingerprint, resolved primary details, raw native current-spell ID,
and primary visual identity from owner and observer views before the death and
after the respawn. It requires each view to preserve those fields and requires
cross-peer agreement for the semantic spell, build, and spellbook fields;
peer-local equipment visual-lane types are not used as spell identity.

R18's final artifact copy was interrupted after the live captures and exact
owned-process cleanup. Its host log, timelines, ledgers, screenshots, semantic
captures, result, and clean after-receipt are preserved; its client runtime log
is unavailable. The missing client log does not affect the paired semantic
loadout proof or the host-side absence of respawn publication.

## Rerun requirement

The product failure fixes, restored website flow, corrected damage attribution,
bounded endurance probe continuity, and wave-boundary respawn correction must
be rebuilt together and rerun through the same real launcher, lobby, and Steam
flow. Completion requires both Bot Play takeovers to become active through the
mod setting, positive authoritative enemy damage from each fighter, live state
and transport sampling throughout the match, milestone screenshots from both
peers, equipped-primary persistence after every observed respawn, and either
natural Game Over or the 90-minute endurance cap.
