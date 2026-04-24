local function create_mod_require()
  local runtime = type(sd) == "table" and type(sd.runtime) == "table" and sd.runtime or nil
  if runtime ~= nil and type(runtime.get_mod_text_file) == "function" and type(load) == "function" then
    local loading_sentinel = {}
    local module_cache = {}

    local function normalize_module_path(path)
      local normalized = tostring(path or "")
      normalized = normalized:gsub("\\", "/")
      normalized = normalized:gsub("^%./", "")
      normalized = normalized:gsub("/+", "/")
      if normalized == "" then
        error("module path must not be empty")
      end
      return normalized
    end

    return function(path)
      local normalized = normalize_module_path(path)
      local cached = module_cache[normalized]
      if cached == loading_sentinel then
        error("circular module load for " .. normalized)
      end
      if cached ~= nil then
        return cached
      end

      local source = runtime.get_mod_text_file(normalized)
      if type(source) ~= "string" then
        error("unable to read module " .. normalized)
      end

      local chunk, load_error = load(source, "@" .. normalized, "t", _ENV)
      if chunk == nil then
        error("unable to compile module " .. normalized .. ": " .. tostring(load_error))
      end

      module_cache[normalized] = loading_sentinel
      local ok, result = pcall(chunk)
      if not ok then
        module_cache[normalized] = nil
        error("error loading module " .. normalized .. ": " .. tostring(result))
      end

      if result == nil then
        result = true
      end
      module_cache[normalized] = result
      return result
    end
  end

  if type(dofile) == "function" then
    return function(path)
      return dofile("mods/lua_bots/" .. tostring(path or ""))
    end
  end

  error("sd.runtime.get_mod_text_file is unavailable")
end

sd.runtime = type(sd.runtime) == "table" and sd.runtime or {}
sd.runtime.require_mod = sd.runtime.require_mod or create_mod_require()

local app = sd.runtime.require_mod("scripts/lib/app.lua")
if type(app) ~= "table" or type(app.start) ~= "function" then
  error("scripts/lib/app.lua must return a table with start()")
end

app.start()
