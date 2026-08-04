-- Minimap: a local radar centered on the local player.
--
-- Every dot comes from the locally materialized world (sd.world.list_actors),
-- which replication already keeps identical on all peers, plus the public
-- Solomon Dig state. Rendering is presentation-class sd.draw output only, so
-- the same script is multiplayer-native with zero transport code.

if type(sd) ~= "table" or type(sd.draw) ~= "table" then
  error("generic.lua.minimap requires the sd.draw runtime")
end

-- Players and bots are player-family actors (object_type_id 0x1); enemies use
-- the loader-computed tracked_enemy flag. Both are stable across module
-- relocation, unlike raw vtable addresses. Ground pickups come from the
-- replicated loot snapshot, whose rows carry kind + live position on every
-- peer (verified live: Gold/Item/Potion/Powerup rows with x/y in-run).
local PLAYER_OBJECT_TYPE = 0x1

-- Health/mana orbs are their own world-actor family (native type 0x7DB / 2011,
-- docs/reverse-engineering/native-items-equipment-and-loot.md); they magnet to
-- players and never enter the pickup-arbitrated loot rows.
local ORB_OBJECT_TYPE = 0x7DB

-- Loot-row kind -> settings toggle + dot color category.
local LOOT_KIND_CATEGORY = {
  Orb = "orb",
  Gold = "gold",
  Item = "item",
  Potion = "item",
  Powerup = "item",
}

-- Radar geometry and budget.
local RADAR_RADIUS_PX = 78
local RADAR_MARGIN_PX = 20
local RING_SEGMENTS = 28
local MAX_DOTS = 140

local COLOR_PANEL = {r = 8, g = 14, b = 28, a = 208}
local COLOR_RING = {r = 76, g = 214, b = 255, a = 190}
local COLOR_RING_SOFT = {r = 76, g = 214, b = 255, a = 56}
local COLOR_SELF = {r = 255, g = 255, b = 255, a = 255}
local COLOR_PLAYER = {r = 96, g = 255, b = 128, a = 255}
local COLOR_PLAYER_DOWN = {r = 150, g = 150, b = 150, a = 220}
local COLOR_ENEMY = {r = 255, g = 82, b = 68, a = 255}
local COLOR_ORB = {r = 122, g = 162, b = 255, a = 255}
local COLOR_GOLD = {r = 255, g = 205, b = 92, a = 255}
local COLOR_ITEM = {r = 255, g = 152, b = 64, a = 255}
local COLOR_DIG = {r = 76, g = 214, b = 255, a = 255}

local SETTING_KEYS = {
  "show_players",
  "show_enemies",
  "show_orbs",
  "show_items",
  "show_gold",
  "show_dig",
}

local shown = {}
for _, key in ipairs(SETTING_KEYS) do
  local value = sd.settings.get(key)
  if type(value) ~= "boolean" then
    error("generic.lua.minimap setting '" .. key .. "' did not resolve to a toggle")
  end
  shown[key] = value
end

local radar_range = sd.settings.get("radar_range")
if type(radar_range) ~= "number" or radar_range <= 0 then
  error("generic.lua.minimap setting 'radar_range' did not resolve to a number")
end

-- The launcher live-applies edits into the running game; this keeps every
-- toggle and the range dial responsive without a restart.
sd.settings.on_changed(function(key, new_value)
  if key == "radar_range" and type(new_value) == "number" and new_value > 0 then
    radar_range = new_value
  elseif shown[key] ~= nil and type(new_value) == "boolean" then
    shown[key] = new_value
  end
end)

local function dot(x, y, size, color)
  sd.draw.rect(x - size * 0.5, y - size * 0.5, size, size, {color = color})
end

sd.events.on("runtime.tick", function(event)
  local viewport = sd.draw.get_viewport()
  if viewport == nil then
    return
  end
  local player = sd.player.get_state()
  if type(player) ~= "table" or type(player.x) ~= "number" then
    return
  end
  local actors = sd.world.list_actors()
  if type(actors) ~= "table" then
    return
  end

  local cx = viewport.width - RADAR_MARGIN_PX - RADAR_RADIUS_PX
  local cy = RADAR_MARGIN_PX + RADAR_RADIUS_PX
  local scale = RADAR_RADIUS_PX / radar_range

  -- Panel and rings.
  sd.draw.rect(
    cx - RADAR_RADIUS_PX - 4,
    cy - RADAR_RADIUS_PX - 4,
    RADAR_RADIUS_PX * 2 + 8,
    RADAR_RADIUS_PX * 2 + 8,
    {color = COLOR_PANEL})
  local step = (2.0 * math.pi) / RING_SEGMENTS
  for i = 0, RING_SEGMENTS - 1 do
    local a1 = i * step
    local a2 = a1 + step
    sd.draw.line(
      cx + math.cos(a1) * RADAR_RADIUS_PX,
      cy + math.sin(a1) * RADAR_RADIUS_PX,
      cx + math.cos(a2) * RADAR_RADIUS_PX,
      cy + math.sin(a2) * RADAR_RADIUS_PX,
      {thickness = 2, color = COLOR_RING})
    sd.draw.line(
      cx + math.cos(a1) * RADAR_RADIUS_PX * 0.5,
      cy + math.sin(a1) * RADAR_RADIUS_PX * 0.5,
      cx + math.cos(a2) * RADAR_RADIUS_PX * 0.5,
      cy + math.sin(a2) * RADAR_RADIUS_PX * 0.5,
      {thickness = 1, color = COLOR_RING_SOFT})
  end

  local drawn = 0
  for _, actor in ipairs(actors) do
    if drawn >= MAX_DOTS then
      break
    end
    local dx = actor.x - player.x
    local dy = actor.y - player.y
    local distance = math.sqrt(dx * dx + dy * dy)
    if distance > 0.5 then
      local is_player = actor.object_type_id == PLAYER_OBJECT_TYPE
      local kind = nil
      local color = nil
      local size = 3
      if is_player and shown.show_players then
        kind = "player"
        color = actor.dead and COLOR_PLAYER_DOWN or COLOR_PLAYER
        size = 4
      elseif actor.tracked_enemy and not actor.dead and shown.show_enemies then
        kind = "enemy"
        color = COLOR_ENEMY
      elseif actor.object_type_id == ORB_OBJECT_TYPE and shown.show_orbs then
        kind = "orb"
        color = COLOR_ORB
      end
      if kind ~= nil then
        local mx = dx * scale
        local my = dy * scale
        local map_distance = distance * scale
        if map_distance > RADAR_RADIUS_PX - 4 then
          if kind == "player" then
            -- Allies never fall off the radar; pin them to the rim.
            local pin = (RADAR_RADIUS_PX - 5) / map_distance
            mx = mx * pin
            my = my * pin
          else
            kind = nil
          end
        end
        if kind ~= nil then
          dot(cx + mx, cy + my, size, color)
          drawn = drawn + 1
        end
      end
    end
  end

  -- Ground pickups from the replicated loot snapshot: identical rows on every
  -- peer, so host and client minimaps agree without any transport code here.
  if shown.show_orbs or shown.show_gold or shown.show_items then
    local loot = sd.world.get_replicated_loot()
    local drops = type(loot) == "table" and loot.drops or nil
    if type(drops) == "table" then
      for _, drop in ipairs(drops) do
        if drawn >= MAX_DOTS then
          break
        end
        if drop.active then
          local category = LOOT_KIND_CATEGORY[drop.kind]
          local visible =
            (category == "orb" and shown.show_orbs) or
            (category == "gold" and shown.show_gold) or
            (category == "item" and shown.show_items)
          if visible then
            local dx = (drop.x - player.x) * scale
            local dy = (drop.y - player.y) * scale
            if (dx * dx + dy * dy) <= (RADAR_RADIUS_PX - 4) * (RADAR_RADIUS_PX - 4) then
              local color = COLOR_ITEM
              if category == "orb" then
                color = COLOR_ORB
              elseif category == "gold" then
                color = COLOR_GOLD
              end
              dot(cx + dx, cy + dy, 3, color)
              drawn = drawn + 1
            end
          end
        end
      end
    end
  end

  -- Solomon Dig site: marked whenever the dig actor is live.
  if shown.show_dig then
    local ok, dig = pcall(sd.hub.get_solomon_dig_state)
    if ok and type(dig) == "table" and dig.valid then
      local dx = (dig.x - player.x) * scale
      local dy = (dig.y - player.y) * scale
      local map_distance = math.sqrt(dx * dx + dy * dy)
      if map_distance > RADAR_RADIUS_PX - 6 then
        local pin = (RADAR_RADIUS_PX - 7) / map_distance
        dx = dx * pin
        dy = dy * pin
      end
      local x = cx + dx
      local y = cy + dy
      local arm = 4
      local color = COLOR_DIG
      if dig.participant_acquired then
        local pulse = (math.sin(event.monotonic_milliseconds / 140.0) + 1.0) * 0.5
        color = {r = 76, g = 214, b = 255, a = 140 + math.floor(pulse * 115)}
        arm = 5
      end
      sd.draw.line(x - arm, y - arm, x + arm, y + arm, {thickness = 2, color = color})
      sd.draw.line(x - arm, y + arm, x + arm, y - arm, {thickness = 2, color = color})
    end
  end

  -- Local player: fixed center marker.
  dot(cx, cy, 5, COLOR_SELF)
  sd.draw.rect(cx - 3.5, cy - 3.5, 7, 7, {
    filled = false,
    thickness = 1,
    color = COLOR_RING,
  })
end)
