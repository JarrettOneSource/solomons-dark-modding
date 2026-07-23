if type(sd) ~= "table" or type(sd.bus) ~= "table" then
  error("sd.bus is unavailable")
end

sd.bus.subscribe("sample.bus.echo.request", function(payload, context)
  if type(payload) ~= "table" or type(payload.token) ~= "string" then
    error("echo request requires a token")
  end
  sd.bus.publish("sample.bus.echo.response", {
    token = payload.token,
    request_mod_id = context.publisher_mod_id,
  })
end)

print("bus provider ready")
