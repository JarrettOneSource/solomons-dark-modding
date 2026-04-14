local require_mod = sd.runtime.require_mod

local actions = require_mod("scripts/lib/actions.lua")
local common = require_mod("scripts/lib/common.lua")
local config = require_mod("scripts/lib/config.lua")
local create_probe = require_mod("scripts/lib/create_probe.lua")
local setup = require_mod("scripts/lib/setup.lua")
local trace_util = require_mod("scripts/lib/trace_util.lua")
local wizard_compare = require_mod("scripts/lib/wizard_compare.lua")

local function arm_startup_traces_if_requested(ctx)
  local preset = tostring(ctx.active_preset or "")
  local should_queue =
    preset == "trace_rich_item_startup" or
    preset == "create_ready_earth" or
    preset == "create_ready_ether" or
    preset == "create_ready_fire" or
    preset == "create_ready_water" or
    preset == "create_ready_air"
  if not should_queue then
    return
  end

  local trace_specs = {
    { key = "trace_gameplay_finalize_player_start", name = "trace_gameplay_finalize_player_start" },
    { key = "trace_equip_attachment_sink_attach", name = "trace_equip_attachment_sink_attach" },
    { key = "trace_rich_item_build", name = "trace_rich_item_build" },
    { key = "trace_rich_item_clone", name = "trace_rich_item_clone" },
  }
  trace_util.queue_traces(ctx, trace_specs, 0, 20000)
  ctx.log_status("startup trace preset queued gameplay startup traces")
end

local function start()
  local ctx = common.new_context(config, actions)
  ctx.mode, ctx.active_preset = setup.resolve_mode()
  arm_startup_traces_if_requested(ctx)

  ctx.mode_handlers.create_probe = create_probe.new(ctx)
  ctx.mode_handlers.wizard_compare = wizard_compare.new(ctx)

  local setup_runner = setup.new(ctx)

  sd.events.on("run.started", function()
    ctx.lifecycle_events["run.started"] = true
    ctx.mode_handlers.wizard_compare.on_run_started()
  end)

  sd.events.on("run.ended", function()
    ctx.lifecycle_events["run.started"] = false
    ctx.mode_handlers.wizard_compare.on_run_ended()
  end)

  sd.events.on("runtime.tick", function(event)
    local now_ms = tonumber(event.monotonic_milliseconds) or 0
    local trace_ok, trace_detail = trace_util.advance(ctx, now_ms)
    if trace_ok == false and type(trace_detail) == "string" then
      ctx.log_error(trace_detail)
    end
    setup_runner.advance(now_ms)
    if ctx.mode == "create_probe" then
      ctx.mode_handlers.create_probe.run(now_ms, setup_runner.setup_complete)
    elseif ctx.mode == "wizard_compare" then
      ctx.mode_handlers.wizard_compare.update(now_ms, setup_runner.setup_complete)
    end
  end)
end

return {
  start = start,
}
