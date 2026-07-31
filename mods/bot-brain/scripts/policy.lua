local policy = {}
local Runtime = {}
Runtime.__index = Runtime

local function finite_number(value)
  return type(value) == "number" and value == value and
    value > -math.huge and value < math.huge
end

local function fail(message)
  error("invalid bot policy: " .. message, 3)
end

local function validate_names(actual, expected, label)
  if type(actual) ~= "table" or #actual ~= #expected then
    fail(label .. " names do not match the policy-v3 contract")
  end
  for index, expected_name in ipairs(expected) do
    if actual[index] ~= expected_name then
      fail(
        label .. " name " .. tostring(index - 1) ..
        " must be " .. tostring(expected_name))
    end
  end
end

local function validate_vector(value, length, label)
  if type(value) ~= "table" or #value ~= length then
    fail(
      label .. " must contain " .. tostring(length) ..
      " finite numbers")
  end
  for index = 1, length do
    if not finite_number(value[index]) then
      fail(label .. "[" .. tostring(index) .. "] is not finite")
    end
  end
end

local function validate_matrix(value, rows, columns, label)
  if type(value) ~= "table" or #value ~= rows then
    fail(label .. " must contain " .. tostring(rows) .. " rows")
  end
  for row = 1, rows do
    validate_vector(
      value[row],
      columns,
      label .. "[" .. tostring(row) .. "]")
  end
end

local function action_names(actions)
  local names = {}
  for index, action in ipairs(actions) do
    names[index] = action.name
  end
  return names
end

local function validate_parameter_names(parameters)
  local required = {
    input_weight = true,
    input_bias = true,
    hidden_weight = true,
    hidden_bias = true,
    movement_weight = true,
    movement_bias = true,
    target_weight = true,
    target_bias = true,
    ability_weight = true,
    ability_bias = true,
    aim_weight = true,
    aim_bias = true,
    value_weight = true,
    value_bias = true,
    choice_option_weight = true,
    choice_option_bias = true,
    choice_score_weight = true,
    choice_score_bias = true,
    choice_value_weight = true,
    choice_value_bias = true,
  }
  for name in pairs(parameters) do
    if required[name] ~= true then
      fail("unexpected policy-v3 parameter " .. tostring(name))
    end
    required[name] = nil
  end
  for name in pairs(required) do
    fail("missing policy-v3 parameter " .. tostring(name))
  end
end

local function validate_weights(spec, candidate)
  if type(candidate) ~= "table" then
    fail("model must be a table")
  end
  if candidate.version == 1 or candidate.version == 2 or
      candidate.observation_version == 1 or
      candidate.observation_version == 2 or
      candidate.architecture == "mlp-tanh-two-head-v1" or
      candidate.architecture == "mlp-tanh-three-head-v2" or
      candidate.observation_size == 87 or
      candidate.observation_size == 395 then
    fail(
      "policy v1/v2 artifacts are incompatible with the strict " ..
      "policy-v3 loader")
  end
  if candidate.format ~= spec.model_format then
    fail("format must be " .. tostring(spec.model_format))
  end
  if candidate.version ~= spec.model_version then
    fail(
      "version must be " .. tostring(spec.model_version) ..
      "; policy v1/v2 and other versions are not supported")
  end
  if candidate.observation_version ~= spec.observation_version then
    fail(
      "observation_version must be " ..
      tostring(spec.observation_version))
  end
  if candidate.architecture ~= spec.architecture then
    fail("architecture must be " .. tostring(spec.architecture))
  end

  local observation_size = #spec.observation_names
  local first_hidden_size = spec.hidden_sizes[1]
  local second_hidden_size = spec.hidden_sizes[2]
  local movement_size = #spec.movement_actions
  local target_size = #spec.target_actions
  local ability_size = #spec.ability_actions
  local aim_size = #spec.aim_actions
  local descriptor_size = #spec.option_descriptor_names
  local choice_hidden_size = spec.choice_hidden_size
  if candidate.observation_size ~= observation_size or
      type(candidate.hidden_sizes) ~= "table" or
      #candidate.hidden_sizes ~= 2 or
      candidate.hidden_sizes[1] ~= first_hidden_size or
      candidate.hidden_sizes[2] ~= second_hidden_size or
      candidate.movement_action_size ~= movement_size or
      candidate.target_action_size ~= target_size or
      candidate.ability_action_size ~= ability_size or
      candidate.aim_action_size ~= aim_size or
      candidate.value_size ~= 1 or
      candidate.option_descriptor_size ~= descriptor_size or
      candidate.choice_hidden_size ~= choice_hidden_size or
      candidate.choice_value_size ~= 1 then
    fail(
      "declared policy-v3 tensor shape must be 1279 -> 512 -> 256 " ..
      "with movement 9, target 9, ability 22, aim 9, value 1, " ..
      "and a 56 -> 128 shared choice scorer")
  end
  validate_names(
    candidate.observation_names,
    spec.observation_names,
    "observation")
  validate_names(
    candidate.movement_action_names,
    action_names(spec.movement_actions),
    "movement action")
  validate_names(
    candidate.target_action_names,
    action_names(spec.target_actions),
    "target action")
  validate_names(
    candidate.ability_action_names,
    action_names(spec.ability_actions),
    "ability action")
  validate_names(
    candidate.aim_action_names,
    action_names(spec.aim_actions),
    "aim action")
  validate_names(
    candidate.option_descriptor_names,
    spec.option_descriptor_names,
    "choice option descriptor")

  local temperature = candidate.choice_temperature
  if temperature ~= spec.choice_exploration_temperature and
      temperature ~= spec.choice_final_temperature then
    fail(
      "choice_temperature must be " ..
      tostring(spec.choice_exploration_temperature) .. " or " ..
      tostring(spec.choice_final_temperature))
  end

  local parameters = candidate.parameters
  if type(parameters) ~= "table" then
    fail("parameters must be a table")
  end
  validate_parameter_names(parameters)
  validate_matrix(
    parameters.input_weight,
    first_hidden_size,
    observation_size,
    "parameters.input_weight")
  validate_vector(
    parameters.input_bias,
    first_hidden_size,
    "parameters.input_bias")
  validate_matrix(
    parameters.hidden_weight,
    second_hidden_size,
    first_hidden_size,
    "parameters.hidden_weight")
  validate_vector(
    parameters.hidden_bias,
    second_hidden_size,
    "parameters.hidden_bias")
  validate_matrix(
    parameters.movement_weight,
    movement_size,
    second_hidden_size,
    "parameters.movement_weight")
  validate_vector(
    parameters.movement_bias,
    movement_size,
    "parameters.movement_bias")
  validate_matrix(
    parameters.target_weight,
    target_size,
    second_hidden_size,
    "parameters.target_weight")
  validate_vector(
    parameters.target_bias,
    target_size,
    "parameters.target_bias")
  validate_matrix(
    parameters.ability_weight,
    ability_size,
    second_hidden_size,
    "parameters.ability_weight")
  validate_vector(
    parameters.ability_bias,
    ability_size,
    "parameters.ability_bias")
  validate_matrix(
    parameters.aim_weight,
    aim_size,
    second_hidden_size,
    "parameters.aim_weight")
  validate_vector(
    parameters.aim_bias,
    aim_size,
    "parameters.aim_bias")
  validate_vector(
    parameters.value_weight,
    second_hidden_size,
    "parameters.value_weight")
  validate_vector(
    parameters.value_bias,
    1,
    "parameters.value_bias")
  validate_matrix(
    parameters.choice_option_weight,
    choice_hidden_size,
    second_hidden_size + descriptor_size,
    "parameters.choice_option_weight")
  validate_vector(
    parameters.choice_option_bias,
    choice_hidden_size,
    "parameters.choice_option_bias")
  validate_vector(
    parameters.choice_score_weight,
    choice_hidden_size,
    "parameters.choice_score_weight")
  validate_vector(
    parameters.choice_score_bias,
    1,
    "parameters.choice_score_bias")
  validate_vector(
    parameters.choice_value_weight,
    second_hidden_size,
    "parameters.choice_value_weight")
  validate_vector(
    parameters.choice_value_bias,
    1,
    "parameters.choice_value_bias")
  if candidate.metadata ~= nil and
      type(candidate.metadata) ~= "table" then
    fail("metadata must be a table")
  end
  return candidate
end

local function tanh(value)
  if value >= 20.0 then
    return 1.0
  end
  if value <= -20.0 then
    return -1.0
  end
  local exponent = math.exp(2.0 * value)
  return (exponent - 1.0) / (exponent + 1.0)
end

local function dense_tanh(inputs, weights, biases)
  local output = {}
  for row, weight_row in ipairs(weights) do
    local value = biases[row]
    for column = 1, #inputs do
      value = value + weight_row[column] * inputs[column]
    end
    output[row] = tanh(value)
  end
  return output
end

local function logits(inputs, weights, biases)
  local output = {}
  for row, weight_row in ipairs(weights) do
    local value = biases[row]
    for column = 1, #inputs do
      value = value + weight_row[column] * inputs[column]
    end
    output[row] = value
  end
  return output
end

local function masked_softmax(values, mask, label, temperature)
  if type(mask) ~= "table" or #mask ~= #values then
    fail(label .. " mask shape mismatch")
  end
  local divisor = temperature or 1.0
  if not finite_number(divisor) or divisor <= 0.0 then
    fail(label .. " temperature must be positive and finite")
  end
  local maximum = -math.huge
  local legal_count = 0
  for index, value in ipairs(values) do
    if mask[index] == true then
      legal_count = legal_count + 1
      maximum = math.max(maximum, value / divisor)
    end
  end
  if legal_count == 0 then
    fail(label .. " mask has no legal action")
  end

  local probabilities = {}
  local total = 0.0
  for index, value in ipairs(values) do
    if mask[index] == true then
      local probability = math.exp(value / divisor - maximum)
      probabilities[index] = probability
      total = total + probability
    else
      probabilities[index] = 0.0
    end
  end
  for index = 1, #probabilities do
    probabilities[index] = probabilities[index] / total
  end
  return probabilities
end

local function argmax(probabilities)
  local best_index = 1
  local best_value = -math.huge
  for index, value in ipairs(probabilities) do
    if value > best_value then
      best_index = index
      best_value = value
    end
  end
  return best_index
end

local function scalar_value(inputs, weights, bias)
  local value = bias[1]
  for index = 1, #inputs do
    value = value + weights[index] * inputs[index]
  end
  return value
end

function Runtime:encode(observation)
  validate_vector(
    observation,
    #self.spec.observation_names,
    "observation")
  local parameters = self.weights.parameters
  local first_hidden = dense_tanh(
    observation,
    parameters.input_weight,
    parameters.input_bias)
  return dense_tanh(
    first_hidden,
    parameters.hidden_weight,
    parameters.hidden_bias)
end

function Runtime:random_unit()
  self.random_state =
    (self.random_state * 48271) % 2147483647
  return self.random_state / 2147483647
end

function Runtime:sample(probabilities)
  local threshold = self:random_unit()
  local cumulative = 0.0
  for index, probability in ipairs(probabilities) do
    cumulative = cumulative + probability
    if threshold <= cumulative then
      return index
    end
  end
  return #probabilities
end

function Runtime:set_seed(seed)
  local normalized = math.floor(tonumber(seed) or 1)
  normalized = normalized % 2147483647
  if normalized <= 0 then
    normalized = normalized + 2147483646
  end
  self.random_state = normalized
end

function Runtime:load(candidate)
  self.weights = validate_weights(self.spec, candidate)
  self.generation = self.generation + 1
  return self.generation
end

function Runtime:status()
  return {
    format = self.spec.model_format,
    version = self.spec.model_version,
    observation_version = self.spec.observation_version,
    architecture = self.spec.architecture,
    observation_size = #self.spec.observation_names,
    hidden_sizes = {
      self.spec.hidden_sizes[1],
      self.spec.hidden_sizes[2],
    },
    movement_action_size = #self.spec.movement_actions,
    target_action_size = #self.spec.target_actions,
    ability_action_size = #self.spec.ability_actions,
    aim_action_size = #self.spec.aim_actions,
    value_size = 1,
    option_descriptor_size = #self.spec.option_descriptor_names,
    choice_hidden_size = self.weights.choice_hidden_size,
    choice_value_size = 1,
    choice_temperature = self.weights.choice_temperature,
    generation = self.generation,
    metadata = self.weights.metadata,
  }
end

function Runtime:forward(
    observation,
    movement_mask,
    target_mask,
    ability_mask_builder,
    aim_mask_builder,
    stochastic)
  if type(ability_mask_builder) ~= "function" then
    fail("ability mask builder must be a function")
  end
  if type(aim_mask_builder) ~= "function" then
    fail("aim mask builder must be a function")
  end

  local parameters = self.weights.parameters
  local hidden = self:encode(observation)
  local movement_probabilities = masked_softmax(
    logits(
      hidden,
      parameters.movement_weight,
      parameters.movement_bias),
    movement_mask,
    "movement")
  local target_probabilities = masked_softmax(
    logits(
      hidden,
      parameters.target_weight,
      parameters.target_bias),
    target_mask,
    "target")
  local movement_index = stochastic == true and
    self:sample(movement_probabilities) or
    argmax(movement_probabilities)
  local target_index = stochastic == true and
    self:sample(target_probabilities) or
    argmax(target_probabilities)

  local ability_mask = ability_mask_builder(target_index - 1)
  local ability_probabilities = masked_softmax(
    logits(
      hidden,
      parameters.ability_weight,
      parameters.ability_bias),
    ability_mask,
    "ability")
  local ability_index = stochastic == true and
    self:sample(ability_probabilities) or
    argmax(ability_probabilities)

  local aim_mask = aim_mask_builder(ability_index - 1)
  local aim_probabilities = masked_softmax(
    logits(
      hidden,
      parameters.aim_weight,
      parameters.aim_bias),
    aim_mask,
    "aim")
  local aim_index = stochastic == true and
    self:sample(aim_probabilities) or
    argmax(aim_probabilities)

  local movement_probability = movement_probabilities[movement_index]
  local target_probability = target_probabilities[target_index]
  local ability_probability = ability_probabilities[ability_index]
  local aim_probability = aim_probabilities[aim_index]
  return {
    movement_action = movement_index - 1,
    target_action = target_index - 1,
    ability_action = ability_index - 1,
    aim_action = aim_index - 1,
    movement = self.spec.movement_actions[movement_index],
    target = self.spec.target_actions[target_index],
    ability = self.spec.ability_actions[ability_index],
    aim = self.spec.aim_actions[aim_index],
    log_probability =
      math.log(movement_probability) +
      math.log(target_probability) +
      math.log(ability_probability) +
      math.log(aim_probability),
    value = scalar_value(
      hidden,
      parameters.value_weight,
      parameters.value_bias),
    movement_probability = movement_probability,
    target_probability = target_probability,
    ability_probability = ability_probability,
    aim_probability = aim_probability,
    movement_probabilities = movement_probabilities,
    target_probabilities = target_probabilities,
    ability_probabilities = ability_probabilities,
    aim_probabilities = aim_probabilities,
    ability_mask = ability_mask,
    aim_mask = aim_mask,
    generation = self.generation,
  }
end

function Runtime:forward_choice(
    observation,
    option_descriptors,
    option_mask,
    stochastic)
  if type(option_descriptors) ~= "table" or
      #option_descriptors == 0 or
      #option_descriptors > self.spec.max_choice_options then
    fail(
      "choice options must contain between 1 and " ..
      tostring(self.spec.max_choice_options) .. " descriptors")
  end
  if type(option_mask) ~= "table" or
      #option_mask ~= #option_descriptors then
    fail("choice option mask shape mismatch")
  end

  local hidden = self:encode(observation)
  local parameters = self.weights.parameters
  local scores = {}
  for option_index, descriptor in ipairs(option_descriptors) do
    validate_vector(
      descriptor,
      #self.spec.option_descriptor_names,
      "choice option descriptor " .. tostring(option_index - 1))
    local joined = {}
    for index, value in ipairs(hidden) do
      joined[index] = value
    end
    local offset = #hidden
    for index, value in ipairs(descriptor) do
      joined[offset + index] = value
    end
    local option_hidden = dense_tanh(
      joined,
      parameters.choice_option_weight,
      parameters.choice_option_bias)
    scores[option_index] = scalar_value(
      option_hidden,
      parameters.choice_score_weight,
      parameters.choice_score_bias)
  end
  local probabilities = masked_softmax(
    scores,
    option_mask,
    "choice option",
    self.weights.choice_temperature)
  local selected_index = stochastic == true and
    self:sample(probabilities) or argmax(probabilities)
  local selected_probability = probabilities[selected_index]
  return {
    choice_action = selected_index - 1,
    log_probability = math.log(selected_probability),
    choice_probability = selected_probability,
    probabilities = probabilities,
    value = scalar_value(
      hidden,
      parameters.choice_value_weight,
      parameters.choice_value_bias),
    temperature = self.weights.choice_temperature,
    generation = self.generation,
  }
end

function policy.new(spec, weights, seed)
  local runtime = setmetatable({
    spec = assert(spec),
    weights = nil,
    generation = 0,
    random_state = 1,
  }, Runtime)
  runtime:set_seed(seed)
  runtime:load(weights)
  return runtime
end

policy.validate = validate_weights

return policy
