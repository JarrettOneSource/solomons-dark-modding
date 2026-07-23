const LuaModValue* FindField(
    const LuaModValue& object,
    std::string_view field_name) {
    const auto found = object.object_value.find(field_name);
    return found == object.object_value.end() ? nullptr : &found->second;
}

bool IsNumeric(const LuaModValue& value) {
    return value.type == LuaModValueType::Integer ||
        value.type == LuaModValueType::Number;
}

double AsNumber(const LuaModValue& value) {
    return value.type == LuaModValueType::Integer
        ? static_cast<double>(value.integer_value)
        : value.number_value;
}

bool ReadBoundedFloat(
    const LuaModValue& object,
    std::string_view field_name,
    float default_value,
    float minimum,
    float maximum,
    float* value,
    std::string* error_message) {
    const auto* field = FindField(object, field_name);
    if (field == nullptr) {
        *value = default_value;
        return true;
    }
    if (!IsNumeric(*field)) {
        *error_message = std::string(field_name) + " must be numeric";
        return false;
    }
    const auto parsed = AsNumber(*field);
    if (!std::isfinite(parsed) || parsed < minimum || parsed > maximum) {
        *error_message = std::string(field_name) + " is outside its supported range";
        return false;
    }
    *value = static_cast<float>(parsed);
    return true;
}

std::uint32_t ReadConfigInteger(
    const LuaSpellDefinition& definition,
    std::string_view field_name,
    std::uint32_t default_value) {
    if (definition.config.type != LuaModValueType::Object) {
        return default_value;
    }
    const auto* value = FindField(definition.config, field_name);
    if (value == nullptr || value->type != LuaModValueType::Integer ||
        value->integer_value <= 0 ||
        value->integer_value >
            (std::numeric_limits<std::uint32_t>::max)()) {
        return default_value;
    }
    return static_cast<std::uint32_t>(value->integer_value);
}

float ReadConfigNumber(
    const LuaSpellDefinition& definition,
    std::string_view field_name,
    float default_value) {
    if (definition.config.type != LuaModValueType::Object) {
        return default_value;
    }
    const auto* value = FindField(definition.config, field_name);
    if (value == nullptr || !IsNumeric(*value)) {
        return default_value;
    }
    const auto parsed = AsNumber(*value);
    return std::isfinite(parsed)
        ? static_cast<float>(parsed)
        : default_value;
}

bool IsKnownDescriptorField(std::string_view field_name) {
    return field_name == "key" || field_name == "x" ||
        field_name == "y" || field_name == "velocity_x" ||
        field_name == "velocity_y" || field_name == "radius" ||
        field_name == "lifetime_ms" || field_name == "data";
}

bool IsKnownPatchField(std::string_view field_name) {
    return field_name == "x" || field_name == "y" ||
        field_name == "velocity_x" || field_name == "velocity_y" ||
        field_name == "radius" || field_name == "data" ||
        field_name == "done";
}

bool ValidateReplicatedData(
    const LuaModValue& data,
    std::string* error_message) {
    std::vector<std::uint8_t> encoded;
    if (!EncodeLuaModValue(data, &encoded, error_message)) {
        return false;
    }
    if (encoded.size() > kMaximumReplicatedEffectDataBytes) {
        *error_message = "effect data exceeds the 128-byte replication limit";
        return false;
    }
    return true;
}

bool ParseEffectDescriptor(
    const LuaModValue& descriptor,
    const LuaSpellDefinition& definition,
    const LuaRegisteredSpellCastRequest& request,
    LuaSpellEffectInstance* effect,
    std::string* error_message) {
    if (descriptor.type != LuaModValueType::Object) {
        *error_message = "each effect must be an object";
        return false;
    }
    for (const auto& [field_name, unused] : descriptor.object_value) {
        (void)unused;
        if (!IsKnownDescriptorField(field_name)) {
            *error_message = "effect contains unknown field '" + field_name + "'";
            return false;
        }
    }

    const auto* key = FindField(descriptor, "key");
    if (key == nullptr || key->type != LuaModValueType::String ||
        key->string_value.empty() ||
        key->string_value.size() > kMaximumEffectKeyBytes ||
        key->string_value.find('\0') != std::string::npos) {
        *error_message = "effect key must contain 1..64 text bytes";
        return false;
    }

    LuaSpellEffectInstance parsed;
    parsed.cast_request_id = request.request_id;
    parsed.content_id = request.content_id;
    parsed.owner_participant_id = request.owner_participant_id;
    parsed.key = key->string_value;
    if (!ReadBoundedFloat(
            descriptor,
            "x",
            request.aim_x,
            -kMaximumCoordinateMagnitude,
            kMaximumCoordinateMagnitude,
            &parsed.x,
            error_message) ||
        !ReadBoundedFloat(
            descriptor,
            "y",
            request.aim_y,
            -kMaximumCoordinateMagnitude,
            kMaximumCoordinateMagnitude,
            &parsed.y,
            error_message) ||
        !ReadBoundedFloat(
            descriptor,
            "velocity_x",
            0.0f,
            -kMaximumEffectScalar,
            kMaximumEffectScalar,
            &parsed.velocity_x,
            error_message) ||
        !ReadBoundedFloat(
            descriptor,
            "velocity_y",
            0.0f,
            -kMaximumEffectScalar,
            kMaximumEffectScalar,
            &parsed.velocity_y,
            error_message) ||
        !ReadBoundedFloat(
            descriptor,
            "radius",
            ReadConfigNumber(definition, "radius", 0.0f),
            0.0f,
            kMaximumEffectScalar,
            &parsed.radius,
            error_message)) {
        return false;
    }

    const auto default_lifetime = (std::min)(
        ReadConfigInteger(
            definition,
            "duration_ms",
            kDefaultEffectLifetimeMs),
        kMaximumEffectLifetimeMs);
    const auto* lifetime = FindField(descriptor, "lifetime_ms");
    std::uint32_t lifetime_ms = default_lifetime;
    if (lifetime != nullptr) {
        if (lifetime->type != LuaModValueType::Integer ||
            lifetime->integer_value < 1 ||
            lifetime->integer_value > kMaximumEffectLifetimeMs) {
            *error_message = "lifetime_ms must be an integer from 1 through 600000";
            return false;
        }
        lifetime_ms = static_cast<std::uint32_t>(lifetime->integer_value);
    }
    parsed.expires_ms = lifetime_ms;
    parsed.tick_interval_ms = (std::max)(
        1u,
        ReadConfigInteger(
            definition,
            "tick_interval_ms",
            kDefaultTickIntervalMs));
    if (const auto* data = FindField(descriptor, "data"); data != nullptr) {
        if (!ValidateReplicatedData(*data, error_message)) {
            return false;
        }
        parsed.data = *data;
    }
    *effect = std::move(parsed);
    return true;
}
