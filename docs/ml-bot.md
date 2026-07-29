# Learned bot

Lua Bots 1.1 includes a learned policy that controls a real synthetic player
slot. It chooses movement, a persisted enemy target, and attacks; the existing
native bot rails perform movement, mana/cooldown checks, spell casts, damage,
death, replication, and collision. It is not an overlay, aim suggestion, or
external process.

## Use it in a normal game

Enable **Lua Bots** in the launcher, open its mod settings, and add or edit a
row under **Bot roster**:

1. set **Behavior** to **Learned — ML movement and casting**;
2. choose the bot's element and native Discipline;
3. leave **Cast at enemies** enabled; and
4. launch normally.

The bundled policy runs entirely in the mod's Lua state. Players do not need
Python, NumPy, a GPU, a model server, an account, or an internet connection.
The host makes decisions and clients receive ordinary participant movement and
cast traffic. Scripted Skirmisher, Guardian, and Striker rows can coexist with
Learned rows.

The learned policy decides every 100 ms of simulation time. The launcher's
**Scripted bot cadence** setting therefore affects only the three scripted
behaviors.

## What policy v2 controls

Policy v2 has three masked action heads:

- idle or one of eight compass movement directions;
- keep the persisted target or select one of eight nearest-enemy slots; and
- no cast, class primary, or one of eight loaded secondary slots.

Lua samples movement and target first. It persists the selected enemy by
`network_actor_id`, rebuilds the cast mask against that enemy, and then samples
the cast. Blocked movement directions are rejected with
`sd.nav.test_segment`. Cast legality uses offense/cast state plus per-slot
occupancy, affordability, resolved cooldown/readiness, and the selected
target's range. Unknown native secondary range is deliberately not guessed;
the native cast rail remains the final validator.

The policy receives exactly 395 ordered values. They cover self vitals;
the active primary and eight secondary descriptors; eight enemies with
actor-ID velocity history; the persisted target; cached clearance rays and a
7x7 egocentric walkability patch; four replicated pickups; four nearest
in-run allies; cap-independent enemy/ally aggregates; arena, history, weld,
and progression-derived combat features. The canonical order is
`tools/ml_bot/spec.py` and
`mods/bot-brain/scripts/policy_spec.lua`.

Normalization is fixed by the versioned contract, never fitted from a batch:

- mana: 2000;
- HP: 1000;
- velocity: 1000 world units/second;
- cooldown: 60 seconds;
- range: 1000 world units; and
- radius: 100 world units.

The mana and HP ceilings cover catalogued native upgrades and stock charms.
The velocity ceiling covers the fastest native movement envelope measured by
the speed probe. The cooldown ceiling is the live-proven Teleport cap.
Evidence comments live beside the constants in `policy_spec.lua`.

The deterministic skill manager remains separate from the learned heads. It
recognizes Spell Welding option 52 and honors
`policy_weld_preference=prefer|avoid|auto`. Nearby host-owned pickups are also
requested by a rate-limited scripted assist; the learned action is navigating
to the observed drop.

## Runtime architecture and strict versioning

Architecture `mlp-tanh-three-head-v2` is a feed-forward actor-critic:

1. 395 inputs;
2. tanh layers of 192 and 96 units;
3. masked movement logits (9), target logits (9), and cast logits (10); and
4. one scalar value output used by training.

The joint action log probability is the sum of all three selected-head log
probabilities. Model, observation, and trajectory versions are all 2. Lua and
Python validate every ordered name, declared shape, parameter name, and finite
value. Historical v1 JSON remains in source control, but both loaders reject
v1 artifacts explicitly; there is no migration shim.

## Bootstrap and validate a model

Training uses Python and NumPy, but game-time inference does not. From a
Windows terminal in the repository:

```powershell
py -3 tools/train_bot_policy.py bootstrap
py -3 tools/train_bot_policy.py validate
```

Bootstrap generation is deterministic and starts from fresh v2 initialization.
Its semantic expert chooses an enemy slot from the eight enemy observations
first, then derives a target-conditioned cast. It does not reuse v1 weights,
trajectories, data, or wrapper-selected target labels. Held-out movement,
target, cast, and three-head joint gates write:

- `models/bot-brain/policy-v2.json`, the trainer checkpoint; and
- `mods/bot-brain/scripts/policy_weights.lua`, the player runtime model.

The JSON checkpoint and Lua export are generated from one parameter map and
the contract tests require the checked-in Lua file to equal a fresh export of
the checked-in JSON file.

## Train with live PPO

Build the launcher and native loader first, then run:

```powershell
py -3 tools/train_bot_policy.py live-ppo `
  --game-directory "C:\path\to\SolomonDarkAbandonware" `
  --iterations 10 `
  --rollout-steps 1024
```

The command owns a staged single-player instance with only `bot.brain`
enabled. By default it launches headless, disables audio, keeps the stock
10 ms fixed simulation step, and batches unchanged steps as fast as the
machine allows. Learned decisions remain exactly 100 ms apart in simulation
time regardless of wall-clock acceleration.

The live trainer uses a controlled curriculum arena. It enables the existing
manual-enemy test mode, keeps stock wave production suppressed, and asks the
game's exact stock enemy constructor for one ordinary type-1001 enemy with no
elite modifiers. The bot's primary spell is unlocked through native level-up
offers and `sd.bots.choose_skill`; the trainer does not write a spell directly
into its loadout.

For each update the trainer:

1. collects strict trajectory-v2 observations, three masks, three actions,
   composite old log probabilities, values, rewards, and simulation ticks;
2. computes trajectory-local generalized advantage estimates;
3. applies clipped three-head PPO with finite and gradient checks;
4. atomically replaces each JSON/Lua checkpoint file; and
5. stages the large Lua export in sub-1-MiB pipe chunks, validates/commits it
   as one runtime candidate, and verifies generation advance.

Default entropy coefficients are movement `0.01`, target `0.02`, and cast
`0.01`. The target bonus is intentionally doubled because `keep_current` is
often legal and otherwise becomes an easy early attractor. PPO reports each
head's entropy independently as well as their sum.

Checkpoints are written under `runtime/ml-training/<instance>/`; the source
model is not overwritten. Cleanup targets only the exact process launched and
registered by that session.

## Known limitations

- Native secondary range or cooldown coverage is incomplete for some entries.
  Unresolved range skips only that slot's range gate; unresolved cooldown uses
  the accepted global-readiness fallback. Both remain explicitly unresolved
  in the loadout API.
- Only four nearest allies and eight nearest enemies have per-slot features,
  although aggregate counts use the full configured participant/world state.
  No Lua participant-cap assumption is made.
- There is no learned skill-upgrade/weld head, aim-offset head, recurrent
  state, item consume/equip action, or inventory-transfer action.
- The controlled one-enemy arena is curriculum plumbing, not a competence
  evaluation. It omits normal wave cadence, elites, broad builds, and team
  compositions.
- Fresh boneyard seed/session and team-composition rotation belong to the
  Phase 5 training harness. Until that gate lands, do not promote a long run
  from the current single-session curriculum as a production-trained policy.

## Install a trained checkpoint

Validate and export the selected checkpoint:

```powershell
py -3 tools/train_bot_policy.py validate `
  --model runtime/ml-training/<instance>/policy-final.json `
  --lua mods/bot-brain/scripts/policy_weights.lua

Copy-Item `
  runtime/ml-training/<instance>/policy-final.json `
  models/bot-brain/policy-v2.json
```

Keep the JSON and Lua files from the same checkpoint. Rebuild or repackage Lua
Bots after replacement.

## Contracts

The complete action/model/trajectory schema is documented in
[`design/ml-bot-policy-contract.md`](design/ml-bot-policy-contract.md).
Numerical, Lua-parity, PPO, ring-buffer, serialization, and strict-version
coverage lives in `tests/test_ml_bot_policy.py`,
`tests/lua/ml_bot_policy_contract.lua`, and
`tests/re/static_lua_ml_bot_contracts.py`.
