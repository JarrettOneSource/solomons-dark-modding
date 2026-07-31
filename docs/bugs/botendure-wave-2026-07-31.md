# Botendure owner wave

Date: 2026-07-31

Status: corrective code complete; exact-SHA owner-topology rerun pending

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

## Rerun requirement

The product failure fixes and remote staging fix must be rebuilt together and
rerun through the same real launcher, lobby, and Steam flow. Completion
requires both Bot Play takeovers to become active through the mod setting,
live state and transport sampling throughout the match, milestone screenshots
from both peers, and either natural Game Over or the 90-minute endurance cap.
