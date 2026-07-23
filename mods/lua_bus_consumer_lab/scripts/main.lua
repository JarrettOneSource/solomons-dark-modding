if type(sd) ~= "table" or type(sd.bus) ~= "table" then
  error("sd.bus is unavailable")
end
if not sd.bus.has("sample.bus.echo.v1") then
  error("sample.bus.echo.v1 provider did not load first")
end

local providers = sd.bus.providers("sample.bus.echo.v1")
if #providers ~= 1 or providers[1] ~= "sample.lua.bus_provider_lab" then
  error("unexpected echo provider set")
end

local startup_reply
local startup_subscription
startup_subscription = sd.bus.subscribe("sample.bus.echo.response", function(payload, context)
  startup_reply = {
    token = payload.token,
    publisher_mod_id = context.publisher_mod_id,
  }
end)
local delivered = sd.bus.publish("sample.bus.echo.request", { token = "startup" })
if delivered ~= 1 or not startup_reply or startup_reply.token ~= "startup" or
    startup_reply.publisher_mod_id ~= "sample.lua.bus_provider_lab" then
  error("startup bus round trip failed")
end
sd.bus.unsubscribe(startup_subscription)

sd.bus.subscribe("sample.bus.consumer.request", function(payload, context)
  sd.bus.publish("sample.bus.consumer.response", {
    token = payload.token,
    request_mod_id = context.publisher_mod_id,
  })
end)

print("bus consumer ready")
