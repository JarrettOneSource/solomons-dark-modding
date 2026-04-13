local RETRY_INTERVAL_MS = 500
local DEFAULT_TIMEOUT_MS = 15000

local function get_debug_api(name)
  if type(sd) ~= "table" or type(sd.debug) ~= "table" then
    return nil
  end
  local value = sd.debug[name]
  if type(value) ~= "function" then
    return nil
  end
  return value
end

local function get_last_error()
  local getter = get_debug_api("get_last_error")
  if getter == nil then
    return nil
  end
  local ok, result = pcall(getter)
  if not ok then
    return nil
  end
  if type(result) ~= "string" or result == "" then
    return nil
  end
  return result
end

local function normalize_specs(ctx, specs)
  local normalized = {}
  for _, spec in ipairs(specs or {}) do
    if type(spec) == "table" and type(spec.name) == "string" and spec.name ~= "" then
      local address = spec.address
      if address == nil and type(spec.key) == "string" then
        address = ctx.config and ctx.config.addresses and ctx.config.addresses[spec.key]
      end
      local patch_size = tonumber(spec.patch_size)
      normalized[#normalized + 1] = {
        key = spec.key,
        name = spec.name,
        address = tonumber(address),
        patch_size = patch_size,
      }
    end
  end
  return normalized
end

local function ensure_state(ctx)
  ctx.trace_arming = ctx.trace_arming or {
    pending = {},
    next_attempt_ms = 0,
    deadline_ms = 0,
  }
  return ctx.trace_arming
end

local function apis_available()
  return get_debug_api("trace_function") ~= nil and
      get_debug_api("untrace_function") ~= nil and
      get_debug_api("clear_trace_hits") ~= nil
end

local function try_arm_one(spec)
  if tonumber(spec.address) == nil or tonumber(spec.address) == 0 then
    return false, "missing address"
  end

  local untrace = get_debug_api("untrace_function")
  local clear_hits = get_debug_api("clear_trace_hits")
  local trace = get_debug_api("trace_function")
  if untrace == nil or clear_hits == nil or trace == nil then
    return false, "sd.debug trace APIs unavailable"
  end

  pcall(untrace, spec.address)
  pcall(clear_hits, spec.name)

  local ok, result
  if tonumber(spec.patch_size) ~= nil and spec.patch_size > 0 then
    ok, result = pcall(trace, spec.address, spec.name, spec.patch_size)
  else
    ok, result = pcall(trace, spec.address, spec.name)
  end

  if not ok then
    return false, tostring(result)
  end
  if result then
    return true, nil
  end

  return false, get_last_error() or "trace_function returned false"
end

local function queue_traces(ctx, specs, now_ms, timeout_ms)
  local state = ensure_state(ctx)
  local deadline_ms = (tonumber(now_ms) or 0) + (tonumber(timeout_ms) or DEFAULT_TIMEOUT_MS)

  for _, spec in ipairs(normalize_specs(ctx, specs)) do
    local existing = state.pending[spec.name]
    if existing == nil then
      state.pending[spec.name] = {
        spec = spec,
        armed = false,
        last_detail = nil,
        attempts = 0,
      }
    else
      existing.spec = spec
    end
  end

  if state.deadline_ms == 0 or deadline_ms > state.deadline_ms then
    state.deadline_ms = deadline_ms
  end
end

local function advance(ctx, now_ms)
  local state = ensure_state(ctx)
  if next(state.pending) == nil then
    return true
  end

  if not apis_available() then
    return false, "sd.debug trace APIs unavailable"
  end

  local now = tonumber(now_ms) or 0
  if state.next_attempt_ms ~= 0 and now < state.next_attempt_ms then
    return false, "waiting to retry trace arming"
  end

  local all_armed = true
  for name, entry in pairs(state.pending) do
    if not entry.armed then
      local armed, detail = try_arm_one(entry.spec)
      entry.attempts = (entry.attempts or 0) + 1
      if armed then
        entry.armed = true
        entry.last_detail = nil
        ctx.log_status(string.format(
          "armed trace name=%s address=%s attempts=%s",
          tostring(name),
          tostring(entry.spec.address),
          tostring(entry.attempts)))
      else
        all_armed = false
        if entry.last_detail ~= detail then
          entry.last_detail = detail
          ctx.log_status(string.format(
            "trace pending name=%s address=%s reason=%s attempt=%s",
            tostring(name),
            tostring(entry.spec.address),
            tostring(detail),
            tostring(entry.attempts)))
        end
      end
    end
  end

  if all_armed then
    for name, _ in pairs(state.pending) do
      state.pending[name] = nil
    end
    state.next_attempt_ms = 0
    state.deadline_ms = 0
    return true
  end

  state.next_attempt_ms = now + RETRY_INTERVAL_MS
  if state.deadline_ms ~= 0 and now >= state.deadline_ms then
    local failures = {}
    for name, entry in pairs(state.pending) do
      if not entry.armed then
        failures[#failures + 1] = string.format("%s(%s)", tostring(name), tostring(entry.last_detail or "unknown"))
      end
    end
    local detail = "trace arm timeout: " .. table.concat(failures, ", ")
    state.pending = {}
    state.next_attempt_ms = 0
    state.deadline_ms = 0
    return false, detail
  end

  return nil, "trace arming in progress"
end

return {
  advance = advance,
  queue_traces = queue_traces,
}
