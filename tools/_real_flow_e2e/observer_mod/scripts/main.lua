-- Harness-only observer. The runtime stages this disabled-by-default tool mod
-- into isolated E2E instances; it is not part of a release package. Apart
-- from the explicitly armed capture barrier below, it only exposes read-only
-- semantic APIs through the exec pipe and never changes gameplay state.
_G.__real_flow_e2e_observer = true

local capture_event = "real_flow.capture_barrier"
local capture = {
  armed = nil,
  result = nil,
  last_tick_count = 0,
  last_tick_monotonic_ms = 0,
}

local function frame_state()
  local state = sd.runtime.get_frame_state() or {}
  return {
    frame_count = tonumber(state.frame_count) or 0,
    observed_ms = tonumber(state.observed_ms) or 0,
  }
end

sd.events.on("runtime.tick", function(event)
  capture.last_tick_count = tonumber(event.tick_count) or 0
  capture.last_tick_monotonic_ms =
    tonumber(event.monotonic_milliseconds) or 0
end)

sd.events.on(capture_event, function(payload, context)
  local barrier_id =
    type(payload) == "table" and tostring(payload.barrier_id or "") or ""
  local armed = capture.armed
  if armed == nil or barrier_id == "" or barrier_id ~= armed.barrier_id then
    return
  end

  local before = frame_state()
  local result = {
    status = "capturing",
    barrier_id = barrier_id,
    authority_participant_id =
      tonumber(context.authority_participant_id) or 0,
    stream_sequence = tonumber(context.stream_sequence) or 0,
    trigger_tick_count = capture.last_tick_count,
    trigger_monotonic_ms = capture.last_tick_monotonic_ms,
    capture_monotonic_ms = before.observed_ms,
    capture_frame_count = before.frame_count,
    capture_completed_monotonic_ms = 0,
    capture_completed_frame_count = 0,
    ok = false,
    error = "",
  }
  capture.result = result

  local ok, error_message = sd.debug.capture_backbuffer(armed.path)
  local after = frame_state()
  result.capture_completed_monotonic_ms = after.observed_ms
  result.capture_completed_frame_count = after.frame_count
  result.ok = ok == true
  result.error = tostring(error_message or "")
  result.status = result.ok and "captured" or "failed"
  capture.armed = nil
end)

function _G.__real_flow_e2e_capture_arm(barrier_id, path)
  barrier_id = tostring(barrier_id or "")
  path = tostring(path or "")
  assert(barrier_id ~= "", "capture barrier id must not be empty")
  assert(path ~= "", "capture path must not be empty")
  assert(capture.armed == nil, "a capture barrier is already armed")
  capture.armed = {barrier_id = barrier_id, path = path}
  capture.result = {
    status = "armed",
    barrier_id = barrier_id,
  }
  return true
end

function _G.__real_flow_e2e_capture_publish(barrier_id)
  barrier_id = tostring(barrier_id or "")
  assert(sd.state.is_authority(), "capture barrier must be published by authority")
  assert(capture.armed ~= nil, "capture barrier is not armed")
  assert(
    capture.armed.barrier_id == barrier_id,
    "capture barrier id does not match the armed capture")
  return sd.events.broadcast(capture_event, {barrier_id = barrier_id})
end

function _G.__real_flow_e2e_capture_result()
  return capture.result
end
