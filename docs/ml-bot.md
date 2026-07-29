# Learned bot

Lua Bots 1.1 includes a learned policy that controls a real synthetic player
slot. It chooses movement and attacks; the existing native bot rails perform
the movement, mana/cooldown checks, spell casts, damage, death, replication,
and collision. It is not an overlay, aim suggestion, or external process.

## Use it in a normal game

Enable **Lua Bots** in the launcher, open its mod settings, and add or edit a
row under **Bot roster**:

1. set **Behavior** to **Learned — ML movement and casting**;
2. choose the bot's element and native Discipline;
3. leave **Cast at enemies** enabled; and
4. launch normally.

The bundled policy runs entirely in the mod's Lua state. Players do not need
Python, NumPy, a GPU, a model server, an account, or an internet connection.
The host makes decisions and clients receive the same ordinary participant
movement and cast traffic. Scripted Skirmisher, Guardian, and Striker rows can
coexist with Learned rows.

The learned policy decides every 100 ms of simulation time. The launcher's
**Scripted bot cadence** setting therefore affects only the three scripted
Behaviors.

## What version 1 controls

The action space has two masked heads:

- idle or one of eight compass movement directions; and
- no cast, class primary, or one of eight loaded secondary slots.

Lua rejects blocked movement directions with `sd.nav.test_segment` before
selection. It masks casts when the bot has no valid target, the target is
outside the live native attack window, the native cast state is busy, offense
is disabled, or the requested slot is absent. A selected action then calls the
same `bot:move_to`, `bot:stop`, or `bot:cast` API used by scripted bots.

The observation includes bot and target vitals, range, threats, arena
geometry, status effects, temporal deltas, element, Discipline, owned
inventory summaries, potion stacks, equipped slots, gold, spellbook
progression, availability of all eight loaded secondary slots, and derived
combat multipliers. Automatic skill selection continues to use the game's
real pending-choice API before Learned decisions. It prioritizes the bot's
configured elemental primary and same-element upgrades and will not select a
conflicting elemental primary.

There is one deliberate limitation: the loader does not yet expose
owner-safe per-bot consume, equip, unequip, or inventory-transfer mutations.
The model can see consumables and equipment and can use spells already present
in its loadout, but version 1 cannot activate an item or change equipment.
Inventing item actions that bypass native ownership would produce a model that
could not actually play the game, so those actions are omitted. Adding the
native mutation rails will require a new masked action head and policy-contract
version.

## Why the first model is feed-forward

Version 1 is a 48-unit tanh actor-critic with separate 9-way movement and
10-way cast heads. It includes health, mana, target, enemy-count, prior-action,
and elapsed-action temporal features. This is much easier to audit and export
to the player Lua runtime than an LSTM, while PPO still trains the movement and
attack policy end to end.

A GRU is the next recurrent candidate if measured partially-observable
failures remain after the feed-forward baseline. An LSTM is not warranted
until a GRU demonstrably lacks memory capacity. A recurrent model must use a
new architecture identifier and model version; version 1 weights will never be
silently reinterpreted.

Before recurrence, version 2 should add per-slot spell identity, mana cost,
range, and cooldown/readiness features and learned target selection. Version 1
distinguishes every loaded slot and leaves final validation to the native cast
rail, but its mask conservatively uses the shared primary attack window. That
is enough to train real movement and casting without claiming that the model
already understands every secondary spell's semantics.

## Bootstrap and validate a model

Training uses Python and NumPy, but game-time inference does not. From a
Windows terminal in the repository:

```powershell
py -3 tools/train_bot_policy.py bootstrap
py -3 tools/train_bot_policy.py validate
```

Bootstrap generation is deterministic. It trains against a semantic expert
curriculum, checks held-out movement, casting, and joint-accuracy gates, and
writes:

- `models/bot-brain/policy-v1.json`, the trainer checkpoint; and
- `mods/bot-brain/scripts/policy_weights.lua`, the player runtime model.

Both files use the versioned contract in `tools/ml_bot/spec.py` and
`mods/bot-brain/scripts/policy_spec.lua`. Lua validates every name, tensor
shape, and finite parameter before accepting a model.

## Train with live PPO

Build the launcher and native loader first, then run:

```powershell
py -3 tools/train_bot_policy.py live-ppo `
  --game-directory "C:\path\to\SolomonDarkAbandonware" `
  --iterations 10 `
  --rollout-steps 1024
```

The command owns a disposable single-player instance with only `bot.brain`
enabled. By default it launches headless, disables audio, keeps the stock
10 ms fixed simulation step, and batches unchanged steps as fast as the
machine allows. Learned decisions remain exactly 100 ms apart in simulation
time regardless of wall-clock acceleration.

The live trainer uses a controlled curriculum arena. It enables the existing
manual-enemy test mode, keeps stock wave production suppressed, and asks the
game's exact stock enemy constructor for one ordinary type-1001 enemy with no
elite modifiers. The enemy is placed 260 units from the bot, retains its native
movement and attacks, and is replaced after death. The bot's primary spell is
unlocked through real native level-up offers and `sd.bots.choose_skill`; the
trainer does not write a spell directly into its loadout. Direct spawning is
accepted only in explicit test mode and on the simulation authority.

This arena is a curriculum, not a substitute for normal-wave evaluation: it
keeps the wave at zero and omits production cadence, compositions, and elite
modifiers. Evaluate candidate checkpoints in ordinary games across elements,
Disciplines, waves, and seeds before shipping one to players.

For each iteration the trainer:

1. enables stochastic Lua sampling and a bounded trajectory ring;
2. collects observations, masks, selected actions, old log probabilities,
   values, rewards, and exact simulation ticks;
3. disables collection and drains it below the pipe's payload bound;
4. calculates trajectory-local generalized advantage estimates;
5. applies clipped PPO updates with finite-value and gradient checks;
6. atomically checkpoints JSON and Lua weights; and
7. hot-loads the updated weights into the running game and verifies that the
   policy generation advances.

The launcher PID and executable path are recorded before training. Cleanup
targets only that owned staged process. Checkpoints are written under
`runtime/ml-training/<instance>/`; the source model is not overwritten.
Use `--visible` when visual inspection is more valuable than maximum speed.

A short pipeline smoke is:

```powershell
py -3 tools/train_bot_policy.py live-ppo `
  --game-directory "C:\path\to\SolomonDarkAbandonware" `
  --iterations 1 `
  --rollout-steps 128
```

The command fails if it does not observe the simulation clock, finite PPO
metrics, an advancing hot-load generation, real policy decisions, accepted
native movement, and accepted native attacks.

Run the live action acceptance separately with:

```powershell
py -3 tools/verify_ml_bot_live.py `
  --game-directory "C:\path\to\SolomonDarkAbandonware"
```

That gate requires simulation-clock decisions, physical bot displacement,
accepted native movement and casts, and an actual decrease in a stock enemy's
HP. Bootstrap held-out accuracy and the live plumbing gates are not competence
scores; survival, damage, item use once available, and normal-wave results are
the promotion criteria for a player checkpoint.

## Install a trained checkpoint

Validate and export the selected checkpoint:

```powershell
py -3 tools/train_bot_policy.py validate `
  --model runtime/ml-training/<instance>/policy-final.json `
  --lua mods/bot-brain/scripts/policy_weights.lua

Copy-Item `
  runtime/ml-training/<instance>/policy-final.json `
  models/bot-brain/policy-v1.json
```

Rebuild or repackage Lua Bots after replacement. Keep the JSON and Lua files
from the same checkpoint. The player package needs only the Lua file, while
the JSON file preserves the exact training checkpoint for future PPO work.

## Contracts

The complete observation/action/trajectory schema is documented in
[`design/ml-bot-policy-contract.md`](design/ml-bot-policy-contract.md).
Numerical, Lua-parity, PPO, ring-buffer, packaging, native-action, and
simulation-tick coverage lives in `tests/test_ml_bot_policy.py`,
`tests/lua/ml_bot_policy_contract.lua`, and
`tests/re/static_lua_ml_bot_contracts.py`.
