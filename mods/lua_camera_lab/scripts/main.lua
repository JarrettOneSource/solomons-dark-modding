function lua_camera_lab_state()
  return sd.camera.get_state()
end

function lua_camera_lab_focus(world_x, world_y)
  return sd.camera.set_focus(world_x, world_y)
end

function lua_camera_lab_focus_current_center()
  local state = sd.camera.get_state()
  assert(state.scene_available, "a gameplay Region is required")
  return sd.camera.set_focus(state.center_x, state.center_y)
end

function lua_camera_lab_release()
  return sd.camera.clear_focus()
end

function lua_camera_lab_shake(intensity)
  return sd.camera.shake(intensity or 0.1)
end

print("Lua Camera Lab loaded; use lua_camera_lab_state/focus/release/shake")
