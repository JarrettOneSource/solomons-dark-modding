local enemy = sd.enemies.register({
  key = "grave_tyrant",
  base = "skeleton",
  hp = 250,
  speed = 2.5,
  scale = 1.2,
  loot = "gold",
})

assert(enemy.id == 8726222830294414077, "unexpected deterministic enemy id")
print("registered Lua enemy " .. enemy.mod_id .. ":" .. enemy.key)
