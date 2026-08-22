# ML Bot Diagnostics & Training Playbook

Working document for the training phase of the learned bot policy (schema v4,
1333 obs, four masked heads + value + SMDP choice head — see
`ml-bot-policy-v3.md`). Its purpose is twofold and symmetric:

1. **Provably improve** — every change to the training stack must be justified
   by a pre-registered metric measured under the fixed evaluation protocol,
   or it does not land.
2. **Falsifiably conclude** — if the policy cannot reach the target, this
   document defines the exact evidence ladder that must be exhausted before
   anyone may claim "it can't generalize to this task." Expected outcome:
   we never reach that claim. The BC bootstrap already imitates the scripted
   expert, and live probes have shown learned welding, hazard dodging, and
   aim lead. The ladder exists to make the negative claim expensive and the
   positive claims trustworthy.

Doctrine that governs everything here (established, non-negotiable):

- **Two-surface order.** Every pathology is investigated integration-first:
  prove the observations, masks, actions, and rewards tell the truth about
  the game before touching the algorithm. Integration bugs masquerade as
  learning failure (canonical precedent: the Air-primary bug — 1,466
  accepted casts, zero applied damage; PPO would have learned "casting is
  worthless" from a seam bug). Every closed investigation records which
  surface owned the failure.
- **Applied truth only.** Success metrics are native applied effects
  (damage edges with `source_participant_id`, XP deltas, wave transitions),
  never accepted-call counts.
- **No band-aids.** A NaN, a dead feature, or a miscalibrated guard is a
  seam bug to root-cause, not a value to clamp.
- **The campaign gate.** Training campaigns (including any hyperparameter
  sweep) launch only on explicit owner authorization. Short live probes,
  fixtures, and single-episode diagnostics are the same class as the V3
  gate proofs and are always allowed.

---

## 1. Metrics contract

Two append-only JSONL streams, written by the trainer next to checkpoints
under `runtime/ml-training/<instance>/`:

### 1.1 `metrics.jsonl` — one record per PPO iteration

```
iter, wall_seconds, env_steps_total, episodes_completed,
return_mean, return_std, wave_depth_mean, wave_depth_max, ep_len_mean,
policy_loss, value_loss, kl_divergence, clip_fraction, grad_norm,
adv_mean, adv_std,
entropy_move, entropy_target, entropy_ability, entropy_aim,
smdp: {events, policy_loss, value_loss, entropy_normalized, temperature,
       selections_per_family},
reward_terms: {xp, own_damage, self_hp, wave, death}   # summed this iter
```

### 1.2 `episodes.jsonl` — one record per completed episode

```
seed, composition, boneyard_layout, waves_reached, steps, return,
reward_terms: {xp, own_damage, self_hp, wave, death},
action_histograms: {move[9], target[9], ability[22], aim[9]},
consumables_used, powerups_collected, keys_held_max,
death: bool, final_level, choice_events: [{options, chosen, interval_steps}]
```

Rules: records are emitted even for failed/aborted episodes (marked), no
field is ever silently omitted, and schema changes bump a `metrics_version`
field. The reward-term decomposition must sum to the episode return (clamp
applied last, logged when it binds — a frequently-binding clamp is itself a
finding).

---

## 2. Evaluation protocol

All comparative claims — between checkpoints, hyperparameters, or against
baselines — use this protocol. Nothing else counts.

- **Eval seed sets.** `tools/ml_bot/eval-seeds.json` defines two frozen
  lists: `eval_train_dist` (seeds from the training rotation) and
  `eval_holdout` (seeds + layouts the trainer never sees, including any
  custom boneyards from the owner's corpus when it arrives). The holdout
  set is the generalization instrument — the owner mandate is generality
  across randomly-seeded and custom boneyards, so the number that matters
  long-term is holdout wave depth, not training-distribution wave depth.
- **Statistics.** Wave depth and return are high-variance. Report
  mean ± bootstrap 95% CI over ≥ 30 episodes per condition; a comparison
  is a "win" only if CIs separate or a paired-by-seed test agrees.
  Never compare single episodes.
- **Baselines (measured once under this exact protocol, then frozen):**
  - random-policy floor,
  - BC bootstrap (the campaign starting point),
  - scripted expert (`tools/ml_bot/expert.py`) — historical reference
    22.67 waves, to be re-measured under this protocol before first use.
- **Promotion rule.** A checkpoint is "better" only if it beats the
  incumbent on eval_train_dist without regressing eval_holdout, both
  CI-backed. A train/holdout gap that grows across iterations is
  memorization and is treated as a regression even if train-dist improves.
- **One change at a time.** Every experiment pre-registers: the change,
  the metric expected to move, and the eval condition — in
  `runtime/ml-training/experiments.md` before launch. Changes that alter
  the task itself (reward weights, observation schema) are owner-gated
  and version-bumped; they reset baselines and are never mixed into a
  tuning comparison.

---

## 3. Diagnostic toolkit

Status legend: **[exists]** — usable today; **[build]** — contract defined
here, implementation is dispatchable work.

### 3.1 Training curves dashboard **[build]**
`tools/ml_bot/plot_metrics.py` renders `metrics.jsonl` into a single
self-contained HTML page: return/wave-depth (with baselines as horizontal
bands), losses, KL/clip fraction, grad norm, the four per-head entropies,
and the SMDP stream on its own axes. Reach for it every session; entropy
and KL panels are the early-warning instruments.

### 3.2 Reward decomposition view **[build]**
Stacked per-term area over iterations from `episodes.jsonl`, plus a
per-episode drill-down. This is the reward-hacking detector: wave depth
flat while one term grows is the signature (e.g. chip-damage farming pays
the 0.65 own-damage term without kills — watch the damage:xp ratio).

### 3.3 Spatial episode replay **[build]**
The single highest-value inspection tool. The trainer (or
`verify_ml_bot_live.py --record`) logs per-tick bot position, enemy
positions, drops, hazards, chosen actions, and V(s) to
`runtime/ml-training/replays/<episode-id>.jsonl`; a renderer produces a
self-contained HTML canvas replay over the exact collision geometry from
`sd.nav.get_collision_geometry`, path colored by value estimate. Watching
one replay answers "what is it actually doing" faster than any curve —
kiting, wall-hugging, hazard behavior, drop routing are all visible at a
glance. Screen-space overlay only; world rendering stays native per the
owner's cutover mandate — this is an offline HTML artifact, not an
in-game overlay.

### 3.4 Observation audit **[build]**
Per-feature min/max/mean/std/NaN/const-fraction over a rollout batch,
diffed against the schema. Catches scaling explosions, dead features
(a feature that never varies is a seam bug or wasted width), and
NaN/inf at the source. Run after every schema change and on any numeric
instability. Integration surface, first resort.

### 3.5 Per-head action audit **[exists partially / build]**
Action histograms already land in `episodes.jsonl` **[build]**; the live
verifier already prints per-head choices **[exists]**. The audit view
overlays histogram evolution per head across training — the
collapse-detection companion to the entropy curves (e.g. target head
degenerating to "always nearest").

### 3.6 Value calibration scatter **[build]**
Predicted V(s) vs realized discounted return, per rollout. Systematic
bias or exploding spread localizes value-function trouble independent of
policy trouble — this is the first stop for the SMDP value-loss watchlist
item (6760 on the 1-interval smoke; check whether batch-32 normalization
tames it, else add return normalization to the SMDP stream).

### 3.7 Block saliency **[build]**
|∂ chosen-logit / ∂ observation|, aggregated to the block level (enemy
block, pickup block, hazard block, ally block, inventory, choice
descriptors), averaged per episode. Answers "what was it looking at when
it did that" at interpretable granularity. Cheap (one backward pass per
sampled decision) and the honest version of "is it using the new v4
identity features or ignoring them."

### 3.8 Choice-head (SMDP) audit **[build]**
Per-event log already specified in `episodes.jsonl`; the audit renders
per-family/weld selection frequencies over training vs the temperature
schedule, option-descriptor coverage, and realized-return-per-choice.
Degenerate build selection (one family regardless of context) shows up
here first.

### 3.9 Behavior probe scorecard **[build]**
Fixed, seeded micro-scenarios run per checkpoint via the live-verifier
machinery; each returns pass/fail + a scalar. Initial set:

| probe | setup | pass condition |
|---|---|---|
| kite | one fast melee enemy, open field | survive 60s, mean distance in band |
| obstacle-path | target behind wall | reaches without stall (8u clearance) |
| potion | HP < 40%, health potion held, no threat | drinks within 5s |
| orb-route | low mana, mana orb 200u away | collects it |
| hazard-exit | telegraphed hazard underfoot | exits before activation |
| aim-lead | strafing enemy at range | hit rate ≥ stationary baseline |
| level-choice | forced level-up | legal, non-degenerate selection |
| powerup | powerup drop nearby, enemies present | collects within episode |
| drop-triage | health potion vs junk equipment drop, low HP | routes to potion first |
| golem-anchor (web) | Raise Golem build, mixed melee wave | golem alive ≥ 60% of episode; bot within 300u of it ≥ 50% of combat ticks |
| recast-timing (web) | golem alive at 80% HP, full mana | no Raise Golem recast within 10s |
| circle-kite (web) | Magic Circle build, melee pack | ≥ 1 enemy crosses own circle per 20s of combat |
| trap-stack (web) | live Magic Trap underfoot | no second trap within its radius while it lives |
| swing-dodge (web) | weapon skeleton at reach, bot at full HP | leaves skeleton reach before the first marker on ≥ 70% of swings |
| recovery-punish (web) | mixed melee wave | damage/s dealt during enemy recover/cooldown ≥ damage/s during windup |

The scorecard turns "the model got better" into a behavior-level diff
between checkpoints, and each probe doubles as an integration fixture
(a probe that no policy can pass is a seam bug by two-surface order).

Web Port (schema v5) integration fixtures precede the probes above:
own-projectile-visible, own-held-visible, own-area-visible,
effect-active-flags, own-golem-visible, ally-golem-visible,
minion-target-link, hazard-ttc-exact, already-hit-me, golem-kill-credit,
strike-tick-exact, claw-loop, ranged-strike-exact, phase-closed,
dying-excluded, targeting-self, and status-join, as specified in
`ml-bot-policy-web-port.md` §9. Each
fixture ships with its mutation (block zeroed or flag inverted must fail),
and the observation audit (§3.4) must show non-constant Blocks R and S on
every composition that includes Raise Golem or an area skill.

### 3.10 Checkpoint arena **[build]**
Round-robin evaluation of stored checkpoints on the frozen eval sets,
maintained as a ladder table. Detects silent regressions and gives the
promotion rule its data. Full-scale arena runs are campaign-class
(gated); a 3-checkpoint spot-check is not.

### 3.11 Linear/BC probe **[build]**
Fit a linear policy (and optionally a small-kernel one) on the same 1333
features to imitate the expert, and compare to the trunk's BC accuracy.
Establishes how much of the task is linearly solvable given our feature
engineering, i.e. how much work the 512/256 trunk actually does. If a
linear probe nearly matches the trunk, plateaus are feature/reward
problems, not capacity problems. Uses existing expert + bridge machinery.

### 3.12 Existing instruments **[exists]**
Fixture battery (546 Python / 308 static — includes idle-reward-zero,
free-rider-zero, mask-legality), `verify_ml_bot_live.py` live gates,
`verify_lua_bot_brain.py`, headless accel harness, per-episode fresh
seeding via `sd.rng.set_seed`, composition rotation
(`tools/ml_bot/team-compositions.json`). These stay the ground-truth
layer under every tool above.

---

## 4. Pathology → playbook

Symptom-indexed. In every row the integration check comes first, per
doctrine.

| symptom | integration check first | then ML surface |
|---|---|---|
| entropy → 0 early, return flat | obs audit (scaling blow-up saturates tanh trunk) | entropy coefficient, advantage normalization |
| one head collapses (e.g. target) | mask legality vs native acceptance for that head | per-head entropy coefficient |
| value loss diverges (SMDP watchlist) | reward decomposition sums correct; clamp not binding constantly | return normalization on SMDP stream, batch size |
| return ↑ but wave depth flat | reward decomposition — which term is growing; replay the top-return episode | reward hacking confirmed → report to owner (reward is owner-gated), do not tune around it |
| learns solo, flat on team compositions | free-rider fixture on live build; `source_participant_id` edge attribution spot-check | composition rotation weights, credit horizon |
| train-dist ↑, holdout flat/↓ | layouts actually rotating (episode records) | more seed diversity per iter, fewer PPO epochs per batch, entropy floor |
| plateau below expert baseline | linear probe (features sufficient?); probe scorecard (which behaviors missing?) | BO over declared space; γ/GAE horizon vs wave length |
| choice head degenerate | option descriptors vary correctly per family (descriptor truth fixture) | temperature floor, minimum-choice-batch |
| any NaN/inf | obs audit → find the producing seam and fix it there | never clamp at the consumer |
| episode guard trips / rollouts time out | XP path live check (the V3 guard precedent: guard was miscalibrated, integration was healthy) | autoscale factors only after integration is proven |

Every closed investigation appends one line to
`runtime/ml-training/findings.md`: date, symptom, owning surface
(integration | algorithm | protocol), root cause, fix commit.

---

## 5. Hyperparameter search (gated)

When the owner lifts the campaign gate, tuning runs as GP Bayesian
optimization (expensive noisy black-box, ~10 dims — the textbook regime),
not hand-twiddling:

- **Search space:** learning rate, PPO clip, per-head entropy
  coefficients, value-loss weight, GAE λ, γ, SMDP loss scale /
  normalization, choice-temperature schedule bounds, PPO epochs.
- **Excluded from search:** reward weights (owner-adjudicated task
  definition), observation schema, episode/guard semantics.
- **Objective:** mean holdout wave depth over a fixed reduced seed set on
  short proxy campaigns; final candidates re-run at full length (proxy
  rank ≠ full rank is itself a finding to record).
- Every trial is one `experiments.md` row; the BO log is a committed
  artifact.

---

## 6. The falsification ladder ("it can't generalize")

The claim may only be made after **all** rungs are green-checked with
artifacts. Any rung failing short-circuits into a fix, not a conclusion.

1. **Integration certified.** Full fixture battery green; obs audit clean
   on a fresh rollout; reward decomposition hand-audited against 3 raw
   episode logs (native XP/damage/wave events vs logged terms).
2. **Representation floor.** BC on expert demonstrations reaches a
   pre-registered fraction of expert wave depth. Success proves the task
   is representable and optimizable in this architecture — any later RL
   failure is then optimization/reward, *not* "the net can't express it."
3. **Credit-assignment floor.** Overfit a single frozen seed to
   expert-level. Proves the reward → gradient path can shape behavior at
   all.
4. **Tuning exhausted.** BO budget (pre-registered trial count) spent;
   no configuration crosses the expert baseline on eval_train_dist.
5. **Capacity checked.** One 2× trunk-width run at the best-known config.
6. **Horizon checked.** γ/GAE range in the BO space covers episode-length
   timescales (waves are minutes at 100 Hz — verify the discount horizon
   actually spans a wave).

Required artifacts for the negative claim: curves, BO log, probe
scorecards, arena table, and replays of the best policy — enough that a
reviewer can see *what the best attempt actually does* and agree the
failure is fundamental rather than procedural. If rungs 2 and 3 pass but
4–6 fail persistently, the honest conclusion is "not with this reward /
horizon," which is a design conversation with the owner, not a dead end.

---

## 7. Build order

When tool-building is dispatched, the dependency-honest order is:

1. Metrics contract (§1) + eval seeds file (§2) — everything else reads
   these.
2. Curves dashboard (3.1), reward decomposition (3.2), obs audit (3.4) —
   the minimum session kit.
3. Spatial replay (3.3) — highest single-tool value.
4. Probe scorecard (3.9) + arena (3.10) — the promotion machinery.
5. Value calibration (3.6), saliency (3.7), SMDP audit (3.8), linear
   probe (3.11).
6. BO harness (§5) — built last, launched only past the campaign gate.

All renderers produce self-contained artifacts (no external assets), all
readers tolerate partial/in-progress JSONL, and nothing in this toolkit
mutates training state — inspection is strictly read-only.
