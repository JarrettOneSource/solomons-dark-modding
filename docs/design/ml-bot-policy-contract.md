# ML bot policy contract

The player build executes a compact feed-forward policy entirely inside the
`bot.brain` Lua mod. Python and NumPy are training tools only. The shipped mod
does not open a network service, start Python, require a GPU, or send gameplay
state outside the game process.

## Versioned model

Model format `solomon-dark-bot-policy` version 1 uses architecture
`mlp-tanh-two-head-v1`:

1. 87 normalized observations;
2. one fully connected tanh layer with 48 units;
3. a masked 9-way movement head;
4. a masked 10-way cast head; and
5. one scalar value head used only while training.

The ordered observation and action names are canonical in
`tools/ml_bot/spec.py`. `scripts/policy_spec.lua` carries the same contract for
the in-game runtime. A model is rejected unless every version, name, and tensor
shape matches exactly.

A recurrent model is deliberately not the first shipped architecture. The
observations include one-step deltas, the preceding action, and elapsed-action
signals. This keeps player inference small and makes the initial PPO evidence
easy to audit. A future GRU must use a new architecture and model version; it
cannot silently reinterpret version 1 weights.

## Actions

Movement action 0 stops the bot. Actions 1 through 8 select a world-space
compass direction. Before sampling or selecting, Lua tests the corresponding
segment against the navigation grid. Untraversable directions are masked. A
selected direction is sent to the existing native `bot:move_to` participant
rail, so the learned bot moves as a real replicated player slot.

Cast action 0 does nothing. Action 1 uses primary slot 0. Actions 2 through 9
use secondary slots 1 through 8. Cast actions are masked unless offense is
enabled, a live target is in the validated attack window, the native bot is
ready to cast, and the selected loadout slot exists. The selected action is
sent through `bot:cast`, which retains the native queue, mana, cooldown, and
spell validation.

Scripted skill-upgrade selection remains active for learned bots. Inventory,
equipment, spellbook, ability-loadout, gold, status, and derived-stat state are
observed by version 1. The loader does not currently expose owner-safe
per-bot consume or equip mutations, so version 1 has no dishonest item action
that could never execute. Adding those native rails requires a new masked
action head and a contract version bump.

Version 1 records whether each secondary slot is populated, but not that
slot's spell identity, mana cost, range, or independent readiness. Its cast
mask therefore uses the bot's validated primary attack window and relies on
the native cast rail for final per-spell rejection. Per-slot spell semantics
and learned target selection are higher-priority version-2 additions than
recurrence.

## Rollouts

Training is disabled by default. When explicitly enabled through the local Lua
execution pipe, each completed transition contains:

- contract and episode identity;
- participant and exact 100 Hz simulation tick;
- observation, movement mask, and cast mask;
- zero-based movement and cast actions;
- the combined old log probability and old value estimate;
- transition reward; and
- terminal state.

The reward belongs to the preceding selected action: Lua holds a pending
transition until it observes the next state. Death and run-end events flush the
pending transition as terminal. PPO uses a single combined log probability for
the two conditionally independent masked heads.

## Controlled live-training arena

The live PPO bridge deliberately separates curriculum combat from production
waves. It enables manual-enemy test mode and queues a direct call to the game's
exact stock enemy constructor with an empty modifier array. The gameplay pump
accepts that path only for explicit direct-arena requests while test mode is
active and the process is the simulation authority. Arena wave state is pinned
for the duration of test mode so stock wave production cannot race the
curriculum manager.

Each requested enemy must appear as a tracked, living world actor before a
rollout can continue. The enemy retains stock AI and combat behavior. The
bridge also unlocks the configured elemental primary by stepping the real
native level-up and pending-choice APIs; it refuses conflicting elemental
primaries rather than mutating a loadout directly.

This controlled arena proves and trains the policy-to-native action loop. It
does not reproduce wave cadence, multi-enemy credit assignment, elite
modifiers, or the distribution of elements, Disciplines, items, and builds
seen in player games. Those require separate ordinary-wave evaluation gates.
