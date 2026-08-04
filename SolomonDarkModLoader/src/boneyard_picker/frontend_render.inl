// Boneyard picker frontend, native edition. Draws with the game's own
// primitives — the stock ExactText font renderer and the stock untextured
// HUD quad — after the complete stock HUD render, while the native renderer
// still owns its presentation boundary, so the picker carries the retail look (owner mandate:
// existing in-game art and fonts).
// Consumes only the public snapshot plus the picker cursor; pick/cancel
// intent stays in ProcessPickerInput.
//
// Layout contract (owner-directed, carried from v2): the list zone spans
// the top two-thirds of the screen; the zone below shows the highlighted
// entry's name, source mod, update date, and description. Every metric
// multiplies by a viewport-derived scale so text stays readable at any
// resolution.

constexpr float kPickerBaseViewportHeight = 720.0f;
constexpr float kPickerMinUiScale = 1.0f;
constexpr float kPickerMaxUiScale = 3.0f;
// Stock ExactText advances measured from live half-scale nameplate captures
// (see EstimateGameplayNameplateTextWidth): 16px per glyph, 8px per space at
// scale 1.0. Line height observed ~32px at scale 1.0.
constexpr float kPickerStockGlyphAdvance = 16.0f;
constexpr float kPickerStockLineHeight = 32.0f;
constexpr std::size_t kPickerDescriptionMaxLines = 4;
// Stock ExactText anchors near the glyph baseline: visible glyphs rise
// ~0.55 line-heights ABOVE the submitted y (measured from the beta.31
// picker capture: row text at y rendered its cap span at [y-11, y-2] with
// row_scale 0.65). List-row text must therefore be pushed down from row_y
// to sit centered inside the cursor/selection quad, which spans
// [row_y - 3*ui_scale, row_y + row_height - 8*ui_scale].
constexpr float kPickerRowTextBaselineNudge = 12.0f;
constexpr float kPickerRowMetaBaselineNudge = 11.0f;

// Text scale factors, multiplied by the viewport ui_scale and emitted as
// _s(<value>) ExactText commands.
constexpr float kPickerTitleTextScale = 0.80f;
constexpr float kPickerCountTextScale = 0.42f;
constexpr float kPickerRowTextScale = 0.52f;
constexpr float kPickerRowMetaTextScale = 0.40f;
constexpr float kPickerDetailNameTextScale = 0.62f;
constexpr float kPickerDetailMetaTextScale = 0.44f;
constexpr float kPickerDescriptionTextScale = 0.46f;
constexpr float kPickerHintTextScale = 0.44f;

const NativeWorldIndicatorColor kPickerBackdrop{0, 0, 0, 150};
const NativeWorldIndicatorColor kPickerPanelFill{10, 12, 18, 244};
const NativeWorldIndicatorColor kPickerPanelEdge{212, 178, 90, 255};
const NativeWorldIndicatorColor kPickerPanelEdgeInner{60, 52, 34, 255};
const NativeWorldIndicatorColor kPickerDivider{212, 178, 90, 90};
const NativeWorldIndicatorColor kPickerRowCursorFill{84, 64, 28, 235};
const NativeWorldIndicatorColor kPickerRowCursorBar{236, 197, 102, 255};
const NativeWorldIndicatorColor kPickerRowSelectedFill{40, 44, 30, 220};
const NativeWorldIndicatorColor kPickerCardFill{14, 16, 24, 235};
const NativeWorldIndicatorColor kPickerScrollTrack{40, 36, 26, 200};
const NativeWorldIndicatorColor kPickerScrollThumb{212, 178, 90, 220};
const NativeWorldIndicatorColor kPickerErrorFill{64, 16, 16, 240};

std::string TruncatePickerText(const std::string& text, std::size_t limit) {
    if (text.size() <= limit) {
        return text;
    }
    return text.substr(0, limit > 3 ? limit - 3 : limit) + "...";
}

float PickerStockTextWidth(std::string_view text, float text_scale) {
    return static_cast<float>(text.size()) *
        kPickerStockGlyphAdvance * text_scale;
}

std::size_t PickerCharsPerLine(float inner_width, float text_scale) {
    const float advance = kPickerStockGlyphAdvance * text_scale;
    if (advance <= 0.0f || inner_width <= advance) {
        return 1;
    }
    return static_cast<std::size_t>(inner_width / advance);
}

// Word-wraps into at most max_lines separate lines; each line is submitted
// as its own ExactText draw because the stock renderer takes single-line
// strings. The last line is ellipsized when text overflows.
std::vector<std::string> WrapPickerText(
    const std::string& text,
    std::size_t max_chars,
    std::size_t max_lines) {
    std::vector<std::string> lines;
    if (max_chars < 4 || max_lines == 0) {
        return lines;
    }
    std::size_t line_start = 0;
    while (line_start < text.size() && lines.size() < max_lines) {
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
        if (lines.size() + 1 == max_lines && line_end < text.size()) {
            line = TruncatePickerText(line, max_chars > 3 ? max_chars - 3 : 1);
        }
        lines.push_back(std::move(line));
        line_start = line_end;
        while (line_start < text.size() && text[line_start] == ' ') {
            ++line_start;
        }
    }
    return lines;
}

std::size_t CountPickerSourceMods(const BoneyardPickerCatalog& catalog) {
    std::unordered_set<std::string> mods;
    for (const auto& entry : catalog.entries) {
        mods.insert(entry.source_mod_id);
    }
    return mods.size();
}

bool DrawPickerStockText(
    const std::string& text,
    float x,
    float y,
    float text_scale) {
    if (text.empty()) {
        return false;
    }
    char command[16];
    std::snprintf(command, sizeof(command), "_s(%.2f)", text_scale);
    return DrawNativeWorldIndicatorExactText(command + text, x, y);
}

void RenderBoneyardPickerUi(const BoneyardPickerSnapshot& snapshot) {
    if (!snapshot.is_open && snapshot.error_message.empty()) {
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
    const float title_scale = kPickerTitleTextScale * ui_scale;
    const float count_scale = kPickerCountTextScale * ui_scale;
    const float row_scale = kPickerRowTextScale * ui_scale;
    const float row_meta_scale = kPickerRowMetaTextScale * ui_scale;
    const float detail_name_scale = kPickerDetailNameTextScale * ui_scale;
    const float detail_meta_scale = kPickerDetailMetaTextScale * ui_scale;
    const float description_scale = kPickerDescriptionTextScale * ui_scale;
    const float hint_scale = kPickerHintTextScale * ui_scale;
    const float row_height =
        kPickerStockLineHeight * row_scale + 10.0f * ui_scale;
    const float description_line_height =
        kPickerStockLineHeight * description_scale + 4.0f * ui_scale;

    // Backdrop and list panel through the stock untextured-quad primitive.
    (void)DrawNativeScreenQuad(0.0f, 0.0f, vw, vh, kPickerBackdrop);
    (void)DrawNativeScreenQuad(
        list_panel_x,
        list_panel_y,
        list_panel_width,
        list_panel_height,
        kPickerPanelFill);
    // Gold edge as four thin quads (native pipeline has no outline command).
    const float edge = (std::max)(2.0f, 2.0f * ui_scale);
    (void)DrawNativeScreenQuad(
        list_panel_x, list_panel_y, list_panel_width, edge, kPickerPanelEdge);
    (void)DrawNativeScreenQuad(
        list_panel_x,
        list_panel_y + list_panel_height - edge,
        list_panel_width,
        edge,
        kPickerPanelEdge);
    (void)DrawNativeScreenQuad(
        list_panel_x, list_panel_y, edge, list_panel_height, kPickerPanelEdge);
    (void)DrawNativeScreenQuad(
        list_panel_x + list_panel_width - edge,
        list_panel_y,
        edge,
        list_panel_height,
        kPickerPanelEdge);

    DrawPickerStockText(
        "CHOOSE A BONEYARD",
        list_panel_x + pad,
        list_panel_y + pad,
        title_scale);

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
        DrawPickerStockText(
            count_line,
            list_panel_x + list_panel_width - pad -
                PickerStockTextWidth(count_line, count_scale),
            list_panel_y + pad + 10.0f * ui_scale,
            count_scale);
    }

    const float header_height =
        pad + kPickerStockLineHeight * title_scale + 8.0f * ui_scale;
    (void)DrawNativeScreenQuad(
        list_panel_x + pad * 0.8f,
        list_panel_y + header_height,
        list_panel_width - pad * 1.6f,
        1.0f,
        kPickerDivider);

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
            row_scale);
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
                (void)DrawNativeScreenQuad(
                    list_x,
                    row_y - 3.0f * ui_scale,
                    list_width,
                    row_height - 5.0f * ui_scale,
                    at_cursor ? kPickerRowCursorFill
                              : kPickerRowSelectedFill);
            }
            if (at_cursor) {
                (void)DrawNativeScreenQuad(
                    list_x,
                    row_y - 3.0f * ui_scale,
                    4.0f * ui_scale,
                    row_height - 5.0f * ui_scale,
                    kPickerRowCursorBar);
            }

            DrawPickerStockText(
                TruncatePickerText(entry.display_name, name_chars),
                list_x + 16.0f * ui_scale,
                row_y + kPickerRowTextBaselineNudge * ui_scale,
                row_scale);

            std::string row_meta = is_committed_selection
                ? std::string("[SELECTED]")
                : entry.source_mod_name;
            row_meta = TruncatePickerText(row_meta, meta_chars);
            DrawPickerStockText(
                row_meta,
                list_x + list_width - 14.0f * ui_scale -
                    PickerStockTextWidth(row_meta, row_meta_scale),
                row_y + kPickerRowMetaBaselineNudge * ui_scale,
                row_meta_scale);
            row_y += row_height;
        }

        if (entry_count > visible_rows) {
            const float track_x =
                list_panel_x + list_panel_width - 10.0f * ui_scale;
            const float track_height = list_bottom - list_top;
            (void)DrawNativeScreenQuad(
                track_x,
                list_top,
                4.0f * ui_scale,
                track_height,
                kPickerScrollTrack);
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
            (void)DrawNativeScreenQuad(
                track_x,
                thumb_y,
                4.0f * ui_scale,
                thumb_height,
                kPickerScrollThumb);
        }
    } else {
        DrawPickerStockText(
            "No boneyards are staged.",
            list_x + 16.0f * ui_scale,
            list_top,
            row_scale);
    }

    // Details zone: name, source mod, update date, and description for the
    // highlighted entry; the stat dump (size/layout/sha/file) stays gone by
    // owner direction.
    (void)DrawNativeScreenQuad(
        list_panel_x,
        detail_panel_y,
        list_panel_width,
        detail_panel_height,
        kPickerCardFill);
    (void)DrawNativeScreenQuad(
        list_panel_x,
        detail_panel_y,
        list_panel_width,
        1.0f,
        kPickerPanelEdgeInner);

    const float detail_x = list_panel_x + pad;
    const float detail_inner_width = list_panel_width - pad * 2.0f;
    float detail_y = detail_panel_y + pad * 0.7f;

    if (has_entries) {
        const auto& entry = snapshot.catalog->entries[cursor];

        DrawPickerStockText(
            TruncatePickerText(
                entry.display_name,
                PickerCharsPerLine(
                    detail_inner_width * 0.7f,
                    detail_name_scale)),
            detail_x,
            detail_y,
            detail_name_scale);

        if (!entry.updated_utc.empty()) {
            const std::string updated = "Updated " + entry.updated_utc;
            DrawPickerStockText(
                updated,
                detail_x + detail_inner_width -
                    PickerStockTextWidth(updated, detail_meta_scale),
                detail_y + 4.0f * ui_scale,
                detail_meta_scale);
        }
        detail_y += kPickerStockLineHeight * detail_name_scale +
            6.0f * ui_scale;

        DrawPickerStockText(
            TruncatePickerText(
                "from " + entry.source_mod_name + " v" +
                    entry.source_mod_version,
                PickerCharsPerLine(detail_inner_width, detail_meta_scale)),
            detail_x,
            detail_y,
            detail_meta_scale);
        detail_y += kPickerStockLineHeight * detail_meta_scale +
            6.0f * ui_scale;

        const std::string& description = entry.source_mod_description;
        if (!description.empty()) {
            const auto lines = WrapPickerText(
                description,
                PickerCharsPerLine(detail_inner_width, description_scale),
                kPickerDescriptionMaxLines);
            for (const auto& line : lines) {
                DrawPickerStockText(
                    line,
                    detail_x,
                    detail_y,
                    description_scale);
                detail_y += description_line_height;
            }
        } else {
            DrawPickerStockText(
                "No description provided.",
                detail_x,
                detail_y,
                description_scale);
        }
    }

    const float footer_y = detail_panel_y + detail_panel_height -
        pad * 0.7f - kPickerStockLineHeight * hint_scale;

    if (!snapshot.error_message.empty()) {
        const float error_y = footer_y -
            kPickerStockLineHeight * hint_scale - 10.0f * ui_scale;
        (void)DrawNativeScreenQuad(
            detail_x - 6.0f * ui_scale,
            error_y - 4.0f * ui_scale,
            detail_inner_width + 12.0f * ui_scale,
            kPickerStockLineHeight * hint_scale + 8.0f * ui_scale,
            kPickerErrorFill);
        DrawPickerStockText(
            TruncatePickerText(
                "ERROR: " + snapshot.error_message,
                PickerCharsPerLine(detail_inner_width, hint_scale)),
            detail_x,
            error_y,
            hint_scale);
    }

    std::string status_line;
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
    } else if (snapshot.phase == BoneyardPickerPhase::Launching) {
        std::string target = "the selected boneyard";
        if (has_entries &&
            snapshot.selected_index < snapshot.catalog->entries.size()) {
            target = snapshot.catalog->entries[snapshot.selected_index]
                         .display_name;
        }
        status_line =
            "Entering " + TruncatePickerText(target, 40) + "...";
    } else {
        status_line =
            "Up/Down select   PgUp/PgDn jump   Enter play   Esc stock maps";
    }
    DrawPickerStockText(status_line, detail_x, footer_y, hint_scale);
}
