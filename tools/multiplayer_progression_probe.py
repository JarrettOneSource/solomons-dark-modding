#!/usr/bin/env python3
"""Reusable native/ledger progression probes for multiplayer verification."""

from __future__ import annotations

import json
from typing import Any

from verify_local_multiplayer_sync import lua, parse_int_text, parse_key_values


def query_ranked_numeric_stat(
    pipe_name: str,
    entry_index: int,
    property_name: str,
    *,
    participant_id: int | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Read one live ranked StatBook property for a local or remote participant."""
    participant_selector = "nil" if participant_id is None else str(participant_id)
    property_selector = json.dumps(property_name)
    code = f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local requested_participant_id = {participant_selector}
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local bot = nil
if requested_participant_id ~= nil then
  bot = sd.bots and sd.bots.get_participant_state and
    sd.bots.get_participant_state(requested_participant_id) or nil
end
local progression = requested_participant_id == nil and
  tonumber(player and player.progression_address) or
  tonumber(bot and bot.progression_runtime_state_address)
progression = progression or 0
emit('available', progression ~= 0)
emit('progression', progression)
emit('entry_index', {entry_index})
emit('property_name', {property_selector})
if progression == 0 then return end

local function off(name) return sd.debug.layout_offset(name) end
local table_address = tonumber(sd.debug.read_u32(
  progression + off('standalone_wizard_progression_table_base'))) or 0
local table_count = tonumber(sd.debug.read_i32(
  progression + off('standalone_wizard_progression_table_count'))) or 0
emit('table', table_address)
emit('table_count', table_count)
if table_address == 0 or {entry_index} < 0 or {entry_index} >= table_count then
  return
end

local entry = table_address +
  ({entry_index} * off('standalone_wizard_progression_entry_stride'))
local rank = tonumber(sd.debug.read_u16(
  entry + off('standalone_wizard_progression_active_flag'))) or 0
local statbook = tonumber(sd.debug.read_u32(
  entry + off('standalone_wizard_progression_entry_statbook'))) or 0
emit('rank', rank)
emit('statbook', statbook)
if statbook == 0 then return end

local property_list = statbook + off('statbook_numeric_property_list')
local property_count = tonumber(sd.debug.read_i32(
  property_list + off('pointer_list_count'))) or 0
local property_items = tonumber(sd.debug.read_u32(
  property_list + off('pointer_list_items'))) or 0
emit('property_count', property_count)
if property_count <= 0 or property_count > 64 or property_items == 0 then return end

for index = 0, property_count - 1 do
  local wrapper = tonumber(sd.debug.read_u32(property_items + index * 4)) or 0
  local property = wrapper ~= 0 and
    (tonumber(sd.debug.read_u32(wrapper)) or 0) or 0
  if property ~= 0 then
    local name_data = tonumber(sd.debug.read_u32(
      property + off('native_string_data'))) or 0
    local name_length = tonumber(sd.debug.read_i32(
      property + off('native_string_length'))) or 0
    local name = ''
    if name_data ~= 0 and name_length > 0 and name_length <= 128 then
      name = sd.debug.read_string(name_data, name_length + 1) or ''
      name = string.sub(name, 1, name_length)
    end
    if name == {property_selector} then
      local values_address = tonumber(sd.debug.read_u32(
        property + off('statbook_numeric_property_values'))) or 0
      local value_count = tonumber(sd.debug.read_i32(
        property + off('statbook_numeric_property_value_count'))) or 0
      emit('property_found', true)
      emit('value_count', value_count)
      if values_address == 0 or value_count <= 0 or value_count > 1024 then return end
      local resolved_rank = math.min(rank, value_count - 1)
      emit('resolved_rank', resolved_rank)
      emit('value', sd.debug.read_float(values_address + resolved_rank * 4))
      return
    end
  end
end
emit('property_found', false)
"""
    values = parse_key_values(lua(pipe_name, code, timeout=timeout))
    return {
        "available": values.get("available") == "true",
        "progression": parse_int_text(values.get("progression"), 0),
        "entry_index": parse_int_text(values.get("entry_index"), entry_index),
        "property_name": values.get("property_name", property_name),
        "table": parse_int_text(values.get("table"), 0),
        "table_count": parse_int_text(values.get("table_count"), 0),
        "rank": parse_int_text(values.get("rank"), -1),
        "statbook": parse_int_text(values.get("statbook"), 0),
        "property_count": parse_int_text(values.get("property_count"), 0),
        "property_found": values.get("property_found") == "true",
        "value_count": parse_int_text(values.get("value_count"), 0),
        "resolved_rank": parse_int_text(values.get("resolved_rank"), -1),
        "value": _parse_float(values, "value"),
    }


def _progression_probe_lua(
    participant_id: int | None,
    include_native_text: bool,
) -> str:
    participant_selector = "nil" if participant_id is None else str(participant_id)
    native_text_selector = "true" if include_native_text else "false"
    return rf"""
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end

local function clean_string(value)
  if type(value) ~= 'string' or value == '' then
    return ''
  end
  local nul = string.find(value, '\0', 1, true)
  if nul ~= nil then
    value = string.sub(value, 1, nul - 1)
  end
  if value == '' or string.find(value, '[%z\1-\8\11\12\14-\31\127]') ~= nil then
    return ''
  end
  return value
end

local function read_c_string(address, max_len)
  address = tonumber(address) or 0
  if address == 0 then return '' end
  local ok, value = pcall(sd.debug.read_string, address, max_len or 96)
  if not ok then return '' end
  return clean_string(value)
end

local function read_native_string_object(address)
  address = tonumber(address) or 0
  if address == 0 then return '' end
  local data_offset = sd.debug.layout_offset('native_string_data')
  local length_offset = sd.debug.layout_offset('native_string_length')
  local data = tonumber(sd.debug.read_u32(address + data_offset)) or 0
  local length = tonumber(sd.debug.read_i32(address + length_offset)) or 0
  if data == 0 or length <= 0 or length > 256 then return '' end
  return read_c_string(data, length + 1)
end

local function read_statbook_strings(statbook)
  statbook = tonumber(statbook) or 0
  if statbook == 0 then return '', '' end
  local values = {{}}
  local seen = {{}}
  local function append(value)
    value = clean_string(value)
    if #value >= 3 and not seen[value] then
      seen[value] = true
      table.insert(values, value)
    end
  end
  local string_object = statbook + sd.debug.layout_offset('statbook_name_string')
  local name = read_native_string_object(string_object)
  append(name)
  local ptr = tonumber(sd.debug.read_u32(string_object)) or 0
  append(read_native_string_object(ptr))
  append(read_c_string(ptr, 96))
  append(read_c_string(string_object, 96))

  -- Root discipline/element records have no quick-description string. Scan
  -- the compact 0x7C StatBook object only for those rows so their alternate
  -- native label/description fields can still be mapped to config files.
  if #values == 0 then
    for field_offset = 0, 0x78, 4 do
      local field = statbook + field_offset
      append(read_native_string_object(field))
      local field_ptr = tonumber(sd.debug.read_u32(field)) or 0
      append(read_native_string_object(field_ptr))
      append(read_c_string(field_ptr, 128))
      append(read_c_string(field, 128))
    end
  end
  return values[1] or '', table.concat(values, '|||')
end

local requested_participant_id = {participant_selector}
local include_native_text = {native_text_selector}
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local bot = nil
if requested_participant_id ~= nil then
  bot = sd.bots and sd.bots.get_participant_state and
    sd.bots.get_participant_state(requested_participant_id) or nil
end
local progression = requested_participant_id == nil and
  tonumber(player and player.progression_address) or
  tonumber(bot and bot.progression_runtime_state_address)
progression = progression or 0

local mp = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
local runtime_participant = nil
if mp and mp.participants then
  for _, participant in ipairs(mp.participants) do
    if (requested_participant_id == nil and participant.is_owner) or
       (requested_participant_id ~= nil and
        tonumber(participant.participant_id) == requested_participant_id) then
      runtime_participant = participant
      break
    end
  end
end

emit('available', progression ~= 0)
emit('progression', progression)
emit('runtime.available', runtime_participant ~= nil)
emit('runtime.participant_id', runtime_participant and runtime_participant.participant_id or 0)
emit('runtime.level', runtime_participant and runtime_participant.level or 0)
emit('runtime.experience', runtime_participant and runtime_participant.experience_current or 0)
emit('runtime.life_current', runtime_participant and runtime_participant.life_current or 0)
emit('runtime.life_max', runtime_participant and runtime_participant.life_max or 0)
emit('runtime.mana_current', runtime_participant and runtime_participant.mana_current or 0)
emit('runtime.mana_max', runtime_participant and runtime_participant.mana_max or 0)
emit('runtime.move_speed', runtime_participant and runtime_participant.move_speed or 0)

local owned = runtime_participant and runtime_participant.owned_progression or nil
emit('ledger.initialized', owned and owned.initialized or false)
emit('ledger.spellbook_revision', owned and owned.spellbook_revision or 0)
emit('ledger.statbook_revision', owned and owned.statbook_revision or 0)
emit('ledger.concentration_revision', owned and owned.concentration_revision or 0)
emit('ledger.concentration_selection_valid', owned and owned.concentration_selection_valid or false)
emit('ledger.concentration_entry_a', owned and owned.concentration_entry_a or -1)
emit('ledger.concentration_entry_b', owned and owned.concentration_entry_b or -1)
emit('ledger.derived_stat_revision', owned and owned.derived_stat_revision or 0)
local ledger_derived = owned and owned.derived_stats or nil
emit('ledger.derived.valid', ledger_derived ~= nil)
if ledger_derived then
  emit('ledger.derived.cast_speed_multiplier', ledger_derived.cast_speed_multiplier)
  emit('ledger.derived.mana_recovery_multiplier', ledger_derived.mana_recovery_multiplier)
  emit('ledger.derived.resist_magic_fraction', ledger_derived.resist_magic_fraction)
  emit('ledger.derived.resist_poison_fraction', ledger_derived.resist_poison_fraction)
  emit('ledger.derived.deflect_chance', ledger_derived.deflect_chance)
  emit('ledger.derived.staff_melee_damage_a', ledger_derived.staff_melee_damage_a)
  emit('ledger.derived.staff_melee_damage_b', ledger_derived.staff_melee_damage_b)
  emit('ledger.derived.pickup_range', ledger_derived.pickup_range)
  emit('ledger.derived.secondary_recharge_multiplier', ledger_derived.secondary_recharge_multiplier)
  emit('ledger.derived.offensive_damage_multiplier', ledger_derived.offensive_damage_multiplier)
  emit('ledger.derived.offensive_mana_multiplier', ledger_derived.offensive_mana_multiplier)
  emit('ledger.derived.meditation_recovery_bonus', ledger_derived.meditation_recovery_bonus)
  emit('ledger.derived.meditation_idle_ticks', ledger_derived.meditation_idle_ticks)
end
emit('ledger.entry_count', owned and owned.progression_book_entry_count or 0)
emit('ledger.entry_total_count', owned and owned.progression_book_entry_total_count or 0)
emit('ledger.truncated', owned and owned.progression_book_truncated or false)
if owned and owned.progression_book_entries then
  for _, entry in ipairs(owned.progression_book_entries) do
    emit(
      'ledger.entry.' .. tostring(entry.entry_index),
      table.concat({{
        entry.internal_id or -1,
        entry.active or 0,
        entry.visible or 0,
        entry.category or 0,
        entry.statbook_max_level or -1,
      }}, ','))
  end
end

local primary_entry = -1
local combo_entry = -1
local secondary_entries = {{ -1, -1, -1, -1, -1, -1, -1, -1 }}
if owned and owned.ability_loadout then
  primary_entry = tonumber(owned.ability_loadout.primary_entry_index) or -1
  combo_entry = tonumber(owned.ability_loadout.primary_combo_entry_index) or -1
  local owned_secondaries = owned.ability_loadout.secondary_entry_indices or {{}}
  for index = 1, 8 do
    secondary_entries[index] = tonumber(owned_secondaries[index]) or -1
  end
end
emit('loadout.primary_entry', primary_entry)
emit('loadout.combo_entry', combo_entry)
emit('loadout.secondary_entries', table.concat(secondary_entries, ','))

local gameplay_slot = requested_participant_id == nil and 0 or
  tonumber(bot and bot.gameplay_slot) or -1
local selection_state = sd.gameplay and sd.gameplay.get_selection_debug_state and
  sd.gameplay.get_selection_debug_state() or nil
emit('native.gameplay_slot', gameplay_slot)
emit(
  'native.process_concentration_entry_a',
  tonumber(selection_state and selection_state.concentration_entry_a) or -1)
emit(
  'native.process_concentration_entry_b',
  tonumber(selection_state and selection_state.concentration_entry_b) or -1)
local concentration_slot_index = gameplay_slot + 1
local concentration_by_slot_a =
  selection_state and selection_state.concentration_entries_a_by_slot or nil
local concentration_by_slot_b =
  selection_state and selection_state.concentration_entries_b_by_slot or nil
emit(
  'native.slot_concentration_entry_a',
  tonumber(
    concentration_by_slot_a and concentration_by_slot_a[concentration_slot_index]) or -1)
emit(
  'native.slot_concentration_entry_b',
  tonumber(
    concentration_by_slot_b and concentration_by_slot_b[concentration_slot_index]) or -1)

if progression ~= 0 then
  local function offset(name) return sd.debug.layout_offset(name) end
  emit('native.level', sd.debug.read_i32(progression + offset('progression_level')))
  emit('native.xp', sd.debug.read_float(progression + offset('progression_xp')))
  emit('native.previous_xp_threshold', sd.debug.read_float(progression + offset('progression_previous_xp_threshold')))
  emit('native.next_xp_threshold', sd.debug.read_float(progression + offset('progression_next_xp_threshold')))
  emit('native.hp', sd.debug.read_float(progression + offset('progression_hp')))
  emit('native.max_hp', sd.debug.read_float(progression + offset('progression_max_hp')))
  emit('native.mp', sd.debug.read_float(progression + offset('progression_mp')))
  emit('native.max_mp', sd.debug.read_float(progression + offset('progression_max_mp')))
  emit('native.move_speed', sd.debug.read_float(progression + offset('progression_move_speed')))
  emit('native.derived.cast_speed_multiplier', sd.debug.read_float(progression + offset('progression_cast_speed_multiplier')))
  emit('native.derived.mana_recovery_multiplier', sd.debug.read_float(progression + offset('progression_mana_recovery_multiplier')))
  emit('native.derived.resist_magic_fraction', sd.debug.read_float(progression + offset('progression_resist_magic_fraction')))
  emit('native.derived.resist_poison_fraction', sd.debug.read_float(progression + offset('progression_resist_poison_fraction')))
  emit('native.derived.deflect_chance', sd.debug.read_float(progression + offset('progression_deflect_chance')))
  emit('native.derived.staff_melee_damage_a', sd.debug.read_float(progression + offset('progression_staff_melee_damage_a')))
  emit('native.derived.staff_melee_damage_b', sd.debug.read_float(progression + offset('progression_staff_melee_damage_b')))
  emit('native.derived.pickup_range', sd.debug.read_float(progression + offset('progression_pickup_range')))
  emit('native.derived.secondary_recharge_multiplier', sd.debug.read_float(progression + offset('progression_secondary_recharge_multiplier')))
  emit('native.derived.offensive_damage_multiplier', sd.debug.read_float(progression + offset('progression_offensive_damage_multiplier')))
  emit('native.derived.offensive_mana_multiplier', sd.debug.read_float(progression + offset('progression_offensive_mana_multiplier')))
  emit('native.derived.meditation_idle_ticks', sd.debug.read_i32(progression + offset('progression_meditation_idle_ticks')))
  emit('native.derived.meditation_recovery_bonus', sd.debug.read_float(progression + offset('progression_meditation_recovery_bonus')))
  emit('native.nonlocal_mode', sd.debug.read_u8(progression + offset('progression_nonlocal_mode_flag')))

  local table_address = tonumber(sd.debug.read_u32(
    progression + offset('standalone_wizard_progression_table_base'))) or 0
  local table_count = tonumber(sd.debug.read_i32(
    progression + offset('standalone_wizard_progression_table_count'))) or 0
  emit('native.table', table_address)
  emit('native.entry_count', table_count)
  local limit = table_count
  if limit > 128 then limit = 128 end
  if table_address ~= 0 and limit > 0 then
    local stride = offset('standalone_wizard_progression_entry_stride')
    local internal_offset = offset('standalone_wizard_progression_entry_internal_id')
    local active_offset = offset('standalone_wizard_progression_active_flag')
    local visible_offset = offset('standalone_wizard_progression_visible_flag')
    local category_offset = offset('standalone_wizard_progression_entry_category')
    local statbook_offset = offset('standalone_wizard_progression_entry_statbook')
    local max_level_offset = offset('statbook_max_level')
    for index = 0, limit - 1 do
      local address = table_address + (index * stride)
      local statbook = tonumber(sd.debug.read_u32(address + statbook_offset)) or 0
      local max_level = -1
      if statbook ~= 0 then
        max_level = tonumber(sd.debug.read_i32(statbook + max_level_offset)) or -1
      end
      local internal_id = sd.debug.read_i32(address + internal_offset) or -1
      local category = sd.debug.read_u16(address + category_offset) or 0
      if index >= table_count - 3 and
         (internal_id == 65535 or max_level < 0 or max_level > 256) then
        category = 0
        max_level = 0
      end
      emit(
        'native.entry.' .. tostring(index),
        table.concat({{
          internal_id,
          sd.debug.read_u16(address + active_offset) or 0,
          sd.debug.read_u16(address + visible_offset) or 0,
          category,
          max_level,
        }}, ','))
      emit('native.entry.' .. tostring(index) .. '.statbook', statbook)
      if include_native_text then
        local native_name, native_candidates = read_statbook_strings(statbook)
        emit('native.entry.' .. tostring(index) .. '.name', native_name)
        emit('native.entry.' .. tostring(index) .. '.candidates', native_candidates)
      end
    end
  end

  if primary_entry >= 0 and combo_entry >= 0 then
    local stats = sd.debug.resolve_native_primary_spell_stats(
      progression,
      primary_entry,
      combo_entry)
    emit('spell.resolved', stats and stats.resolved or false)
    if stats then
      for _, key in ipairs({{
        'build_skill_id',
        'current_spell_id',
        'progression_level',
        'output_count',
        'damage',
        'secondary_damage',
        'secondary_damage_available',
        'mana_cost',
        'mana_cost_available',
        'mana_spend_cost',
        'mana_spend_cost_available',
        'mana_output_scale',
        'mana_output_scaled',
        'builder_seh_code',
        'error',
      }}) do
        emit('spell.' .. key, stats[key])
      end
      if stats.outputs then
        emit('spell.output_count_emitted', #stats.outputs)
        for index, value in ipairs(stats.outputs) do
          emit('spell.output.' .. tostring(index), value)
        end
      end
    end
  else
    emit('spell.resolved', false)
    emit('spell.error', 'loadout_unavailable')
  end
end
"""


def _parse_float(values: dict[str, str], key: str) -> float:
    try:
        return float(values.get(key, "0") or 0.0)
    except ValueError:
        return 0.0


def _parse_int_list(values: dict[str, str], key: str) -> list[int]:
    parsed: list[int] = []
    for value in values.get(key, "").split(","):
        if value == "":
            continue
        parsed.append(parse_int_text(value, -1))
    return parsed


def _parse_book_entries(values: dict[str, str], prefix: str) -> dict[int, dict[str, Any]]:
    entries: dict[int, dict[str, Any]] = {}
    marker = prefix + ".entry."
    for key, raw in values.items():
        if not key.startswith(marker):
            continue
        try:
            entry_index = int(key[len(marker) :])
            fields = [int(value) for value in raw.split(",")]
        except ValueError:
            continue
        if len(fields) != 5:
            continue
        entries[entry_index] = {
            "entry_index": entry_index,
            "internal_id": fields[0],
            "active": fields[1],
            "visible": fields[2],
            "category": fields[3],
            "statbook_max_level": fields[4],
        }
    if prefix == "native":
        for entry_index, entry in entries.items():
            entry["statbook_address"] = parse_int_text(
                values.get(f"{prefix}.entry.{entry_index}.statbook"), 0
            )
            entry["native_text"] = values.get(
                f"{prefix}.entry.{entry_index}.name", ""
            )
            entry["native_text_candidates"] = [
                candidate
                for candidate in values.get(
                    f"{prefix}.entry.{entry_index}.candidates", ""
                ).split("|||")
                if candidate
            ]
    return entries


def query_progression_snapshot(
    pipe_name: str,
    *,
    participant_id: int | None = None,
    include_native_text: bool = False,
    timeout: float = 8.0,
) -> dict[str, Any]:
    values = parse_key_values(
        lua(
            pipe_name,
            _progression_probe_lua(participant_id, include_native_text),
            timeout=timeout,
        )
    )
    native_entries = _parse_book_entries(values, "native")
    ledger_entries = _parse_book_entries(values, "ledger")
    spell_output_count = parse_int_text(values.get("spell.output_count_emitted"), 0)
    return {
        "available": values.get("available") == "true",
        "progression": parse_int_text(values.get("progression"), 0),
        "runtime": {
            "available": values.get("runtime.available") == "true",
            "participant_id": parse_int_text(values.get("runtime.participant_id"), 0),
            "level": parse_int_text(values.get("runtime.level"), 0),
            "experience": parse_int_text(values.get("runtime.experience"), 0),
            "life_current": _parse_float(values, "runtime.life_current"),
            "life_max": _parse_float(values, "runtime.life_max"),
            "mana_current": _parse_float(values, "runtime.mana_current"),
            "mana_max": _parse_float(values, "runtime.mana_max"),
            "move_speed": _parse_float(values, "runtime.move_speed"),
        },
        "ledger": {
            "initialized": values.get("ledger.initialized") == "true",
            "spellbook_revision": parse_int_text(values.get("ledger.spellbook_revision"), 0),
            "statbook_revision": parse_int_text(values.get("ledger.statbook_revision"), 0),
            "concentration_revision": parse_int_text(
                values.get("ledger.concentration_revision"), 0
            ),
            "concentration_selection_valid":
                values.get("ledger.concentration_selection_valid") == "true",
            "concentration_entry_a": parse_int_text(
                values.get("ledger.concentration_entry_a"), -1
            ),
            "concentration_entry_b": parse_int_text(
                values.get("ledger.concentration_entry_b"), -1
            ),
            "derived_stat_revision": parse_int_text(
                values.get("ledger.derived_stat_revision"), 0
            ),
            "derived": {
                "valid": values.get("ledger.derived.valid") == "true",
                "cast_speed_multiplier": _parse_float(
                    values, "ledger.derived.cast_speed_multiplier"
                ),
                "mana_recovery_multiplier": _parse_float(
                    values, "ledger.derived.mana_recovery_multiplier"
                ),
                "resist_magic_fraction": _parse_float(
                    values, "ledger.derived.resist_magic_fraction"
                ),
                "resist_poison_fraction": _parse_float(
                    values, "ledger.derived.resist_poison_fraction"
                ),
                "deflect_chance": _parse_float(
                    values, "ledger.derived.deflect_chance"
                ),
                "staff_melee_damage_a": _parse_float(
                    values, "ledger.derived.staff_melee_damage_a"
                ),
                "staff_melee_damage_b": _parse_float(
                    values, "ledger.derived.staff_melee_damage_b"
                ),
                "pickup_range": _parse_float(values, "ledger.derived.pickup_range"),
                "secondary_recharge_multiplier": _parse_float(
                    values, "ledger.derived.secondary_recharge_multiplier"
                ),
                "offensive_damage_multiplier": _parse_float(
                    values, "ledger.derived.offensive_damage_multiplier"
                ),
                "offensive_mana_multiplier": _parse_float(
                    values, "ledger.derived.offensive_mana_multiplier"
                ),
                "meditation_recovery_bonus": _parse_float(
                    values, "ledger.derived.meditation_recovery_bonus"
                ),
                "meditation_idle_ticks": parse_int_text(
                    values.get("ledger.derived.meditation_idle_ticks"), -1
                ),
            },
            "entry_count": parse_int_text(values.get("ledger.entry_count"), 0),
            "entry_total_count": parse_int_text(values.get("ledger.entry_total_count"), 0),
            "truncated": values.get("ledger.truncated") == "true",
            "entries": ledger_entries,
        },
        "loadout": {
            "primary_entry": parse_int_text(values.get("loadout.primary_entry"), -1),
            "combo_entry": parse_int_text(values.get("loadout.combo_entry"), -1),
            "secondary_entry_indices": _parse_int_list(
                values, "loadout.secondary_entries"
            ),
        },
        "native": {
            "gameplay_slot": parse_int_text(values.get("native.gameplay_slot"), -1),
            "process_concentration_entry_a": parse_int_text(
                values.get("native.process_concentration_entry_a"), -1
            ),
            "process_concentration_entry_b": parse_int_text(
                values.get("native.process_concentration_entry_b"), -1
            ),
            "slot_concentration_entry_a": parse_int_text(
                values.get("native.slot_concentration_entry_a"), -1
            ),
            "slot_concentration_entry_b": parse_int_text(
                values.get("native.slot_concentration_entry_b"), -1
            ),
            "level": parse_int_text(values.get("native.level"), 0),
            "xp": _parse_float(values, "native.xp"),
            "previous_xp_threshold": _parse_float(values, "native.previous_xp_threshold"),
            "next_xp_threshold": _parse_float(values, "native.next_xp_threshold"),
            "hp": _parse_float(values, "native.hp"),
            "max_hp": _parse_float(values, "native.max_hp"),
            "mp": _parse_float(values, "native.mp"),
            "max_mp": _parse_float(values, "native.max_mp"),
            "move_speed": _parse_float(values, "native.move_speed"),
            "derived": {
                "cast_speed_multiplier": _parse_float(
                    values, "native.derived.cast_speed_multiplier"
                ),
                "mana_recovery_multiplier": _parse_float(
                    values, "native.derived.mana_recovery_multiplier"
                ),
                "resist_magic_fraction": _parse_float(
                    values, "native.derived.resist_magic_fraction"
                ),
                "resist_poison_fraction": _parse_float(
                    values, "native.derived.resist_poison_fraction"
                ),
                "deflect_chance": _parse_float(
                    values, "native.derived.deflect_chance"
                ),
                "staff_melee_damage_a": _parse_float(
                    values, "native.derived.staff_melee_damage_a"
                ),
                "staff_melee_damage_b": _parse_float(
                    values, "native.derived.staff_melee_damage_b"
                ),
                "pickup_range": _parse_float(
                    values, "native.derived.pickup_range"
                ),
                "secondary_recharge_multiplier": _parse_float(
                    values, "native.derived.secondary_recharge_multiplier"
                ),
                "offensive_damage_multiplier": _parse_float(
                    values, "native.derived.offensive_damage_multiplier"
                ),
                "offensive_mana_multiplier": _parse_float(
                    values, "native.derived.offensive_mana_multiplier"
                ),
                "meditation_idle_ticks": parse_int_text(
                    values.get("native.derived.meditation_idle_ticks"), 0
                ),
                "meditation_recovery_bonus": _parse_float(
                    values, "native.derived.meditation_recovery_bonus"
                ),
            },
            "nonlocal_mode": parse_int_text(values.get("native.nonlocal_mode"), -1),
            "table": parse_int_text(values.get("native.table"), 0),
            "entry_count": parse_int_text(values.get("native.entry_count"), 0),
            "entries": native_entries,
        },
        "spell": {
            "resolved": values.get("spell.resolved") == "true",
            "build_skill_id": parse_int_text(values.get("spell.build_skill_id"), -1),
            "current_spell_id": parse_int_text(values.get("spell.current_spell_id"), -1),
            "progression_level": parse_int_text(values.get("spell.progression_level"), 0),
            "output_count": parse_int_text(values.get("spell.output_count"), 0),
            "damage": _parse_float(values, "spell.damage"),
            "secondary_damage": _parse_float(values, "spell.secondary_damage"),
            "secondary_damage_available": values.get("spell.secondary_damage_available") == "true",
            "mana_cost": _parse_float(values, "spell.mana_cost"),
            "mana_cost_available": values.get("spell.mana_cost_available") == "true",
            "mana_spend_cost": _parse_float(values, "spell.mana_spend_cost"),
            "mana_spend_cost_available": values.get("spell.mana_spend_cost_available") == "true",
            "mana_output_scale": _parse_float(values, "spell.mana_output_scale"),
            "mana_output_scaled": values.get("spell.mana_output_scaled") == "true",
            "builder_seh_code": parse_int_text(values.get("spell.builder_seh_code"), 0),
            "error": values.get("spell.error", ""),
            "outputs": [
                _parse_float(values, f"spell.output.{index}")
                for index in range(1, spell_output_count + 1)
            ],
        },
        "raw": values,
    }


def compare_book_rows(
    expected: dict[int, dict[str, Any]],
    actual: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    synchronized_fields = (
        "entry_index",
        "internal_id",
        "active",
        "visible",
        "category",
        "statbook_max_level",
    )
    mismatches: list[dict[str, Any]] = []
    for entry_index in sorted(set(expected) | set(actual)):
        expected_entry = expected.get(entry_index)
        actual_entry = actual.get(entry_index)
        expected_synchronized = (
            None
            if expected_entry is None
            else {field: expected_entry.get(field) for field in synchronized_fields}
        )
        actual_synchronized = (
            None
            if actual_entry is None
            else {field: actual_entry.get(field) for field in synchronized_fields}
        )
        if expected_synchronized != actual_synchronized:
            mismatches.append(
                {
                    "entry_index": entry_index,
                    "expected": expected_synchronized,
                    "actual": actual_synchronized,
                }
            )
    return mismatches


def compare_float_fields(
    expected: dict[str, Any],
    actual: dict[str, Any],
    fields: tuple[str, ...],
    *,
    tolerance: float = 0.001,
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for field in fields:
        expected_value = float(expected[field])
        actual_value = float(actual[field])
        if abs(expected_value - actual_value) > tolerance:
            mismatches.append(
                {
                    "field": field,
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )
    return mismatches
