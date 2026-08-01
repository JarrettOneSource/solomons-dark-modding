// Boneyard picker frontend. Two-pane keyboard-driven selection screen drawn
// through the loader Lua-draw layer; consumes only the public snapshot plus
// the picker cursor. Pick/cancel intent stays in ProcessPickerInput — this
// file draws and never mutates picker state beyond the ambient frame counter.

constexpr float kPickerPanelMaxWidth = 980.0f;
constexpr float kPickerPanelMaxHeight = 560.0f;
constexpr float kPickerRowHeight = 32.0f;
constexpr std::size_t kPickerNameTruncation = 38;
constexpr std::size_t kPickerDetailTruncation = 30;

const LuaDrawColor kPickerBackdrop{0, 0, 0, 150};
const LuaDrawColor kPickerPanelFill{10, 12, 18, 244};
const LuaDrawColor kPickerPanelEdge{212, 178, 90, 255};
const LuaDrawColor kPickerPanelEdgeInner{60, 52, 34, 255};
const LuaDrawColor kPickerDivider{212, 178, 90, 90};
const LuaDrawColor kPickerTitleGold{248, 220, 150, 255};
const LuaDrawColor kPickerTextBright{232, 232, 228, 255};
const LuaDrawColor kPickerTextDim{158, 162, 170, 255};
const LuaDrawColor kPickerTextMeta{128, 132, 142, 255};
const LuaDrawColor kPickerRowCursorFill{84, 64, 28, 235};
const LuaDrawColor kPickerRowCursorBar{236, 197, 102, 255};
const LuaDrawColor kPickerRowSelectedFill{40, 44, 30, 220};
const LuaDrawColor kPickerCardFill{14, 16, 24, 235};
const LuaDrawColor kPickerScrollTrack{40, 36, 26, 200};
const LuaDrawColor kPickerScrollThumb{212, 178, 90, 220};
const LuaDrawColor kPickerErrorFill{64, 16, 16, 240};
const LuaDrawColor kPickerErrorText{255, 122, 122, 255};
const LuaDrawColor kPickerWaitGold{236, 205, 130, 255};
const LuaDrawColor kPickerHintText{170, 182, 198, 255};

std::string TruncatePickerText(const std::string& text, std::size_t limit) {
    if (text.size() <= limit) {
        return text;
    }
    return text.substr(0, limit > 3 ? limit - 3 : limit) + "...";
}

std::string FormatPickerByteSize(std::uint64_t bytes) {
    constexpr std::uint64_t kKib = 1024;
    constexpr std::uint64_t kMib = kKib * 1024;
    char buffer[48];
    if (bytes >= kMib) {
        std::snprintf(
            buffer,
            sizeof(buffer),
            "%.1f MB",
            static_cast<double>(bytes) / static_cast<double>(kMib));
    } else if (bytes >= kKib) {
        std::snprintf(
            buffer,
            sizeof(buffer),
            "%.1f KB",
            static_cast<double>(bytes) / static_cast<double>(kKib));
    } else {
        std::snprintf(
            buffer,
            sizeof(buffer),
            "%llu B",
            static_cast<unsigned long long>(bytes));
    }
    return buffer;
}

std::string ShortPickerSha(const std::string& sha256) {
    return sha256.size() > 12 ? sha256.substr(0, 12) : sha256;
}

std::size_t CountPickerSourceMods(const BoneyardPickerCatalog& catalog) {
    std::unordered_set<std::string> mods;
    for (const auto& entry : catalog.entries) {
        mods.insert(entry.source_mod_id);
    }
    return mods.size();
}

void SubmitPickerLabelValue(
    float label_x,
    float value_x,
    float y,
    const char* label,
    std::string value,
    LuaDrawColor value_color) {
    SubmitPickerDrawCommand(MakeText(
        label_x,
        y,
        label,
        kPickerTextMeta,
        0.65f));
    SubmitPickerDrawCommand(MakeText(
        value_x,
        y,
        std::move(value),
        value_color,
        0.7f));
}

void RenderBoneyardPickerUi(const BoneyardPickerSnapshot& snapshot) {
    if (!IsLuaDrawRuntimeInitialized() ||
        (!snapshot.is_open && snapshot.error_message.empty())) {
        ClearLuaDrawFrameForMod(kPickerDrawOwner);
        return;
    }

    static std::uint32_t s_picker_frame_counter = 0;
    ++s_picker_frame_counter;

    std::uint32_t viewport_width = 1280;
    std::uint32_t viewport_height = 720;
    std::string ignored_error;
    (void)TryGetLuaDrawViewport(
        &viewport_width,
        &viewport_height,
        &ignored_error);

    const float panel_width = (std::min)(
        kPickerPanelMaxWidth,
        static_cast<float>(viewport_width) - 64.0f);
    const float panel_height = (std::min)(
        kPickerPanelMaxHeight,
        static_cast<float>(viewport_height) - 64.0f);
    const float panel_x =
        (static_cast<float>(viewport_width) - panel_width) * 0.5f;
    const float panel_y =
        (static_cast<float>(viewport_height) - panel_height) * 0.5f;

    BeginLuaDrawFrame(kPickerDrawOwner);

    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::FilledRect,
        0.0f,
        0.0f,
        static_cast<float>(viewport_width),
        static_cast<float>(viewport_height),
        kPickerBackdrop));
    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::FilledRect,
        panel_x,
        panel_y,
        panel_width,
        panel_height,
        kPickerPanelFill));
    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::OutlinedRect,
        panel_x,
        panel_y,
        panel_width,
        panel_height,
        kPickerPanelEdge,
        2.0f));
    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::OutlinedRect,
        panel_x + 6.0f,
        panel_y + 6.0f,
        panel_width - 12.0f,
        panel_height - 12.0f,
        kPickerPanelEdgeInner,
        1.0f));

    SubmitPickerDrawCommand(MakeText(
        panel_x + 24.0f,
        panel_y + 20.0f,
        "CHOOSE A BONEYARD",
        kPickerTitleGold,
        1.15f));

    const bool has_entries =
        snapshot.catalog != nullptr && !snapshot.catalog->entries.empty();
    if (has_entries) {
        const auto entry_count = snapshot.catalog->entries.size();
        char count_line[96];
        std::snprintf(
            count_line,
            sizeof(count_line),
            "%zu boneyard%s from %zu mod%s",
            entry_count,
            entry_count == 1 ? "" : "s",
            CountPickerSourceMods(*snapshot.catalog),
            CountPickerSourceMods(*snapshot.catalog) == 1 ? "" : "s");
        SubmitPickerDrawCommand(MakeText(
            panel_x + 24.0f,
            panel_y + 44.0f,
            count_line,
            kPickerTextMeta,
            0.65f));
    }

    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::FilledRect,
        panel_x + 18.0f,
        panel_y + 64.0f,
        panel_width - 36.0f,
        1.0f,
        kPickerDivider));

    const float footer_height = 46.0f;
    const float list_top = panel_y + 76.0f;
    const float list_bottom = panel_y + panel_height - footer_height - 12.0f;
    const float list_x = panel_x + 20.0f;
    const float list_width = panel_width * 0.54f;
    const auto rows_fit = static_cast<std::size_t>(
        (std::max)(1.0f, (list_bottom - list_top) / kPickerRowHeight));
    const auto visible_rows = (std::min<std::size_t>)(
        kVisibleBoneyardRows,
        rows_fit);

    std::size_t cursor = 0;
    if (has_entries) {
        std::scoped_lock lock(g_picker.mutex);
        cursor = (std::min)(
            g_picker.cursor_index,
            snapshot.catalog->entries.size() - 1);
    }

    if (has_entries) {
        const auto entry_count = snapshot.catalog->entries.size();
        const auto first = cursor >= visible_rows
            ? cursor - visible_rows + 1
            : 0;
        const auto last = (std::min)(first + visible_rows, entry_count);

        float row_y = list_top;
        for (std::size_t index = first; index < last; ++index) {
            const auto& entry = snapshot.catalog->entries[index];
            const bool at_cursor = index == cursor;
            const bool is_committed_selection =
                index == snapshot.selected_index &&
                snapshot.phase != BoneyardPickerPhase::Choosing;

            if (at_cursor || is_committed_selection) {
                SubmitPickerDrawCommand(MakeRectangle(
                    LuaDrawCommandKind::FilledRect,
                    list_x,
                    row_y - 3.0f,
                    list_width,
                    kPickerRowHeight - 4.0f,
                    at_cursor ? kPickerRowCursorFill
                              : kPickerRowSelectedFill));
            }
            if (at_cursor) {
                SubmitPickerDrawCommand(MakeRectangle(
                    LuaDrawCommandKind::FilledRect,
                    list_x,
                    row_y - 3.0f,
                    3.0f,
                    kPickerRowHeight - 4.0f,
                    kPickerRowCursorBar));
            }

            SubmitPickerDrawCommand(MakeText(
                list_x + 14.0f,
                row_y,
                TruncatePickerText(entry.display_name, kPickerNameTruncation),
                at_cursor ? kPickerTitleGold : kPickerTextBright,
                0.85f));
            std::string meta =
                entry.source_mod_name + " v" + entry.source_mod_version;
            if (is_committed_selection) {
                meta += "  [SELECTED]";
            }
            SubmitPickerDrawCommand(MakeText(
                list_x + 14.0f,
                row_y + 14.0f,
                TruncatePickerText(meta, kPickerNameTruncation + 8),
                is_committed_selection ? kPickerWaitGold : kPickerTextMeta,
                0.6f));
            row_y += kPickerRowHeight;
        }

        if (entry_count > visible_rows) {
            const float track_x = list_x + list_width + 8.0f;
            const float track_height = list_bottom - list_top;
            SubmitPickerDrawCommand(MakeRectangle(
                LuaDrawCommandKind::FilledRect,
                track_x,
                list_top,
                4.0f,
                track_height,
                kPickerScrollTrack));
            const float thumb_height = (std::max)(
                18.0f,
                track_height * static_cast<float>(visible_rows) /
                    static_cast<float>(entry_count));
            const float scroll_range = track_height - thumb_height;
            const float denom = static_cast<float>(
                entry_count - visible_rows);
            const float thumb_y = list_top +
                (denom > 0.0f
                     ? scroll_range * static_cast<float>(first) / denom
                     : 0.0f);
            SubmitPickerDrawCommand(MakeRectangle(
                LuaDrawCommandKind::FilledRect,
                track_x,
                thumb_y,
                4.0f,
                thumb_height,
                kPickerScrollThumb));
        }
    } else {
        SubmitPickerDrawCommand(MakeText(
            list_x + 14.0f,
            list_top,
            "No boneyards are staged.",
            kPickerTextDim,
            0.8f));
    }

    if (has_entries) {
        const float card_x = list_x + list_width + 24.0f;
        const float card_width = panel_x + panel_width - card_x - 20.0f;
        const float card_height = list_bottom - list_top;
        SubmitPickerDrawCommand(MakeRectangle(
            LuaDrawCommandKind::FilledRect,
            card_x,
            list_top - 3.0f,
            card_width,
            card_height,
            kPickerCardFill));
        SubmitPickerDrawCommand(MakeRectangle(
            LuaDrawCommandKind::OutlinedRect,
            card_x,
            list_top - 3.0f,
            card_width,
            card_height,
            kPickerPanelEdgeInner,
            1.0f));

        const auto& entry = snapshot.catalog->entries[cursor];
        float detail_y = list_top + 12.0f;
        SubmitPickerDrawCommand(MakeText(
            card_x + 14.0f,
            detail_y,
            TruncatePickerText(entry.display_name, kPickerDetailTruncation),
            kPickerTitleGold,
            0.95f));
        detail_y += 24.0f;
        SubmitPickerDrawCommand(MakeText(
            card_x + 14.0f,
            detail_y,
            TruncatePickerText(
                "from " + entry.source_mod_name + " v" +
                    entry.source_mod_version,
                kPickerDetailTruncation + 10),
            kPickerTextDim,
            0.7f));
        detail_y += 26.0f;

        const float label_x = card_x + 14.0f;
        const float value_x = card_x + 96.0f;
        SubmitPickerLabelValue(
            label_x,
            value_x,
            detail_y,
            "Size",
            FormatPickerByteSize(entry.preview.file_length),
            kPickerTextBright);
        detail_y += 20.0f;
        {
            char complexity[64];
            std::snprintf(
                complexity,
                sizeof(complexity),
                "%u chunks / %u buffers",
                entry.preview.chunk_count,
                entry.preview.named_buffer_count);
            SubmitPickerLabelValue(
                label_x,
                value_x,
                detail_y,
                "Layout",
                complexity,
                kPickerTextBright);
        }
        detail_y += 20.0f;
        SubmitPickerLabelValue(
            label_x,
            value_x,
            detail_y,
            "Depth",
            std::to_string(entry.preview.max_depth),
            kPickerTextBright);
        detail_y += 20.0f;
        SubmitPickerLabelValue(
            label_x,
            value_x,
            detail_y,
            "SHA-256",
            ShortPickerSha(entry.content_sha256),
            kPickerTextMeta);
        detail_y += 20.0f;
        SubmitPickerLabelValue(
            label_x,
            value_x,
            detail_y,
            "File",
            TruncatePickerText(entry.filename, kPickerDetailTruncation),
            kPickerTextMeta);
    }

    const float footer_y = panel_y + panel_height - footer_height + 6.0f;
    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::FilledRect,
        panel_x + 18.0f,
        footer_y - 8.0f,
        panel_width - 36.0f,
        1.0f,
        kPickerDivider));

    if (!snapshot.error_message.empty()) {
        SubmitPickerDrawCommand(MakeRectangle(
            LuaDrawCommandKind::FilledRect,
            panel_x + 18.0f,
            footer_y - 34.0f,
            panel_width - 36.0f,
            24.0f,
            kPickerErrorFill));
        SubmitPickerDrawCommand(MakeText(
            panel_x + 26.0f,
            footer_y - 30.0f,
            TruncatePickerText(
                "ERROR: " + snapshot.error_message,
                110),
            kPickerErrorText,
            0.7f));
    }

    std::string status_line;
    LuaDrawColor status_color = kPickerHintText;
    if (snapshot.phase == BoneyardPickerPhase::WaitingForPeers) {
        const auto missing = snapshot.missing_participant_ids.size();
        std::string dots(
            1 + (s_picker_frame_counter / 20u) % 3u,
            '.');
        char waiting[128];
        std::snprintf(
            waiting,
            sizeof(waiting),
            "Waiting for %zu player%s to fetch this boneyard%s",
            missing,
            missing == 1 ? "" : "s",
            dots.c_str());
        status_line = waiting;
        status_color = kPickerWaitGold;
    } else if (snapshot.phase == BoneyardPickerPhase::Launching) {
        std::string target = "the selected boneyard";
        if (has_entries &&
            snapshot.selected_index < snapshot.catalog->entries.size()) {
            target = snapshot.catalog->entries[snapshot.selected_index]
                         .display_name;
        }
        status_line =
            "Entering " + TruncatePickerText(target, 40) + "...";
        status_color = kPickerWaitGold;
    } else {
        status_line =
            "Up/Down select   PgUp/PgDn jump   Enter play   Esc stock maps";
    }
    SubmitPickerDrawCommand(MakeText(
        panel_x + 24.0f,
        footer_y,
        std::move(status_line),
        status_color,
        0.7f));

    CommitLuaDrawFrame(kPickerDrawOwner);
}
