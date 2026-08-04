# beta.31 hostile-targeting class

Date: 2026-08-04

Status: fixed and live-verified

## Report and scope

The owner reported three symptoms from beta.31 hosted play with a Lua Bots
teammate:

- after the owner leveled and chose a skill, the bot stopped attacking and
  rotated in place;
- skeleton targeting was generally erratic; and
- waves sometimes waited on distant idle enemies until a player searched for
  them.

The read-only source-session log is
`/mnt/d/codex-evidence/botlevel-owner-session-20260803.log`, SHA-256
`10afb5c60e6db0571fd210094319aeecc38a78cbdb910da1593a15ccb5c0f94d`.
That session used the real Steam transport. The owner identity in its target
records is Steam ID `76561198120430463`; Lua teammates use synthetic
participant IDs in the `1152921504606846976` range.

The targeting investigation was performed in the isolated clone at
`/mnt/d/codex-worktrees/botlevel-20260804/Mod Loader`. The behavior baseline is
`b341ab3b67e0c6c198cb0dce110791abfc38a72d`. No owner install or owner runtime
profile was used.

## Owner-log timing

The level-up picker and targeting diagnostics do not begin the bot's control
wedge:

- `22:03:39.619`: the bot reaches level 2 and receives choice generation 1;
  the owner receives a separate owner-only offer.
- `22:03:39.628`: the bot applies its own choice and clears its pending state.
- `22:03:44.612`: the owner applies a different choice; the picker and owner
  barrier clear.
- `22:03:47.772` through `22:03:55.980`: the bot starts seven more native
  casts after the owner's accepted choice.
- `22:03:56.279`: the bot enters its permanent exact-10% Lua mana hold. This is
  the independent control wedge documented in
  `beta31-lua-bot-exact-mana-boundary-freeze-2026-08-04.md`.
- `22:05:43.963`: the first `rejected extended target candidate` line appears,
  nearly two minutes after the mana wedge and at the owner's death edge.

There are 1,676 rejection lines. Of them, 1,675 name the owner's Steam ID and
one names the bot. The common tail is an expected excluded-corpse state:
`ineligible=1`, after life zero and Game Over. Logging that expected exclusion
at the global 250 ms diagnostic cadence creates the roughly 4 Hz storm; it
does not prove the picker blocked either participant and did not cause the
earlier attack stop.

The campaign still exposes a real targeting-class defect. The adjacent
`authoritative nearest target applied. reason=native_selector` lines show the
loader repeatedly replacing a stock target, and the binary control flow
explains why that replacement is unsafe.

## Recovered native selector contract

The supported retail executable's
`MonsterPathfinding_SelectNearestTarget (0x00481A60)`:

1. sets the selector-completion latch at `hostile + 0x68`;
2. scans the stock hostile-target candidate list;
3. chooses the closest eligible candidate;
4. if the winner is in ActorWorld group zero, calls
   `ActorWorld_RelocateHostileToGroupZero (0x0063F7A0)`;
5. writes the winner to `hostile + 0x168`, writes the bucket delta to
   `hostile + 0x164`, and completes the latch contract.

`ActorWorld_RelocateHostileToGroupZero` relocates the hostile, not its target.
It unconditionally unregisters and re-registers the hostile in ActorWorld.
That lifecycle mutates scene membership while pathfinding is selecting a
target.

The beta.31 hook in
`gameplay_hooks/monster_pathfinding_hook.inl` calls the retail selector first
and then calls `ApplyNearestValidHostileTarget`. The extended scan can see a
materialized remote player or Lua teammate that stock group-zero selection
cannot represent. When that extended participant is closer, one logical
selection therefore has two authorities:

```text
retail: choose group-zero owner -> relocate hostile -> write owner
loader: choose closer group-one bot            -> write bot
```

This violates the multiplayer authority contract even though the eventual
target pointer is correct. It transiently steers toward the wrong actor and
unregisters/re-registers the hostile on every native selection pass. Repeated
passes can make enemies look indecisive and can leave wave bookkeeping without
a stable live actor while the enemy remains present.

## Live pre-fix reproduction

`pre-fix-targeting-live-8/result.json` is the canonical isolated pre-fix
result. It used instance `botlevel-targeting-prefx8`, unique UDP ports 52765
and 52766, `SDMOD_DISABLE_AUDIO=1`, a copied game, and the full Steam-format
owner participant ID. The harness materialized a native skeleton wave, kept
the owner stationary, placed the Lua teammate mathematically nearer to a
skeleton, and held the original enemies stationary without player input.

The nearest-target sample itself was superficially correct: all 25 live
samples selected the nearer bot and all 25 observed a clear selector latch.
The runtime log reveals the hidden double decision: 294 native-selector apply
records changed a just-written stock owner target to the extended bot target.

The same run then reduced the stationary original enemies to one hit and
placed the bot 500.56 units away. Over the acceptance window:

- the owner displacement was 0 and the harness issued no player search input;
- the locked enemy displacement was 0;
- bot accepted casts advanced by 16 and movement accepts advanced by 35;
- four authoritative bot damage edges occurred; and
- an original enemy remained alive while the wave stayed at 1.

This reproduces the wave stall without conflating it with an inactive bot.
The owned game was PID 27440 at
`D:\codex-evidence\botlevel-20260804\pre-fix-targeting-live-8\staging\runtime\instances\botlevel-targeting-prefx8\stage\SolomonDark.exe`.
The harness stopped that exact PID/path, removed its staging tree, and recorded
no owned process or reserved-port binding afterward.

## Root cause

The host default-policy path performs a stock selection and an extended
selection serially. Stock is allowed to relocate the hostile and commit the
group-zero owner before the loader overwrites the target with the actually
nearest extended participant. The final pointer hides the first decision, but
cannot undo its ActorWorld lifecycle and steering side effects.

The rejected-candidate storm is a second defect in the same class: expected
dead/ineligible participants are logged as anomalous extended-candidate
failures forever. It amplifies the visible incident and obscures the selector
churn, but is not itself a targeting decision or participant-control barrier.

The level-up-window bot freeze has the separate exact-mana cause already fixed
on `main`. A participant's choice state did not wedge another participant:
both choices cleared independently and the bot cast afterward. The expanded
campaign retains that proof alongside the targeting-authority correction.

## Resolution

The host now computes one nearest-target decision before invoking stock. Each
validated candidate records whether the retail list's group-zero branch can
commit it. A retail-compatible winner remains under the stock selector. An
extended winner is committed directly and skips stock, so retail cannot
relocate the hostile or transiently author a different target. If that direct
write fails, the hook falls through to retail instead of returning with an
uncommitted target. Higher-priority Lua, Turn Undead, manual-freeze, and client
snapshot policies retain precedence.

Expected dead or ineligible extended participants remain excluded, but no
longer emit the anomalous rejection diagnostic. Unexpected validation
failures retain the rate-limited diagnostic path.

## Post-fix live acceptance

`post-fix-targeting-live-6/result.json` is the canonical isolated correction
proof. It used instance `botlevel-targeting-post6`, unique UDP ports 52777 and
52778, `SDMOD_DISABLE_AUDIO=1`, a copied game, and the full Steam-format owner
participant ID. The verifier observed:

- 25 of 25 live samples selecting the mathematically nearer Lua teammate;
- 25 of 25 samples with the native selector latch clear;
- zero stock-owner-to-extended-bot rewrites and zero rejected-candidate spam;
- all ten original skeleton actors receiving authoritative bot damage;
- 30 additional accepted bot casts and 67 movement accepts;
- wave 1 advancing to wave 2 from an initial 510.51-unit bot distance; and
- zero owner displacement and zero player-search input.

The verifier stopped owned PID 22180 only after matching its executable to
`D:\codex-evidence\botlevel-20260804\post-fix-targeting-live-6\staging\runtime\instances\botlevel-targeting-post6\stage\SolomonDark.exe`.
Its after receipt records no owned process and no binding on either reserved
port.

Together with the separate owner-level-up continuity proof, acceptance covers
all three reported outcomes:

1. a hosted Lua teammate continues casting and causing native damage through
   an owner level-up choice;
2. a skeleton holds the mathematically nearest live participant with a clear
   selector latch and no stock-owner-to-extended rewrite; and
3. a stationary distant straggler is killed and the wave advances while the
   owner remains stationary and sends no search input.
