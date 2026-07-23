local received = 0

sd.net.on("lab.echo", function(payload, message)
  received = received + 1
  print(string.format(
    "Lua net lab received %d bytes from participant %d (sequence %d)",
    #payload,
    message.sender_participant_id,
    message.sequence))
end)

function lua_net_lab_broadcast(payload)
  assert(type(payload) == "string", "payload must be a string")
  return sd.net.broadcast("lab.echo", payload)
end

function lua_net_lab_send(target_participant_id, payload)
  assert(type(payload) == "string", "payload must be a string")
  return sd.net.send(target_participant_id, "lab.echo", payload)
end

function lua_net_lab_state()
  return {
    received = received,
    limits = sd.net.get_limits(),
  }
end

print("Lua Raw Network Lab loaded; use lua_net_lab_broadcast or lua_net_lab_send")

