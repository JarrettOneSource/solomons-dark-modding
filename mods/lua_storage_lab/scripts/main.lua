if type(sd) ~= "table" or type(sd.storage) ~= "table" then
  error("sd.storage is unavailable")
end

local launches = sd.storage.get("launches", 0) + 1
sd.storage.set("launches", launches)
print("persistent profile launch count=" .. tostring(launches))
