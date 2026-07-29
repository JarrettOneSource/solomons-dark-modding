local root = assert(arg[1], "repository root argument is required")

local function load_module(relative_path)
  local chunk, error_message = loadfile(root .. "/" .. relative_path)
  assert(chunk, error_message)
  return chunk()
end

local spec = load_module("mods/bot-brain/scripts/policy_spec.lua")
local policy = load_module("mods/bot-brain/scripts/policy.lua")
local weights = load_module("mods/bot-brain/scripts/policy_weights.lua")
local training = load_module("mods/bot-brain/scripts/policy_training.lua")

local runtime = policy.new(spec, weights)
local observation = {}
for index = 1, #spec.observation_names do
  observation[index] = ((index * 37) % 101 - 50) / 50
end
local movement_mask = {}
for index = 1, #spec.movement_actions do
  movement_mask[index] = index % 3 ~= 0
end
local cast_mask = {}
for index = 1, #spec.cast_actions do
  cast_mask[index] = index % 4 ~= 0
end

local decision = runtime:forward(
  observation,
  movement_mask,
  cast_mask,
  false)
print("movement_action=" .. tostring(decision.movement_action))
print("cast_action=" .. tostring(decision.cast_action))
print(string.format("value=%.17g", decision.value))

local movement_probabilities = {}
for index, value in ipairs(decision.movement_probabilities) do
  movement_probabilities[index] = string.format("%.17g", value)
end
print("movement_probabilities=" ..
  table.concat(movement_probabilities, ","))
local cast_probabilities = {}
for index, value in ipairs(decision.cast_probabilities) do
  cast_probabilities[index] = string.format("%.17g", value)
end
print("cast_probabilities=" .. table.concat(cast_probabilities, ","))

local controller = training.new(spec, runtime)
local context = {participant_id = 42}
local capture = {
  values = observation,
  movement_mask = movement_mask,
  cast_mask = cast_mask,
  metrics = {
    hp_ratio = 1.0,
    mana_ratio = 1.0,
    wave = 1,
    alive = true,
    enemy_count = 1,
    enemy_health = {[7] = 1.0},
  },
}
controller:enable({seed = 123, capacity = 128})
controller:record(context, capture, decision, 10)
capture.metrics = {
  hp_ratio = 1.0,
  mana_ratio = 0.9,
  wave = 1,
  alive = true,
  enemy_count = 1,
  enemy_health = {[7] = 0.8},
}
controller:record(context, capture, decision, 20)
capture.metrics = {
  hp_ratio = 1.0,
  mana_ratio = 0.8,
  wave = 2,
  alive = true,
  enemy_count = 0,
  enemy_health = {},
}
controller:record(context, capture, decision, 30)
local before = controller:status()
assert(before.buffered == 2)
assert(before.recorded == 2)
assert(before.dropped == 0)
local drained = controller:drain(2)
assert(#drained.records == 2)
assert(drained.records[1].simulation_tick == 10)
assert(drained.records[2].simulation_tick == 20)
assert(drained.records[1].reward > 0)
assert(drained.records[2].reward > drained.records[1].reward)
assert(controller:status().buffered == 0)
capture.metrics.hp_ratio = 0.0
capture.metrics.alive = false
controller:terminal(context, capture.metrics)
local terminal = controller:drain(1)
assert(#terminal.records == 1)
assert(terminal.records[1].done == true)
assert(terminal.records[1].reward < -3.0)
print("training_ring_ok=true")
