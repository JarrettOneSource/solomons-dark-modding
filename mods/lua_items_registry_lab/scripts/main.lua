local item = sd.items.register({
  key = "pentaclostic_ring",
  name = "Pentaclostic Ring",
  type = "ring",
})

assert(item.id == 5785942626980372610, "unexpected deterministic item id")
print("registered Lua item " .. item.mod_id .. ":" .. item.key)
