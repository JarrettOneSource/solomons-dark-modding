#include "mod_settings.h"
#include "mod_settings_json.h"

#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace {

using sdmod::settings_json::Type;
using sdmod::settings_json::Value;

[[noreturn]] void Fail(const std::string& message) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
}

const Value& RequireField(
    const Value& object,
    const char* field,
    Type type) {
    const auto* value = object.Find(field);
    if (value == nullptr || value->type != type) {
        Fail(std::string("fixture field has wrong type: ") + field);
    }
    return *value;
}

sdmod::ModSettingsDeclaration BuildPersistenceDeclaration() {
    constexpr std::string_view kManifest = R"json({
      "settings": {
        "version": 1,
        "entries": [
          {
            "key": "enabled",
            "type": "toggle",
            "label": "Enabled",
            "default": true
          },
          {
            "key": "count",
            "type": "number",
            "label": "Count",
            "default": 2,
            "min": 1,
            "max": 4,
            "integer": true
          },
          {
            "key": "run",
            "type": "action",
            "label": "Run"
          }
        ]
      }
    })json";
    sdmod::ModSettingsManifestResult parsed;
    if (!sdmod::ParseModSettingsManifestJson(kManifest, &parsed) ||
        !parsed.has_settings ||
        !parsed.valid) {
        Fail("unable to build persistence declaration: " + parsed.error);
    }
    return parsed.declaration;
}

void TestCanonicalKeybindNamespace() {
    std::vector<std::string> canonical;
    for (char letter = 'A'; letter <= 'Z'; ++letter) {
        canonical.emplace_back(1, letter);
    }
    for (char digit = '0'; digit <= '9'; ++digit) {
        canonical.emplace_back(1, digit);
    }
    for (int number = 1; number <= 24; ++number) {
        canonical.push_back("F" + std::to_string(number));
    }
    for (const auto* named : {
             "SPACE", "TAB", "ENTER", "SHIFT", "CTRL", "ALT",
             "UP", "DOWN", "LEFT", "RIGHT",
             "MOUSE3", "MOUSE4", "MOUSE5", "NONE"}) {
        canonical.emplace_back(named);
    }
    for (const auto& keybind : canonical) {
        if (!sdmod::IsCanonicalModSettingKeybind(keybind)) {
            Fail("canonical keybind rejected: " + keybind);
        }
    }
    for (const auto* invalid : {
             "", "a", "ESC", "F0", "F25", "F01",
             "MOUSE1", "MOUSE2", "CTRL+A"}) {
        if (sdmod::IsCanonicalModSettingKeybind(invalid)) {
            Fail(std::string("noncanonical keybind accepted: ") + invalid);
        }
    }
}

void TestInvalidManifestUnicode() {
    constexpr std::string_view kManifest = R"json({
      "settings": {
        "version": 1,
        "entries": [
          {
            "key": "name",
            "type": "text",
            "label": "\uD800",
            "default": ""
          }
        ]
      }
    })json";
    sdmod::ModSettingsManifestResult parsed;
    if (!sdmod::ParseModSettingsManifestJson(kManifest, &parsed) ||
        !parsed.has_settings ||
        parsed.valid ||
        parsed.error.empty()) {
        Fail("settings manifest accepted an unpaired Unicode surrogate");
    }
}

void TestPersistedValueFiltering() {
    const auto declaration = BuildPersistenceDeclaration();
    sdmod::ModSettingsValuesResult parsed;
    constexpr std::string_view kPersisted = R"json({
      "schemaVersion": 1,
      "values": {
        "enabled": false,
        "count": 2.5,
        "run": true,
        "removed": "old"
      }
    })json";
    if (!sdmod::ParsePersistedModSettingsJson(
            kPersisted,
            declaration,
            &parsed) ||
        !parsed.valid) {
        Fail("valid persisted settings were rejected: " + parsed.error);
    }
    if (parsed.values.size() != 1 ||
        parsed.values.at("enabled") !=
            sdmod::ModSettingValue::Boolean(false) ||
        parsed.warnings.size() != 3 ||
        parsed.entry_errors.size() != 1 ||
        parsed.entry_errors.find("count") ==
            parsed.entry_errors.end()) {
        Fail("persisted settings did not filter invalid, action, and unknown values");
    }

    if (!sdmod::ParsePersistedModSettingsJson(
            R"json({"schemaVersion":2,"values":{}})json",
            declaration,
            &parsed) ||
        parsed.valid ||
        parsed.error.empty()) {
        Fail("invalid persisted root schema was not rejected");
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        Fail("expected the validation-vector path");
    }
    std::ifstream stream(argv[1], std::ios::binary);
    if (!stream.is_open()) {
        Fail("unable to open validation vectors");
    }
    const std::string source{
        std::istreambuf_iterator<char>(stream),
        std::istreambuf_iterator<char>()};

    Value fixture;
    std::string parse_error;
    if (!sdmod::settings_json::Parse(source, &fixture, &parse_error)) {
        Fail("unable to parse validation vectors: " + parse_error);
    }
    const auto& required_rules =
        RequireField(fixture, "requiredRules", Type::Array);
    const auto& required_value_rules =
        RequireField(fixture, "requiredValueRules", Type::Array);
    const auto& vectors = RequireField(fixture, "vectors", Type::Array);
    const auto& value_vectors =
        RequireField(fixture, "valueVectors", Type::Array);
    std::set<std::string, std::less<>> required;
    std::set<std::string, std::less<>> required_values;
    std::map<std::string, std::pair<bool, bool>, std::less<>> coverage;
    std::map<std::string, std::pair<bool, bool>, std::less<>>
        value_coverage;
    std::map<std::string, const Value*, std::less<>> manifests;
    for (const auto& rule : required_rules.array_value) {
        if (rule.type != Type::String ||
            !required.insert(rule.string_value).second) {
            Fail("requiredRules contains an invalid or duplicate rule");
        }
    }
    for (const auto& rule : required_value_rules.array_value) {
        if (rule.type != Type::String ||
            !required_values.insert(rule.string_value).second) {
            Fail("requiredValueRules contains an invalid or duplicate rule");
        }
    }

    std::size_t passed = 0;
    for (const auto& vector : vectors.array_value) {
        if (vector.type != Type::Object) {
            Fail("validation vector must be an object");
        }
        const auto& name =
            RequireField(vector, "name", Type::String).string_value;
        const auto expected =
            RequireField(vector, "valid", Type::Boolean).boolean_value;
        const auto& rules = RequireField(vector, "rules", Type::Array);
        const auto& manifest =
            RequireField(vector, "manifest", Type::Object);
        if (!manifests.emplace(name, &manifest).second) {
            Fail("validation vectors contain a duplicate name: " + name);
        }

        sdmod::ModSettingsManifestResult result;
        if (!sdmod::ParseModSettingsManifestJson(
                sdmod::settings_json::Serialize(manifest),
                &result)) {
            Fail(name + ": validator call failed");
        }
        const auto actual = result.has_settings && result.valid;
        if (actual != expected) {
            Fail(
                name + ": expected valid=" +
                (expected ? "true" : "false") +
                ", actual valid=" + (actual ? "true" : "false") +
                ", error=" + result.error);
        }
        for (const auto& rule : rules.array_value) {
            if (rule.type != Type::String ||
                required.find(rule.string_value) == required.end()) {
                Fail(name + ": vector names an unknown rule");
            }
            auto& covered = coverage[rule.string_value];
            (expected ? covered.first : covered.second) = true;
        }
        ++passed;
    }
    for (const auto& vector : value_vectors.array_value) {
        if (vector.type != Type::Object) {
            Fail("value validation vector must be an object");
        }
        const auto& name =
            RequireField(vector, "name", Type::String).string_value;
        const auto expected =
            RequireField(vector, "valid", Type::Boolean).boolean_value;
        const auto& rules = RequireField(vector, "rules", Type::Array);
        const auto& definition_name =
            RequireField(
                vector,
                "definitionVector",
                Type::String).string_value;
        const auto& entry_key =
            RequireField(vector, "entryKey", Type::String).string_value;
        const auto* source_value = vector.Find("value");
        const auto definition = manifests.find(definition_name);
        if (source_value == nullptr || definition == manifests.end()) {
            Fail(name + ": value vector references missing fixture data");
        }

        sdmod::ModSettingsManifestResult declaration;
        if (!sdmod::ParseModSettingsManifestJson(
                sdmod::settings_json::Serialize(*definition->second),
                &declaration) ||
            !declaration.has_settings ||
            !declaration.valid) {
            Fail(
                name + ": referenced declaration is invalid: " +
                declaration.error);
        }

        Value persisted;
        persisted.type = Type::Object;
        Value schema_version;
        schema_version.type = Type::Number;
        schema_version.number_value = 1.0;
        persisted.object_value.emplace(
            "schemaVersion",
            std::move(schema_version));
        Value persisted_values;
        persisted_values.type = Type::Object;
        persisted_values.object_value.emplace(entry_key, *source_value);
        persisted.object_value.emplace(
            "values",
            std::move(persisted_values));

        sdmod::ModSettingsValuesResult parsed;
        if (!sdmod::ParsePersistedModSettingsJson(
                sdmod::settings_json::Serialize(persisted),
                declaration.declaration,
                &parsed) ||
            !parsed.valid) {
            Fail(name + ": persisted-value validator call failed");
        }
        const auto actual =
            parsed.values.find(entry_key) != parsed.values.end();
        if (actual != expected) {
            Fail(
                name + ": expected value valid=" +
                (expected ? "true" : "false") +
                ", actual valid=" + (actual ? "true" : "false"));
        }
        for (const auto& rule : rules.array_value) {
            if (rule.type != Type::String ||
                required_values.find(rule.string_value) ==
                    required_values.end()) {
                Fail(name + ": value vector names an unknown rule");
            }
            auto& covered = value_coverage[rule.string_value];
            (expected ? covered.first : covered.second) = true;
        }
        ++passed;
    }

    for (const auto& rule : required) {
        const auto found = coverage.find(rule);
        if (found == coverage.end() ||
            !found->second.first ||
            !found->second.second) {
            Fail(rule + ": requires at least one accept and reject vector");
        }
    }
    for (const auto& rule : required_values) {
        const auto found = value_coverage.find(rule);
        if (found == value_coverage.end() ||
            !found->second.first ||
            !found->second.second) {
            Fail(
                rule +
                ": requires at least one accept and reject value vector");
        }
    }
    TestCanonicalKeybindNamespace();
    TestInvalidManifestUnicode();
    TestPersistedValueFiltering();
    std::cout << "PASS: " << passed
              << " mod-settings validation vectors; "
              << required.size() + required_values.size()
              << " rules covered\n";
    return 0;
}
