if type(sd) ~= "table" or type(sd.runtime) ~= "table" then
  error("remote latency harness requires the Lua runtime")
end

print("Remote latency harness controller ready.")
