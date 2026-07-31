local root = assert(arg[1], "repository root argument is required")

local function load_module(relative_path)
  local chunk, error_message = loadfile(root .. "/" .. relative_path)
  assert(chunk, error_message)
  return chunk()
end

local function action_names(actions)
  local names = {}
  for index, action in ipairs(actions) do
    names[index] = action.name
  end
  return names
end

local function print_probabilities(label, probabilities)
  local values = {}
  for index, value in ipairs(probabilities) do
    values[index] = string.format("%.17g", value)
  end
  print(label .. "=" .. table.concat(values, ","))
end

local spec = load_module("mods/bot-brain/scripts/policy_spec.lua")
local policy = load_module("mods/bot-brain/scripts/policy.lua")
local weights = load_module("mods/bot-brain/scripts/policy_weights.lua")
local training = load_module("mods/bot-brain/scripts/policy_training.lua")

local runtime = policy.new(spec, weights, 20260730)
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
local selected_ability_mask = nil
local selected_aim_mask = nil
local decision = runtime:forward(
  observation,
  movement_mask,
  target_mask,
  function(target_action)
    local mask = {}
    for index = 1, #spec.ability_actions do
      mask[index] = (index + target_action) % 5 ~= 0
    end
    mask[1] = true
    selected_ability_mask = mask
    return mask
  end,
  function(ability_action)
    local mask = {}
    for index = 1, #spec.aim_actions do
      mask[index] = (index + ability_action) % 4 ~= 0
    end
    mask[1] = true
    selected_aim_mask = mask
    return mask
  end,
  false)

local descriptors = {}
for row = 1, 3 do
  descriptors[row] = {}
  for column = 1, #spec.option_descriptor_names do
    descriptors[row][column] =
      ((row * (column + 4)) % 29 - 14) / 14
  end
end
local choice_mask = {true, false, true}
local choice = runtime:forward_choice(
  observation,
  descriptors,
  choice_mask,
  false)

print("observation_count=" .. tostring(#spec.observation_names))
print("observation_names=" .. table.concat(spec.observation_names, ","))
print(
  "option_descriptor_count=" ..
  tostring(#spec.option_descriptor_names))
print(
  "option_descriptor_names=" ..
  table.concat(spec.option_descriptor_names, ","))
print(
  "movement_names=" ..
  table.concat(action_names(spec.movement_actions), ","))
print(
  "target_names=" ..
  table.concat(action_names(spec.target_actions), ","))
print(
  "ability_names=" ..
  table.concat(action_names(spec.ability_actions), ","))
print(
  "aim_names=" ..
  table.concat(action_names(spec.aim_actions), ","))
print(
  "hidden_sizes=" .. tostring(spec.hidden_sizes[1]) .. "," ..
  tostring(spec.hidden_sizes[2]))
print(
  "choice_hidden_size=" ..
  tostring(runtime:status().choice_hidden_size))
print("movement_action=" .. tostring(decision.movement_action))
print("target_action=" .. tostring(decision.target_action))
print("ability_action=" .. tostring(decision.ability_action))
print("aim_action=" .. tostring(decision.aim_action))
print(string.format("log_probability=%.17g", decision.log_probability))
print(string.format("value=%.17g", decision.value))
print_probabilities(
  "movement_probabilities", decision.movement_probabilities)
print_probabilities(
  "target_probabilities", decision.target_probabilities)
print_probabilities(
  "ability_probabilities", decision.ability_probabilities)
print_probabilities("aim_probabilities", decision.aim_probabilities)
print("choice_action=" .. tostring(choice.choice_action))
print(string.format("choice_value=%.17g", choice.value))
print(
  string.format(
    "choice_log_probability=%.17g", choice.log_probability))
print_probabilities("choice_probabilities", choice.probabilities)

for _, version in ipairs({1, 2}) do
  local ok, error_message = pcall(function()
    policy.new(spec, {
      format = "solomon-dark-bot-policy",
      version = version,
      observation_version = version,
      architecture = version == 1 and
        "mlp-tanh-two-head-v1" or
        "mlp-tanh-three-head-v2",
      observation_size = version == 1 and 87 or 395,
    })
  end)
  assert(ok == false)
  assert(
    string.find(
      tostring(error_message),
      "policy v1/v2 artifacts are incompatible",
      1,
      true) ~= nil)
  print("v" .. tostring(version) .. "_rejected=true")
  print("v" .. tostring(version) .. "_error=" .. tostring(error_message))
end

local controller = training.new(spec, runtime)
local context = {participant_id = 42}
local capture = {
  values = observation,
  movement_mask = movement_mask,
  target_mask = target_mask,
  ability_mask = selected_ability_mask,
  aim_mask = selected_aim_mask,
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
local reset = controller:clear_main()
assert(reset.enabled == true)
assert(reset.buffered == 0)
assert(reset.recorded == 0)
capture.metrics = {
  hp_ratio = 1.0,
  mana_ratio = 0.9,
  wave = 1,
  alive = true,
  enemy_count = 1,
  enemy_health = {[7] = 0.8},
}
controller:record(context, capture, decision, 20)
local finished = controller:finish_episode()
assert(finished.enabled == false)
assert(finished.buffered == 1)
local drained = controller:drain(1)
assert(#drained.records == 1)
assert(drained.records[1].trajectory_version == 3)
assert(#drained.records[1].observation == 1279)
assert(#drained.records[1].ability_mask == 22)
assert(#drained.records[1].aim_mask == 9)
assert(drained.records[1].done == true)
print("main_only_reset_ok=true")
print("training_ring_ok=true")
