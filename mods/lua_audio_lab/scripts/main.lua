if type(sd) ~= "table" or type(sd.audio) ~= "table" or
    not sd.audio.is_available() then
  error("sd.audio is unavailable")
end

local music_handle = nil

sd.events.on("sample.audio.stinger", function(payload)
  local path = type(payload) == "table" and payload.path or "audio/stinger.ogg"
  local volume = type(payload) == "table" and payload.volume or 0.8
  sd.audio.play_sample(path, {volume = volume})
end)

sd.events.on("sample.audio.music", function(payload)
  if music_handle ~= nil then
    sd.audio.stop(music_handle)
  end
  local path = type(payload) == "table" and payload.path or "audio/music.ogg"
  local volume = type(payload) == "table" and payload.volume or 0.5
  music_handle = sd.audio.play_stream(path, {
    volume = volume,
    loop = true,
  })
end)

sd.events.on("sample.audio.volume", function(payload)
  if music_handle ~= nil and type(payload) == "table" then
    sd.audio.set_volume(music_handle, payload.volume)
  end
end)

sd.events.on("sample.audio.stop", function()
  sd.audio.clear()
  music_handle = nil
end)

print("Lua Audio Lab ready for replicated sample.audio.* cues")
