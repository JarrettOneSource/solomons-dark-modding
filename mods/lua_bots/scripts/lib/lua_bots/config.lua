local config = {}

local ACTIVE_BOTS_ENV_VAR = "SDMOD_LUA_BOTS_ACTIVE"

local function default_primary_entry_index_for_element(element_id)
  -- Keep bot primary loadout aligned with the stock live selection-state map:
  -- ether -> 0x08, fire -> 0x10, air -> 0x18, water -> 0x20, earth -> 0x28.
  local map = {
    [0] = 0x10,
    [1] = 0x20,
    [2] = 0x28,
    [3] = 0x18,
    [4] = 0x08,
  }
  return map[tonumber(element_id) or -1] or 0x08
end

local function make_bot_profile(element_id, discipline_id)
  local primary_entry_index = default_primary_entry_index_for_element(element_id)
  return {
    element_id = element_id,
    discipline_id = discipline_id,
    level = 1,
    experience = 0,
    loadout = {
      primary_entry_index = primary_entry_index,
      primary_combo_entry_index = primary_entry_index,
      secondary_entry_indices = { -1, -1, -1 },
    },
  }
end

local function parse_active_bot_keys(source)
  local keys = {}
  local seen = {}
  local all_requested = false

  if type(source) == "table" then
    for _, value in ipairs(source) do
      local key = tostring(value or ""):lower()
      if key == "all" or key == "*" then
        all_requested = true
      elseif key ~= "" and not seen[key] then
        seen[key] = true
        table.insert(keys, key)
      end
    end
    return keys, all_requested
  end

  source = tostring(source or ""):gsub("\r\n", "\n"):gsub("\r", "\n")
  for line in (source .. "\n"):gmatch("([^\n]*)\n") do
    line = line:gsub("#.*", "")
    for token in line:gmatch("[^,%s]+") do
      local key = token:lower()
      if key == "all" or key == "*" then
        all_requested = true
      elseif key ~= "" and not seen[key] then
        seen[key] = true
        table.insert(keys, key)
      end
    end
  end

  return keys, all_requested
end

local function load_active_bot_keys(default_active_bot_keys)
  if type(sd) == "table" and type(sd.runtime) == "table" and
      type(sd.runtime.get_environment_variable) == "function" then
    local active_bots = sd.runtime.get_environment_variable(ACTIVE_BOTS_ENV_VAR)
    if type(active_bots) == "string" and active_bots ~= "" then
      local normalized = active_bots:match("^%s*(.-)%s*$"):lower()
      if normalized == "default" then
        return default_active_bot_keys, false
      end
      local keys, all_requested = parse_active_bot_keys(active_bots)
      if all_requested or #keys > 0 then
        return keys, all_requested
      end
      return default_active_bot_keys, false
    end
  end

  if type(sd) == "table" and type(sd.runtime) == "table" and
      type(sd.runtime.get_mod_text_file) == "function" then
    local ok, text = pcall(sd.runtime.get_mod_text_file, "config/active_bots.txt")
    if ok and type(text) == "string" then
      local keys, all_requested = parse_active_bot_keys(text)
      if all_requested or #keys > 0 then
        return keys, all_requested
      end
    end
  end

  return default_active_bot_keys, false
end

local function select_bot_configs(all_bot_configs, default_active_bot_keys)
  local keys, all_requested = load_active_bot_keys(default_active_bot_keys)
  if all_requested then
    return all_bot_configs
  end

  local requested = {}
  for _, key in ipairs(keys or default_active_bot_keys) do
    requested[tostring(key):lower()] = true
  end

  local selected = {}
  for _, bot_config in ipairs(all_bot_configs) do
    if requested[bot_config.key] then
      table.insert(selected, bot_config)
    end
  end
  if #selected > 0 then
    return selected
  end

  requested = {}
  for _, key in ipairs(default_active_bot_keys) do
    requested[key] = true
  end
  for _, bot_config in ipairs(all_bot_configs) do
    if requested[bot_config.key] then
      table.insert(selected, bot_config)
    end
  end
  return selected
end

function config.create()
  local result = {}

  result.MANAGED_BOT_NAMES = {
    ["Lua Bot Fire"] = true,
    ["Lua Bot Water"] = true,
    ["Lua Bot Earth"] = true,
    ["Lua Bot Air"] = true,
    ["Lua Bot Ether"] = true,
  }

  result.ALL_BOT_CONFIGS = {
    {
      key = "water",
      name = "Lua Bot Water",
      element_id = 1,
      discipline_id = 1,
      spawn_offset_x = 50.0,
      spawn_offset_y = -60.0,
    },
    {
      key = "earth",
      name = "Lua Bot Earth",
      element_id = 2,
      discipline_id = 1,
      spawn_offset_x = 50.0,
      spawn_offset_y = -20.0,
    },
    {
      key = "air",
      name = "Lua Bot Air",
      element_id = 3,
      discipline_id = 1,
      spawn_offset_x = 50.0,
      spawn_offset_y = 20.0,
    },
    {
      key = "ether",
      name = "Lua Bot Ether",
      element_id = 4,
      discipline_id = 1,
      spawn_offset_x = 50.0,
      spawn_offset_y = 60.0,
    },
    {
      key = "fire",
      name = "Lua Bot Fire",
      element_id = 0,
      discipline_id = 1,
      spawn_offset_x = 50.0,
      spawn_offset_y = 100.0,
    },
  }

  result.DEFAULT_ACTIVE_BOT_KEYS = { "fire", "earth" }
  result.BOT_CONFIGS = select_bot_configs(result.ALL_BOT_CONFIGS, result.DEFAULT_ACTIVE_BOT_KEYS)
  result.CURRENT_MANAGED_BOT_NAMES = {}
  for _, bot_config in ipairs(result.BOT_CONFIGS) do
    bot_config.profile = make_bot_profile(bot_config.element_id, bot_config.discipline_id)
    result.CURRENT_MANAGED_BOT_NAMES[bot_config.name] = true
  end

  result.DEFAULT_SPAWN_OFFSET_X = 50.0
  result.DEFAULT_SPAWN_OFFSET_Y = 0.0
  result.DEFAULT_HUB_SPAWN_X = 956.0
  result.DEFAULT_HUB_SPAWN_Y = 508.0
  result.FOLLOW_STOP_DISTANCE = 100.0
  result.FOLLOW_RESUME_DISTANCE = 250.0
  result.FOLLOW_TARGET_ARRIVAL_DISTANCE = 32.0
  result.FOLLOW_TARGET_REFRESH_DISTANCE = 24.0
  result.FOLLOW_TARGET_SAMPLE_ATTEMPTS = 8
  result.FOLLOW_MOVE_TIMEOUT_MS = 30000
  result.COMMAND_COOLDOWN_MS = 250
  result.TICK_INTERVAL_MS = 100
  result.ATTACK_DIAG_INTERVAL_MS = 1000
  result.DEFAULT_ATTACK_RANGE = 96.0
  result.WATER_BASE_CONE_RANGE = 205.0
  result.WATER_RANGE_PER_SHAPE_UNIT = 4.0
  result.WATER_RANGE_SAFETY_MARGIN = 5.0
  result.ATTACK_RANGE_BY_ELEMENT_ID = {
    [0] = 360.0,
    [1] = result.WATER_BASE_CONE_RANGE - result.WATER_RANGE_SAFETY_MARGIN,
    [2] = 360.0,
    [3] = 360.0,
    [4] = 360.0,
  }
  result.MIN_ATTACK_RANGE_BY_ELEMENT_ID = {
    [2] = 96.0,
  }
  result.WAVE_ENEMY_OBJECT_TYPE_ID = 1001
  result.SPAWN_RETRY_MS = 500
  result.SCENE_UPDATE_COOLDOWN_MS = 250
  result.NAV_GRID_REFRESH_MS = 3000
  result.NAV_GRID_SUBDIVISIONS = 2
  result.ENABLE_FOLLOW_MOVEMENT = true
  result.ENTRANCE_TRIGGER_DISTANCE = 96.0
  result.ENTRANCE_ARRIVAL_DISTANCE = 20.0
  result.HUB_ENTRANCE_ARM_DELAY_MS = 1500
  result.HUB_ENTRANCE_DWELL_MS = 350
  result.PLAYER_MOVEMENT_ARM_DISTANCE = 12.0
  result.STUCK_SAMPLE_THRESHOLD = 8
  result.STUCK_POSITION_EPSILON = 1.0
  result.SUPPORTED_PRIVATE_AREAS = {
    memorator = {
      name = "memorator",
      region_index = 1,
      region_type_id = 4002,
      hub_anchor = { x = 87.480285644531, y = 443.60046386719 },
      hub_wait_anchor = { x = 75.0, y = 375.0 },
      interior_anchor = { x = 512.0, y = 798.25897216797 },
    },
    librarian = {
      name = "librarian",
      region_index = 2,
      region_type_id = 4004,
      hub_anchor = { x = 124.76531219482, y = 496.97552490234 },
      hub_wait_anchor = { x = 75.0, y = 525.0 },
      interior_anchor = { x = 512.0, y = 924.0 },
    },
    dowser = {
      name = "dowser",
      region_index = 3,
      region_type_id = 4003,
      hub_anchor = { x = 627.5, y = 137.6875 },
      hub_wait_anchor = { x = 675.0, y = 75.0 },
      interior_anchor = { x = 537.5, y = 647.73309326172 },
    },
    polisher_arch = {
      name = "polisher_arch",
      region_index = 4,
      region_type_id = 4005,
      hub_anchor = { x = 952.5, y = 106.6875 },
      hub_wait_anchor = { x = 825.0, y = 75.0 },
      interior_anchor = { x = 512.0, y = 867.88549804688 },
    },
  }

  return result
end

return config
