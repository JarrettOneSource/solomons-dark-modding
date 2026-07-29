#pragma once

#include <cstddef>
#include <cstdint>

namespace sdmod::multiplayer {

constexpr std::size_t kParticipantHitFeedbackMaximumInFlightEvents = 8;
constexpr std::size_t kParticipantHitFeedbackMaximumSendsPerTick = 4;
constexpr std::uint64_t kParticipantHitFeedbackResendMs = 100;

enum class ParticipantHitFeedbackSendAction {
    None,
    FirstSend,
    Retransmit,
};

inline ParticipantHitFeedbackSendAction
SelectParticipantHitFeedbackSendAction(
    std::size_t pending_index,
    std::uint64_t last_sent_ms,
    std::uint64_t now_ms,
    std::size_t in_flight_count,
    std::size_t sends_this_tick) {
    if (sends_this_tick >=
        kParticipantHitFeedbackMaximumSendsPerTick) {
        return ParticipantHitFeedbackSendAction::None;
    }
    if (last_sent_ms == 0) {
        return in_flight_count <
                kParticipantHitFeedbackMaximumInFlightEvents
            ? ParticipantHitFeedbackSendAction::FirstSend
            : ParticipantHitFeedbackSendAction::None;
    }
    if (pending_index != 0 ||
        now_ms < last_sent_ms ||
        now_ms - last_sent_ms <
            kParticipantHitFeedbackResendMs) {
        return ParticipantHitFeedbackSendAction::None;
    }
    return ParticipantHitFeedbackSendAction::Retransmit;
}

}  // namespace sdmod::multiplayer
