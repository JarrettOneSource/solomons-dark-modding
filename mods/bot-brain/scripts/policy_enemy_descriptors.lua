local descriptors = {}
local Resolver = {}
Resolver.__index = Resolver

-- Stable native-enemy-catalog order. Roles are semantic facts from
-- native-enemies.md; an unknown/custom identity receives no guessed roles.
local SPECIES = {
  [1000] = {index = 1, melee = true},
  [1001] = {index = 2, melee = true},
  [1002] = {index = 3, ranged = true},
  [1003] = {index = 4, ranged = true, caster = true},
  [1004] = {index = 5, melee = true, spawner = true, flying = true},
  [1005] = {index = 6, melee = true, flying = true},
  [1006] = {index = 7, melee = true, exploder = true},
  [1007] = {index = 8, melee = true, flying = true},
  [1008] = {
    index = 9,
    melee = true,
    ranged = true,
    caster = true,
    spawner = true,
    boss = true,
    flying = true,
  },
  [1009] = {
    index = 10,
    melee = true,
    ranged = true,
    caster = true,
    spawner = true,
    exploder = true,
    boss = true,
  },
  [1010] = {
    index = 11,
    ranged = true,
    caster = true,
    boss = true,
  },
  [1011] = {
    index = 12,
    melee = true,
    spawner = true,
    boss = true,
  },
  [1012] = {index = 13, melee = true, flying = true},
  [1013] = {index = 14, spawner = true, stationary = true},
  [2044] = {index = 15, melee = true, flying = true},
  [2045] = {index = 16, melee = true},
  [2057] = {index = 17, melee = true, ranged = true},
  [2058] = {index = 18, stationary = true},
  [5021] = {index = 19, spawner = true, stationary = true},
}

-- Only states with an explicit native mapping are classified. Everything
-- else deliberately remains telegraph_known=false.
local TELEGRAPHS = {
  [1008] = {
    [0x18] = "attack",
    [0x1A] = "attack",
    [0x1B] = "attack",
    [0x1C] = "attack",
  },
  [1010] = {
    [0x1F] = "attack",
    [0x21] = "attack",
  },
  [1013] = {
    [1] = "windup",
    [2] = "recover",
    [3] = "attack",
  },
}

local function finite_number(value)
  return type(value) == "number" and value == value and
    value > -math.huge and value < math.huge
end

local function number(value, fallback)
  local result = tonumber(value)
  if not finite_number(result) then
    return fallback or 0.0
  end
  return result
end

local function facing(heading)
  local radians = number(heading) * math.pi / 180.0
  return math.sin(radians), -math.cos(radians)
end

local function active_status(resolved, active, remaining)
  if resolved ~= true then
    return false, 0.0
  end
  return active == true, math.max(number(remaining), 0.0)
end

function Resolver:describe(enemy)
  enemy = type(enemy) == "table" and enemy or {}
  local type_id = math.floor(number(
    enemy.object_type_id,
    number(enemy.native_type_id)))
  local species = SPECIES[type_id]
  local state = math.floor(number(enemy.anim_drive_state))
  local phase = TELEGRAPHS[type_id] and
    TELEGRAPHS[type_id][state] or nil
  local facing_x, facing_y = facing(enemy.heading)
  local combat_resolved =
    enemy.combat_status_resolved == true
  local slowed, slow_remaining = active_status(
    combat_resolved,
    enemy.slowed,
    enemy.slow_remaining_seconds)
  local frozen, frozen_remaining = active_status(
    combat_resolved,
    enemy.frozen,
    enemy.frozen_remaining_seconds)
  local poisoned, poison_remaining = active_status(
    combat_resolved,
    enemy.poisoned,
    enemy.poison_remaining_seconds)
  local webbed, webbed_remaining = active_status(
    combat_resolved,
    enemy.webbed,
    enemy.webbed_remaining_seconds)
  local turn_undead, turn_undead_remaining = active_status(
    enemy.turn_undead_resolved == true,
    enemy.turn_undead,
    enemy.turn_undead_remaining_seconds)

  return {
    species_index_scaled =
      species ~= nil and
        species.index / self.spec.enemy_species_scale or 0.0,
    species_known = species ~= nil,
    role_melee = species ~= nil and species.melee == true,
    role_ranged = species ~= nil and species.ranged == true,
    role_caster = species ~= nil and species.caster == true,
    role_spawner = species ~= nil and species.spawner == true,
    role_exploder = species ~= nil and species.exploder == true,
    role_boss = species ~= nil and species.boss == true,
    role_flying = species ~= nil and species.flying == true,
    role_stationary =
      species ~= nil and species.stationary == true,
    facing_dx = facing_x,
    facing_dy = facing_y,
    anim_state_scaled = math.max(
      -1.0,
      math.min(
        state / self.spec.enemy_animation_state_scale,
        1.0)),
    telegraph_known = phase ~= nil,
    winding_up = phase == "windup",
    attack_active = phase == "attack",
    recovering = phase == "recover",
    slowed = slowed,
    slow_remaining_seconds = slow_remaining,
    frozen = frozen,
    frozen_remaining_seconds = frozen_remaining,
    poisoned = poisoned,
    poison_remaining_seconds = poison_remaining,
    webbed = webbed,
    webbed_remaining_seconds = webbed_remaining,
    turn_undead = turn_undead,
    turn_undead_remaining_seconds =
      turn_undead_remaining,
  }
end

function descriptors.new(spec)
  return setmetatable({spec = assert(spec)}, Resolver)
end

return descriptors
