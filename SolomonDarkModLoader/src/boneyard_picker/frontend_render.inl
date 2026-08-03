// Boneyard picker frontend. Keyboard-driven selection screen drawn through
// the loader Lua-draw layer; consumes only the public snapshot plus the
// picker cursor. Pick/cancel intent stays in ProcessPickerInput — this file
// draws and never mutates picker state beyond the ambient frame counter.
//
// Layout contract (owner-directed): the list zone spans the top two-thirds
// of the screen; the zone below it shows the highlighted entry's name,
// source mod, update date, and description. Every metric multiplies by a
// viewport-derived scale so text stays readable at any resolution.

constexpr float kPickerBaseViewportHeight = 720.0f;
constexpr float kPickerMinUiScale = 1.0f;
constexpr float kPickerMaxUiScale = 3.0f;
constexpr float kPickerRowHeight = 34.0f;
constexpr float kPickerGlyphAdvance = 7.6f;
constexpr std::size_t kPickerDescriptionMaxLines = 4;

const LuaDrawColor kPickerBackdrop{0, 0, 0, 150};
const LuaDrawColor kPickerPanelFill{10, 12, 18, 244};
const LuaDrawColor kPickerPanelEdge{212, 178, 90, 255};
const LuaDrawColor kPickerPanelEdgeInner{60, 52, 34, 255};
const LuaDrawColor kPickerDivider{212, 178, 90, 90};
const LuaDrawColor kPickerTitleGold{248, 220, 150, 255};
const LuaDrawColor kPickerTextBright{232, 232, 228, 255};
const LuaDrawColor kPickerTextDim{170, 174, 182, 255};
const LuaDrawColor kPickerTextMeta{140, 144, 154, 255};
const LuaDrawColor kPickerRowCursorFill{84, 64, 28, 235};
const LuaDrawColor kPickerRowCursorBar{236, 197, 102, 255};
const LuaDrawColor kPickerRowSelectedFill{40, 44, 30, 220};
const LuaDrawColor kPickerCardFill{14, 16, 24, 235};
const LuaDrawColor kPickerScrollTrack{40, 36, 26, 200};
const LuaDrawColor kPickerScrollThumb{212, 178, 90, 220};
const LuaDrawColor kPickerErrorFill{64, 16, 16, 240};
const LuaDrawColor kPickerErrorText{255, 122, 122, 255};
const LuaDrawColor kPickerWaitGold{236, 205, 130, 255};
const LuaDrawColor kPickerHintText{176, 188, 202, 255};

std::string TruncatePickerText(const std::string& text, std::size_t limit) {
    if (text.size() <= limit) {
        return text;
    }
    return text.substr(0, limit > 3 ? limit - 3 : limit) + "...";
}

std::size_t PickerCharsPerLine(float inner_width, float text_scale) {
    const float advance = kPickerGlyphAdvance * text_scale;
    if (advance <= 0.0f || inner_width <= advance) {
        return 1;
    }
    return static_cast<std::size_t>(inner_width / advance);
}

// Word-wraps into at most max_lines '\n'-joined lines; the renderer handles
// '\n' natively. The last line is ellipsized when text overflows.
std::string WrapPickerText(
    const std::string& text,
    std::size_t max_chars,
    std::size_t max_lines) {
    if (max_chars < 4 || max_lines == 0) {
        return std::string();
    }
    std::string wrapped;
    std::size_t line_start = 0;
    std::size_t lines = 0;
    while (line_start < text.size() && lines < max_lines) {
        std::size_t line_end = line_start + max_chars;
        if (line_end >= text.size()) {
            line_end = text.size();
        } else {
            auto break_at = text.rfind(' ', line_end);
            if (break_at != std::string::npos && break_at > line_start) {
                line_end = break_at;
            }
        }
        std::string line = text.substr(line_start, line_end - line_start);
        ++lines;
        if (lines == max_lines && line_end < text.size()) {
            line = TruncatePickerText(line, max_chars > 3 ? max_chars - 3 : 1);
        }
        if (!wrapped.empty()) {
            wrapped += '\n';
        }
        wrapped += line;
        line_start = line_end;
        while (line_start < text.size() && text[line_start] == ' ') {
            ++line_start;
        }
    }
    return wrapped;
}

std::size_t CountPickerSourceMods(const BoneyardPickerCatalog& catalog) {
    std::unordered_set<std::string> mods;
    for (const auto& entry : catalog.entries) {
        mods.insert(entry.source_mod_id);
    }
    return mods.size();
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
    const auto vw = static_cast<float>(viewport_width);
    const auto vh = static_cast<float>(viewport_height);

    // Readability contract: one scale factor drives every metric below, so
    // the picker renders identically proportioned at 720p and 4K.
    const float ui_scale = (std::min)(
        kPickerMaxUiScale,
        (std::max)(kPickerMinUiScale, vh / kPickerBaseViewportHeight));

    // List zone: top two-thirds of the screen.
    const float list_panel_x = vw * 0.06f;
    const float list_panel_width = vw * 0.88f;
    const float list_panel_y = vh * 0.05f;
    const float list_panel_height = vh * 0.61f;
    // Details zone: the strip below, ending above the screen bottom.
    const float detail_panel_y = list_panel_y + list_panel_height + vh * 0.02f;
    const float detail_panel_height = vh * 0.26f;

    const float pad = 20.0f * ui_scale;
    const float title_scale = 1.5f * ui_scale;
    const float row_text_scale = 1.0f * ui_scale;
    const float row_meta_scale = 0.8f * ui_scale;
    const float detail_name_scale = 1.25f * ui_scale;
    const float detail_meta_scale = 0.85f * ui_scale;
    const float description_scale = 0.9f * ui_scale;
    const float hint_scale = 0.85f * ui_scale;
    const float row_height = kPickerRowHeight * ui_scale;
    const float line_height = 16.0f * ui_scale;

    BeginLuaDrawFrame(kPickerDrawOwner);

    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::FilledRect,
        0.0f,
        0.0f,
        vw,
        vh,
        kPickerBackdrop));

    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::FilledRect,
        list_panel_x,
        list_panel_y,
        list_panel_width,
        list_panel_height,
        kPickerPanelFill));
    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::OutlinedRect,
        list_panel_x,
        list_panel_y,
        list_panel_width,
        list_panel_height,
        kPickerPanelEdge,
        2.0f));
    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::OutlinedRect,
        list_panel_x + 5.0f,
        list_panel_y + 5.0f,
        list_panel_width - 10.0f,
        list_panel_height - 10.0f,
        kPickerPanelEdgeInner,
        1.0f));

    SubmitPickerDrawCommand(MakeText(
        list_panel_x + pad,
        list_panel_y + pad,
        "CHOOSE A BONEYARD",
        kPickerTitleGold,
        title_scale));

    const bool has_entries =
        snapshot.catalog != nullptr && !snapshot.catalog->entries.empty();
    if (has_entries) {
        const auto entry_count = snapshot.catalog->entries.size();
        const auto mod_count = CountPickerSourceMods(*snapshot.catalog);
        char count_line[96];
        std::snprintf(
            count_line,
            sizeof(count_line),
            "%zu boneyard%s from %zu mod%s",
            entry_count,
            entry_count == 1 ? "" : "s",
            mod_count,
            mod_count == 1 ? "" : "s");
        const float count_width =
            static_cast<float>(std::strlen(count_line)) *
            kPickerGlyphAdvance * row_meta_scale;
        SubmitPickerDrawCommand(MakeText(
            list_panel_x + list_panel_width - pad - count_width,
            list_panel_y + pad + 6.0f * ui_scale,
            count_line,
            kPickerTextMeta,
            row_meta_scale));
    }

    const float header_height = pad + 26.0f * ui_scale;
    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::FilledRect,
        list_panel_x + pad * 0.8f,
        list_panel_y + header_height,
        list_panel_width - pad * 1.6f,
        1.0f,
        kPickerDivider));

    const float list_top = list_panel_y + header_height + 12.0f * ui_scale;
    const float list_bottom =
        list_panel_y + list_panel_height - 14.0f * ui_scale;
    const float list_x = list_panel_x + pad * 0.8f;
    const float list_width = list_panel_width - pad * 1.6f;
    const auto rows_fit = static_cast<std::size_t>(
        (std::max)(1.0f, (list_bottom - list_top) / row_height));
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
        const auto name_chars = PickerCharsPerLine(
            list_width * 0.58f,
            row_text_scale);
        const auto meta_chars = PickerCharsPerLine(
            list_width * 0.36f,
            row_meta_scale);

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
                    row_y - 3.0f * ui_scale,
                    list_width,
                    row_height - 5.0f * ui_scale,
                    at_cursor ? kPickerRowCursorFill
                              : kPickerRowSelectedFill));
            }
            if (at_cursor) {
                SubmitPickerDrawCommand(MakeRectangle(
                    LuaDrawCommandKind::FilledRect,
                    list_x,
                    row_y - 3.0f * ui_scale,
                    4.0f * ui_scale,
                    row_height - 5.0f * ui_scale,
                    kPickerRowCursorBar));
            }

            SubmitPickerDrawCommand(MakeText(
                list_x + 16.0f * ui_scale,
                row_y,
                TruncatePickerText(entry.display_name, name_chars),
                at_cursor ? kPickerTitleGold : kPickerTextBright,
                row_text_scale));

            std::string row_meta = is_committed_selection
                ? std::string("[SELECTED]")
                : entry.source_mod_name;
            row_meta = TruncatePickerText(row_meta, meta_chars);
            const float row_meta_width =
                static_cast<float>(row_meta.size()) *
                kPickerGlyphAdvance * row_meta_scale;
            SubmitPickerDrawCommand(MakeText(
                list_x + list_width - 14.0f * ui_scale - row_meta_width,
                row_y + 3.0f * ui_scale,
                std::move(row_meta),
                is_committed_selection ? kPickerWaitGold : kPickerTextMeta,
                row_meta_scale));
            row_y += row_height;
        }

        if (entry_count > visible_rows) {
            const float track_x =
                list_panel_x + list_panel_width - 10.0f * ui_scale;
            const float track_height = list_bottom - list_top;
            SubmitPickerDrawCommand(MakeRectangle(
                LuaDrawCommandKind::FilledRect,
                track_x,
                list_top,
                4.0f * ui_scale,
                track_height,
                kPickerScrollTrack));
            const float thumb_height = (std::max)(
                18.0f * ui_scale,
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
                4.0f * ui_scale,
                thumb_height,
                kPickerScrollThumb));
        }
    } else {
        SubmitPickerDrawCommand(MakeText(
            list_x + 16.0f * ui_scale,
            list_top,
            "No boneyards are staged.",
            kPickerTextDim,
            row_text_scale));
    }

    // Details zone: name, source mod, update date, and description for the
    // highlighted entry; the stat dump (size/layout/sha/file) is gone by
    // owner direction.
    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::FilledRect,
        list_panel_x,
        detail_panel_y,
        list_panel_width,
        detail_panel_height,
        kPickerCardFill));
    SubmitPickerDrawCommand(MakeRectangle(
        LuaDrawCommandKind::OutlinedRect,
        list_panel_x,
        detail_panel_y,
        list_panel_width,
        detail_panel_height,
        kPickerPanelEdgeInner,
        1.0f));

    const float detail_x = list_panel_x + pad;
    const float detail_inner_width = list_panel_width - pad * 2.0f;
    float detail_y = detail_panel_y + pad * 0.7f;

    if (has_entries) {
        const auto& entry = snapshot.catalog->entries[cursor];

        const auto detail_name_chars = PickerCharsPerLine(
            detail_inner_width * 0.7f,
            detail_name_scale);
        SubmitPickerDrawCommand(MakeText(
            detail_x,
            detail_y,
            TruncatePickerText(entry.display_name, detail_name_chars),
            kPickerTitleGold,
            detail_name_scale));

        if (!entry.updated_utc.empty()) {
            const std::string updated = "Updated " + entry.updated_utc;
            const float updated_width =
                static_cast<float>(updated.size()) *
                kPickerGlyphAdvance * detail_meta_scale;
            SubmitPickerDrawCommand(MakeText(
                detail_x + detail_inner_width - updated_width,
                detail_y + 4.0f * ui_scale,
                updated,
                kPickerTextDim,
                detail_meta_scale));
        }
        detail_y += 26.0f * ui_scale;

        SubmitPickerDrawCommand(MakeText(
            detail_x,
            detail_y,
            TruncatePickerText(
                "from " + entry.source_mod_name + " v" +
                    entry.source_mod_version,
                PickerCharsPerLine(detail_inner_width, detail_meta_scale)),
            kPickerTextDim,
            detail_meta_scale));
        detail_y += 24.0f * ui_scale;

        const std::string& description = entry.source_mod_description;
        if (!description.empty()) {
            SubmitPickerDrawCommand(MakeText(
                detail_x,
                detail_y,
                WrapPickerText(
                    description,
                    PickerCharsPerLine(
                        detail_inner_width,
                        description_scale),
                    kPickerDescriptionMaxLines),
                kPickerTextBright,
                description_scale));
        } else {
            SubmitPickerDrawCommand(MakeText(
                detail_x,
                detail_y,
                "No description provided.",
                kPickerTextMeta,
                description_scale));
        }
    }

    const float footer_y =
        detail_panel_y + detail_panel_height - pad * 0.7f - line_height;

    if (!snapshot.error_message.empty()) {
        const float error_y = footer_y - 26.0f * ui_scale;
        SubmitPickerDrawCommand(MakeRectangle(
            LuaDrawCommandKind::FilledRect,
            detail_x - 6.0f * ui_scale,
            error_y - 4.0f * ui_scale,
            detail_inner_width + 12.0f * ui_scale,
            22.0f * ui_scale,
            kPickerErrorFill));
        SubmitPickerDrawCommand(MakeText(
            detail_x,
            error_y,
            TruncatePickerText(
                "ERROR: " + snapshot.error_message,
                PickerCharsPerLine(detail_inner_width, hint_scale)),
            kPickerErrorText,
            hint_scale));
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
        detail_x,
        footer_y,
        std::move(status_line),
        status_color,
        hint_scale));

    CommitLuaDrawFrame(kPickerDrawOwner);
}
