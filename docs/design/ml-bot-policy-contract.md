# ML bot policy contract

The player build executes a feed-forward policy entirely inside the
`bot.brain` Lua mod. Python and NumPy are training tools only. The shipped mod
does not open a network service, start Python, require a GPU, or send gameplay
state outside the game process.

## Versioned model

Model format `solomon-dark-bot-policy` version 2 uses architecture
`mlp-tanh-three-head-v2`:

1. 395 ordered normalized observations;
2. a fully connected tanh layer with 192 units;
3. a fully connected tanh layer with 96 units;
4. masked movement, target, and cast heads of 9, 9, and 10 logits; and
5. one scalar value head.

`tools/ml_bot/spec.py` and
`mods/bot-brain/scripts/policy_spec.lua` carry the same ordered observation
and action names. A model is rejected unless format, model/observation
versions, architecture, both hidden sizes, all four output sizes, every name,
every parameter name/shape, and every parameter value match the contract.

`models/bot-brain/policy-v1.json` is historical only. Its version, 87-input
shape, 48-unit layer, and two-head architecture are incompatible. Lua and
Python issue an explicit v1 error and provide no adapter, migration, or
fallback.

## Observations

The canonical 395-name list is generated in the same block order in both spec
files:

- A: 15 self values;
- B: 11 active-primary values;
- C: 104 values for eight secondary slots;
- D: 80 values for eight nearest enemies;
- E: 10 persisted-target values;
- F: 56 cached geometry values;
- G: 33 values for four replicated pickups plus count;
- I: 41 values for four nearest allies plus cap-independent count; and
- H: 45 aggregate, arena, config, history, weld, and multiplier values.

All values are finite. Fixed scales are mana 2000, HP 1000, velocity 1000,
cooldown 60, range 1000, and radius 100. These constants derive from
catalogued stat/skill maxima and live movement/cooldown probes and do not vary
with a batch.

The navigation patch and clearance rays come from a per-scene cached grid
refreshed at roughly two seconds only from complete snapshots.
`sd.nav.test_segment` remains exclusive to the movement mask. Enemy velocity
and target persistence use `network_actor_id`. The four ally slots exclude
self, but the ally count traverses the full in-run participant list without a
participant-cap constant.

## Autoregressive actions

Movement action 0 stops the bot. Actions 1 through 8 select compass
directions. The corresponding 110-unit native segment must be legal.

Target action 0 keeps the persisted target. It is legal when that actor is
live or when no enemy exists. Actions 1 through 8 choose the corresponding
present, living Block D enemy slot. The selected actor then persists by
network ID even though distance-sorted slots can change.

Cast action 0 does nothing. Action 1 uses primary slot 0. Actions 2 through 9
use secondary slots 1 through 8. Lua selects movement and target from their
masks first, invokes the observation builder to persist that target and build
its cast mask, then selects cast. A cast requires common offense/readiness plus
per-slot occupancy, affordability, readable readiness, and resolved range
legality. Unknown secondary range is not guessed and remains subject to native
validation.

The selected composite log probability is:

```text
log p(move) + log p(target) + log p(cast | target mask)
```

PPO clips the ratio of this composite action. Entropy bonuses and metrics are
separate per head. Defaults are movement `0.01`, target `0.02`, and cast
`0.01`; the doubled target coefficient counteracts early attraction to the
often-legal `keep_current` action.

## Rollouts

Training is disabled by default. Strict trajectory version 2 records:

- trajectory, episode, participant, and exact simulation-tick identity;
- the 395-value observation;
- movement, target, and target-conditioned cast masks;
- zero-based movement, target, and cast actions;
- the three-head composite old log probability and old value;
- transition reward; and
- terminal state.

The reward belongs to the preceding composite action: Lua holds a transition
until the next state. Its coefficients are unchanged from v1 and contain no
wrapper-target reward. GAE groups by `(episode_id, participant_id)`.
Trajectory-v1 frames are rejected rather than reinterpreted.

## Bootstrap and live training

The deterministic bootstrap initializes a new v2 model and generates new
target-first expert samples. It scores the eight enemy slots, selects a slot
or legal persisted target, and only then derives the cast mask/action for that
enemy. Block E remains the pre-decision persisted target; it is not copied into
the target label. No v1 weights, trajectories, or expert data are loaded.

The checked-in JSON and Lua artifacts originate from the same model map. Tests
require a fresh Lua render of `policy-v2.json` to equal the checked-in
`policy_weights.lua`, and compare Lua/Python probabilities, actions, value,
and composite log probability on the same fixture.

Live PPO hot-loads the same strict model after writing temporary JSON and Lua
files and atomically replacing each destination. Because the v2 text export is
larger than the loader's 1 MiB exec request limit, the bridge stages 512 KiB
chunks in Lua and invokes `load_parameters` only after every chunk is present
and the candidate compiles. A partial transfer cannot replace the active
weights or advance generation. The current controlled arena proves this
data/action path but is not a production competence environment.

## Accepted limits

- Some native secondary range/cooldown rows remain unresolved; explicit flags
  select the approved no-range-gate/global-readiness behavior.
- Per-slot enemy/ally observations are bounded to 8/4 while aggregate roster
  counts remain cap-agnostic.
- Scripted pickup and weld managers remain outside the learned action heads.
- Skill-choice learning, aim offsets, recurrence, inventory mutations, fresh
  seed/session rotation, and team-composition rotation are outside Phase 4.
