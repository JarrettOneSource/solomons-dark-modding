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
    fail(label .. " names do not match the policy contract")
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

local function validate_weights(spec, candidate)
  if type(candidate) ~= "table" then
    fail("model must be a table")
  end
  if candidate.format ~= spec.model_format or
      candidate.version ~= spec.model_version or
      candidate.observation_version ~= spec.observation_version or
      candidate.architecture ~= spec.architecture then
    fail("format, version, or architecture mismatch")
  end

  local observation_size = #spec.observation_names
  local movement_size = #spec.movement_actions
  local cast_size = #spec.cast_actions
  if candidate.observation_size ~= observation_size or
      candidate.hidden_size ~= spec.hidden_size or
      candidate.movement_action_size ~= movement_size or
      candidate.cast_action_size ~= cast_size then
    fail("declared tensor shape mismatch")
  end
  validate_names(
    candidate.observation_names,
    spec.observation_names,
    "observation")

  local movement_names = {}
  for index, action in ipairs(spec.movement_actions) do
    movement_names[index] = action.name
  end
  validate_names(
    candidate.movement_action_names,
    movement_names,
    "movement action")
  local cast_names = {}
  for index, action in ipairs(spec.cast_actions) do
    cast_names[index] = action.name
  end
  validate_names(
    candidate.cast_action_names,
    cast_names,
    "cast action")

  local parameters = candidate.parameters
  if type(parameters) ~= "table" then
    fail("parameters must be a table")
  end
  validate_matrix(
    parameters.input_weight,
    spec.hidden_size,
    observation_size,
    "parameters.input_weight")
  validate_vector(
    parameters.input_bias,
    spec.hidden_size,
    "parameters.input_bias")
  validate_matrix(
    parameters.movement_weight,
    movement_size,
    spec.hidden_size,
    "parameters.movement_weight")
  validate_vector(
    parameters.movement_bias,
    movement_size,
    "parameters.movement_bias")
  validate_matrix(
    parameters.cast_weight,
    cast_size,
    spec.hidden_size,
    "parameters.cast_weight")
  validate_vector(
    parameters.cast_bias,
    cast_size,
    "parameters.cast_bias")
  validate_vector(
    parameters.value_weight,
    spec.hidden_size,
    "parameters.value_weight")
  validate_vector(
    parameters.value_bias,
    1,
    "parameters.value_bias")
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

local function logits(
    hidden,
    weights,
    biases)
  local output = {}
  for row, weight_row in ipairs(weights) do
    local value = biases[row]
    for column = 1, #hidden do
      value = value + weight_row[column] * hidden[column]
    end
    output[row] = value
  end
  return output
end

local function masked_softmax(values, mask, label)
  if type(mask) ~= "table" or #mask ~= #values then
    fail(label .. " mask shape mismatch")
  end
  local maximum = -math.huge
  local legal_count = 0
  for index, value in ipairs(values) do
    if mask[index] == true then
      legal_count = legal_count + 1
      maximum = math.max(maximum, value)
    end
  end
  if legal_count == 0 then
    fail(label .. " mask has no legal action")
  end

  local probabilities = {}
  local total = 0.0
  for index, value in ipairs(values) do
    if mask[index] == true then
      local probability = math.exp(value - maximum)
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
    architecture = self.spec.architecture,
    observation_size = #self.spec.observation_names,
    hidden_size = self.spec.hidden_size,
    movement_action_size = #self.spec.movement_actions,
    cast_action_size = #self.spec.cast_actions,
    generation = self.generation,
    metadata = self.weights.metadata,
  }
end

function Runtime:forward(
    observation,
    movement_mask,
    cast_mask,
    stochastic)
  validate_vector(
    observation,
    #self.spec.observation_names,
    "observation")
  local parameters = self.weights.parameters
  local hidden = {}
  for row, weight_row in ipairs(parameters.input_weight) do
    local value = parameters.input_bias[row]
    for column = 1, #observation do
      value = value + weight_row[column] * observation[column]
    end
    hidden[row] = tanh(value)
  end

  local movement_probabilities = masked_softmax(
    logits(
      hidden,
      parameters.movement_weight,
      parameters.movement_bias),
    movement_mask,
    "movement")
  local cast_probabilities = masked_softmax(
    logits(
      hidden,
      parameters.cast_weight,
      parameters.cast_bias),
    cast_mask,
    "cast")
  local movement_index = stochastic == true and
    self:sample(movement_probabilities) or
    argmax(movement_probabilities)
  local cast_index = stochastic == true and
    self:sample(cast_probabilities) or
    argmax(cast_probabilities)

  local value = parameters.value_bias[1]
  for index = 1, #hidden do
    value =
      value + parameters.value_weight[index] * hidden[index]
  end
  local movement_probability =
    movement_probabilities[movement_index]
  local cast_probability = cast_probabilities[cast_index]
  return {
    movement_action = movement_index - 1,
    cast_action = cast_index - 1,
    movement = self.spec.movement_actions[movement_index],
    cast = self.spec.cast_actions[cast_index],
    log_probability =
      math.log(movement_probability) +
      math.log(cast_probability),
    value = value,
    movement_probability = movement_probability,
    cast_probability = cast_probability,
    movement_probabilities = movement_probabilities,
    cast_probabilities = cast_probabilities,
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
