#include "wave_intelligence.h"

#include "logger.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <map>
#include <mutex>
#include <string_view>
#include <utility>

namespace sdmod {
namespace {

constexpr std::int32_t kMaximumWaveCount = 4096;

struct ParsedWave {
    WaveScheduleEntry entry;
    std::map<std::int32_t, std::int32_t> configured_type_counts;
};

struct LiveWave {
    WaveSummary summary;
    bool completion_reported = false;
};

struct TrackedWaveEnemy {
    std::int32_t wave = 0;
    std::int32_t enemy_type = 0;
};

struct WaveIntelligenceState {
    std::mutex mutex;
    bool initialized = false;
    std::filesystem::path source_path;
    std::vector<WaveScheduleEntry> schedule;
    std::map<std::pair<std::uintptr_t, std::uintptr_t>, std::int32_t>
        wave_by_spawner_identity;
    std::map<std::int32_t, LiveWave> live_waves;
    std::map<std::uintptr_t, TrackedWaveEnemy> enemies;
    std::int32_t current_wave = 0;
    std::int32_t next_wave = 1;
    bool have_replicated_summary = false;
    WaveSummary replicated_summary;
};

WaveIntelligenceState g_wave_state;

std::string Trim(std::string_view value) {
    std::size_t begin = 0;
    while (begin < value.size() &&
           std::isspace(static_cast<unsigned char>(value[begin])) != 0) {
        ++begin;
    }
    std::size_t end = value.size();
    while (end > begin &&
           std::isspace(static_cast<unsigned char>(value[end - 1])) != 0) {
        --end;
    }
    return std::string(value.substr(begin, end - begin));
}

std::string Uppercase(std::string value) {
    std::transform(
        value.begin(),
        value.end(),
        value.begin(),
        [](unsigned char character) {
            return static_cast<char>(std::toupper(character));
        });
    return value;
}

bool StartsWithDirective(const std::string& line, std::string_view directive) {
    return line == directive ||
        (line.size() > directive.size() &&
         line.compare(0, directive.size(), directive) == 0 &&
         line[directive.size()] == ':');
}

bool TryParseNonNegative(
    const std::string& text,
    std::int32_t* value) {
    if (value == nullptr || text.empty()) {
        return false;
    }
    std::size_t consumed = 0;
    try {
        const auto parsed = std::stoll(text, &consumed, 10);
        if (consumed != text.size() || parsed < 0 || parsed > kMaximumWaveCount) {
            return false;
        }
        *value = static_cast<std::int32_t>(parsed);
        return true;
    } catch (...) {
        return false;
    }
}

bool TryParseDirectiveValue(
    const std::string& line,
    std::string_view directive,
    std::int32_t* value) {
    if (!StartsWithDirective(line, directive) || line.size() <= directive.size() + 1) {
        return false;
    }
    return TryParseNonNegative(Trim(line.substr(directive.size() + 1)), value);
}

bool TryParseDirectiveRange(
    const std::string& line,
    std::string_view directive,
    std::int32_t* minimum,
    std::int32_t* maximum) {
    if (minimum == nullptr || maximum == nullptr ||
        !StartsWithDirective(line, directive) ||
        line.size() <= directive.size() + 1) {
        return false;
    }
    const auto range = Trim(line.substr(directive.size() + 1));
    const auto separator = range.find('-');
    if (separator == std::string::npos ||
        !TryParseNonNegative(Trim(range.substr(0, separator)), minimum) ||
        !TryParseNonNegative(Trim(range.substr(separator + 1)), maximum) ||
        *maximum < *minimum) {
        return false;
    }
    return true;
}

bool TryResolveWaveEnemyType(
    const std::string& token,
    std::int32_t* enemy_type) {
    static const std::map<std::string, std::int32_t> kEnemyTypes = {
        {"SKELETON", 1001},
        {"SKELETONARCHER", 1002},
        {"SKELETONMAGE", 1003},
        {"IMP", 1004},
        {"ZOMBIE", 1006},
        {"WRAITH", 1007},
        {"DEMON", 1009},
        {"COFFIN", 1013},
    };
    const auto found = kEnemyTypes.find(token);
    if (enemy_type == nullptr || found == kEnemyTypes.end()) {
        return false;
    }
    *enemy_type = found->second;
    return true;
}

std::vector<WaveCompositionRow> ProjectComposition(
    const std::map<std::int32_t, std::int32_t>& configured_type_counts,
    std::int32_t budget) {
    std::vector<WaveCompositionRow> rows;
    if (budget <= 0 || configured_type_counts.empty()) {
        return rows;
    }

    std::int32_t configured_total = 0;
    for (const auto& [enemy_type, count] : configured_type_counts) {
        (void)enemy_type;
        configured_total += count;
    }
    if (configured_total <= 0) {
        return rows;
    }

    struct Remainder {
        std::size_t row = 0;
        std::int64_t value = 0;
        std::int32_t enemy_type = 0;
    };
    std::vector<Remainder> remainders;
    std::int32_t assigned = 0;
    rows.reserve(configured_type_counts.size());
    remainders.reserve(configured_type_counts.size());
    for (const auto& [enemy_type, count] : configured_type_counts) {
        const auto numerator =
            static_cast<std::int64_t>(budget) * count;
        WaveCompositionRow row;
        row.enemy_type = enemy_type;
        row.planned = static_cast<std::int32_t>(numerator / configured_total);
        assigned += row.planned;
        const auto row_index = rows.size();
        rows.push_back(row);
        remainders.push_back({
            row_index,
            numerator % configured_total,
            enemy_type,
        });
    }

    std::sort(
        remainders.begin(),
        remainders.end(),
        [](const Remainder& left, const Remainder& right) {
            if (left.value != right.value) {
                return left.value > right.value;
            }
            return left.enemy_type < right.enemy_type;
        });
    for (std::int32_t index = 0; index < budget - assigned; ++index) {
        rows[remainders[static_cast<std::size_t>(index) % remainders.size()].row]
            .planned += 1;
    }
    return rows;
}

bool FinalizeParsedWave(
    ParsedWave* wave,
    std::vector<WaveScheduleEntry>* schedule,
    std::string* error_message,
    std::size_t line_number) {
    if (wave == nullptr || schedule == nullptr || error_message == nullptr) {
        return false;
    }
    if (wave->entry.spawn_budget <= 0) {
        *error_message =
            "wave ending near line " + std::to_string(line_number) +
            " has no positive SPAWN budget";
        return false;
    }
    if (wave->configured_type_counts.empty()) {
        *error_message =
            "wave ending near line " + std::to_string(line_number) +
            " has no recognized enemy entries";
        return false;
    }
    if (wave->configured_type_counts.size() > kWaveCompositionMaxRows) {
        *error_message =
            "wave ending near line " + std::to_string(line_number) +
            " exceeds the supported composition row limit";
        return false;
    }
    wave->entry.wave = static_cast<std::int32_t>(schedule->size() + 1);
    wave->entry.composition = ProjectComposition(
        wave->configured_type_counts,
        wave->entry.spawn_budget);
    schedule->push_back(std::move(wave->entry));
    *wave = ParsedWave{};
    return true;
}

bool ParseWaveSchedule(
    const std::filesystem::path& path,
    std::vector<WaveScheduleEntry>* schedule,
    std::string* error_message) {
    if (schedule == nullptr || error_message == nullptr) {
        return false;
    }
    schedule->clear();
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        *error_message = "unable to open effective wave schedule: " + path.string();
        return false;
    }

    ParsedWave current;
    bool in_wave = false;
    bool in_group = false;
    std::string raw_line;
    std::size_t line_number = 0;
    while (std::getline(input, raw_line)) {
        ++line_number;
        if (line_number == 1 && raw_line.size() >= 3 &&
            static_cast<unsigned char>(raw_line[0]) == 0xEF &&
            static_cast<unsigned char>(raw_line[1]) == 0xBB &&
            static_cast<unsigned char>(raw_line[2]) == 0xBF) {
            raw_line.erase(0, 3);
        }
        const auto line = Uppercase(Trim(raw_line));
        if (line.empty() || line[0] == '#' || line[0] == ';') {
            continue;
        }
        if (StartsWithDirective(line, "WAVE")) {
            if (in_wave &&
                !FinalizeParsedWave(
                    &current,
                    schedule,
                    error_message,
                    line_number)) {
                return false;
            }
            in_wave = true;
            in_group = false;
            continue;
        }
        if (line == "ENDWAVE") {
            if (!in_wave) {
                continue;
            }
            if (!FinalizeParsedWave(
                    &current,
                    schedule,
                    error_message,
                    line_number)) {
                return false;
            }
            in_wave = false;
            in_group = false;
            continue;
        }
        if (!in_wave) {
            *error_message =
                "wave schedule content before first WAVE at line " +
                std::to_string(line_number);
            return false;
        }
        if (line == "GROUP" || line == "FORMATION") {
            in_group = true;
            continue;
        }
        if (line == "ZOMBIEWAVE") {
            current.entry.zombie_wave = true;
            continue;
        }
        if (StartsWithDirective(line, "NEXT")) {
            in_group = false;
            continue;
        }
        if (StartsWithDirective(line, "SPAWN")) {
            in_group = false;
            if (!TryParseDirectiveValue(
                    line,
                    "SPAWN",
                    &current.entry.spawn_budget)) {
                *error_message = "invalid SPAWN value at line " +
                    std::to_string(line_number);
                return false;
            }
            continue;
        }
        if (StartsWithDirective(line, "SPAWNDELAY")) {
            in_group = false;
            if (!TryParseDirectiveRange(
                    line,
                    "SPAWNDELAY",
                    &current.entry.spawn_delay_min,
                    &current.entry.spawn_delay_max)) {
                *error_message = "invalid SPAWNDELAY range at line " +
                    std::to_string(line_number);
                return false;
            }
            continue;
        }
        if (StartsWithDirective(line, "WAVEDELAY")) {
            in_group = false;
            if (!TryParseDirectiveRange(
                    line,
                    "WAVEDELAY",
                    &current.entry.wave_delay_min,
                    &current.entry.wave_delay_max)) {
                *error_message = "invalid WAVEDELAY range at line " +
                    std::to_string(line_number);
                return false;
            }
            continue;
        }
        if (StartsWithDirective(line, "MAXENEMIES")) {
            in_group = false;
            if (!TryParseDirectiveValue(
                    line,
                    "MAXENEMIES",
                    &current.entry.max_enemies)) {
                *error_message = "invalid MAXENEMIES value at line " +
                    std::to_string(line_number);
                return false;
            }
            continue;
        }
        if (!in_group) {
            *error_message =
                "unknown wave directive at line " +
                std::to_string(line_number) + ": " + line;
            return false;
        }

        const auto separator = line.find(':');
        const auto token = Trim(line.substr(0, separator));
        std::int32_t enemy_type = 0;
        if (!TryResolveWaveEnemyType(token, &enemy_type)) {
            *error_message =
                "unknown wave enemy token at line " +
                std::to_string(line_number) + ": " + token;
            return false;
        }
        current.configured_type_counts[enemy_type] += 1;
    }

    if (input.bad()) {
        *error_message = "failed while reading effective wave schedule: " + path.string();
        return false;
    }
    if (in_wave &&
        !FinalizeParsedWave(
            &current,
            schedule,
            error_message,
            line_number)) {
        return false;
    }
    if (schedule->empty()) {
        *error_message = "effective wave schedule contains no waves: " + path.string();
        return false;
    }
    return true;
}

WaveSummary IdleSummary() {
    WaveSummary summary;
    summary.valid = true;
    summary.phase = WavePhase::Idle;
    return summary;
}

WaveSummary BuildInitialSummary(
    std::int32_t wave,
    std::int32_t remaining_to_spawn,
    const std::vector<WaveScheduleEntry>& schedule) {
    WaveSummary summary;
    summary.valid = true;
    summary.wave = wave;
    summary.phase = remaining_to_spawn > 0
        ? WavePhase::Spawning
        : WavePhase::Completed;
    summary.remaining_to_spawn = remaining_to_spawn;
    if (wave > 0 && static_cast<std::size_t>(wave) <= schedule.size()) {
        const auto& scheduled = schedule[static_cast<std::size_t>(wave - 1)];
        std::map<std::int32_t, std::int32_t> weights;
        for (const auto& row : scheduled.composition) {
            weights[row.enemy_type] = row.planned;
        }
        summary.composition = ProjectComposition(weights, remaining_to_spawn);
    }
    return summary;
}

WaveCompositionRow* FindOrAddCompositionRow(
    WaveSummary* summary,
    std::int32_t enemy_type) {
    if (summary == nullptr) {
        return nullptr;
    }
    const auto found = std::find_if(
        summary->composition.begin(),
        summary->composition.end(),
        [enemy_type](const WaveCompositionRow& row) {
            return row.enemy_type == enemy_type;
        });
    if (found != summary->composition.end()) {
        return &*found;
    }
    if (summary->composition.size() >= kWaveCompositionMaxRows) {
        return nullptr;
    }
    WaveCompositionRow row;
    row.enemy_type = enemy_type;
    const auto inserted = std::lower_bound(
        summary->composition.begin(),
        summary->composition.end(),
        enemy_type,
        [](const WaveCompositionRow& candidate, std::int32_t type) {
            return candidate.enemy_type < type;
        });
    return &*summary->composition.insert(inserted, row);
}

void RecomputeSummaryTotals(WaveSummary* summary) {
    if (summary == nullptr) {
        return;
    }
    summary->spawned = 0;
    summary->alive = 0;
    summary->killed = 0;
    for (const auto& row : summary->composition) {
        summary->spawned += row.spawned;
        summary->alive += row.alive;
        summary->killed += row.killed;
    }
}

void RecomputeWavePhase(LiveWave* wave) {
    if (wave == nullptr) {
        return;
    }
    if (wave->summary.remaining_to_spawn > 0) {
        wave->summary.phase = WavePhase::Spawning;
    } else if (wave->summary.alive > 0) {
        wave->summary.phase = WavePhase::Clearing;
    } else {
        wave->summary.phase = WavePhase::Completed;
    }
}

WaveSummaryUpdate MakeUpdate(LiveWave* wave, bool started) {
    WaveSummaryUpdate update;
    if (wave == nullptr) {
        return update;
    }
    update.summary = wave->summary;
    if (started) {
        update.started_wave = wave->summary.wave;
    }
    if (wave->summary.phase == WavePhase::Completed &&
        !wave->completion_reported) {
        wave->completion_reported = true;
        update.completed_wave = wave->summary.wave;
    }
    return update;
}

}  // namespace

bool InitializeWaveIntelligence(
    const std::filesystem::path& stage_root,
    std::string* error_message) {
    if (error_message == nullptr) {
        return false;
    }
    error_message->clear();
    const auto source_path = stage_root / "data" / "wave.txt";
    std::vector<WaveScheduleEntry> schedule;
    if (!ParseWaveSchedule(source_path, &schedule, error_message)) {
        return false;
    }

    std::scoped_lock lock(g_wave_state.mutex);
    g_wave_state.initialized = true;
    g_wave_state.source_path = source_path;
    g_wave_state.schedule = std::move(schedule);
    g_wave_state.wave_by_spawner_identity.clear();
    g_wave_state.live_waves.clear();
    g_wave_state.enemies.clear();
    g_wave_state.current_wave = 0;
    g_wave_state.next_wave = 1;
    g_wave_state.have_replicated_summary = false;
    g_wave_state.replicated_summary = WaveSummary{};
    Log(
        "Wave intelligence loaded " +
        std::to_string(g_wave_state.schedule.size()) +
        " waves from " + source_path.string());
    return true;
}

void ShutdownWaveIntelligence() {
    std::scoped_lock lock(g_wave_state.mutex);
    g_wave_state.initialized = false;
    g_wave_state.source_path.clear();
    g_wave_state.schedule.clear();
    g_wave_state.wave_by_spawner_identity.clear();
    g_wave_state.live_waves.clear();
    g_wave_state.enemies.clear();
    g_wave_state.current_wave = 0;
    g_wave_state.next_wave = 1;
    g_wave_state.have_replicated_summary = false;
    g_wave_state.replicated_summary = WaveSummary{};
}

bool IsWaveIntelligenceInitialized() {
    std::scoped_lock lock(g_wave_state.mutex);
    return g_wave_state.initialized;
}

void ResetWaveIntelligenceRun() {
    std::scoped_lock lock(g_wave_state.mutex);
    g_wave_state.wave_by_spawner_identity.clear();
    g_wave_state.live_waves.clear();
    g_wave_state.enemies.clear();
    g_wave_state.current_wave = 0;
    g_wave_state.next_wave = 1;
    g_wave_state.have_replicated_summary = false;
    g_wave_state.replicated_summary = WaveSummary{};
}

WaveSummary SnapshotWaveSummary() {
    std::scoped_lock lock(g_wave_state.mutex);
    if (!g_wave_state.initialized) {
        return WaveSummary{};
    }
    if (g_wave_state.have_replicated_summary) {
        return g_wave_state.replicated_summary;
    }
    const auto found = g_wave_state.live_waves.find(g_wave_state.current_wave);
    return found != g_wave_state.live_waves.end()
        ? found->second.summary
        : IdleSummary();
}

std::vector<WaveScheduleEntry> GetUpcomingWaveSchedule(std::size_t count) {
    std::scoped_lock lock(g_wave_state.mutex);
    std::vector<WaveScheduleEntry> preview;
    if (!g_wave_state.initialized || count == 0) {
        return preview;
    }
    const auto current_wave = g_wave_state.have_replicated_summary
        ? g_wave_state.replicated_summary.wave
        : g_wave_state.current_wave;
    const auto start = static_cast<std::size_t>((std::max)(0, current_wave));
    if (start >= g_wave_state.schedule.size()) {
        return preview;
    }
    const auto end = (std::min)(g_wave_state.schedule.size(), start + count);
    preview.insert(
        preview.end(),
        g_wave_state.schedule.begin() + start,
        g_wave_state.schedule.begin() + end);
    return preview;
}

WaveSummaryUpdate ObserveAuthorityWaveSpawner(
    std::uintptr_t spawner_address,
    std::uintptr_t action_record_address,
    std::int32_t remaining_to_spawn,
    std::int32_t native_wave_hint) {
    std::scoped_lock lock(g_wave_state.mutex);
    if (!g_wave_state.initialized || spawner_address == 0 ||
        action_record_address == 0 || remaining_to_spawn < 0 ||
        remaining_to_spawn > kMaximumWaveCount) {
        return {};
    }

    const auto identity = std::make_pair(spawner_address, action_record_address);
    auto identity_it = g_wave_state.wave_by_spawner_identity.find(identity);
    bool started = false;
    std::int32_t wave_number = 0;
    if (identity_it == g_wave_state.wave_by_spawner_identity.end()) {
        const bool usable_hint =
            native_wave_hint == g_wave_state.next_wave &&
            static_cast<std::size_t>(native_wave_hint) <=
                g_wave_state.schedule.size() &&
            g_wave_state.live_waves.find(native_wave_hint) ==
                g_wave_state.live_waves.end();
        wave_number = usable_hint ? native_wave_hint : g_wave_state.next_wave;
        g_wave_state.next_wave = (std::max)(
            g_wave_state.next_wave,
            wave_number + 1);
        g_wave_state.wave_by_spawner_identity.emplace(identity, wave_number);
        LiveWave wave;
        wave.summary = BuildInitialSummary(
            wave_number,
            remaining_to_spawn,
            g_wave_state.schedule);
        g_wave_state.live_waves.emplace(wave_number, std::move(wave));
        g_wave_state.current_wave = (std::max)(
            g_wave_state.current_wave,
            wave_number);
        g_wave_state.have_replicated_summary = false;
        started = true;
    } else {
        wave_number = identity_it->second;
    }

    auto wave_it = g_wave_state.live_waves.find(wave_number);
    if (wave_it == g_wave_state.live_waves.end()) {
        return {};
    }
    wave_it->second.summary.remaining_to_spawn = remaining_to_spawn;
    RecomputeWavePhase(&wave_it->second);
    return MakeUpdate(&wave_it->second, started);
}

void ObserveAuthorityWaveEnemySpawn(
    std::uintptr_t enemy_address,
    std::int32_t enemy_type,
    std::int32_t wave) {
    std::scoped_lock lock(g_wave_state.mutex);
    if (!g_wave_state.initialized || enemy_address == 0 || enemy_type < 0 || wave <= 0) {
        return;
    }
    auto wave_it = g_wave_state.live_waves.find(wave);
    if (wave_it == g_wave_state.live_waves.end()) {
        return;
    }
    const auto existing = g_wave_state.enemies.find(enemy_address);
    if (existing != g_wave_state.enemies.end()) {
        return;
    }
    auto* row = FindOrAddCompositionRow(&wave_it->second.summary, enemy_type);
    if (row == nullptr) {
        return;
    }
    row->spawned += 1;
    row->alive += 1;
    g_wave_state.enemies.emplace(
        enemy_address,
        TrackedWaveEnemy{wave, enemy_type});
    RecomputeSummaryTotals(&wave_it->second.summary);
    RecomputeWavePhase(&wave_it->second);
}

WaveSummaryUpdate ObserveAuthorityWaveEnemyDeath(
    std::uintptr_t enemy_address) {
    std::scoped_lock lock(g_wave_state.mutex);
    if (!g_wave_state.initialized || enemy_address == 0) {
        return {};
    }
    const auto tracked = g_wave_state.enemies.find(enemy_address);
    if (tracked == g_wave_state.enemies.end()) {
        return {};
    }
    const auto tracked_enemy = tracked->second;
    g_wave_state.enemies.erase(tracked);
    auto wave_it = g_wave_state.live_waves.find(tracked_enemy.wave);
    if (wave_it == g_wave_state.live_waves.end()) {
        return {};
    }
    auto* row = FindOrAddCompositionRow(
        &wave_it->second.summary,
        tracked_enemy.enemy_type);
    if (row == nullptr) {
        return {};
    }
    row->alive = (std::max)(0, row->alive - 1);
    row->killed += 1;
    RecomputeSummaryTotals(&wave_it->second.summary);
    RecomputeWavePhase(&wave_it->second);
    return MakeUpdate(&wave_it->second, false);
}

WaveSummaryUpdate ApplyReplicatedWaveSummary(const WaveSummary& summary) {
    std::scoped_lock lock(g_wave_state.mutex);
    if (!g_wave_state.initialized || !summary.valid || summary.wave < 0 ||
        summary.remaining_to_spawn < 0 || summary.spawned < 0 ||
        summary.alive < 0 || summary.killed < 0 ||
        summary.composition.size() > kWaveCompositionMaxRows) {
        return {};
    }

    WaveSummaryUpdate update;
    const auto previous = g_wave_state.have_replicated_summary
        ? g_wave_state.replicated_summary
        : IdleSummary();
    g_wave_state.replicated_summary = summary;
    g_wave_state.have_replicated_summary = true;
    update.summary = summary;
    if (summary.wave > 0 && summary.wave != previous.wave) {
        update.started_wave = summary.wave;
    }
    if (summary.wave > 0 && summary.wave == previous.wave &&
        previous.phase != WavePhase::Completed &&
        summary.phase == WavePhase::Completed) {
        update.completed_wave = summary.wave;
    }
    return update;
}

const char* WavePhaseLabel(WavePhase phase) {
    switch (phase) {
    case WavePhase::Idle:
        return "idle";
    case WavePhase::Spawning:
        return "spawning";
    case WavePhase::Clearing:
        return "clearing";
    case WavePhase::Completed:
        return "completed";
    }
    return "idle";
}

}  // namespace sdmod
