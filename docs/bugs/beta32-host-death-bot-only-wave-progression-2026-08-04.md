# beta.32 host death with a surviving bot: wave progression

Date: 2026-08-04

Status: native human gate disproved; deterministic bot-only regression passing

## Report

The owner reported that beta.32 could stop progressing after the host died while
a bot remained alive. The visible result was either that no new enemies spawned
or that enemies stopped attacking the bot.

The targeting half is not reopened here. Commit `86b01a0e` and
`beta32-bot-mana-and-lone-target-handoff-2026-08-04.md` already prove that a
hostile drops a dead human and acquires the surviving bot without an idle frame
or authority-publication delay. The installed beta.32 predates that landing.
This report isolates the previously unproven wave-director half.

## Required contract

A bot is a synthetic player. While any bot is alive:

- the host wave director remains active;
- scheduled spawns are produced;
- spawned hostiles select and damage the bot;
- the bot can damage and clear the hostiles;
- completed waves advance; and
- the all-participant Game Over command remains unaccepted.

The existing stock wave-boundary respawn contract still applies to dead humans.
A multi-wave bot-only verifier therefore has to kill the client and then the
host again after each boundary respawns them. That test action preserves the
product's respawn behavior; suppressing respawn would test a different game.

## Native director investigation

Read-only headless Ghidra inspection used the stock executable and the existing
analysis project. The relevant native functions are:

- `Arena::Tick` at `0x0046E570`. Its initial start hold checks the arena
  countdown, the active flag, and whether `Solomon_Dig` (`0x1391`) is still
  present. It does not enumerate gameplay slots or human actors.
- `ArenaStartWaves` at `0x00465C00`. It initializes the section, wave index,
  wait state, advance mode, wave counter, active flag, and music. It has no
  player census.
- the arena director advance helper at `0x00465D70`. It gates on the arena
  active byte, the global run-active byte, wait/advance fields, live-enemy and
  spawner counts, and the completion latch. It has no living-human predicate.
- `WaveSpawner_Tick` at `0x0046D000`. It consumes spawn budget and delay fields
  subject to the native maximum-enemy count. It does not read a human slot.

Conclusion: the native wave director and spawn scheduler do not gate on a living
gameplay-slot human. A foundational patch that fabricates a living human for the
native director would be both unnecessary and at the wrong semantic boundary.

## Loader seam investigation

The host's `HookWaveSpawnerTick` calls the stock spawner unless one of four
explicit controls is active: manual-spawn test mode, combat-prelude-only mode,
a shared multiplayer pause, or client-side host-authority suppression. Host
death and death-spectator mode are not suppression inputs.

`ShouldPauseMultiplayerGameplay` can hold waves for an unresolved level-up choice
or an intentional shared gameplay menu. The live bot-only interval below had
neither: `shared_pause=false` and `level_wait=false` throughout the terminal
sample.

The other lifecycle seams already use participant semantics:

- `HasConnectedRunPeer` accepts any ready, connected, in-run non-local
  participant, including a bot, so host death enters spectator presentation.
- spectator target collection accepts a living bot.
- `IsConnectedRunGameOverMember` includes every ready, connected, in-run
  participant in the run nonce.
- `RefreshHostRunGameOverCommand` returns as soon as any such participant is not
  terminally dead. The command can be accepted only after the bot's life reaches
  zero and its native death-drive state is nonzero.

## Deterministic regression design

`tools/verify_multiplayer_bot_only_wave_progression.py` launches an isolated
host/client pair with one bot, starts the native arena director, and requires
two completed bot-only actions. The fixture controls only encounter size,
enemy health, schedule timing, and contact geometry:

- each action schedules five stock melee skeletons;
- the client and host are killed in that order by stock native damage;
- both humans are re-killed after the stock wave-boundary respawn contract
  revives them;
- live hostiles are periodically rebound near the bot so Boneyard path
  randomness cannot turn the test into a navigation soak; and
- the verifier never calls `trigger_enemy_death`, the native enemy-death test
  helper, or any wave-counter mutation during either proof cycle.

An action is complete only when all of these independent receipts exist for
that action index: a scheduled spawn, an authoritative target pointer to the
bot, hostile damage to the bot, bot damage to a hostile, a director-counter
transition, and the native-death-driven `wave.completed` event. Advancing to a
newer overlapping action is not accepted as completion of an older one.

The test also accounts for two stock lifecycle details. A newly started action
has a pending dead-participant respawn window, so the initial human deaths occur
only after that window has elapsed. At later action boundaries, the verifier
lets stock respawn both humans and then kills the client and host again. Those
controls preserve rather than bypass the shipped death/spectator and respawn
flows.

## Untouched-main live result

Baseline SHA: `c1724f51553bf45d58f40cc17c9600e71f902af4`

The isolated `bw-baseline62` hosted pair used UDP ports 52261 and 52262, disabled
audio, one Water/Arcane/Skirmisher bot, and the deterministic schedule above.
Raw receipt: `baseline62-c1724f51.json` under the campaign evidence root.

The client and host died from native damage at
`2026-08-05T04:08:37.974414Z`. Game Over remained unaccepted, and the host
entered `Spectating` with participant `1152921504606851073`, the living bot, as
its target.

Two full bot-only actions then completed naturally:

| action | first spawn UTC | first bot-target UTC | hostile damage to bot | bot damage to hostiles | completion tick |
| --- | --- | --- | ---: | ---: | ---: |
| 2 | `04:08:45.505903Z` | `04:08:45.505903Z` | 40 edges / 60 HP | 20 edges / 0.50 HP | `1136172968` |
| 3 | `04:08:46.672147Z` | `04:08:46.672147Z` | 3 edges / 4.5 HP | 30 edges / 0.75 HP | `1136218921` |

Every precise target sample in those actions named the bot in both the local
native target pointer and the host authority snapshot. Action 4 then started at
tick `1136232062`, proving scheduled advancement after the second completion.
Throughout the bot-only interval, shared pause and level-up wait remained false
and Game Over remained unaccepted.

For the terminal contract, the bot was held at low life while a stock skeleton
remained in contact. The skeleton's 1.5-damage edge changed bot life from 1.0 to
-0.5 at `2026-08-05T04:09:55.325656Z`. Host and client each accepted exactly
one stock Game Over dispatch at epoch 1. No Game Over dispatch occurred while
the bot was alive.

Raw campaign evidence is rooted at
`D:\codex-evidence\botwaves-20260804`. Every launched game process was acquired
from the launcher ledger and stopped only after its executable path matched the
owned `bw-*` staging directory. The after-check found no remaining owned process.

## Conclusion and disposition

The beta.32 report is consistent with the already-fixed targeting defect: if
enemies do not attack the last bot, they cannot finish the bot or participate in
the expected combat loop, and the director legitimately remains in its clearing
phase. Current main does not show an independent all-human-dead wave gate or a
Game Over limbo.

There is no independent wave-director defect to patch on current main. The
native director neither asks for a living human nor enters an all-human-dead
limbo. Death-spectator mode coexists with active spawning and clearing, and the
participant-aware Game Over seam stays open for a living bot before accepting
exactly once after the bot dies.

A fabricated-human director patch or a caller-side exception would weaken the
native lifecycle and is therefore rejected. The foundational behavior is
already correct at the director and participant seams; this campaign lands the
deterministic regression and investigation record only. The owner's observed
beta.32 symptom is explained by the pre-`86b01a0e` hostile-targeting behavior:
idle hostiles make a legitimate clearing phase look like stalled progression.
