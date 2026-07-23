local boss = sd.enemies.register({
  key = "grave_oracle",
  base = "skeleton_mage",
  hp = 500,
  speed = 2.8,
  scale = 1.35,
  loot = "powerup",
})

assert(boss.id == 6758053804871806748, "unexpected deterministic enemy id")

local controller = sd.ai.register({
  enemy = boss.id,
  interval_ms = 100,
  blackboard = {step = 0},
  on_think = function(context)
    local closest = nil
    local closest_distance_squared = math.huge
    for _, participant in ipairs(context.participants) do
      if participant.in_run and participant.alive then
        local dx = participant.x - context.x
        local dy = participant.y - context.y
        local distance_squared = dx * dx + dy * dy
        if distance_squared < closest_distance_squared then
          closest = participant
          closest_distance_squared = distance_squared
        end
      end
    end

    if not closest then
      return {
        target = false,
        move_goal = false,
        blackboard = context.blackboard,
      }
    end

    local step = ((context.blackboard and context.blackboard.step) or 0) + 1
    local quadrant = math.floor(step / 20) % 4
    local offsets = {
      {x = 120, y = 0},
      {x = 0, y = 120},
      {x = -120, y = 0},
      {x = 0, y = -120},
    }
    local offset = offsets[quadrant + 1]
    return {
      target = closest.ref,
      move_goal = {
        x = closest.x + offset.x,
        y = closest.y + offset.y,
        stop_distance = 36,
      },
      blackboard = {step = step},
    }
  end,
})

assert(controller.enemy_id == boss.id)
print("registered Lua AI boss " .. boss.mod_id .. ":" .. boss.key)
