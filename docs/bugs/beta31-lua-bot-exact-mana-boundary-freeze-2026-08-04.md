# beta.31 Lua bot exact-mana boundary freeze

Date: 2026-08-04

Status: fixed and live-verified; product change commit
`1fee775adf048202e0c3de074f6875dc4bf1e14a`

## Report and evidence

The owner reported that a Lua Bots teammate stopped attacking and rotated in
place after the owner leveled up and chose a skill in a hosted beta.31 match.
The source session used the real Steam transport. Its authority participant was
Steam ID `76561198120430463`; the Lua teammate was synthetic participant
`1152921504606851072`.

The read-only owner log is
`/mnt/d/codex-evidence/botlevel-owner-session-20260803.log` with SHA-256
`10afb5c60e6db0571fd210094319aeecc38a78cbdb910da1593a15ccb5c0f94d`.
The deterministic current-`main` reproduction is under
`/mnt/d/codex-evidence/botlevel-20260804/pre-fix-live-3` at source commit
`d0c119e1a25a2e02f0e89cfa0198942dbe7dbf02`.

## Owner-log correlation

The level-up choice paths complete independently and do not explain the
freeze:

- At `22:03:39.619`, the bot advances from level 1 to 2 and receives pending
  choice generation 1 with options `[49,16,18]`. The owner-only barrier starts
  with `participant_count=1`, and the owner receives a distinct offer with
  options `[56,49,48]`.
- At `22:03:39.628`, the bot applies option 49 to its own progression. At
  `22:03:44.612`, the owner applies option 56, the native picker closes, and
  barrier 1 completes without timeout.
- The bot starts seven more native casts after the owner's accepted choice,
  from `22:03:47.772` through `22:03:55.980`. A choice wait therefore did not
  stop its controls.
- At `22:03:56.279`, the Lua brain logs its final state transition:
  `mana hold-start ... current=10.0 maximum=100.0 ratio=0.1`. There is no
  corresponding native `mana reserve entered`, no native recovery, no Lua
  hold end, and no later bot cast.
- A second level-up begins at `22:04:34.329`, after the bot is already wedged.
  The bot applies generation 2 option 16 at `22:04:34.346`. The unresolved
  owner offer times out and auto-picks at `22:05:34.339`, after which the picker
  closes and the barrier clears. This is further evidence that bot-owned
  choices continue to clear while its casting is wedged.

The 1,676 `rejected extended target candidate` diagnostics are a later death
signal, not the start of the freeze. The first is at `22:05:43.963`, when the
owner becomes `runtime_dead=1`, almost two minutes after the exact-mana hold.
Of those diagnostics, 1,675 name the owner's Steam ID and one names the bot;
1,602 are the lingering post-death/post-Game-Over form with
`ineligible=1 runtime_dead=0 participant_dead=0`. The owner life-zero capture
is at `22:05:44.000`; all-player Game Over follows at `22:06:02.260`. The
roughly 4 Hz diagnostic tail is noisy, but it cannot be the reported control
wedge because it begins after the owner dies.

## Live reproduction

The isolated verifier stages a fresh copy of the current Release package and
game, disables audio, reserves unique local UDP ports 52741 and 52742, and
launches with transport participant ID `76561198120430463`. It starts a hosted
match with one Lua teammate, observes real native enemy damage from that bot,
forces the established bot-sync-then-owner-offer level-up order, and waits for
both participant-owned outcomes.

During the owner picker, the owner offer remains valid and the shared wait is
active while the bot reports `choice_pending=false`, picker screen 0, and one
accepted skill choice. After the owner chooses, the offer and wait both clear.
The verifier then places the bot at the incident boundary of 10/100 mana.

Over the following 14 seconds:

- accepted casts remain 7;
- movement accepts advance from 14 to 38;
- brain think ticks advance from 14 to 62;
- the Lua mana hold becomes and remains active;
- native `mana_reserve_active` remains false;
- mana remains exactly 10/100;
- eight live enemies remain; and
- the bot produces no native damage edge.

This reproduces the visible symptom: the brain and steering continue, but the
attack path is permanently gated. The owned process was PID 14044 at
`D:\codex-evidence\botlevel-20260804\pre-fix-live-3\staging\runtime\instances\botlevel-pre-host3\stage\SolomonDark.exe`.
It was stopped by exact PID and executable path; the after receipt contains no
owned process and no bound reserved port.

## Root cause

Bot Brain and the native bot runtime independently implement the same mana
hysteresis with different boundary operators:

- `mods/bot-brain/scripts/brain.lua` enters its local cast hold when
  `ratio <= 0.10` and exits when `ratio >= 0.80`.
- `UpdateBotManaReserveStateLocked` enters native reserve only when
  `ratio < 0.10` and exits only when `ratio > 0.80`.

At exactly 10%, Lua refuses to issue another cast, but native never enters the
reserve state that drives recovery. Because no cast can spend mana and no
reserve recovery can add mana, the ratio cannot cross either state machine's
next transition. Movement is independent and continues, which presents as a
non-attacking bot that turns or rotates in place.

The level-up timing was causal only in the owner's observation window. Its
participant-owned bot choice completed, its owner-only barrier completed, and
the bot attacked afterward. The actual permanent transition was the later
10% mana sample.

## Resolution

`UpdateBotManaReserveStateLocked` now enters reserve at `ratio <= 0.10` and
exits at `ratio >= 0.80`. For roster bots, Bot Brain no longer owns a parallel
threshold state machine: it reads `mana_reserve_active` from that bot's own
participant snapshot and mirrors the native decision. Bot Play For Me keeps
its local-player threshold path because a local human is not represented by a
bot participant snapshot.

The native reserve map was already keyed by bot participant ID. The executable
Lua contract in `tests/lua/bot_mana_reserve_contract.lua` now pins that
isolation directly: a pending choice for participant 42 does not change
participant 43's reserve or Lua hold, while exact 10% enters and exact 80%
exits. Static contracts pin the inclusive native operators and the per-bot
snapshot source. No hostile-targeting behavior was changed.

## Post-fix live proof

The same isolated verifier passed in continuity mode from pre-rebase fix commit
`cc16cab6873de9055e37e13e7f54bd6dcfed5ca1`; the identical product change
landed after the unrelated concurrent `main` advance as
`1fee775adf048202e0c3de074f6875dc4bf1e14a`. The result is
`/mnt/d/codex-evidence/botlevel-20260804/post-fix-live/result.json`. It used
unique UDP ports 52743 and 52744 and the full Steam-format transport ID
`76561198120430463`.

While the owner offer was valid and its wait count was one, the bot had already
accepted its own skill, reported `choice_pending=false`, and had picker screen
0. The owner selection then cleared both the offer and barrier. At the forced
10/100 boundary, native reserve entered inclusively; the same participant's
Lua hold observed that state. Native recovery reached exactly 80/100, reserve
and Lua hold both cleared, and the bot resumed from five to seven accepted
casts. Two subsequent authoritative native damage edges, each for 4 damage,
were attributed to the bot while eight enemies remained.

The verifier launched only PID 11444 at
`D:\codex-evidence\botlevel-20260804\post-fix-live\staging\runtime\instances\botlevel-post-host\stage\SolomonDark.exe`.
It stopped that exact PID/path, deleted its staging tree, and recorded no owned
process or reserved-port binding afterward.

## Verification

The final isolated checkout passed:

- 676/676 Python tests;
- 329/329 static reverse-engineering contracts;
- 55/55 launcher contracts;
- all 683 source/header fragments;
- Release rebuild with 0 warnings and 0 errors; and
- `Verify-Workspace.ps1 -Configuration Release` using the independent game
  copy and instance `botlevel-workspace`.
