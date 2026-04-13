local function create_mod_require()
  if type(load) ~= "function" then
    error("Lua base load() is unavailable in this runtime")
  end
  if type(sd) ~= "table" or type(sd.runtime) ~= "table" or
      type(sd.runtime.get_mod_text_file) ~= "function" then
    error("sd.runtime.get_mod_text_file is unavailable")
  end

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

  local function require_mod(path)
    local normalized = normalize_module_path(path)
    local cached = module_cache[normalized]
    if cached == loading_sentinel then
      error("circular module load for " .. normalized)
    end
    if cached ~= nil then
      return cached
    end

    local source = sd.runtime.get_mod_text_file(normalized)
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

  return require_mod
end

sd.runtime.require_mod = create_mod_require()

local app = sd.runtime.require_mod("scripts/lib/app.lua")
if type(app) ~= "table" or type(app.start) ~= "function" then
  error("scripts/lib/app.lua must return a table with start()")
end

app.start()
