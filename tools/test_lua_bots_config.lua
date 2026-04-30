#!/usr/bin/env lua

local function run_case(case)
  local event_handlers = {}
  local environment_variables = {}
  if case.env ~= nil then
    environment_variables.SDMOD_LUA_BOTS_ACTIVE = case.env
  end

  rawset(_G, "lua_bots_debug", nil)
  rawset(_G, "lua_bots_test_hooks", nil)
  rawset(_G, "lua_bots_enable_test_hooks", true)

  rawset(_G, "sd", {
    runtime = {
      get_environment_variable = function(name)
        return environment_variables[name]
      end,
      get_mod_text_file = function(path)
        path = tostring(path or "")
        if path == "config/active_bots.txt" and case.file ~= nil then
          return case.file
        end
        local file = assert(io.open("mods/lua_bots/" .. path, "rb"))
        local contents = file:read("*a")
        file:close()
        return contents
      end,
    },
    events = {
      on = function(name, callback)
        event_handlers[name] = callback
      end,
    },
    world = {
      get_scene = function()
        return {
          name = "hub",
          kind = "hub",
          world_id = 0x1000,
          transitioning = false,
        }
      end,
      get_state = function()
        return { wave = 1 }
      end,
      list_actors = function()
        return {}
      end,
    },
    player = {
      get_state = function()
        return { x = 100.0, y = 100.0, heading = 180.0 }
      end,
    },
    debug = {
      get_nav_grid = function()
        return {
          valid = true,
          world_id = 0x1000,
          width = 1,
          height = 1,
          cells = {},
        }
      end,
    },
    gameplay = {
      get_combat_state = function()
        return { active = false }
      end,
    },
    bots = {
      get_state = function()
        return {}
      end,
    },
  })

  dofile("mods/lua_bots/scripts/main.lua")
  local hooks = rawget(_G, "lua_bots_test_hooks")
  assert(type(hooks) == "table", case.name .. ": test hooks missing")
  local names = {}
  for _, bot in ipairs(hooks.state.bots or {}) do
    table.insert(names, bot.bot_name)
  end
  assert(#names == #case.expected, case.name .. ": expected " .. #case.expected .. " bots, got " .. #names)
  for index, expected_name in ipairs(case.expected) do
    assert(names[index] == expected_name, case.name .. ": bot " .. index .. " expected " .. expected_name .. ", got " .. tostring(names[index]))
  end
end

local cases = {
  {
    name = "default_without_env_or_file",
    file = "",
    expected = { "Lua Bot Earth", "Lua Bot Fire" },
  },
  {
    name = "file_all",
    file = "all",
    expected = { "Lua Bot Water", "Lua Bot Earth", "Lua Bot Air", "Lua Bot Ether", "Lua Bot Fire" },
  },
  {
    name = "env_default_overrides_file",
    env = "default",
    file = "all",
    expected = { "Lua Bot Earth", "Lua Bot Fire" },
  },
  {
    name = "env_all_overrides_file",
    env = "all",
    file = "fire\nearth\n",
    expected = { "Lua Bot Water", "Lua Bot Earth", "Lua Bot Air", "Lua Bot Ether", "Lua Bot Fire" },
  },
  {
    name = "env_subset",
    env = "water,air",
    file = "all",
    expected = { "Lua Bot Water", "Lua Bot Air" },
  },
}

for _, case in ipairs(cases) do
  run_case(case)
end

print("lua_bots_config_ok=true")
