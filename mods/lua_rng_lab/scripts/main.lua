if type(sd) ~= "table" or type(sd.rng) ~= "table" then
  error("sd.rng is unavailable")
end
if not sd.runtime.has_capability("rng.run.seed") then
  error("Lua run-seed capability is unavailable")
end

print("Lua RNG lab ready; seed=" .. tostring(sd.rng.get_seed()))
