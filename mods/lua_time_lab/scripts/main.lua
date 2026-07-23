function lua_time_lab_slow(scale)
  return sd.time.set_scale(scale or 0.25)
end

function lua_time_lab_pause()
  return sd.time.set_scale(0)
end

function lua_time_lab_step(frames)
  return sd.time.step(frames or 1)
end

function lua_time_lab_resume()
  return sd.time.set_scale(1)
end

function lua_time_lab_state()
  return sd.time.get_state()
end

print("Lua Shared Time Lab loaded; use lua_time_lab_pause/step/resume")
