if type(sd) ~= "table" or type(sd.events) ~= "table" or
    type(sd.events.filter) ~= "function" then
  error("sd.events.filter is unavailable")
end

local capabilities = {
  "events.filters.damage",
  "events.filters.enemy_spawn",
  "events.filters.drop_roll",
  "events.filters.wave_spawn",
  "events.filters.spell_cast",
  "events.filters.resources",
}
for _, capability in ipairs(capabilities) do
  if not sd.runtime.has_capability(capability) then
    error("missing filter capability " .. capability)
  end
end

print("filter acceptance lab ready")
