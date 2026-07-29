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
local target_mask = {}
for index = 1, #spec.target_actions do
  target_mask[index] = index % 4 ~= 0
end
local selected_cast_mask = nil
local decision = runtime:forward(
  observation,
  movement_mask,
  target_mask,
  function(target_action)
    local mask = {}
    for index = 1, #spec.cast_actions do
      mask[index] = (index + target_action) % 4 ~= 0
    end
    mask[1] = true
    selected_cast_mask = mask
    return mask
  end,
  false)

print("observation_names=" .. table.concat(spec.observation_names, ","))
local movement_names = {}
for index, action in ipairs(spec.movement_actions) do
  movement_names[index] = action.name
end
print("movement_names=" .. table.concat(movement_names, ","))
local target_names = {}
for index, action in ipairs(spec.target_actions) do
  target_names[index] = action.name
end
print("target_names=" .. table.concat(target_names, ","))
local cast_names = {}
for index, action in ipairs(spec.cast_actions) do
  cast_names[index] = action.name
end
print("cast_names=" .. table.concat(cast_names, ","))
print(
  "hidden_sizes=" ..
  tostring(spec.hidden_sizes[1]) .. "," ..
  tostring(spec.hidden_sizes[2]))
print("movement_action=" .. tostring(decision.movement_action))
print("target_action=" .. tostring(decision.target_action))
print("cast_action=" .. tostring(decision.cast_action))
print(string.format("log_probability=%.17g", decision.log_probability))
print(string.format("value=%.17g", decision.value))

local function print_probabilities(label, probabilities)
  local values = {}
  for index, value in ipairs(probabilities) do
    values[index] = string.format("%.17g", value)
  end
  print(label .. "=" .. table.concat(values, ","))
end

print_probabilities(
  "movement_probabilities",
  decision.movement_probabilities)
print_probabilities(
  "target_probabilities",
  decision.target_probabilities)
print_probabilities(
  "cast_probabilities",
  decision.cast_probabilities)
local cast_mask_bits = {}
for index, value in ipairs(selected_cast_mask) do
  cast_mask_bits[index] = value and "1" or "0"
end
print("cast_mask=" .. table.concat(cast_mask_bits))

local v1_ok, v1_error = pcall(function()
  policy.new(spec, {
    format = "solomon-dark-bot-policy",
    version = 1,
    observation_version = 1,
    architecture = "mlp-tanh-two-head-v1",
    observation_size = 87,
    hidden_size = 48,
  })
end)
assert(v1_ok == false)
assert(
  string.find(
    tostring(v1_error),
    "policy v1 artifacts are incompatible",
    1,
    true) ~= nil)
print("v1_rejected=true")
print("v1_error=" .. tostring(v1_error))

local controller = training.new(spec, runtime)
local context = {participant_id = 42}
local capture = {
  values = observation,
  movement_mask = movement_mask,
  target_mask = target_mask,
  cast_mask = selected_cast_mask,
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
assert(#drained.records[1].target_mask == 9)
assert(
  drained.records[1].target_action ==
  decision.target_action)
assert(#drained.records[1].cast_mask == 10)
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
